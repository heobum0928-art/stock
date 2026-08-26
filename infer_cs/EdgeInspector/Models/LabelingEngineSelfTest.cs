using System.IO;

namespace EdgeInspector.Models;

// LabelingEngine(라벨링 순수 로직) 헤드리스 검증 — WPF UI 없이 돌아가는지 확인.
// "dotnet run --project infer_cs/EdgeInspector -- --selftest"로 실행. --examples와 같은
// 배치 검증 관례를 따른다. 개발 중 임시 검증용(라벨링 탭 도입 시 왕복 변환 정확성 확인).
public static class LabelingEngineSelfTest
{
    public static int Run()
    {
        int fail = 0;
        void Check(string name, bool ok)
        {
            Console.WriteLine((ok ? "PASS " : "FAIL ") + name);
            if (!ok) fail++;
        }

        // 1) pixel<->yolo 왕복
        var box = LabelingEngine.PixelToYolo(2, 100, 50, 300, 250, 640, 480);
        var (x1, y1, x2, y2) = LabelingEngine.YoloToPixel(box, 640, 480);
        Check("pixel->yolo->pixel 왕복(오차<2px)",
            Math.Abs(x1 - 100) < 2 && Math.Abs(y1 - 50) < 2 && Math.Abs(x2 - 300) < 2 && Math.Abs(y2 - 250) < 2);
        Check("클래스ID 보존", box.ClsId == 2);

        // 2) 경계 밖 드래그 → clamp
        var clamped = LabelingEngine.PixelToYolo(0, -50, -50, 700, 500, 640, 480);
        Check("경계 밖 좌표 clamp(cx/cy 0~1 범위)", clamped.Cx is >= 0 and <= 1 && clamped.Cy is >= 0 and <= 1);

        // 3) 임시 폴더에서 라벨 저장/로드/classes/export 왕복
        var tmp = Path.Combine(Path.GetTempPath(), "edgeai_labeltest_" + Guid.NewGuid().ToString("N")[..8]);
        var imagesRoot = Path.Combine(tmp, "images");
        var labelsRoot = Path.Combine(tmp, "images_labels");
        Directory.CreateDirectory(imagesRoot);
        try
        {
            // 가짜 "이미지"(내용은 무관 — export는 파일 복사만 함) 3장 + 라벨 2장(1장은 무라벨)
            for (int i = 0; i < 3; i++)
                File.WriteAllBytes(Path.Combine(imagesRoot, $"img{i}.jpg"), new byte[] { 1, 2, 3 });

            var boxes = new List<LabelBox> { new(0, 0.5, 0.5, 0.2, 0.3), new(1, 0.3, 0.3, 0.1, 0.1) };
            var lp0 = LabelingEngine.LabelPathFor(Path.Combine(imagesRoot, "img0.jpg"), imagesRoot, labelsRoot);
            LabelingEngine.SaveLabels(lp0, boxes);
            var lp1 = LabelingEngine.LabelPathFor(Path.Combine(imagesRoot, "img1.jpg"), imagesRoot, labelsRoot);
            LabelingEngine.SaveLabels(lp1, new List<LabelBox>());   // 빈 라벨(객체 없음)도 유효

            var loaded = LabelingEngine.LoadLabels(lp0);
            Check("라벨 저장->로드 왕복(2개 박스)", loaded.Count == 2 && loaded[0].ClsId == 0 && loaded[1].ClsId == 1);
            Check("빈 라벨 저장/로드", LabelingEngine.LoadLabels(lp1).Count == 0);

            LabelingEngine.SaveClassNames(labelsRoot, new List<string> { "사람", "헬멧" });
            var names = LabelingEngine.LoadClassNames(labelsRoot);
            Check("classes.txt 한글 왕복", names.Count == 2 && names[0] == "사람" && names[1] == "헬멧");

            var listed = LabelingEngine.ListImages(imagesRoot);
            Check("ListImages 3장 발견", listed.Count == 3);

            var outDir = Path.Combine(tmp, "export");
            var result = LabelingEngine.ExportDataset(imagesRoot, labelsRoot, names, outDir);
            Check("export 성공(에러 없음)", result.Error == null);
            Check("export train+val == 라벨된 이미지 수(2)", result.Train + result.Val == 2);
            Check("data.yaml 생성됨", result.DataYaml != null && File.Exists(result.DataYaml));
            if (result.DataYaml != null)
            {
                var yaml = File.ReadAllText(result.DataYaml);
                Check("data.yaml에 클래스 2개 반영", yaml.Contains("nc: 2") && yaml.Contains("사람") && yaml.Contains("헬멧"));
            }
        }
        finally
        {
            try { Directory.Delete(tmp, recursive: true); } catch { }
        }

        Console.WriteLine(fail == 0 ? $"\n전체 통과" : $"\n{fail}개 실패");
        return fail == 0 ? 0 : 1;
    }
}
