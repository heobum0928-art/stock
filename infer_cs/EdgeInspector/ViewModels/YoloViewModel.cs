using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

// 갤러리 썸네일 한 칸.
public sealed class ThumbItem
{
    public required string Path { get; init; }
    public required string Name { get; init; }
    public required ImageSource Image { get; init; }
}

// 검출 결과 리스트 한 줄.
public sealed class DetItem
{
    public required string ClassName { get; init; }
    public required string ScoreText { get; init; }
    public required Brush Color { get; init; }
}

// 클래스 범례 한 줄(좌측 사이드바 LABEL CLASSES).
public sealed class LegendItem
{
    public required int Index { get; init; }
    public required string Name { get; init; }
    public required Brush Color { get; init; }
}

public sealed class YoloViewModel : ViewModelBase, IDisposable
{
    private readonly string? _projectRoot;
    private YoloDetectionEngine? _engine;
    private byte[]? _rgb;
    private int _imgW, _imgH;

    private static Color ClassColor(int id)
    {
        double hue = (id * 137.508) % 360.0;
        return HsvToRgb(hue, 0.68, 1.0);
    }

    private static Color HsvToRgb(double h, double s, double v)
    {
        double c = v * s;
        double x = c * (1 - Math.Abs((h / 60.0) % 2 - 1));
        double m = v - c;
        double r = 0, g = 0, b = 0;
        if (h < 60) { r = c; g = x; }
        else if (h < 120) { r = x; g = c; }
        else if (h < 180) { g = c; b = x; }
        else if (h < 240) { g = x; b = c; }
        else if (h < 300) { r = x; b = c; }
        else { r = c; b = x; }
        return Color.FromRgb((byte)((r + m) * 255), (byte)((g + m) * 255), (byte)((b + m) * 255));
    }

    public IReadOnlyList<YoloDomain> Domains { get; }
    public ObservableCollection<ThumbItem> Thumbnails { get; } = new();
    public ObservableCollection<DetItem> Detections { get; } = new();
    public ObservableCollection<LegendItem> ClassLegend { get; } = new();

    // 좌측 사이드바 표시용 구조화 정보
    private string _domainName = "";
    public string DomainName { get => _domainName; private set => SetField(ref _domainName, value); }

    private string _accuracyText = "—";
    public string AccuracyText { get => _accuracyText; private set => SetField(ref _accuracyText, value); }

    private double _accuracyFraction;
    public double AccuracyFraction { get => _accuracyFraction; private set => SetField(ref _accuracyFraction, value); }

    private string _modelText = "—";
    public string ModelText { get => _modelText; private set => SetField(ref _modelText, value); }

    private string _trainInfoText = "—";
    public string TrainInfoText { get => _trainInfoText; private set => SetField(ref _trainInfoText, value); }

    private YoloDomain? _selectedDomain;
    public YoloDomain? SelectedDomain
    {
        get => _selectedDomain;
        set { if (SetField(ref _selectedDomain, value)) LoadDomainModel(); }
    }

    private ThumbItem? _selectedThumb;
    public ThumbItem? SelectedThumb
    {
        get => _selectedThumb;
        set { if (SetField(ref _selectedThumb, value) && value != null) LoadImage(value.Path); }
    }

    private double _scoreThreshold = 0.25;
    public double ScoreThreshold
    {
        get => _scoreThreshold;
        set { if (SetField(ref _scoreThreshold, value)) RunInference(); }
    }

    // 정답(GT) 라벨 오버레이 — 예측과 나란히 비교(이미지별 예측 검토). images/val 옆의
    // labels/val에서 같은 파일명(.txt)을 찾아 점선 박스로 겹쳐 그린다.
    private bool _showGroundTruth;
    public bool ShowGroundTruth
    {
        get => _showGroundTruth;
        set { if (SetField(ref _showGroundTruth, value)) RunInference(); }
    }

    private string _status = "도메인을 고르세요.";
    public string Status { get => _status; private set => SetField(ref _status, value); }

    private string _detCountText = "";
    public string DetCountText { get => _detCountText; private set => SetField(ref _detCountText, value); }

    private bool _noDetections;
    public bool NoDetections { get => _noDetections; private set => SetField(ref _noDetections, value); }

    private string _domainInfo = "";
    public string DomainInfo { get => _domainInfo; private set => SetField(ref _domainInfo, value); }

    private string _imagePath = "(이미지 없음)";
    public string ImagePath { get => _imagePath; private set => SetField(ref _imagePath, value); }

    private ImageSource? _image;
    public ImageSource? Image { get => _image; private set => SetField(ref _image, value); }

    private ImageSource? _overlay;
    public ImageSource? Overlay { get => _overlay; private set => SetField(ref _overlay, value); }

