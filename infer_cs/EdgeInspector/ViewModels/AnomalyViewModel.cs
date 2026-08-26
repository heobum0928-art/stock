using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

// 이상탐지(anomalib PatchCore) 뷰모델. YOLO/세그와 달리 bbox가 아니라 히트맵 + 점수 +
// OK/NG. pred_label(그래프 내장 임계)은 데모 데이터에선 과민하므로, 점수 대비 임계
// 슬라이더로 OK/NG를 직접 판정한다(다른 탭과 일관 + 정직).
public sealed class AnomalyViewModel : ViewModelBase, IDisposable
{
    private readonly string? _projectRoot;
    private AnomalyDetectionEngine? _engine;
    private byte[]? _rgb;
    private int _imgW, _imgH;
    private AnomalyResult? _last;

    public ObservableCollection<ThumbItem> Thumbnails { get; } = new();

    // 학습된 이상탐지 모델 전환(YOLO 탭의 도메인 드롭다운과 대칭) — 제품 라인이 여러
    // 개면(코그넥스/키엔스 실사용 패턴) 라인마다 별도 모델을 학습하고 여기서 바꿔가며 검사.
    public ObservableCollection<string> AvailableModels { get; } = new();

    private string? _selectedModelName;
    public string? SelectedModelName
    {
        get => _selectedModelName;
        set
        {
            if (!SetField(ref _selectedModelName, value)) return;
            if (value == null || _projectRoot == null) return;
            var path = Path.Combine(_projectRoot, "examples", "anomaly_detect", $"anomaly_{value}.onnx");
            if (File.Exists(path) && path != _modelPath) LoadModel(path);
        }
    }

    private void RefreshAvailableModels()
    {
        AvailableModels.Clear();
        if (_projectRoot == null) return;
        var dir = Path.Combine(_projectRoot, "examples", "anomaly_detect");
        if (!Directory.Exists(dir)) return;
        foreach (var f in Directory.EnumerateFiles(dir, "anomaly_*.onnx").OrderBy(f => f))
        {
            var name = Path.GetFileNameWithoutExtension(f);
            if (name.StartsWith("anomaly_")) name = name["anomaly_".Length..];
            AvailableModels.Add(name);
        }
    }

    private ThumbItem? _selectedThumb;
    public ThumbItem? SelectedThumb
    {
        get => _selectedThumb;
        set { if (SetField(ref _selectedThumb, value) && value != null) LoadImage(value.Path); }
    }

    private bool _loaded;
    private Process? _trainProc;
    private string? _lastTrainNormalDir;

    public AnomalyViewModel(string? projectRoot)
    {
        _projectRoot = projectRoot;
        // 무거운 로드는 탭 첫 활성화 때(EnsureLoaded) — 시작 프리징 방지.
    }

    // ===== 양품 폴더로 새 이상탐지 모델 학습 (코그넥스/키엔스식 "양품만 등록") =====
    private bool _isTraining;
    public bool IsTraining { get => _isTraining; private set => SetField(ref _isTraining, value); }

    private string _trainStatus = "";
    public string TrainStatus { get => _trainStatus; private set => SetField(ref _trainStatus, value); }

    // train_anomaly.py --normal-dir 를 서브프로세스로 실행. 무거운 anomalib 학습 로직은
    // 재구현하지 않고 검증된 스크립트를 그대로 호출한다. 완료되면 새 ONNX를 로드한다.
    private static void Trace(string msg)
    {
        try
        {
            Directory.CreateDirectory(@"C:\EdgeAI\logs");
            File.AppendAllText(@"C:\EdgeAI\logs\anomaly_click_trace.txt", $"{DateTime.Now:HH:mm:ss}  [VM] {msg}\n");
        }
        catch { }
    }

