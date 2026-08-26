using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using EdgeInspector.Models;

namespace EdgeInspector.Examples;

// vision_detect/example_usage.py와 같은 취지 — 실제 모델 + 실제 학습 이미지 전체로
// 일괄 추론해 결과를 눈으로 바로 확인할 수 있게 저장한다.
// 실행: dotnet run --project infer_cs/EdgeInspector -- --examples
public static class ExampleRunner
{
    public static void RunBatch()
    {
        var root = ProjectPaths.FindRoot();
        if (root == null)
        {
            Console.WriteLine("프로젝트 루트(train/, infer_cs/)를 찾을 수 없습니다.");
            return;
        }

        var modelPath = Path.Combine(root, "train", "edge_unet_v2.onnx");
        var imagesDir = Path.Combine(root, "train", "data", "images");
        var outDir = Path.Combine(root, "infer_cs", "EdgeInspector", "examples_out");

        if (!File.Exists(modelPath))
        {
            Console.WriteLine($"모델을 찾을 수 없습니다: {modelPath}");
            return;
        }
        if (!Directory.Exists(imagesDir))
        {
            Console.WriteLine($"샘플 이미지 폴더를 찾을 수 없습니다: {imagesDir}");
            return;
        }

        Directory.CreateDirectory(outDir);

        var images = Directory.GetFiles(imagesDir)
            .Where(p => p.EndsWith(".bmp", StringComparison.OrdinalIgnoreCase) ||
                        p.EndsWith(".png", StringComparison.OrdinalIgnoreCase))
            .OrderBy(p => p)
            .ToArray();

        if (images.Length == 0)
        {
            Console.WriteLine($"{imagesDir}에 이미지가 없습니다.");
            return;
        }

        Console.WriteLine($"모델: {modelPath}");
        Console.WriteLine($"샘플 {images.Length}개 -> {outDir}\n");
        Console.WriteLine($"{"파일",-40} {"크기",-12} {"추론(ms)",-9} {"에지 비율",-8}");
        Console.WriteLine(new string('-', 75));

        EdgeSegmentationEngine engine;
        try
        {
            engine = new EdgeSegmentationEngine(modelPath);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"모델 로드 실패({modelPath}): {ex.Message}");
            return;
        }
        using var _ = engine;
        var edgeRatios = new List<double>();
        var times = new List<double>();

        foreach (var imagePath in images)
        {
            var name = Path.GetFileNameWithoutExtension(imagePath);
            var (gray, w, h) = LoadGrayscale(imagePath);
            var result = engine.Run(gray, w, h, threshold: 0.5);

            int edgePixels = result.BinaryMask.Count(v => v != 0);
            double edgeRatio = (double)edgePixels / (w * h);
            edgeRatios.Add(edgeRatio);
            times.Add(result.InferenceMilliseconds);

            SaveOverlay(gray, result.BinaryMask, w, h, Path.Combine(outDir, $"{name}_overlay.png"));
            SaveGray(result.ProbabilityMap, w, h, Path.Combine(outDir, $"{name}_prob.png"));

            Console.WriteLine($"{name,-40} {$"{w}x{h}",-12} {result.InferenceMilliseconds,-9:F1} {edgeRatio,-8:P2}");
        }

        Console.WriteLine(new string('-', 75));
        Console.WriteLine($"평균 추론 시간: {times.Average():F1} ms, 평균 에지 비율: {edgeRatios.Average():P2}");
        Console.WriteLine($"결과 이미지 {images.Length * 2}장 저장 완료: {outDir}");
    }

    private static unsafe (byte[] gray, int w, int h) LoadGrayscale(string path)
    {
        using var bmp = new Bitmap(path);
        int w = bmp.Width, h = bmp.Height;
        var gray = new byte[w * h];
        var rect = new Rectangle(0, 0, w, h);
        var data = bmp.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
        byte* basePtr = (byte*)data.Scan0;
        for (int y = 0; y < h; y++)
        {
            byte* row = basePtr + y * data.Stride;
            for (int x = 0; x < w; x++)
                gray[y * w + x] = (byte)(0.299 * row[x * 3 + 2] + 0.587 * row[x * 3 + 1] + 0.114 * row[x * 3 + 0]);
        }
        bmp.UnlockBits(data);
        return (gray, w, h);
    }

    private static unsafe void SaveOverlay(byte[] gray, byte[] mask, int w, int h, string path)
    {
        using var bmp = new Bitmap(w, h, PixelFormat.Format24bppRgb);
        var rect = new Rectangle(0, 0, w, h);
        var data = bmp.LockBits(rect, ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
        byte* basePtr = (byte*)data.Scan0;
        for (int y = 0; y < h; y++)
        {
            byte* row = basePtr + y * data.Stride;
            for (int x = 0; x < w; x++)
            {
                int idx = y * w + x;
                byte g = gray[idx];
                bool isEdge = mask[idx] != 0;
                row[x * 3 + 0] = g;
                row[x * 3 + 1] = isEdge ? (byte)0 : g;
                row[x * 3 + 2] = isEdge ? (byte)255 : g;
            }
        }
        bmp.UnlockBits(data);
        bmp.Save(path, ImageFormat.Png);
    }

    private static unsafe void SaveGray(byte[] values, int w, int h, string path)
    {
        using var bmp = new Bitmap(w, h, PixelFormat.Format24bppRgb);
        var rect = new Rectangle(0, 0, w, h);
        var data = bmp.LockBits(rect, ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
        byte* basePtr = (byte*)data.Scan0;
        for (int y = 0; y < h; y++)
        {
            byte* row = basePtr + y * data.Stride;
            for (int x = 0; x < w; x++)
            {
                byte v = values[y * w + x];
                row[x * 3 + 0] = v;
                row[x * 3 + 1] = v;
                row[x * 3 + 2] = v;
            }
        }
        bmp.UnlockBits(data);
        bmp.Save(path, ImageFormat.Png);
    }
}
