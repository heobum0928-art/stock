using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using EdgeInspector.ViewModels;

namespace EdgeInspector.Views;

public partial class SegLabelingView : UserControl
{
    // ===== 줌/팬 — LabelingView와 동일한 검증된 패턴 그대로 재사용 =====
    private readonly ScaleTransform _zoomScale = new(1, 1);
    private readonly TranslateTransform _zoomTranslate = new(0, 0);
    private Point? _panStart;
    private const double MaxZoom = 40.0;

    // ===== 폴리곤 그리기(진행 중) =====
    private readonly List<Point> _currentPoints = new();      // DrawCanvas 좌표계(픽셀 아님)
    private Polyline? _previewLine;                            // 지금까지 찍은 점들을 잇는 선
    private Line? _rubberBand;                                  // 마지막 점 → 현재 마우스 위치(미리보기)
    private readonly List<Ellipse> _previewDots = new();

    // ===== 브러쉬/매직브러쉬 =====
    private Point? _brushLastImgPt;    // 직전 페인트 위치(이미지 픽셀 좌표) — 드래그 보간용
    private Shape? _brushCursor;       // 브러쉬 크기 미리보기(원/사각형 윤곽, 마우스 따라다님)

    public SegLabelingView()
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
        // 브러쉬 드래그 중 캔버스 밖으로 나가는 등 MouseLeftButtonUp을 못 받는 경우의 안전망.
        DrawCanvas.LostMouseCapture += (_, _) => _brushLastImgPt = null;