    // 이미지가 없을 때 안내 오버레이(빈 화면 방지)
    private bool _hasImage;
    public bool HasImage { get => _hasImage; private set => SetField(ref _hasImage, value); }

    private bool _hasReport;
    public bool HasReport { get => _hasReport; private set => SetField(ref _hasReport, value); }

    // 평가 리포트(혼동행렬·PR곡선·정답비교·재학습 이력) HTML을 기본 브라우저로 연다.
    // WPF에 차트를 다시 구현하지 않고, 파이썬이 이미 만든 풍부한 리포트를 그대로 활용.
    public void OpenReport()
    {
        var rel = SelectedDomain?.Meta?.ReportRelPath;
        if (_projectRoot == null || string.IsNullOrEmpty(rel)) return;
        var full = Path.Combine(_projectRoot, rel.Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(full)) { Status = "평가 리포트 파일을 찾지 못했습니다."; return; }
        try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(full) { UseShellExecute = true }); }
        catch (Exception ex) { Status = $"리포트 열기 실패 — {FriendlyError.Describe(ex)}"; }
    }

    private bool _loaded;

    public YoloViewModel(string? projectRoot, string? initialDomain = null)
    {
        _projectRoot = projectRoot;
        Domains = YoloDomain.Load(projectRoot);
        // 무거운 모델·썸네일·추론 로드는 생성자에서 하지 않는다(시작 시 UI 프리징 방지).
        // 탭이 처음 열릴 때 EnsureLoaded()로 로드한다. 여기선 선택 도메인만 정해둔다.
        _selectedDomain = (initialDomain != null
                              ? Domains.FirstOrDefault(d => d.DisplayName == initialDomain)
                              : null)
                          ?? (Domains.Count > 0 ? Domains[0] : null);
        UpdateDomainInfo();
    }

    // 탭이 처음 활성화될 때 1회 호출 — 모델 로드 + 썸네일 + 첫 샘플 자동 추론.
    public void EnsureLoaded()
    {
        if (_loaded) return;
        _loaded = true;
        LoadDomainModel();
    }

    public string? SampleDirForOpen =>
        _projectRoot != null && SelectedDomain != null ? SelectedDomain.ResolveSampleDir(_projectRoot) : null;

    private void UpdateDomainInfo()
    {
        ClassLegend.Clear();
        if (SelectedDomain == null)
        {
            DomainInfo = ""; DomainName = ""; AccuracyText = "—"; ModelText = "—"; TrainInfoText = "—";
            return;
        }
        DomainName = SelectedDomain.DisplayName;
        var m = SelectedDomain.Meta;
        // 평가 리포트(혼동행렬·PR곡선·재학습 이력) 열기 버튼 표시 여부 — 실제 파일이 있을 때만.
        HasReport = _projectRoot != null && !string.IsNullOrEmpty(m?.ReportRelPath)
                    && File.Exists(Path.Combine(_projectRoot, m!.ReportRelPath!.Replace('/', Path.DirectorySeparatorChar)));
        AccuracyText = m?.MAP50 is double v ? $"{v * 100:F1}%" : "—";
        AccuracyFraction = m?.MAP50 is double v2 ? v2 : 0.0;
        ModelText = string.IsNullOrEmpty(m?.Model) ? "—" : m!.Model!;
        var bits = new List<string> { $"클래스 {SelectedDomain.ClassNames.Length}종" };
        if (m?.NTrain is int nt) bits.Add($"학습 {nt}장");
        if (!string.IsNullOrEmpty(m?.Created)) bits.Add(m!.Created!);
        else if (!string.IsNullOrEmpty(m?.Note)) bits.Add(m!.Note!);
        TrainInfoText = string.Join("  ·  ", bits);

        for (int i = 0; i < SelectedDomain.ClassNames.Length; i++)
            ClassLegend.Add(new LegendItem { Index = i, Name = SelectedDomain.ClassNames[i], Color = new SolidColorBrush(ClassColor(i)) });

        var classes = $"클래스 {SelectedDomain.ClassNames.Length}종: {string.Join(", ", SelectedDomain.ClassNames)}";
        var metaSummary = m?.Summary();
        DomainInfo = string.IsNullOrEmpty(metaSummary) ? classes : $"{metaSummary}   ·   {classes}";
    }

    private void LoadDomainModel()
    {
        UpdateDomainInfo();
        _rgb = null; _imgW = _imgH = 0;
        Image = null; Overlay = null; HasImage = false; ImagePath = "(이미지 없음)";
        Detections.Clear(); DetCountText = "";
        Thumbnails.Clear(); _selectedThumb = null; OnPropertyChanged(nameof(SelectedThumb));

        if (_projectRoot == null) { Status = "프로젝트 루트를 찾지 못했습니다."; return; }
        if (SelectedDomain == null) { Status = "등록된 도메인이 없습니다 — 학습 마법사로 모델을 만들어보세요."; return; }
        var onnx = SelectedDomain.ResolveOnnx(_projectRoot);
        if (!File.Exists(onnx))
        {
            Status = $"모델 없음 — 먼저 '② 학습' 탭에서 이 데이터로 학습을 완료하세요.";
            _engine?.Dispose(); _engine = null;
            return;
        }
        try
        {
            _engine?.Dispose();
            _engine = new YoloDetectionEngine(onnx, SelectedDomain.ClassNames);
            LoadThumbnails();
            // 첫 샘플을 자동으로 열어 화면을 바로 채운다(빈 화면이 제일 허접해 보이므로).
            if (Thumbnails.Count > 0)
            {
                _selectedThumb = Thumbnails[0]; OnPropertyChanged(nameof(SelectedThumb));
                LoadImage(Thumbnails[0].Path);
            }
            else
            {
                Status = $"'{SelectedDomain.DisplayName}' 모델 로드 완료 — 이미지를 여세요.";
            }
        }
        catch (Exception ex)
        {
            _engine = null;
            Status = $"모델 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private void LoadThumbnails()
    {
        Thumbnails.Clear();
        var dir = SampleDirForOpen;
        if (dir == null || !Directory.Exists(dir)) return;
        var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
        var files = Directory.EnumerateFiles(dir)
            .Where(f => exts.Contains(System.IO.Path.GetExtension(f).ToLowerInvariant()))
            .OrderBy(f => f).Take(60);
        foreach (var f in files)
        {
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.UriSource = new Uri(f);
                bmp.DecodePixelWidth = 132;   // 썸네일 크기로만 디코드(메모리·속도)
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.CreateOptions = BitmapCreateOptions.IgnoreColorProfile;
                bmp.EndInit();
                bmp.Freeze();
                Thumbnails.Add(new ThumbItem { Path = f, Name = System.IO.Path.GetFileName(f), Image = bmp });
            }
            catch { /* 개별 이미지 실패는 건너뜀 */ }
        }
    }

    public void LoadImage(string path)
    {
        try
        {
            var decoder = BitmapDecoder.Create(new Uri(path), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            var rgb24 = new FormatConvertedBitmap(decoder.Frames[0], PixelFormats.Rgb24, null, 0);
            rgb24.Freeze();
            _imgW = rgb24.PixelWidth; _imgH = rgb24.PixelHeight;
            int stride = _imgW * 3;
            _rgb = new byte[stride * _imgH];
            rgb24.CopyPixels(_rgb, stride, 0);

            var display = new FormatConvertedBitmap(decoder.Frames[0], PixelFormats.Bgra32, null, 0);
            display.Freeze();
            Image = display;
            HasImage = true;
            ImagePath = path;
            RunInference();
        }
        catch (Exception ex)
        {
            Status = $"이미지 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // images/val 안의 이미지 경로 → labels/val 옆 폴더의 같은 이름 .txt(YOLO 정규화 포맷)를
    // 찾아 픽셀 좌표 박스 목록으로 변환. 없으면 빈 리스트(검증셋 밖 이미지는 GT가 없을 수 있음).
    private List<(float x1, float y1, float x2, float y2, int cls)> LoadGroundTruth(string imagePath)
    {
        var boxes = new List<(float, float, float, float, int)>();
        try
        {
            var dir = System.IO.Path.GetDirectoryName(imagePath);
            if (dir == null) return boxes;
            var labelsDir = dir.Replace($"{System.IO.Path.DirectorySeparatorChar}images{System.IO.Path.DirectorySeparatorChar}",
                                        $"{System.IO.Path.DirectorySeparatorChar}labels{System.IO.Path.DirectorySeparatorChar}");
            var txt = System.IO.Path.Combine(labelsDir, System.IO.Path.GetFileNameWithoutExtension(imagePath) + ".txt");
            if (!File.Exists(txt)) return boxes;
            foreach (var line in File.ReadAllLines(txt))
            {
                var p = line.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (p.Length != 5) continue;
                if (!int.TryParse(p[0], out int cls)) continue;
                if (!float.TryParse(p[1], System.Globalization.CultureInfo.InvariantCulture, out float cx)) continue;
                if (!float.TryParse(p[2], System.Globalization.CultureInfo.InvariantCulture, out float cy)) continue;
                if (!float.TryParse(p[3], System.Globalization.CultureInfo.InvariantCulture, out float w)) continue;
                if (!float.TryParse(p[4], System.Globalization.CultureInfo.InvariantCulture, out float h)) continue;
                float x1 = (cx - w / 2) * _imgW, y1 = (cy - h / 2) * _imgH;
                float x2 = (cx + w / 2) * _imgW, y2 = (cy + h / 2) * _imgH;
                boxes.Add((x1, y1, x2, y2, cls));
            }
        }
        catch { /* GT는 부가 기능 — 못 읽어도 예측은 정상 진행 */ }
        return boxes;
    }

    private void RunInference()
    {
        if (_engine == null || _rgb == null) return;
        try
        {
            var result = _engine.Run(_rgb, _imgW, _imgH, (float)ScoreThreshold);
            var gt = ShowGroundTruth && ImagePath != "(이미지 없음)" ? LoadGroundTruth(ImagePath) : null;
            Overlay = BuildOverlay(result, gt);
            Detections.Clear();
            foreach (var d in result.Detections)
                Detections.Add(new DetItem
                {
                    ClassName = d.ClassName,
                    ScoreText = $"{d.Score * 100:F0}%",
                    Color = new SolidColorBrush(ClassColor(d.ClassId)),
                });
            DetCountText = $"검출 {result.Detections.Count}건";
            NoDetections = _rgb != null && result.Detections.Count == 0;
            Status = $"{result.Detections.Count}개 검출 · {result.InferenceMilliseconds:F1} ms · thr {ScoreThreshold:F2}";
        }
        catch (Exception ex)
        {
            Status = $"추론 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // 현재 이미지로 추론 속도를 측정(코그넥스/키엔스식 처리량 확인). 워밍업 후 여러 번
    // 돌려 중앙값 ms와 초당 처리장수(FPS)를 보고한다 — 단발 지연보다 현실적인 지표.
    public void RunBenchmark()
    {
        if (_engine == null || _rgb == null) { Status = "먼저 이미지를 여세요."; return; }
        try
        {
            const int warmup = 3, iters = 30;
            for (int i = 0; i < warmup; i++) _engine.Run(_rgb, _imgW, _imgH, (float)ScoreThreshold);
            var times = new List<double>(iters);
            for (int i = 0; i < iters; i++)
                times.Add(_engine.Run(_rgb, _imgW, _imgH, (float)ScoreThreshold).InferenceMilliseconds);
            times.Sort();
            double median = times[times.Count / 2];
            double fps = median > 0 ? 1000.0 / median : 0;
            Status = $"속도 측정({iters}회 중앙값): {median:F1} ms · 약 {fps:F0} FPS · 입력 {_imgW}x{_imgH}";
        }
        catch (Exception ex)
        {
            Status = $"속도 측정 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private DrawingImage BuildOverlay(YoloResult result, List<(float x1, float y1, float x2, float y2, int cls)>? gt)
    {
        var group = new DrawingGroup();
        // 투명한 전체 이미지 사각형으로 DrawingImage 경계를 원본 이미지 크기에 고정한다
        // (없으면 박스들의 bounding box로 축소돼 Stretch=Uniform 정렬이 어긋남).
        if (_imgW > 0 && _imgH > 0)
            group.Children.Add(new GeometryDrawing(Brushes.Transparent, null,
                new RectangleGeometry(new Rect(0, 0, _imgW, _imgH))));
        var typeface = new Typeface("Segoe UI");

        // GT(정답) 박스 — 점선, 라벨 없이 예측과 구분(예측=실선+신뢰도, GT=점선).
        if (gt != null)
        {
            foreach (var (x1, y1, x2, y2, cls) in gt)
            {
                var color = ClassColor(cls);
                var pen = new Pen(new SolidColorBrush(color), Math.Max(1.5, _imgW / 400.0))
                { DashStyle = new DashStyle(new double[] { 4, 3 }, 0) };
                group.Children.Add(new GeometryDrawing(null, pen, new RectangleGeometry(new Rect(x1, y1, x2 - x1, y2 - y1))));
            }
        }

        foreach (var d in result.Detections)
        {
            var color = ClassColor(d.ClassId);
            var pen = new Pen(new SolidColorBrush(color), Math.Max(1.5, _imgW / 400.0));
            var rect = new Rect(d.X1, d.Y1, d.X2 - d.X1, d.Y2 - d.Y1);
            group.Children.Add(new GeometryDrawing(null, pen, new RectangleGeometry(rect)));

            double fontSize = Math.Max(10, _imgW / 45.0);
            var text = new FormattedText($"{d.ClassName} {d.Score:F2}",
                System.Globalization.CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                typeface, fontSize, Brushes.Black, 1.0);
            double ty = Math.Max(0, d.Y1 - text.Height);
            var bg = new RectangleGeometry(new Rect(d.X1, ty, text.Width + 4, text.Height));
            group.Children.Add(new GeometryDrawing(new SolidColorBrush(color), null, bg));
            group.Children.Add(new GeometryDrawing(Brushes.Black, null,
                text.BuildGeometry(new Point(d.X1 + 2, ty))));
        }
        var img = new DrawingImage(group);
        img.Freeze();
        return img;
    }

    public void Dispose() => _engine?.Dispose();
}
