using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class LabelingView : UserControl
{
    private Point? _dragStart;
    private Rectangle? _tempRect;

    // ===== 확대/축소(줌 이미지가 클수록 정밀한 박스 그리기에 필수 — 반도체 검사 이미지처럼
    // 1만 픽셀 넘는 이미지는 줌 없이는 클릭 1픽셀이 이미지 수십 픽셀이라 박스가 부정확해짐) =====
    private readonly ScaleTransform _zoomScale = new(1, 1);
    private readonly TranslateTransform _zoomTranslate = new(0, 0);
    private Point? _panStart;
    private const double MaxZoom = 40.0;   // 큰 이미지에서 1:1 근접 확대까지 허용

    private readonly System.Windows.Threading.DispatcherTimer _coachTimer;

    public LabelingView()
    {
        InitializeComponent();
        var grp = new TransformGroup();
        grp.Children.Add(_zoomScale);
        grp.Children.Add(_zoomTranslate);
        ZoomGrid.RenderTransform = grp;

        ZoomGrid.MouseWheel += ZoomGrid_MouseWheel;
        ZoomGrid.MouseRightButtonDown += ZoomGrid_PanStart;
        ZoomGrid.MouseMove += ZoomGrid_PanMove;
        ZoomGrid.MouseRightButtonUp += ZoomGrid_PanEnd;

        PreviewKeyDown += LabelingView_PreviewKeyDown;
        DataContextChanged += LabelingView_DataContextChanged;

        // 코치(화살표+말풍선) 갱신 — 상태 변화를 일일이 구독하는 대신 짧은 주기로 재계산해
        // 항상 정확하고(자기치유), 창 크기 변경에도 자동 대응한다.
        _coachTimer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
        _coachTimer.Tick += (_, _) => UpdateCoach();
        Loaded += (_, _) => _coachTimer.Start();
        Unloaded += (_, _) => _coachTimer.Stop();
    }

    private LabelingViewModel? Vm => DataContext as LabelingViewModel;

    // 이미지가 바뀔 때(다음 이미지 클릭 등) 줌/팬 상태를 리셋 — 안 하면 확대된 채로 다음
    // 이미지가 열려 화면 구석만 보이는 혼란을 준다(초보자 대상 도구라 특히 치명적).
    private LabelingViewModel? _subscribedVm;
    private void LabelingView_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_subscribedVm != null)
        {
            _subscribedVm.PropertyChanged -= Vm_PropertyChanged;
            _subscribedVm.SaveFailed -= OnSaveFailed;
        }
        _subscribedVm = DataContext as LabelingViewModel;
        if (_subscribedVm != null)
        {
            _subscribedVm.PropertyChanged += Vm_PropertyChanged;
            _subscribedVm.SaveFailed += OnSaveFailed;
        }
    }

    // 이미지 전환 때 조용히 실행되는 자동저장(SaveCurrent)이 실패해도 예전엔 그냥 묻혔다 —
    // 방금 그린 박스가 디스크에 안 남았는데 사용자는 저장된 줄 아는 게 가장 위험한 유형이라
    // 명시적으로 안내한다(내보내기 실패의 131행과 같은 톤).
    private void OnSaveFailed(string err) =>
        MessageBox.Show(err, "자동저장 실패", MessageBoxButton.OK, MessageBoxImage.Warning);

    private void Vm_PropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LabelingViewModel.Image)) ResetZoom();
    }

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        using var dlg = new System.Windows.Forms.FolderBrowserDialog { Description = "라벨링할 이미지 폴더 선택" };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
            Vm?.OpenFolder(dlg.SelectedPath);
        Focus();
        ResetZoom();
    }

    private void AddClass_Click(object sender, RoutedEventArgs e) => TryAddClass();

    private void NewClassBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) TryAddClass();
    }

    // 이름 추가 전, 기존 클래스와 대소문자/공백만 다른 유사 이름이면 확인창을 띄운다
    // (helmet/Helmet 혼용 → 데이터 분할 → 정확도 저하 방지).
    private void TryAddClass()
    {
        var name = NewClassBox.Text;
        var similar = Vm?.FindSimilarClass(name);
        if (similar != null)
        {
            var r = MessageBox.Show(
                $"이미 '{similar}' 클래스가 있습니다. '{name.Trim()}'을(를) 따로 추가하면 같은 대상이 두 클래스로 나뉘어 정확도가 떨어질 수 있습니다.\n\n" +
                $"그래도 새 클래스로 추가할까요?\n(아니오 = 기존 '{similar}' 사용 권장)",
                "비슷한 클래스 있음", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
            if (r != MessageBoxResult.Yes) return;
        }
        Vm?.AddClass(name);
        NewClassBox.Clear();
    }

    private DateTime _lastClassClick = DateTime.MinValue;
    private int _lastClassClickIndex = -1;

    // 더블클릭=이름변경, 단일클릭=선택. WPF Border엔 더블클릭 이벤트가 따로 없어 시간차로 판별.
    // 인덱스로 비교(참조 비교 아님) — RenameClass가 항목을 새 인스턴스로 교체하므로, 이름을
    // 바꾼 직후 같은 행을 다시 두 번 클릭했을 때도 더블클릭으로 인식되게 하기 위함.
    private void ClassRow_Click(object sender, MouseButtonEventArgs e)
    {
        if (sender is not FrameworkElement fe || fe.Tag is not ClassItem ci) return;
        int idx = Vm?.Classes.IndexOf(ci) ?? -1;
        var now = DateTime.Now;
        bool isDouble = idx >= 0 && idx == _lastClassClickIndex && (now - _lastClassClick).TotalMilliseconds < 400;
        _lastClassClick = now; _lastClassClickIndex = idx;

        if (isDouble)
        {
            var owner = System.Windows.Window.GetWindow(this);
            var newName = owner != null ? TextPromptWindow.Ask(owner, $"'{ci.Name}'의 새 이름:", ci.Name) : null;
            if (!string.IsNullOrWhiteSpace(newName))
                Vm?.RenameClass(ci, newName);
        }
        else
        {
            Vm?.SelectClass(ci);
        }
    }

    private void Export_Click(object sender, RoutedEventArgs e)
    {
        var (dataYaml, train, val, error, warning) = Vm?.Export() ?? (null, 0, 0, "뷰모델 없음", null);
        if (error != null)
        {
            MessageBox.Show(error, "내보내기 실패", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        var msg = $"데이터셋이 만들어졌습니다 (train {train}, val {val}).";
        if (warning != null) msg += $"\n\n⚠ {warning}";
        msg += "\n\n'학습' 탭에서 이 데이터셋으로 바로 학습을 시작할 수 있습니다.";
        MessageBox.Show(msg, "내보내기 완료", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void BoxList_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Delete && BoxList.SelectedIndex >= 0)
        {
            var result = MessageBox.Show("선택한 박스를 삭제할까요?", "박스 삭제", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
            if (result == MessageBoxResult.Yes)
                Vm?.DeleteBox(BoxList.SelectedIndex);
        }
    }

    private void LabelingView_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Z && Keyboard.Modifiers == ModifierKeys.Control)
            Vm?.UndoLastBox();
        else if (e.Key == Key.F && Keyboard.Modifiers == ModifierKeys.None)
            ResetZoom();
    }

    // ===== 줌/팬 =====
    private void ResetZoom()
    {
        _zoomScale.ScaleX = _zoomScale.ScaleY = 1;
        _zoomTranslate.X = _zoomTranslate.Y = 0;
        ZoomLabel.Text = "100%";
    }

    private void ZoomGrid_MouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (Vm?.HasFolder != true) return;
        if (_panStart != null) return;   // 팬 드래그 중 휠이 끼어들면 기준점이 어긋나 이미지가 튐
        double factor = e.Delta > 0 ? 1.2 : 1 / 1.2;
        double newScale = Math.Clamp(_zoomScale.ScaleX * factor, 1.0, MaxZoom);
        factor = newScale / _zoomScale.ScaleX;
        if (Math.Abs(factor - 1) < 1e-6) return;
        var pos = e.GetPosition(ZoomGrid);
        _zoomTranslate.X = (_zoomTranslate.X - pos.X) * factor + pos.X;
        _zoomTranslate.Y = (_zoomTranslate.Y - pos.Y) * factor + pos.Y;
        _zoomScale.ScaleX = _zoomScale.ScaleY = newScale;
        ZoomLabel.Text = $"{newScale * 100:F0}%";
        e.Handled = true;
    }

    // 우클릭 드래그로 이동(좌클릭은 박스 그리기에 쓰므로 겹치지 않게 우클릭 사용).
    private void ZoomGrid_PanStart(object sender, MouseButtonEventArgs e)
    {
        if (_zoomScale.ScaleX <= 1.0001) return;   // 확대 상태에서만 이동
        if (_dragStart != null) return;   // 좌클릭으로 박스 그리는 중이면 마우스 캡처를 뺏지 않음
        _panStart = e.GetPosition(ZoomGrid);
        ZoomGrid.CaptureMouse();
        Cursor = Cursors.SizeAll;
    }

    private void ZoomGrid_PanMove(object sender, MouseEventArgs e)
    {
        if (_panStart == null) return;
        var pos = e.GetPosition(ZoomGrid);
        _zoomTranslate.X += (pos.X - _panStart.Value.X) * _zoomScale.ScaleX;
        _zoomTranslate.Y += (pos.Y - _panStart.Value.Y) * _zoomScale.ScaleY;
        _panStart = pos;
    }

    private void ZoomGrid_PanEnd(object sender, MouseButtonEventArgs e)
    {
        _panStart = null;
        ZoomGrid.ReleaseMouseCapture();
        Cursor = Cursors.Arrow;
    }

    // ===== 드래그로 박스 그리기 — 캔버스 좌표 → 이미지 픽셀 좌표(letterbox 보정) =====
    // ZoomGrid에 RenderTransform(줌/팬)이 걸려 있어도 e.GetPosition(DrawCanvas)는 항상
    // DrawCanvas의 변환 전(un-transformed) 로컬 좌표를 돌려주므로(WPF 좌표계 특성) 이
    // 계산은 줌 여부와 무관하게 그대로 맞다 — 별도 보정 불필요.
    private (double scale, double offX, double offY) Fit()
    {
        var vm = Vm;
        if (vm == null || vm.ImageWidth <= 0 || vm.ImageHeight <= 0) return (1, 0, 0);
        double cw = DrawCanvas.ActualWidth, ch = DrawCanvas.ActualHeight;
        double scale = Math.Min(cw / vm.ImageWidth, ch / vm.ImageHeight);
        double offX = (cw - vm.ImageWidth * scale) / 2;
        double offY = (ch - vm.ImageHeight * scale) / 2;
        return (scale, offX, offY);
    }

    private void DrawCanvas_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (Vm?.HasFolder != true) return;
        if (_panStart != null) return;   // 우클릭 팬 중이면 박스 그리기를 시작하지 않음(캡처 경합 방지)
        _dragStart = e.GetPosition(DrawCanvas);
        DrawCanvas.CaptureMouse();
    }

    private void DrawCanvas_MouseMove(object sender, MouseEventArgs e)
    {
        if (_dragStart == null) return;
        var pos = e.GetPosition(DrawCanvas);
        if (_tempRect == null)
        {
            _tempRect = new Rectangle
            {
                Stroke = System.Windows.Media.Brushes.White,
                StrokeThickness = 1.5 / Math.Max(1, _zoomScale.ScaleX),   // 확대해도 선 두께 일정하게
                StrokeDashArray = new System.Windows.Media.DoubleCollection { 4, 2 },
            };
            DrawCanvas.Children.Add(_tempRect);
        }
        double x = Math.Min(pos.X, _dragStart.Value.X), y = Math.Min(pos.Y, _dragStart.Value.Y);
        double w = Math.Abs(pos.X - _dragStart.Value.X), h = Math.Abs(pos.Y - _dragStart.Value.Y);
        Canvas.SetLeft(_tempRect, x); Canvas.SetTop(_tempRect, y);
        _tempRect.Width = w; _tempRect.Height = h;
    }

    private void DrawCanvas_MouseUp(object sender, MouseButtonEventArgs e)
    {
        DrawCanvas.ReleaseMouseCapture();
        if (_tempRect != null) { DrawCanvas.Children.Remove(_tempRect); _tempRect = null; }
        if (_dragStart == null) return;
        var end = e.GetPosition(DrawCanvas);
        var start = _dragStart.Value;
        _dragStart = null;

        // 확대 상태에선 화면 몇 픽셀=이미지 1픽셀 이하가 되므로, 너무 작은 드래그만
        // 오클릭으로 걸러낸다(줌 배율이 클수록 더 작은 드래그도 유효한 박스로 인정).
        double minDrag = Math.Max(2.0, 5.0 / Math.Max(1, _zoomScale.ScaleX));
        if (Math.Abs(end.X - start.X) < minDrag || Math.Abs(end.Y - start.Y) < minDrag) return;

        var (scale, offX, offY) = Fit();
        if (scale <= 0) return;
        double ix1 = (start.X - offX) / scale, iy1 = (start.Y - offY) / scale;
        double ix2 = (end.X - offX) / scale, iy2 = (end.Y - offY) / scale;
        Vm?.AddBoxPixel(ix1, iy1, ix2, iy2);
    }

    // ===== 코치 오버레이: 지금 뭘 눌러야 하는지 화살표+말풍선으로 안내("의식의 흐름") =====
    private void UpdateCoach()
    {
        var vm = Vm;
        if (vm == null) { CoachCanvas.Children.Clear(); return; }

        FrameworkElement? target;
        string text;
        if (!vm.HasFolder)
        {
            target = OpenFolderBtn;
            text = "① 여기를 눌러 이미지가 들어있는 폴더를 선택하세요";
        }
        else if (vm.Classes.Count == 1 && vm.Classes[0].Name == "class0")
        {
            target = NewClassBox;
            text = "② 찾으려는 대상의 이름을 입력하고 [+]를 누르세요 (예: 결함, 사람)";
        }
        else if (!vm.AnyBoxDrawn)
        {
            target = ViewerBorder;
            text = "③ 이미지 위에서 대상을 감싸듯 마우스로 드래그하세요 (휠로 확대하면 더 정확해요)";
        }
        else if (!vm.Exported)
        {
            target = ExportBtn;
            text = "④ 다 그렸으면 여기를 눌러 데이터셋을 만드세요";
        }
        else
        {
            CoachCanvas.Children.Clear();
            return;
        }

        DrawCoach(target, text);
    }

    private void DrawCoach(FrameworkElement? target, string text)
    {
        CoachCanvas.Children.Clear();
        if (target == null || !target.IsVisible || target.ActualWidth <= 0) return;

        // 사이드바 ScrollViewer 밖으로 밀려난 대상이면 화면으로 끌어옴 — 안 하면 화살표가
        // 안 보이는 곳을 가리켜 코치가 사실상 실종된다. 이 타이머는 400ms마다 재호출되는
        // "자기치유" 설계라 이번 틱에 좌표가 아직 stale해도 다음 틱에 스스로 맞다.
        try { target.BringIntoView(); } catch { }

        Point topLeft;
        try { topLeft = target.TransformToAncestor(this).Transform(new Point(0, 0)); }
        catch (InvalidOperationException) { return; }   // 아직 비주얼 트리에 안 붙었으면 스킵

        var rect = new Rect(topLeft, new Size(target.ActualWidth, target.ActualHeight));
        var accent = (Brush)(FindResource("Accent"));

        // 강조 테두리
        var hl = new Rectangle
        {
            Width = rect.Width + 10, Height = rect.Height + 10,
            Stroke = accent, StrokeThickness = 3, RadiusX = 8, RadiusY = 8, Fill = System.Windows.Media.Brushes.Transparent,
        };
        Canvas.SetLeft(hl, rect.X - 5); Canvas.SetTop(hl, rect.Y - 5);
        CoachCanvas.Children.Add(hl);

        // 말풍선
        var bubble = new Border
        {
            Background = accent, CornerRadius = new CornerRadius(8),
            Padding = new Thickness(12, 8, 12, 8), MaxWidth = 280,
        };
        var tb = new TextBlock
        {
            Text = text, Foreground = System.Windows.Media.Brushes.White,
            TextWrapping = TextWrapping.Wrap, FontSize = 13, FontFamily = new FontFamily("Segoe UI, Malgun Gothic"),
        };
        bubble.Child = tb;
        bubble.Measure(new Size(280, double.PositiveInfinity));
        var bubbleSize = bubble.DesiredSize;

        double bx = Math.Min(rect.X, Math.Max(6, ActualWidth - bubbleSize.Width - 6));
        double by = rect.Bottom + 16;
        bool below = true;
        if (by + bubbleSize.Height > ActualHeight - 6)
        {
            by = rect.Y - bubbleSize.Height - 16;
            below = false;
        }
        by = Math.Max(6, by);
        Canvas.SetLeft(bubble, bx); Canvas.SetTop(bubble, by);
        CoachCanvas.Children.Add(bubble);

        // 화살표(말풍선 → 대상, 작은 삼각형)
        double arrowCenterX = Math.Clamp(rect.X + rect.Width / 2, bx + 10, bx + bubbleSize.Width - 10);
        var arrow = new Polygon { Fill = accent };
        if (below)
        {
            arrow.Points = new PointCollection {
                new Point(arrowCenterX - 8, by), new Point(arrowCenterX + 8, by), new Point(arrowCenterX, by - 10),
            };
        }
        else
        {
            double ay = by + bubbleSize.Height;
            arrow.Points = new PointCollection {
                new Point(arrowCenterX - 8, ay), new Point(arrowCenterX + 8, ay), new Point(arrowCenterX, ay + 10),
            };
        }
        CoachCanvas.Children.Add(arrow);
    }
}