        PreviewKeyDown += SegLabelingView_PreviewKeyDown;
        DataContextChanged += SegLabelingView_DataContextChanged;
    }

    private SegLabelingViewModel? Vm => DataContext as SegLabelingViewModel;

    // 이미지가 바뀌면 줌/팬 리셋 + 그리던 폴리곤 취소(라벨링 탭과 동일한 이유 — 확대된 채로
    // 다음 이미지가 열리는 혼란 방지 + 이전 이미지의 미완성 점이 새 이미지에 남지 않게).
    private SegLabelingViewModel? _subscribedVm;
    private void SegLabelingView_DataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_subscribedVm != null)
        {
            _subscribedVm.PropertyChanged -= Vm_PropertyChanged;
            _subscribedVm.SaveFailed -= OnSaveFailed;
        }
        _subscribedVm = DataContext as SegLabelingViewModel;
        if (_subscribedVm != null)
        {
            _subscribedVm.PropertyChanged += Vm_PropertyChanged;
            _subscribedVm.SaveFailed += OnSaveFailed;
        }
    }

    // 이미지 전환/창 닫기 때 조용히 실행되는 자동저장(SaveCurrent)이 실패해도 예전엔 그냥
    // 묻혔다 — 방금 그린 게 디스크에 안 남았는데 사용자는 저장된 줄 아는 게 가장 위험한
    // 유형이라, 명시적으로 안내한다(수동 "마스크 저장" 버튼의 84행과 같은 톤).
    private void OnSaveFailed(string err) =>
        MessageBox.Show(err, "자동저장 실패", MessageBoxButton.OK, MessageBoxImage.Warning);

    private void Vm_PropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SegLabelingViewModel.Image))
        {
            ResetZoom();
            CancelCurrentPolygon();
            if (DrawCanvas.IsMouseCaptured) DrawCanvas.ReleaseMouseCapture();
            _brushLastImgPt = null;
        }
    }

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        using var dlg = new System.Windows.Forms.FolderBrowserDialog { Description = "세그멘테이션 라벨링할 이미지 폴더 선택" };
        if (dlg.ShowDialog() == System.Windows.Forms.DialogResult.OK)
            Vm?.OpenFolder(dlg.SelectedPath);
        Focus();
        ResetZoom();
    }

    private void SaveMask_Click(object sender, RoutedEventArgs e)
    {
        var err = Vm?.SaveMask();
        if (err != null)
            MessageBox.Show(err, "저장 실패", MessageBoxButton.OK, MessageBoxImage.Warning);
    }

    // 갤러리 다중선택(Ctrl/Shift+클릭) — 2장 이상 선택됐을 때만 일괄삭제 버튼을 보인다
    // (1장뿐이면 이미 열려있는 이미지의 "브러쉬 전체 지우기"와 중복이라 불필요한 노출 방지).
    private void GalleryList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        int count = GalleryList.SelectedItems.Count;
        if (count >= 2)
        {
            ClearSelectedBtn.Content = $"선택한 {count}장 마스크 지우기";
            ClearSelectedBtn.Visibility = Visibility.Visible;
        }
        else
        {
            ClearSelectedBtn.Visibility = Visibility.Collapsed;
        }
    }

    private void ClearSelected_Click(object sender, RoutedEventArgs e)
    {
        if (Vm == null) return;
        var selected = GalleryList.SelectedItems.Cast<ThumbItem>().Select(t => t.Path).ToList();
        if (selected.Count == 0) return;
        var r = MessageBox.Show(
            $"선택한 {selected.Count}장의 저장된 마스크를 지울까요?\n" +
            "이미지 자체는 남고, 그려둔 라벨(마스크)만 지워져 미라벨링 상태로 돌아갑니다.\n되돌릴 수 없습니다.",
            "선택 이미지 마스크 지우기", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
        if (r != MessageBoxResult.Yes) return;

        var (deleted, err) = Vm.ClearMasksForImages(selected);
        if (err != null)
            MessageBox.Show(err, "삭제 실패", MessageBoxButton.OK, MessageBoxImage.Warning);
        else
            MessageBox.Show($"{deleted}장의 마스크를 지웠습니다.", "완료", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    // ===== 도구 전환(폴리곤/브러쉬/매직브러쉬) =====
    // Vm==null 가드로 안전 — XAML의 IsChecked="True" 기본값 때문에 InitializeComponent 중에도
    // Checked가 걸릴 수 있는데(DataContext가 아직 안 붙은 시점), 그때는 그냥 아무 것도 안 함.
    private void ToolPolygon_Checked(object sender, RoutedEventArgs e) => SwitchTool(SegTool.Polygon);
    private void ToolBrush_Checked(object sender, RoutedEventArgs e) => SwitchTool(SegTool.Brush);
    private void ToolMagic_Checked(object sender, RoutedEventArgs e) => SwitchTool(SegTool.MagicWand);

    private void SwitchTool(SegTool tool)
    {
        if (Vm == null) return;
        Vm.Tool = tool;
        CancelCurrentPolygon();   // 도구를 바꾸면 그리던 폴리곤은 취소(어중간한 상태 방지)
        RemoveBrushCursor();
        Cursor = tool == SegTool.MagicWand ? Cursors.Cross : Cursors.Arrow;
    }

    private void ShapeCircle_Checked(object sender, RoutedEventArgs e) { if (Vm != null) Vm.BrushShape = BrushShape.Circle; }
    private void ShapeSquare_Checked(object sender, RoutedEventArgs e) { if (Vm != null) Vm.BrushShape = BrushShape.Square; }

    private void ClearBrush_Click(object sender, RoutedEventArgs e)
    {
        var result = MessageBox.Show("브러쉬로 칠한 부분을 전부 지울까요? (폴리곤은 남습니다)", "브러쉬 지우기",
            MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
        if (result == MessageBoxResult.Yes) Vm?.ClearBrush();
    }

    private void Undo_Click(object sender, RoutedEventArgs e) => Vm?.Undo();

    // ===== AI 초안(반자동 라벨링) =====
    private void TrainDraft_Click(object sender, RoutedEventArgs e)
    {
        if (Vm == null) return;
        int n = Vm.LabeledCount;
        int nFolder = Vm.FolderLabeledCount;
        if (n == 0)
        {
            MessageBox.Show("아직 라벨링된 이미지가 없습니다. 먼저 폴리곤/브러쉬로 몇 장 이상 그려서 저장하세요.",
                "라벨링 필요", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        var warn = n < 20 ? $"\n\n⚠ 지금 {n}장뿐입니다. 정확도를 위해선 수십 장 이상을 권장합니다(적어도 참고용 초안은 나옵니다)." : "";
        // 학습 풀(train/data 전체)에 지금 연 폴더 밖의 이미지가 섞여 있으면(예전 다른 작업물)
        // 미리 알려준다 — 사장님 피드백: "왜 24장으로 한다고 하지?? 난 3개만 라벨링했는데".
        var foreignCount = n - nFolder;
        var foreignWarn = foreignCount > 0
            ? $"\n\n⚠ 학습 풀 {n}장 중 {foreignCount}장은 지금 연 폴더 밖(예전에 다른 폴더에서 라벨링한 것)입니다. 그것들도 함께 학습됩니다."
            : "";
        var ok = MessageBox.Show(
            $"라벨링된 {n}장으로 AI 보조 모델을 학습합니다.\n학습이 끝나면 다른 이미지에서 'AI 초안 채우기'를 쓸 수 있습니다.{warn}{foreignWarn}\n\n" +
            "처음 실행 시 라이브러리 로딩으로 수 분 걸릴 수 있습니다. 시작할까요?",
            "AI 학습", MessageBoxButton.OKCancel, MessageBoxImage.Question);
        if (ok == MessageBoxResult.OK) Vm.TrainDraftModel();
    }

    private void CancelTrainDraft_Click(object sender, RoutedEventArgs e)
    {
        var r = MessageBox.Show("진행 중인 학습을 취소할까요? 지금까지 학습한 내용은 저장되지 않습니다.",
            "학습 취소", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
        if (r == MessageBoxResult.Yes) Vm?.CancelDraftTraining();
    }

    private void ApplyAiDraft_Click(object sender, RoutedEventArgs e)
    {
        if (Vm == null) return;
        if (Vm.AnyMaskDrawn)
        {
            var r = MessageBox.Show(
                "이미 이 이미지에 칠한 내용이 있습니다. AI 초안으로 브러쉬 부분을 덮어쓸까요?(폴리곤은 그대로 유지됩니다)",
                "AI 초안 채우기", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
            if (r != MessageBoxResult.Yes) return;
        }
        var err = Vm.ApplyAiDraft();
        if (err != null)
            MessageBox.Show(err, "AI 초안 실패", MessageBoxButton.OK, MessageBoxImage.Warning);
    }

    private void PolygonList_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Delete && PolygonList.SelectedIndex >= 0)
        {
            var result = MessageBox.Show("선택한 폴리곤을 삭제할까요?", "폴리곤 삭제", MessageBoxButton.YesNo, MessageBoxImage.Question, MessageBoxResult.No);
            if (result == MessageBoxResult.Yes)
                Vm?.DeletePolygon(PolygonList.SelectedIndex);
        }
    }

    private void SegLabelingView_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape) CancelCurrentPolygon();
        else if (e.Key == Key.Enter) TryClosePolygon();
        else if (e.Key == Key.F && Keyboard.Modifiers == ModifierKeys.None) ResetZoom();
        // 브러쉬 크기를 [ ] 키로도 조절(포토샵 등에서 흔한 단축키) — BrushSize 세터가 2~250으로 clamp.
        else if (e.Key == Key.OemOpenBrackets && Vm != null) Vm.BrushSize -= 4;
        else if (e.Key == Key.OemCloseBrackets && Vm != null) Vm.BrushSize += 4;
        else if (e.Key == Key.Z && Keyboard.Modifiers == ModifierKeys.Control) Vm?.Undo();
    }

    // ===== 줌/팬(LabelingView와 동일) =====
    private void ResetZoom()
    {
        _zoomScale.ScaleX = _zoomScale.ScaleY = 1;
        _zoomTranslate.X = _zoomTranslate.Y = 0;
        ZoomLabel.Text = "100%";
    }

    private void ZoomGrid_MouseWheel(object sender, MouseWheelEventArgs e)
    {
        if (Vm?.HasFolder != true) return;
        if (_panStart != null) return;
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

    private void ZoomGrid_PanStart(object sender, MouseButtonEventArgs e)
    {
        if (_zoomScale.ScaleX <= 1.0001) return;
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

    // ===== 캔버스 좌표 → 이미지 픽셀 좌표(letterbox 보정, LabelingView.Fit()과 동일) =====
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

    // ===== 그리기(폴리곤/브러쉬/매직브러쉬 — 도구별로 분기) =====
    private void DrawCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (Vm?.HasFolder != true) return;
        if (_panStart != null) return;   // 팬 중이면 아무 도구도 반응하지 않음(캡처 경합 방지, LabelingView와 동일 원칙)

        var pos = e.GetPosition(DrawCanvas);

        if (Vm.Tool == SegTool.Brush)
        {
            var (scale, offX, offY) = Fit();
            if (scale <= 0) return;
            DrawCanvas.CaptureMouse();
            Vm.BeginBrushStroke();   // 이 드래그(누름~뗌) 전체를 하나의 Ctrl+Z 단위로 스냅샷
            var imgPt = ((pos.X - offX) / scale, (pos.Y - offY) / scale);
            Vm.PaintAt(imgPt.Item1, imgPt.Item2);
            _brushLastImgPt = new Point(imgPt.Item1, imgPt.Item2);
            return;
        }

        if (Vm.Tool == SegTool.MagicWand)
        {
            var (scale, offX, offY) = Fit();
            if (scale <= 0) return;
            var imgPt = ((pos.X - offX) / scale, (pos.Y - offY) / scale);
            Mouse.OverrideCursor = Cursors.Wait;   // 큰 이미지는 플러드필에 최대 1초 안팎 걸릴 수 있음
            try { Vm.MagicFill(imgPt.Item1, imgPt.Item2); }
            finally { Mouse.OverrideCursor = null; }
            return;
        }

        // ===== 폴리곤(기존 로직 그대로) =====
        if (e.ClickCount >= 2)
        {
            // 더블클릭: 방금 단일클릭으로 이미 추가된(중복에 가까운) 마지막 점을 지우고 폴리곤을 닫는다.
            if (_currentPoints.Count > 0) _currentPoints.RemoveAt(_currentPoints.Count - 1);
            TryClosePolygon();
            return;
        }

        _currentPoints.Add(pos);
        RedrawPreview();
    }

    private void DrawCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (Vm?.Tool == SegTool.Brush && DrawCanvas.IsMouseCaptured)
        {
            DrawCanvas.ReleaseMouseCapture();
            _brushLastImgPt = null;
        }
    }

    private void DrawCanvas_MouseMove(object sender, MouseEventArgs e)
    {
        var pos = e.GetPosition(DrawCanvas);
        UpdateBrushCursor(pos);

        if (Vm?.Tool == SegTool.Brush && DrawCanvas.IsMouseCaptured && _brushLastImgPt != null)
        {
            var (scale, offX, offY) = Fit();
            if (scale <= 0) return;
            var cur = ((pos.X - offX) / scale, (pos.Y - offY) / scale);
            Vm.PaintStroke(_brushLastImgPt.Value.X, _brushLastImgPt.Value.Y, cur.Item1, cur.Item2);
            _brushLastImgPt = new Point(cur.Item1, cur.Item2);
            return;
        }

        // ===== 폴리곤 러버밴드(기존 로직 그대로 — 폴리곤을 그리는 중이 아니면 아무 것도 안 함) =====
        if (_currentPoints.Count == 0) return;
        if (_rubberBand == null)
        {
            _rubberBand = new Line
            {
                Stroke = System.Windows.Media.Brushes.White,
                StrokeThickness = 1.2 / Math.Max(1, _zoomScale.ScaleX),
                StrokeDashArray = new System.Windows.Media.DoubleCollection { 3, 2 },
            };
            DrawCanvas.Children.Add(_rubberBand);
        }
        var last = _currentPoints[^1];
        _rubberBand.X1 = last.X; _rubberBand.Y1 = last.Y;
        _rubberBand.X2 = pos.X; _rubberBand.Y2 = pos.Y;
    }

    // 브러쉬 도구일 때 마우스를 따라다니는 크기/모양 미리보기 윤곽(원형·사각형).
    private void UpdateBrushCursor(Point canvasPos)
    {
        if (Vm == null || Vm.Tool != SegTool.Brush || !Vm.HasFolder)
        {
            RemoveBrushCursor();
            return;
        }
        var (scale, _, _) = Fit();
        if (scale <= 0) { RemoveBrushCursor(); return; }
        double screenD = Vm.BrushSize * scale;

        bool wantCircle = Vm.BrushShape == BrushShape.Circle;
        bool needNew = _brushCursor == null
            || (wantCircle && _brushCursor is not Ellipse)
            || (!wantCircle && _brushCursor is not Rectangle);
        if (needNew)
        {
            RemoveBrushCursor();
            _brushCursor = wantCircle
                ? new Ellipse { Stroke = System.Windows.Media.Brushes.White, StrokeThickness = 1.2, IsHitTestVisible = false }
                : new Rectangle { Stroke = System.Windows.Media.Brushes.White, StrokeThickness = 1.2, IsHitTestVisible = false };
            DrawCanvas.Children.Add(_brushCursor);
        }
        _brushCursor!.Width = _brushCursor.Height = screenD;
        Canvas.SetLeft(_brushCursor, canvasPos.X - screenD / 2);
        Canvas.SetTop(_brushCursor, canvasPos.Y - screenD / 2);
    }

    private void RemoveBrushCursor()
    {
        if (_brushCursor != null) { DrawCanvas.Children.Remove(_brushCursor); _brushCursor = null; }
    }

    private void RedrawPreview()
    {
        ClearPreviewShapes();
        if (_currentPoints.Count == 0) return;

        _previewLine = new Polyline
        {
            Stroke = System.Windows.Media.Brushes.Orange,
            StrokeThickness = 2.0 / Math.Max(1, _zoomScale.ScaleX),
            Points = new System.Windows.Media.PointCollection(_currentPoints),
        };
        DrawCanvas.Children.Add(_previewLine);

        double dotR = 3.5 / Math.Max(1, _zoomScale.ScaleX);
        foreach (var p in _currentPoints)
        {
            var dot = new Ellipse
            {
                Width = dotR * 2, Height = dotR * 2,
                Fill = System.Windows.Media.Brushes.Orange,
            };
            Canvas.SetLeft(dot, p.X - dotR); Canvas.SetTop(dot, p.Y - dotR);
            DrawCanvas.Children.Add(dot);
            _previewDots.Add(dot);
        }
    }

    private void ClearPreviewShapes()
    {
        if (_previewLine != null) { DrawCanvas.Children.Remove(_previewLine); _previewLine = null; }
        if (_rubberBand != null) { DrawCanvas.Children.Remove(_rubberBand); _rubberBand = null; }
        foreach (var d in _previewDots) DrawCanvas.Children.Remove(d);
        _previewDots.Clear();
    }

    private void CancelCurrentPolygon()
    {
        _currentPoints.Clear();
        ClearPreviewShapes();
    }

    // 지금까지 찍은 점들을 이미지 픽셀 좌표로 변환해 폴리곤으로 확정한다(3점 미만이면
    // ViewModel이 무시함 — 점/선은 마스크 영역이 될 수 없으므로).
    private void TryClosePolygon()
    {
        if (_currentPoints.Count < 3) { CancelCurrentPolygon(); return; }
        var (scale, offX, offY) = Fit();
        if (scale <= 0) { CancelCurrentPolygon(); return; }
        var pixelPoints = _currentPoints
            .Select(p => ((p.X - offX) / scale, (p.Y - offY) / scale))
            .ToList();
        Vm?.AddPolygonPixel(pixelPoints);
        CancelCurrentPolygon();
    }
}