    // ===== 재학습 후보(양품인데 NG로 나온 이미지 등)를 UI에서 바로 정상 폴더에 추가 =====
    // 사장님 요청: "파일명을 매번 복사하는 게 어려워서" — 화면에서 버튼 한 번으로 지금 보는
    // 이미지를 그 모델의 양품 폴더에 넣게 한다. 어느 모델이 어느 양품 폴더로 학습됐는지는
    // 원래 기록이 없어(TrainNewModel이 폴더를 매번 새로 골라 받을 뿐 저장 안 함), 모델별
    // 매핑을 이 파일에 저장해 한 번 고르면 다음부턴 자동으로 그 폴더를 쓴다.
    private const string NormalDirsFileName = "_model_normal_dirs.json";

    private string? NormalDirsPath =>
        _projectRoot == null ? null : Path.Combine(_projectRoot, "examples", "anomaly_detect", NormalDirsFileName);

    private Dictionary<string, string> LoadNormalDirs()
    {
        var path = NormalDirsPath;
        if (path == null || !File.Exists(path)) return new();
        try
        {
            var json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<Dictionary<string, string>>(json) ?? new();
        }
        catch { return new(); }
    }

    private void SaveNormalDir(string modelName, string dir)
    {
        var path = NormalDirsPath;
        if (path == null) return;
        try
        {
            var map = LoadNormalDirs();
            map[modelName] = dir;
            File.WriteAllText(path, JsonSerializer.Serialize(map, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch { /* 매핑 저장 실패해도 학습/검사 자체엔 영향 없음 */ }
    }

    // 현재 선택된 모델의 양품 폴더를 안다면 반환(모르면 null — View가 폴더선택창을 띄운다).
    public string? NormalDirForModel(string modelName)
    {
        var dir = LoadNormalDirs().GetValueOrDefault(modelName);
        return dir != null && Directory.Exists(dir) ? dir : null;
    }

    // 지금 보고 있는 이미지를 normalDir(그 모델의 양품 폴더)에 복사하고 매핑을 기억해둔다.
    // 반환값이 null이면 성공(Status에 결과 메시지가 채워짐), 문자열이면 오류 메시지.
    public string? AddCurrentImageToRetrainSet(string normalDir)
    {
        if (_imagePath == "(이미지 없음)" || !File.Exists(_imagePath)) return "먼저 이미지를 여세요.";
        if (!Directory.Exists(normalDir)) return $"정상 폴더를 찾을 수 없습니다: {normalDir}";
        if (_selectedModelName != null) SaveNormalDir(_selectedModelName, normalDir);

        try
        {
            var srcFull = Path.GetFullPath(_imagePath);
            var dirFull = Path.GetFullPath(normalDir);
            if (srcFull.StartsWith(dirFull, StringComparison.OrdinalIgnoreCase))
            {
                Status = "이미 그 모델의 양품 폴더 안에 있는 이미지입니다.";
                return null;
            }

            var destFile = Path.Combine(normalDir, Path.GetFileName(_imagePath));
            if (File.Exists(destFile))
            {
                Status = "이미 재학습 후보로 추가된 이미지입니다.";
                return null;
            }
            File.Copy(_imagePath, destFile);
            var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
            int total = Directory.EnumerateFiles(normalDir).Count(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()));
            Status = $"'{Path.GetFileName(_imagePath)}'를 재학습 후보로 추가했습니다 (양품 폴더 총 {total}장) — " +
                      "다 모았으면 위 '양품 폴더로 새 모델 학습'에서 같은 폴더+같은 모델 이름으로 다시 학습하세요.";
            return null;
        }
        catch (Exception ex)
        {
            return $"추가 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // ===== 미검(未檢, 실제 불량인데 OK로 나온 이미지) 기록 =====
    // ★ 절대 양품 폴더에 넣으면 안 된다 — 실제 결함을 "정상"으로 가르치는 꼴이라 재학습하면
    // 오히려 그 결함을 더 못 잡게 된다(과검 케이스와 정반대 처리). 대신 모델별 "확인된 미검"
    // 폴더에 복사해서, 다음에 모델을 바꿀 때마다(재학습·버그수정 등) 이 목록으로 재현율이
    // 유지/개선되는지 검증하는 회귀테스트 세트로 쓴다 — 이번 세션 내내 채팅으로 파일명을
    // 주고받으며 손으로 하던 걸 UI에 남긴다.
    private string ConfirmedDefectsDir(string modelName) =>
        Path.Combine(_projectRoot!, "examples", "anomaly_detect", "_confirmed_defects", modelName);

    public string? AddCurrentImageToConfirmedDefects()
    {
        if (_projectRoot == null) return "프로젝트 루트를 찾을 수 없습니다.";
        if (_imagePath == "(이미지 없음)" || !File.Exists(_imagePath)) return "먼저 이미지를 여세요.";
        if (string.IsNullOrWhiteSpace(_selectedModelName)) return "먼저 모델을 선택하세요.";

        try
        {
            var dir = ConfirmedDefectsDir(_selectedModelName);
            Directory.CreateDirectory(dir);
            var destFile = Path.Combine(dir, Path.GetFileName(_imagePath));
            if (File.Exists(destFile))
            {
                Status = "이미 확인된 미검 목록에 있는 이미지입니다.";
                return null;
            }
            File.Copy(_imagePath, destFile);
            var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
            int total = Directory.EnumerateFiles(dir).Count(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()));
            Status = $"'{Path.GetFileName(_imagePath)}'를 미검(실제 불량) 목록에 기록했습니다 " +
                      $"(총 {total}장) — 양품 폴더엔 넣지 않습니다. 모델을 바꿀 때마다 이 목록으로 재현율을 확인하세요.";
            return null;
        }
        catch (Exception ex)
        {
            return $"기록 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    public void TrainNewModel(string normalDir, string name)
    {
        Trace($"TrainNewModel 진입 (IsTraining={IsTraining}, projectRoot={_projectRoot ?? "null"})");
        if (IsTraining || _projectRoot == null) { Trace("✗ IsTraining이거나 projectRoot null → 반환"); return; }
        _lastTrainNormalDir = normalDir;
        var py = Path.Combine(_projectRoot, "train", ".venv", "Scripts", "python.exe");
        Trace($"python 경로: {py} (존재={File.Exists(py)})");
        if (!File.Exists(py)) { TrainStatus = $"파이썬을 찾을 수 없습니다: {py}"; Trace("✗ python 없음"); return; }
        var script = Path.Combine(_projectRoot, "examples", "anomaly_detect", "train_anomaly.py");
        Trace($"script: {script} (존재={File.Exists(script)})");

        var psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = $"\"{script}\" --normal-dir \"{normalDir}\" --name \"{name}\"",
            WorkingDirectory = _projectRoot,
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        // venv를 확실히 쓰도록 방해 환경변수(PYTHONHOME/PYTHONPATH 등) 정리 + UTF-8.
        Models.PythonEnv.ConfigureVenv(psi, Path.Combine(_projectRoot, "train", ".venv"));

        try
        {
            _trainProc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _trainProc.OutputDataReceived += (_, e) => { if (e.Data != null) OnTrainLine(e.Data); };
            _trainProc.ErrorDataReceived += (_, e) => { if (e.Data != null) OnTrainLine(e.Data); };
            _trainProc.Exited += (_, _) => Application.Current?.Dispatcher.Invoke(() => OnTrainExited(name));
            _trainProc.Start();
            _trainProc.BeginOutputReadLine();
            _trainProc.BeginErrorReadLine();
            IsTraining = true;
            TrainStatus = "학습 시작 — 라이브러리 로딩 중… (처음엔 수 분 걸릴 수 있어요)";
            Status = "이상탐지 모델 학습 중…";
            Trace($"★ 프로세스 시작 성공 (PID={_trainProc.Id})");
        }
        catch (Exception ex)
        {
            TrainStatus = $"학습 시작 실패: {ex.Message}";
            Trace($"✗ 프로세스 시작 예외: {ex}");
        }
    }

    // 사용자가 잘못된 폴더로 학습을 시작했을 때 되돌릴 방법(작업관리자 강제종료뿐이었음).
    public void CancelTraining()
    {
        if (_trainProc == null) return;
        try { if (!_trainProc.HasExited) _trainProc.Kill(entireProcessTree: true); } catch { }
        _trainProc = null;
        IsTraining = false;
        TrainStatus = "학습을 취소했습니다.";
        Status = "학습이 취소되었습니다.";
    }

    private string _trainLog = "";
    private void OnTrainLine(string line)
    {
        Application.Current?.Dispatcher.Invoke(() =>
        {
            _trainLog += line + "\n";
            if (line.StartsWith("[")) TrainStatus = line;          // [1/4] 데이터… 같은 단계 표시
        });
    }

    private void OnTrainExited(string name)
    {
        bool ok = _trainProc?.ExitCode == 0;
        IsTraining = false;
        _trainProc = null;
        if (ok)
        {
            var onnx = Path.Combine(_projectRoot!, "examples", "anomaly_detect", $"anomaly_{name}.onnx");
            if (File.Exists(onnx))
            {
                if (_lastTrainNormalDir != null) SaveNormalDir(name, _lastTrainNormalDir);
                TrainStatus = "학습 완료! 새 모델을 불러왔습니다.";
                LoadModel(onnx);
            }
            else TrainStatus = "학습은 끝났지만 모델 파일을 찾지 못했습니다. 로그를 확인하세요.";
            return;
        }

        // 실패 — 전체 로그를 파일로 남겨(비전공자가 원인 파악·지원 요청에 쓸 수 있게) 경로를 안내.
        var logPath = SaveTrainLog(name);
        var logHint = logPath != null ? $"\n전체 기록: {logPath}" : "";

        // ★ anomalib 미설치는 정확한 패턴으로만 판정한다. 로그엔 site-packages\anomalib\… 경로가
        // 늘 들어있어 단순히 "anomalib" 포함 여부로 보면, 다른 모듈이 없어도 오진한다(실제 버그였음).
        if (_trainLog.Contains("No module named 'anomalib'"))
        {
            TrainStatus = "이상탐지 라이브러리(anomalib)가 설치돼 있지 않습니다. 운영가이드의 설치 명령을 먼저 실행하세요." + logHint;
        }
        else if (_trainLog.Contains("CUDA out of memory") || _trainLog.Contains("CUDA error"))
        {
            TrainStatus = "GPU 메모리가 부족합니다. 다른 프로그램(특히 그래픽 사용 프로그램)을 종료하고 다시 시도하세요." + logHint;
        }
        else
        {
            // 진짜 오류 줄을 뽑아 보여준다(막연한 "실패" 대신).
            var err = ExtractError(_trainLog);
            TrainStatus = (err != null ? $"학습 실패 — {err}" : "학습 실패 — 로그를 확인하세요.") + logHint;
        }
    }

    // 학습 로그에서 마지막 에러/예외 줄을 추출(원인 한 줄 표시용).
    private static string? ExtractError(string log)
    {
        string? last = null;
        foreach (var raw in log.Split('\n'))
        {
            var l = raw.Trim();
            if (l.Length == 0) continue;
            if (l.Contains("Error") || l.Contains("error") || l.Contains("Exception") || l.EndsWith("을 찾을 수 없습니다"))
                last = l;
        }
        return last != null && last.Length > 200 ? last[..200] + "…" : last;
    }

    private string? SaveTrainLog(string name)
    {
        if (_projectRoot == null) return null;
        try
        {
            var dir = Path.Combine(_projectRoot, "logs");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, $"anomaly_{name}.log");
            File.WriteAllText(path, _trainLog);
            return path;
        }
        catch { return null; }
    }

    public void EnsureLoaded()
    {
        if (_loaded) return;
        _loaded = true;
        TryLoadDefaultModel();
    }

    // 내 이미지 폴더를 통째로 열어 갤러리에 채우고 첫 장을 검사한다(한 장씩 열지 않고
    // 폴더째 넘겨보며 배치 검사 — 상용 검사툴의 기본 흐름).
    public void OpenFolder(string dir)
    {
        if (!Directory.Exists(dir)) { Status = "폴더를 찾을 수 없습니다."; return; }
        LoadThumbnails(dir);
        var first = Thumbnails.FirstOrDefault();
        if (first != null)
        {
            _selectedThumb = first; OnPropertyChanged(nameof(SelectedThumb));
            LoadImage(first.Path);
            Status = $"'{Path.GetFileName(dir)}' 폴더에서 {Thumbnails.Count}장 불러옴 — 갤러리에서 넘겨보며 검사하세요.";
        }
        else Status = "선택한 폴더에 이미지가 없습니다(png·jpg·bmp).";
    }

    private void LoadThumbnails(string? dirOverride = null)
    {
        Thumbnails.Clear();
        var dir = dirOverride ?? SampleDirForOpen;
        if (dir == null || !Directory.Exists(dir)) return;
        var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
        // _demo는 normal_test/abnormal 하위폴더 → 재귀 탐색(사용자 폴더도 하위 포함).
        var files = Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories)
            .Where(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()))
            .OrderBy(f => f).Take(200);
        foreach (var f in files)
        {
            try
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.UriSource = new Uri(f);
                bmp.DecodePixelWidth = 132;
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.CreateOptions = BitmapCreateOptions.IgnoreColorProfile;
                bmp.EndInit();
                bmp.Freeze();
                Thumbnails.Add(new ThumbItem { Path = f, Name = Path.GetFileName(f), Image = bmp });
            }
            catch { }
        }
    }

    private double _threshold = 0.8;
    public double Threshold
    {
        get => _threshold;
        set { if (SetField(ref _threshold, value)) UpdateVerdict(); }
    }

    private bool _showHeatmap = true;
    public bool ShowHeatmap
    {
        get => _showHeatmap;
        set { if (SetField(ref _showHeatmap, value)) UpdateOverlayVisibility(); }
    }

    private string _status = "이상탐지 모델을 불러오는 중…";
    public string Status { get => _status; private set => SetField(ref _status, value); }

    private string _modelPath = "(모델 없음)";
    public string ModelPath { get => _modelPath; private set => SetField(ref _modelPath, value); }

    private string _imagePath = "(이미지 없음)";
    public string ImagePath { get => _imagePath; private set => SetField(ref _imagePath, value); }

    // 파일명만(경로 없이) — 사장님 요청: 지금 보고 있는 이미지 파일명을 화면에서 바로 확인·복사해서
    // NG인데 OK로 나온 샘플 같은 걸 리포트할 때 쓸 수 있게.
    public string ImageFileName => _imagePath == "(이미지 없음)" ? "" : Path.GetFileName(_imagePath);

    private ImageSource? _image;
    public ImageSource? Image { get => _image; private set => SetField(ref _image, value); }

    private ImageSource? _heatmap;
    public ImageSource? Heatmap { get => _heatmap; private set => SetField(ref _heatmap, value); }

    // OK/NG 배지
    private string _verdict = "";
    public string Verdict { get => _verdict; private set => SetField(ref _verdict, value); }

    private Brush _verdictColor = Brushes.Gray;
    public Brush VerdictColor { get => _verdictColor; private set => SetField(ref _verdictColor, value); }

    private string _scoreText = "";
    public string ScoreText { get => _scoreText; private set => SetField(ref _scoreText, value); }

    private double _scoreFraction;
    public double ScoreFraction { get => _scoreFraction; private set => SetField(ref _scoreFraction, value); }

    // 히트맵 표시 여부를 오버레이 이미지 자체로 제어(간단히 재빌드)
    private void UpdateOverlayVisibility() { if (_last != null) Heatmap = ShowHeatmap ? BuildHeatmap(_last, _imgW, _imgH) : null; }

    public string? SampleDirForOpen
    {
        get
        {
            if (_projectRoot == null) return null;
            var d = Path.Combine(_projectRoot, "examples", "anomaly_detect", "_demo");
            return Directory.Exists(d) ? d : null;
        }
    }

    private void TryLoadDefaultModel()
    {
        if (_projectRoot == null) { Status = "프로젝트 루트를 찾지 못했습니다."; return; }
        RefreshAvailableModels();
        if (AvailableModels.Count == 0)
        {
            Status = "이상탐지 모델이 없습니다 — 위 '양품 폴더로 새 모델 학습' 버튼으로 내 제품 모델을 만들거나, examples/anomaly_detect/train_anomaly.py로 데모 모델을 먼저 학습하세요.";
            return;
        }
        var preferred = AvailableModels.Contains("demo") ? "demo" : AvailableModels[0];
        var onnx = Path.Combine(_projectRoot, "examples", "anomaly_detect", $"anomaly_{preferred}.onnx");
        LoadModel(onnx);
    }

    // 선택한 제품 모델을 삭제(ONNX + 학습 체크포인트(runs/Patchcore/<name>) + 스테이징 +
    // 실패 로그까지). 되돌릴 수 없음 — 삭제 확인창은 View(DeleteModel_Click)가 띄운다.
    public string? DeleteModel(string name)
    {
        if (_projectRoot == null) return "프로젝트 루트를 찾을 수 없습니다.";
        if (string.IsNullOrWhiteSpace(name)) return "삭제할 모델을 먼저 선택하세요.";
        if (IsTraining) return "학습 중에는 모델을 삭제할 수 없습니다.";
        try
        {
            bool wasSelected = string.Equals(_selectedModelName, name, StringComparison.OrdinalIgnoreCase);
            if (wasSelected)
            {
                _engine?.Dispose();
                _engine = null;
            }

            var dir = Path.Combine(_projectRoot, "examples", "anomaly_detect");
            var onnx = Path.Combine(dir, $"anomaly_{name}.onnx");
            if (File.Exists(onnx)) File.Delete(onnx);

            var runsDir = Path.Combine(dir, "runs", "Patchcore", name);
            if (Directory.Exists(runsDir)) Directory.Delete(runsDir, recursive: true);

            var stagingDir = Path.Combine(dir, "_staging", name);
            if (Directory.Exists(stagingDir)) Directory.Delete(stagingDir, recursive: true);

            var logFile = Path.Combine(_projectRoot, "logs", $"anomaly_{name}.log");
            if (File.Exists(logFile)) File.Delete(logFile);

            RefreshAvailableModels();

            if (wasSelected)
            {
                _selectedModelName = null; OnPropertyChanged(nameof(SelectedModelName));
                _rgb = null; Image = null; Heatmap = null; _last = null;
                Verdict = ""; ScoreText = ""; ScoreFraction = 0;
                ModelPath = "(모델 없음)";
                if (AvailableModels.Count > 0)
                {
                    var next = AvailableModels.Contains("demo") ? "demo" : AvailableModels[0];
                    LoadModel(Path.Combine(dir, $"anomaly_{next}.onnx"));
                }
                else
                {
                    Status = "모델을 삭제했습니다. 남은 모델이 없습니다 — 위 '양품 폴더로 새 모델 학습'으로 새로 만드세요.";
                }
            }
            return null;
        }
        catch (Exception ex)
        {
            return $"모델 삭제 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    public void LoadModel(string path)
    {
        try
        {
            _engine?.Dispose();
            _engine = new AnomalyDetectionEngine(path);
            ModelPath = path;
            RefreshAvailableModels();
            var name = Path.GetFileNameWithoutExtension(path);
            if (name.StartsWith("anomaly_")) name = name["anomaly_".Length..];
            _selectedModelName = name; OnPropertyChanged(nameof(SelectedModelName));
            Status = "이상탐지 모델 로드 완료 — 검사할 이미지를 여세요. (정상만 학습, 결함을 히트맵으로 표시)";
            LoadThumbnails();
            // 첫 샘플 자동 로드(빈 화면 방지) — 가능하면 이상(abnormal) 샘플을 먼저 보여준다.
            var first = Thumbnails.FirstOrDefault(t => t.Path.Replace('\\', '/').Contains("/abnormal/"))
                        ?? Thumbnails.FirstOrDefault();
            if (first != null)
            {
                _selectedThumb = first; OnPropertyChanged(nameof(SelectedThumb));
                LoadImage(first.Path);
            }
            else if (_rgb != null) RunInference();
        }
        catch (Exception ex)
        {
            _engine = null;
            Status = $"모델 로드 실패 — {FriendlyError.Describe(ex)}";
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
            ImagePath = path;
            OnPropertyChanged(nameof(ImageFileName));
            RunInference();
        }
        catch (Exception ex)
        {
            Status = $"이미지 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private void RunInference()
    {
        if (_engine == null || _rgb == null) return;
        try
        {
            _last = _engine.Run(_rgb, _imgW, _imgH);
            Heatmap = ShowHeatmap ? BuildHeatmap(_last, _imgW, _imgH) : null;
            UpdateVerdict();
            Status = $"이상 점수 {_last.Score:F3} · {_last.InferenceMilliseconds:F1} ms";
        }
        catch (Exception ex)
        {
            Status = $"추론 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private void UpdateVerdict()
    {
        if (_last == null) { Verdict = ""; ScoreText = ""; return; }
        bool ng = _last.Score >= Threshold;
        Verdict = ng ? "NG" : "OK";
        VerdictColor = (System.Windows.Application.Current?.TryFindResource(ng ? "Danger" : "Success") as Brush)
                       ?? new SolidColorBrush(ng ? Color.FromRgb(0xD7, 0x5A, 0x52) : Color.FromRgb(0x5F, 0xA8, 0x45));
        ScoreText = $"점수 {_last.Score:F3}  /  임계 {Threshold:F2}";
        // 점수 게이지(0~1 → 0~100%)
        ScoreFraction = Math.Max(0, Math.Min(1, _last.Score));
    }

    // 이상맵을 반투명 빨강 히트맵 BGRA 비트맵으로. 원본 위에 Stretch로 덮는다.
    // 히트맵(r.MapWidth x r.MapHeight, 항상 정사각형에 가까움 — 모델 입력이 256x256 고정)을
    // 원본 이미지 픽셀 크기(imgW x imgH, 보통 정사각형이 아님)로 리샘플해서 만든다.
    // 이유: XAML에서 원본 Image와 히트맵 Image를 같은 Grid에 각각 Stretch="Uniform"으로
    // 겹쳐 그리는데, 두 비트맵의 종횡비가 다르면 WPF가 서로 다르게 letterbox해서 히트맵
    // 위치가 실제 결함과 어긋난다(사용자 보고). 게다가 AnomalyDetectionEngine의 전처리 자체가
    // 종횡비를 무시하고 원본을 256x256으로 늘려서(stretch) 추론하므로, 히트맵을 원본에
    // 되돌릴 때도 같은 방식(종횡비 무시 리샘플)으로 늘려야 좌표가 정확히 대응한다.
    private static BitmapSource BuildHeatmap(AnomalyResult r, int imgW, int imgH)
    {
        int mapW = Math.Max(1, r.MapWidth), mapH = Math.Max(1, r.MapHeight);
        int w = Math.Max(1, imgW), h = Math.Max(1, imgH);
        var pixels = new byte[w * h * 4];
        for (int y = 0; y < h; y++)
        {
            int my = Math.Min(mapH - 1, (int)((long)y * mapH / h));
            for (int x = 0; x < w; x++)
            {
                int mx = Math.Min(mapW - 1, (int)((long)x * mapW / w));
                int mi = my * mapW + mx;
                float v = mi < r.HeatMap.Length ? r.HeatMap[mi] : 0f;   // 0..1
                int o = (y * w + x) * 4;
                // 낮은 이상도는 투명, 높을수록 진한 빨강/주황.
                pixels[o + 0] = 0;                                  // B
                pixels[o + 1] = (byte)(v * v * 120);               // G(고강도에서 주황 기미)
                pixels[o + 2] = (byte)(80 + v * 175);              // R
                pixels[o + 3] = (byte)Math.Clamp(v * 210, 0, 210); // A
            }
        }
        var bmp = BitmapSource.Create(w, h, 96, 96, PixelFormats.Bgra32, null, pixels, w * 4);
        bmp.Freeze();
        return bmp;
    }

    public void Dispose()
    {
        _engine?.Dispose();
        // 학습 중 앱을 종료하면 python.exe가 고아 프로세스로 GPU를 계속 점유하는 걸 방지.
        try { if (_trainProc != null && !_trainProc.HasExited) _trainProc.Kill(entireProcessTree: true); } catch { }
    }
}
