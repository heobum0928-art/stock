using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using EdgeInspector.Models;
using EdgeInspector.ViewModels;
using EdgeInspector.Views;

namespace EdgeInspector;

public partial class MainWindow : Window
{
    // 탭 인덱스: 0=홈 1=가이드 2=라벨링 3=학습 4=객체검출 5=이상탐지 6=세그라벨링 7=세그멘테이션
    private const int TabHome = 0, TabGuide = 1, TabLabeling = 2, TabTraining = 3, TabYolo = 4,
        TabAnomaly = 5, TabSegLabeling = 6, TabSeg = 7;

    private readonly ShellViewModel _shell;
    private readonly string? _projectRoot;

    private readonly HomeView _homeView = new();
    private readonly GuideView _guideView = new();
    private readonly LabelingView _labelingView = new();
    private readonly TrainingView _trainingView = new();
    private readonly YoloView _yoloView = new();
    private readonly AnomalyView _anomalyView = new();
    private readonly SegLabelingView _segLabelingView = new();
    private readonly SegmentationView _segView = new();

    public MainWindow() : this(null) { }

    public MainWindow(string? initialDomain)
    {
        InitializeComponent();
        _projectRoot = ProjectPaths.FindRoot();
        _shell = new ShellViewModel(_projectRoot, initialDomain);
        Closed += (_, _) => _shell.Dispose();

        _homeView.DataContext = _shell.HomeVm;
        _labelingView.DataContext = _shell.LabelingVm;
        _trainingView.DataContext = _shell.TrainingVm;
        _yoloView.DataContext = _shell.YoloVm;
        _anomalyView.DataContext = _shell.AnomalyVm;
        _segLabelingView.DataContext = _shell.SegLabelingVm;
        _segView.DataContext = _shell.EdgeVm;
        _homeView.CardActivated += OnCardActivated;
        _homeView.LabelStepRequested += () => Tabs.SelectedIndex = TabLabeling;
        _homeView.TrainStepRequested += () => Tabs.SelectedIndex = TabTraining;

        // 학습 완료 시 홈의 "내 모델" 카드 목록을 새로고침(방금 만든 모델이 바로 보이게).
        _shell.TrainingVm.TrainingCompleted += () => _shell.HomeVm.Refresh();

        ((TabItem)Tabs.Items[TabHome]).Content = _homeView;
        ((TabItem)Tabs.Items[TabGuide]).Content = _guideView;
        ((TabItem)Tabs.Items[TabLabeling]).Content = _labelingView;
        ((TabItem)Tabs.Items[TabTraining]).Content = _trainingView;
        ((TabItem)Tabs.Items[TabYolo]).Content = _yoloView;
        ((TabItem)Tabs.Items[TabAnomaly]).Content = _anomalyView;
        ((TabItem)Tabs.Items[TabSegLabeling]).Content = _segLabelingView;
        ((TabItem)Tabs.Items[TabSeg]).Content = _segView;

        // 탭이 처음 열릴 때만 그 탭의 무거운 로드를 수행(시작 시 홈만 즉시 렌더 → 프리징 제거).
        Tabs.SelectionChanged += (s, e) =>
        {
            if (!ReferenceEquals(e.Source, Tabs)) return;
            EnsureTabLoaded(Tabs.SelectedIndex);
        };

        Tabs.SelectedIndex = initialDomain != null ? TabYolo : TabHome;
        EnsureTabLoaded(Tabs.SelectedIndex);

        // 개발용 렌더 캡처: 환경변수 EDGEINSPECTOR_SHOT=1이면 로드 후 각 탭을 PNG로 렌더 저장
        // (RustDesk 원격 세션에서 일반 화면캡처가 WPF GPU 합성을 못 잡아, 디자인 확인용).
        if (Environment.GetEnvironmentVariable("EDGEINSPECTOR_SHOT") == "1")
            Loaded += (_, _) => CaptureAllTabs();
    }

    private void CaptureAllTabs()
    {
        int idx = 0;
        var t = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(2800) };
        t.Tick += (_, _) =>
        {
            if (idx > 0) SaveRender(idx - 1);
            if (idx >= Tabs.Items.Count) { t.Stop(); return; }
            Tabs.SelectedIndex = idx;
            idx++;
        };
        t.Start();
    }

    private void SaveRender(int tab)
    {
        try
        {
            int w = (int)ActualWidth, h = (int)ActualHeight;
            if (w <= 0 || h <= 0) return;
            var rtb = new System.Windows.Media.Imaging.RenderTargetBitmap(w, h, 96, 96, System.Windows.Media.PixelFormats.Pbgra32);
            rtb.Render(this);
            var enc = new System.Windows.Media.Imaging.PngBitmapEncoder();
            enc.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(rtb));
            var p = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"edgeinspector_tab{tab}.png");
            using var fs = System.IO.File.Create(p);
            enc.Save(fs);
        }
        catch { }
    }

    private void OnCardActivated(ModelCard card)
    {
        switch (card.NavKey)
        {
            case "yolo":
                if (card.DomainName != null)
                {
                    var d = _shell.YoloVm.Domains.FirstOrDefault(x => x.DisplayName == card.DomainName);
                    if (d != null) _shell.YoloVm.SelectedDomain = d;
                }
                Tabs.SelectedIndex = TabYolo;
                break;
            case "anomaly":
                Tabs.SelectedIndex = TabAnomaly;
                break;
            case "seg":
                Tabs.SelectedIndex = TabSeg;
                break;
        }
    }

    private void EnsureTabLoaded(int index)
    {
        switch (index)
        {
            case TabYolo: _shell.YoloVm.EnsureLoaded(); break;
            case TabAnomaly: _shell.AnomalyVm.EnsureLoaded(); break;
            case TabSeg: _shell.EdgeVm.EnsureLoaded(); break;
        }
    }
}
