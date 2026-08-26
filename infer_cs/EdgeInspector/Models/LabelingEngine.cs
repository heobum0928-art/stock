using System.IO;

namespace EdgeInspector.Models;

// 라벨링 도구의 순수 로직 — examples/_common/labeling_core.py(Python, 헤드리스 테스트됨)와
// 동일한 규약을 그대로 C#으로 이식한 것. 좌표계는 YOLO 표준(정규화 cx/cy/w/h, 0-based 클래스).
// 파이썬 버전과 같은 폴더 규약(images_root 옆에 <name>_labels)을 써서 라벨링 도구(WPF)와
// 학습 마법사(Python)가 같은 데이터셋을 공유할 수 있다.
public sealed record LabelBox(int ClsId, double Cx, double Cy, double W, double H);

public sealed record ExportResult
{
    public string? DataYaml { get; init; }
    public int Train { get; init; }
    public int Val { get; init; }
    public string? Warning { get; init; }
    public string? Error { get; init; }
}

public static class LabelingEngine
{
    private static readonly string[] ImgExts = { ".jpg", ".jpeg", ".png", ".bmp" };

    // 박스가 이미지 밖으로 삐져나가면 먼저 모서리를 이미지 경계로 clamp한 뒤 cx/cy/w/h를
    // 구한다(cx/cy/w/h를 각각 독립적으로 clip하면 중심과 크기가 따로 잘려 기하학적으로
    // 잘못된 박스가 되므로 — labeling_core.pixel_to_yolo와 동일 규칙).
    public static LabelBox PixelToYolo(int clsId, double x1, double y1, double x2, double y2, double imgW, double imgH)
    {
        if (x1 > x2) (x1, x2) = (x2, x1);
        if (y1 > y2) (y1, y2) = (y2, y1);
        x1 = Math.Clamp(x1, 0, imgW); x2 = Math.Clamp(x2, 0, imgW);
        y1 = Math.Clamp(y1, 0, imgH); y2 = Math.Clamp(y2, 0, imgH);
        double cx = (x1 + x2) / 2 / imgW, cy = (y1 + y2) / 2 / imgH;
        double w = (x2 - x1) / imgW, h = (y2 - y1) / imgH;
        return new LabelBox(clsId, cx, cy, w, h);
    }

    public static (double x1, double y1, double x2, double y2) YoloToPixel(LabelBox b, double imgW, double imgH)
    {
        double bw = b.W * imgW, bh = b.H * imgH;
        double px = b.Cx * imgW, py = b.Cy * imgH;
        return (px - bw / 2, py - bh / 2, px + bw / 2, py + bh / 2);
    }

    public static string LabelPathFor(string imagePath, string imagesRoot, string labelsRoot)
    {
        var rel = Path.GetRelativePath(imagesRoot, imagePath);
        var relNoExt = Path.Combine(Path.GetDirectoryName(rel) ?? "", Path.GetFileNameWithoutExtension(rel));
        return Path.Combine(labelsRoot, relNoExt + ".txt");
    }

