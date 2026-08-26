using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace EdgeInspector.ViewModels;

// 학습 탭(WPF) — training_wizard.py(tkinter)와 동일한 파이프라인을 별도 창이 아니라
// EdgeInspector 안에서. 무거운 ultralytics 학습 자체는 여전히 파이썬(train_pipeline.py)에
// 위임하고(재구현하지 않음 — 검증된 로직 재사용), 여기는 프로세스 실행+stdout 파싱+진행률
// 표시만 담당한다. CLI 모드가 "[ XX%] stage" 형식으로 진행률을 찍으므로 정규식으로 파싱.
public sealed class TrainingViewModel : ViewModelBase
{
    private readonly string? _projectRoot;
    private Process? _proc;
    private DispatcherTimer? _curveTimer;
    private bool _wasQuick;
    private static readonly Regex ProgressLine = new(@"^\[\s*(\d+)%\]\s*(.*)$", RegexOptions.Compiled);
    // 진행 문구 속 "epoch 3/120"에서 남은 시간(ETA)을 추정하기 위한 패턴.
    private static readonly Regex EpochLine = new(@"epoch\s*(\d+)\s*/\s*(\d+)", RegexOptions.Compiled);
    private readonly System.Diagnostics.Stopwatch _trainClock = new();

    public event Action? TrainingCompleted;   // 뷰어 홈 카드 새로고침 트리거용

    public TrainingViewModel(string? projectRoot)
    {
        _projectRoot = projectRoot;
    }

    private string _dataYaml = "";
    public string DataYaml { get => _dataYaml; set => SetField(ref _dataYaml, value); }

    private string _displayName = "";
    public string DisplayName { get => _displayName; set => SetField(ref _displayName, value); }

    private string _outName = "";
    public string OutName { get => _outName; set => SetField(ref _outName, value); }

    private bool _quick = true;
    public bool Quick { get => _quick; set => SetField(ref _quick, value); }

    private bool _isTraining;
    public bool IsTraining { get => _isTraining; private set => SetField(ref _isTraining, value); }

    private double _progress;
    public double Progress { get => _progress; private set => SetField(ref _progress, value); }

    private string _status = "데이터셋(data.yaml)을 지정하고 이름을 입력한 뒤 시작하세요.";
    public string Status { get => _status; private set => SetField(ref _status, value); }

    private string _log = "";
    public string Log { get => _log; private set => SetField(ref _log, value); }

    private string _etaText = "";
    public string EtaText { get => _etaText; private set => SetField(ref _etaText, value); }

    public ObservableCollection<double> CurvePoints { get; } = new();

    private Geometry? _curveGeometry;
    public Geometry? CurveGeometry { get => _curveGeometry; private set => SetField(ref _curveGeometry, value); }

    private string _curveLabel = "";
    public string CurveLabel { get => _curveLabel; private set => SetField(ref _curveLabel, value); }

    public void SetDataset(string dataYamlPath)
    {
        DataYaml = dataYamlPath;
        var name = Path.GetFileName(Path.GetDirectoryName(dataYamlPath) ?? "");
        if (string.IsNullOrEmpty(OutName)) OutName = name;
        if (string.IsNullOrEmpty(DisplayName)) DisplayName = name;
        Status = $"데이터셋 연결됨: {dataYamlPath}";
    }

    public void PickDataYaml(string path) => SetDataset(path);

    public void Start()
    {
        if (IsTraining || _projectRoot == null) return;
        if (!File.Exists(DataYaml)) { Status = "data.yaml을 찾을 수 없습니다."; return; }
        if (string.IsNullOrWhiteSpace(DisplayName) || string.IsNullOrWhiteSpace(OutName))
        { Status = "표시 이름과 산출물 이름을 입력하세요."; return; }
        if (!Regex.IsMatch(OutName, "^[A-Za-z0-9_]+$"))
        { Status = "산출물 이름은 영문/숫자/밑줄만 됩니다."; return; }

        var py = Path.Combine(_projectRoot, "train", ".venv", "Scripts", "python.exe");
        if (!File.Exists(py)) { Status = $"파이썬을 찾을 수 없습니다: {py}"; return; }

        _wasQuick = Quick;
        var args = $"-m examples._common.train_pipeline --data \"{DataYaml}\" --name \"{OutName}\" --display \"{DisplayName}\"" + (Quick ? " --quick" : "");
        var psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = args,
            WorkingDirectory = _projectRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        // 파이썬 stdout UTF-8 + venv를 확실히 쓰도록 방해 환경변수(PYTHONHOME/PYTHONPATH) 정리.
        Models.PythonEnv.ConfigureVenv(psi, Path.Combine(_projectRoot, "train", ".venv"));

        try
        {
            _proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _proc.OutputDataReceived += (_, e) => { if (e.Data != null) OnLine(e.Data); };
            _proc.ErrorDataReceived += (_, e) => { if (e.Data != null) OnLine(e.Data); };
            _proc.Exited += (_, _) => Application.Current?.Dispatcher.Invoke(OnExited);
            _proc.Start();
            _proc.BeginOutputReadLine();
            _proc.BeginErrorReadLine();

            IsTraining = true; Progress = 0; Log = ""; CurvePoints.Clear();
            _trainClock.Restart(); EtaText = "";
            Status = "학습 시작…";
            _curveTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            _curveTimer.Tick += (_, _) => PollCurve();
            _curveTimer.Start();
        }
        catch (Exception ex)
        {
            Status = $"학습 시작 실패: {ex.Message}";
        }
    }

