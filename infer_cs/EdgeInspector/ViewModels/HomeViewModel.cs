using System.Collections.ObjectModel;
using System.IO;
using System.Windows.Media;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

// 홈(프로젝트) 화면의 모델 카드 하나. 클릭하면 해당 뷰로 이동한다(NavKey/DomainName).
public sealed class ModelCard
{
    public required string DisplayName { get; init; }
    public required string TypeLabel { get; init; }        // "검출" / "이상탐지" / "세그멘테이션"
    public required Brush TypeColor { get; init; }
    public required string Subtitle { get; init; }         // 정확도·모델·학습수 등
    public required string Metric { get; init; }           // 큰 숫자(예: "96.5%") — 없으면 빈 문자열
    public required string NavKey { get; init; }           // "yolo" / "anomaly" / "seg"
    public string? DomainName { get; init; }               // YOLO 도메인 카드일 때 선택할 도메인
    public bool Available { get; init; } = true;           // ONNX가 실제로 존재하는지

    // 미학습(ONNX 없음) 카드는 흐리게 + "미학습" 배지로 구분(초보자가 클릭 후 "모델 없음"에 혼란 방지).
    public double CardOpacity => Available ? 1.0 : 0.5;
    public bool NotTrained => !Available;
}

// 홈 화면 뷰모델 — domains.json + 이상탐지/세그 모델을 카드 목록으로.
public sealed class HomeViewModel : ViewModelBase
{
    private readonly string? _projectRoot;

    public ObservableCollection<ModelCard> Cards { get; } = new();

    private string _summary = "";
    public string Summary { get => _summary; private set => SetField(ref _summary, value); }

    // 실제로 쓸 수 있는(ONNX가 존재하는) 모델이 하나도 없을 때 true — 처음 켠 사용자에게
    // "무엇부터 하면 되는지" 안내 배너를 띄운다.
    private bool _noTrainedModels;
    public bool NoTrainedModels { get => _noTrainedModels; private set => SetField(ref _noTrainedModels, value); }

    public HomeViewModel(string? projectRoot)
    {
        _projectRoot = projectRoot;
        Build();
    }

    // 학습 완료 후(TrainingViewModel.TrainingCompleted) 새 모델을 즉시 카드에 반영.
    public void Refresh() => Build();

    // ===== 옛 tkinter 런처('학습 스튜디오')에만 있던 두 기능을 Vision Studio로 흡수 =====
    // 파이썬 실행이 필요한 것뿐이라 subprocess로 부른다(코인봇 안전 — 특정 스크립트만 실행).
    private string PyExe() => _projectRoot == null ? "python"
        : Path.Combine(_projectRoot, "train", ".venv", "Scripts", "python.exe");

    // 실시간 웹캠 검출·추적·계수 데모(별도 OpenCV 창). live_demo.py 실행.
    public string? LaunchWebcamDemo()
    {
        if (_projectRoot == null) return "프로젝트 폴더를 찾지 못했습니다.";
        var py = PyExe();
        if (!File.Exists(py)) return "파이썬 환경(train/.venv)이 없습니다. SETUP.md를 먼저 보세요.";
        var script = Path.Combine(_projectRoot, "examples", "video_demo", "live_demo.py");
        if (!File.Exists(script)) return "웹캠 데모 스크립트를 찾지 못했습니다.";
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(py)
            {
                Arguments = "\"" + script + "\" --preset person",
                WorkingDirectory = Path.Combine(_projectRoot, "examples", "video_demo"),
                UseShellExecute = false,
            });
            return null;   // 성공
        }
        catch (Exception ex) { return $"웹캠 데모 실행 실패 — {FriendlyError.Describe(ex)}"; }
    }

    // 도메인별 신호등 건강검진 리포트(HTML) 생성 후 브라우저로 연다. health_check.py --open.
    public string? RunHealthCheck()
    {
        if (_projectRoot == null) return "프로젝트 폴더를 찾지 못했습니다.";
        var py = PyExe();
        if (!File.Exists(py)) return "파이썬 환경(train/.venv)이 없습니다. SETUP.md를 먼저 보세요.";
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(py)
            {
                Arguments = "-m examples._common.health_check --open",
                WorkingDirectory = _projectRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
            });
            return null;
        }
        catch (Exception ex) { return $"건강검진 실행 실패 — {FriendlyError.Describe(ex)}"; }
    }

    // 탭 점 색과 통일 — 테마 리소스 단일 출처(하드코딩 중복 제거). 검출=틸, 이상탐지=앰버, 세그=그린.
    private static Brush Res(string key, byte r, byte g, byte b)
        => (System.Windows.Application.Current?.TryFindResource(key) as Brush) ?? new SolidColorBrush(Color.FromRgb(r, g, b));
    private static readonly Brush DetectColor = Res("Accent", 0x35, 0xB0, 0xA7);
    private static readonly Brush AnomalyColor = Res("Warning", 0xE0, 0xA3, 0x2A);
    private static readonly Brush SegColor = Res("Success", 0x5F, 0xA8, 0x45);

    private void Build()
    {
        Cards.Clear();
        int trained = 0;

        // YOLO 도메인들(domains.json)
        foreach (var d in YoloDomain.Load(_projectRoot))
        {
            bool exists = _projectRoot != null && File.Exists(d.ResolveOnnx(_projectRoot));
            string metric = d.Meta?.MAP50 is double m ? $"{m * 100:F1}%" : "";
            var bits = new List<string> { $"클래스 {d.ClassNames.Length}종" };
            if (d.Meta?.Model is string mo && mo.Length > 0) bits.Add(mo);
            if (d.Meta?.NTrain is int nt) bits.Add($"학습 {nt}장");
            if (d.Meta?.Created is string cr && cr.Length > 0) bits.Add(cr);
            Cards.Add(new ModelCard
            {
                DisplayName = d.DisplayName,
                TypeLabel = "검출",
                TypeColor = DetectColor,
                Subtitle = string.Join("  ·  ", bits),
                Metric = metric,
                NavKey = "yolo",
                DomainName = d.DisplayName,
                Available = exists,
            });
            if (exists) trained++;
        }

        // 이상탐지
        if (_projectRoot != null)
        {
            var anomalyOnnx = Path.Combine(_projectRoot, "examples", "anomaly_detect", "anomaly_demo.onnx");
            bool exists = File.Exists(anomalyOnnx);
            Cards.Add(new ModelCard
            {
                DisplayName = "이상탐지 (데모)",
                TypeLabel = "이상탐지",
                TypeColor = AnomalyColor,
                Subtitle = "정상만 학습 · PatchCore(ResNet18) · 결함 히트맵 + OK/NG",
                Metric = exists ? "AUROC 1.0" : "",
                NavKey = "anomaly",
                Available = exists,
            });
            if (exists) trained++;

            // 에지 세그멘테이션
            var segOnnx = Path.Combine(_projectRoot, "train", "edge_unet_v2.onnx");
            bool segExists = File.Exists(segOnnx);
            Cards.Add(new ModelCard
            {
                DisplayName = "에지 세그멘테이션",
                TypeLabel = "세그멘테이션",
                TypeColor = SegColor,
                Subtitle = "U-Net · 픽셀 단위 에지 확률맵",
                Metric = "",
                NavKey = "seg",
                Available = segExists,
            });
            if (segExists) trained++;
        }

        Summary = $"학습된 모델 {trained}개 · 클릭하면 해당 뷰어로 이동합니다";
        NoTrainedModels = trained == 0;
    }
}