    public static List<LabelBox> LoadLabels(string txtPath)
    {
        var boxes = new List<LabelBox>();
        if (!File.Exists(txtPath)) return boxes;
        foreach (var line in File.ReadAllLines(txtPath))
        {
            var parts = line.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length != 5) continue;
            if (!int.TryParse(parts[0], out int cls)) continue;
            if (!double.TryParse(parts[1], System.Globalization.CultureInfo.InvariantCulture, out double cx)) continue;
            if (!double.TryParse(parts[2], System.Globalization.CultureInfo.InvariantCulture, out double cy)) continue;
            if (!double.TryParse(parts[3], System.Globalization.CultureInfo.InvariantCulture, out double w)) continue;
            if (!double.TryParse(parts[4], System.Globalization.CultureInfo.InvariantCulture, out double h)) continue;
            boxes.Add(new LabelBox(cls, cx, cy, w, h));
        }
        return boxes;
    }

    // 빈 리스트여도 저장(객체 없음 = 유효한 라벨).
    public static void SaveLabels(string txtPath, IReadOnlyList<LabelBox> boxes)
    {
        var dir = Path.GetDirectoryName(txtPath);
        if (dir != null) Directory.CreateDirectory(dir);
        var lines = boxes.Select(b => string.Format(System.Globalization.CultureInfo.InvariantCulture,
            "{0} {1:F6} {2:F6} {3:F6} {4:F6}", b.ClsId, b.Cx, b.Cy, b.W, b.H));
        File.WriteAllText(txtPath, string.Join("\n", lines));
    }

    public static List<string> LoadClassNames(string labelsRoot)
    {
        var p = Path.Combine(labelsRoot, "classes.txt");
        if (!File.Exists(p)) return new List<string>();
        return File.ReadAllLines(p).Select(l => l.Trim()).Where(l => l.Length > 0).ToList();
    }

    public static void SaveClassNames(string labelsRoot, IReadOnlyList<string> names)
    {
        Directory.CreateDirectory(labelsRoot);
        File.WriteAllText(Path.Combine(labelsRoot, "classes.txt"), string.Join("\n", names));
    }

    public static List<string> ListImages(string folder)
    {
        if (!Directory.Exists(folder)) return new List<string>();
        return Directory.EnumerateFiles(folder, "*", SearchOption.AllDirectories)
            .Where(f => ImgExts.Contains(Path.GetExtension(f).ToLowerInvariant()))
            .OrderBy(f => f, StringComparer.Ordinal)
            .ToList();
    }

    // 라벨링한 이미지/라벨을 YOLO 학습 데이터셋(train/val 분할 + data.yaml)으로 export.
    // 라벨 txt가 존재하는 이미지만 사용(라벨 안 한 이미지는 제외).
    public static ExportResult ExportDataset(string imagesRoot, string labelsRoot, IReadOnlyList<string> classNames,
        string outDir, double valRatio = 0.2, int seed = 42)
    {
        var imgs = ListImages(imagesRoot);
        var labeled = imgs.Where(im => File.Exists(LabelPathFor(im, imagesRoot, labelsRoot))).ToList();
        if (labeled.Count == 0)
            return new ExportResult { Error = "라벨된 이미지가 없습니다. 박스를 그리고 저장한 이미지가 있어야 합니다." };

        var rng = new Random(seed);
        // Fisher-Yates — Python random.shuffle과 결과가 다를 수 있지만(RNG 알고리즘 차이),
        // 학습/검증 분할의 "무작위성" 자체가 목적이라 완전히 동일할 필요는 없다.
        for (int i = labeled.Count - 1; i > 0; i--)
        {
            int j = rng.Next(i + 1);
            (labeled[i], labeled[j]) = (labeled[j], labeled[i]);
        }
        int nVal = labeled.Count > 1 ? Math.Max(1, (int)(labeled.Count * valRatio)) : 0;
        var val = labeled.Take(nVal).ToList();
        var train = labeled.Skip(nVal).ToList();

        string? warning = null;
        if (val.Count == 0)
        {
            val = new List<string>(train);
            warning = "라벨된 이미지가 너무 적어 검증셋을 학습셋과 같게 뒀습니다. 데이터를 더 모으세요.";
        }

        string UniqueStem(string im)
        {
            var rel = Path.GetRelativePath(imagesRoot, im);
            var noExt = Path.Combine(Path.GetDirectoryName(rel) ?? "", Path.GetFileNameWithoutExtension(rel));
            return noExt.Replace(Path.DirectorySeparatorChar, '_').Replace(Path.AltDirectorySeparatorChar, '_');
        }

        var counts = new Dictionary<string, int>();
        foreach (var (split, items) in new[] { ("val", val), ("train", train) })
        {
            var imgOut = Path.Combine(outDir, "images", split);
            var lblOut = Path.Combine(outDir, "labels", split);
            Directory.CreateDirectory(imgOut);
            Directory.CreateDirectory(lblOut);
            foreach (var im in items)
            {
                var stem = UniqueStem(im);
                File.Copy(im, Path.Combine(imgOut, stem + Path.GetExtension(im)), overwrite: true);
                var lp = LabelPathFor(im, imagesRoot, labelsRoot);
                File.Copy(lp, Path.Combine(lblOut, stem + ".txt"), overwrite: true);
            }
            counts[split] = items.Count;
        }

        var dataYaml = Path.Combine(outDir, "data.yaml");
        var namesStr = "[" + string.Join(", ", classNames.Select(n => $"'{n}'")) + "]";
        File.WriteAllText(dataYaml,
            $"path: {outDir.Replace('\\', '/')}\n" +
            "train: images/train\n" +
            "val: images/val\n" +
            $"nc: {classNames.Count}\n" +
            $"names: {namesStr}\n");

        return new ExportResult { DataYaml = dataYaml, Train = counts["train"], Val = counts["val"], Warning = warning };
    }
}