    // 사용자가 직접 시작한 자식 프로세스를 PID로 특정해 종료(다른 python 프로세스는 건드리지 않음).
    public void Stop()
    {
        if (_proc == null || _proc.HasExited) return;
        try
        {
            Status = "중단 중…";
            _proc.Kill(entireProcessTree: true);
        }
        catch { /* 이미 종료됐을 수 있음 */ }
    }

    private void OnLine(string line)
    {
        Application.Current?.Dispatcher.Invoke(() =>
        {
            var m = ProgressLine.Match(line);
            if (m.Success)
            {
                Progress = double.Parse(m.Groups[1].Value) / 100.0;
                Status = m.Groups[2].Value;
                UpdateEta(m.Groups[2].Value);
            }
            Log += line + "\n";
        });
    }

    // "epoch N/M"에서 남은 시간을 추정. 완료한 epoch 수로 epoch당 평균 시간을 구하고
    // 남은 epoch에 곱한다(초반 1 epoch은 표본이 부족해 "추정 중"으로 표시).
    private void UpdateEta(string stage)
    {
        var e = EpochLine.Match(stage);
        if (!e.Success) return;
        int cur = int.Parse(e.Groups[1].Value), total = int.Parse(e.Groups[2].Value);
        if (total <= 0 || cur <= 0) return;
        double elapsed = _trainClock.Elapsed.TotalSeconds;
        if (cur < 1 || elapsed < 1) { EtaText = "남은 시간 추정 중…"; return; }
        double perEpoch = elapsed / cur;
        int remain = Math.Max(0, total - cur);
        var eta = TimeSpan.FromSeconds(perEpoch * remain);
        string t = eta.TotalHours >= 1 ? $"{(int)eta.TotalHours}시간 {eta.Minutes}분"
                 : eta.TotalMinutes >= 1 ? $"{eta.Minutes}분 {eta.Seconds}초"
                 : $"{eta.Seconds}초";
        EtaText = $"epoch {cur}/{total} · 남은 시간 약 {t}";
    }

    private void OnExited()
    {
        _curveTimer?.Stop(); _curveTimer = null;
        _trainClock.Stop();
        EtaText = "";
        bool ok = _proc?.ExitCode == 0;
        IsTraining = false;
        if (ok)
        {
            Progress = 1.0;
            Status = _wasQuick
                ? "완료! 단, '빠르게 확인만'으로 만든 모델이라 정확도가 낮습니다. 체크 해제 후 다시 학습해야 실사용 가능합니다."
                : "완료! 홈에서 새 모델을 확인하세요.";
            TrainingCompleted?.Invoke();
        }
        else if (!Log.Contains("사용자 중단"))
        {
            Status = "학습이 중단되었거나 실패했습니다. 로그를 확인하세요.";
        }
        _proc = null;
    }

    private void PollCurve()
    {
        if (_projectRoot == null || string.IsNullOrEmpty(OutName)) return;
        try
        {
            var runRoot = Path.Combine(_projectRoot, "examples", OutName, "runs");
            if (!Directory.Exists(runRoot)) return;
            var csv = Directory.EnumerateFiles(runRoot, "results.csv", SearchOption.AllDirectories)
                .OrderByDescending(f => File.GetLastWriteTimeUtc(f)).FirstOrDefault();
            if (csv == null) return;
            var lines = File.ReadAllLines(csv);
            if (lines.Length < 2) return;
            var header = lines[0].Split(',').Select(h => h.Trim()).ToList();
            int idx = header.IndexOf("metrics/mAP50(B)");
            if (idx < 0) return;
            var vals = new List<double>();
            for (int i = 1; i < lines.Length; i++)
            {
                var cells = lines[i].Split(',');
                if (idx < cells.Length && double.TryParse(cells[idx], System.Globalization.CultureInfo.InvariantCulture, out double v))
                    vals.Add(v);
            }
            CurvePoints.Clear();
            foreach (var v in vals) CurvePoints.Add(v);
            CurveGeometry = BuildCurveGeometry(vals);
            if (vals.Count > 0) CurveLabel = $"mAP50 {vals[^1]:F3}  (epoch {vals.Count})";
        }
        catch { /* 곡선은 부가기능 — 오류가 학습을 방해하지 않음 */ }
    }

    // 0..1 단위 상자에 정규화된 꺾은선 지오메트리. View에서 Path Stretch="Fill"로 컨테이너
    // 크기에 맞춰 자동 확대(반응형 — SizeChanged 처리 불필요).
    private static Geometry? BuildCurveGeometry(List<double> vals)
    {
        if (vals.Count == 0) return null;
        double Y(double v) => 1.0 - Math.Clamp(v, 0.0, 1.0);
        var figure = new PathFigure { StartPoint = new Point(0, Y(vals[0])), IsClosed = false };
        if (vals.Count == 1)
        {
            figure.Segments.Add(new LineSegment(new Point(1, Y(vals[0])), true));
        }
        else
        {
            for (int i = 1; i < vals.Count; i++)
                figure.Segments.Add(new LineSegment(new Point((double)i / (vals.Count - 1), Y(vals[i])), true));
        }
        var geo = new PathGeometry();
        geo.Figures.Add(figure);
        return geo;
    }
}
