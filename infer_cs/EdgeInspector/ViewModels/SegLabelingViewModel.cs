using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

// 폴리곤 하나(좌측 목록 표시용).
public sealed class PolygonItem
{
    public required int Index { get; init; }
    public required string Label { get; init; }   // "폴리곤 1 (5점)" 같은 표시용 텍스트
}

// 그리기 도구: 폴리곤(기존, 각진 경계에 적합) / 브러쉬(자유형 칠하기) / 매직브러쉬(클릭 지점과
// 비슷한 색의 인접 영역을 자동 확장 — 얼룩·변색처럼 색이 뚜렷한 결함에 적합).
public enum SegTool { Polygon, Brush, MagicWand }
public enum BrushShape { Circle, Square }

// 실행 취소(Ctrl+Z) 스택의 항목 하나. 폴리곤 추가/삭제는 가볍게(좌표 리스트만), 브러쉬 계열
// (스트로크/매직브러쉬/전체지우기)은 그 작업 직전의 브러쉬 레이어 전체를 스냅샷해 되돌린다
// (부분 diff보다 단순·확실 — 이미지당 최대 개수를 제한해 메모리를 억제한다).
internal enum UndoActionType { PolygonAdd, PolygonDelete, BrushEdit }
internal sealed class UndoAction
{
    public UndoActionType Type;
    public int PolygonIndex;
    public List<(double X, double Y)>? Polygon;
    public byte[]? PrevBrushPixels;
    public bool PrevBrushHasContent;
}

// 세그멘테이션(에지) 라벨링 — 폴리곤으로 결함/관심영역을 그려 이진 마스크 PNG를 만든다.
// train/train.py(U-Net 에지 세그멘테이션)가 기대하는 train/data/images + train/data/masks
// 포맷(같은 파일명, 마스크는 그레이스케일 PNG·127 초과=대상)에 정확히 맞춰 저장한다.
// 순수 로직은 여기(폴리곤 좌표·마스크 렌더)에 담당하고, 마우스 좌표→픽셀 변환은
// SegLabelingView.xaml.cs가 담당(다른 뷰모델들과 동일한 역할 분리).
public sealed class SegLabelingViewModel : ViewModelBase, IDisposable
{
    private readonly string? _projectRoot;

    public SegLabelingViewModel(string? projectRoot)
    {
        _projectRoot = projectRoot;
        RefreshLabeledCount();
        RefreshDraftModelStatus();
    }

    // "이미지 폴더 열기"로 어디서 이미지를 열었든, 저장은 항상 이 프로젝트 루트 밑
    // train/data/로 고정된다(AI 학습이 한 곳에서 전부 찾을 수 있게 하려는 설계) — 사장님이
    // 실제로 겪은 혼란("D:\Test에서 열었는데 왜 거기 masks 폴더엔 없지?")을 막기 위해 화면에
    // 항상 보이는 안내로 노출한다.
    public string SaveDestinationPath => _projectRoot == null
        ? "(프로젝트 위치를 찾을 수 없음)"
        : Path.Combine(_projectRoot, "train", "data");

    public void Dispose()
    {
        _draftEngine?.Dispose();
        // 학습 중 앱을 종료하면 python.exe가 고아 프로세스로 GPU를 계속 점유하는 걸 방지(AnomalyViewModel과 동일 원칙).
        try { if (_draftTrainProc != null && !_draftTrainProc.HasExited) _draftTrainProc.Kill(entireProcessTree: true); } catch { }
    }

    public ObservableCollection<ThumbItem> Thumbnails { get; } = new();
    public ObservableCollection<PolygonItem> PolygonItems { get; } = new();

    // 완성된 폴리곤들 — 정규화(0~1) 좌표로 저장해 이미지 크기와 무관하게 유지.
    private readonly List<List<(double X, double Y)>> _polygons = new();

    // 실행 취소 스택 — 폴리곤 추가/삭제 + 브러쉬 계열(스트로크/매직브러쉬/전체지우기)을 시간순
    // 하나의 스택으로 관리해 Ctrl+Z 한 번에 "가장 최근에 한 일" 하나를 정확히 되돌린다.
    private readonly List<UndoAction> _undoStack = new();
    private const int MaxUndo = 10;

    private void PushUndo(UndoAction a)
    {
        _undoStack.Add(a);
        if (_undoStack.Count > MaxUndo) _undoStack.RemoveAt(0);
        OnPropertyChanged(nameof(CanUndo));
    }

    public bool CanUndo => _undoStack.Count > 0;

    public void Undo()
    {
        if (_undoStack.Count == 0) return;
        var a = _undoStack[^1];
        _undoStack.RemoveAt(_undoStack.Count - 1);
        switch (a.Type)
        {
            case UndoActionType.PolygonAdd:
                if (a.PolygonIndex >= 0 && a.PolygonIndex < _polygons.Count) _polygons.RemoveAt(a.PolygonIndex);
                break;
            case UndoActionType.PolygonDelete:
                _polygons.Insert(Math.Clamp(a.PolygonIndex, 0, _polygons.Count), a.Polygon!);
                break;
            case UndoActionType.BrushEdit:
                EnsureBrushBitmap();
                _brushBitmap!.WritePixels(new Int32Rect(0, 0, _imgW, _imgH), a.PrevBrushPixels!, _imgW * 4, 0);
                _brushHasContent = a.PrevBrushHasContent;
                break;
        }
        AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
        Saved = false;
        _touched = true;
        RefreshPolygonList();
        OnPropertyChanged(nameof(CanUndo));
    }

    // 브러쉬 드래그(한 번의 마우스 누름~뗌 = 하나의 되돌리기 단위) 시작 시 View가 호출.
    // 스트로크 도중의 개별 PaintAt 호출들은 undo 스택에 각각 쌓지 않고, 이 스냅샷 하나로
    // 스트로크 전체를 한 번에 되돌린다(포토샵 등과 동일한 "붓질 하나 = Ctrl+Z 한 번" 기대에 맞춤).
    public void BeginBrushStroke()
    {
        if (_imgW <= 0 || _imgH <= 0) return;
        EnsureBrushBitmap();
        var buf = new byte[_imgW * _imgH * 4];
        _brushBitmap!.CopyPixels(buf, _imgW * 4, 0);
        PushUndo(new UndoAction { Type = UndoActionType.BrushEdit, PrevBrushPixels = buf, PrevBrushHasContent = _brushHasContent });
    }

    // 브러쉬 레이어 — 폴리곤과 별개로 저장해 저장 시 OR로 합친다(SaveMask 참고).
    // 이미지 원본 크기의 WriteableBitmap(Bgra32)로, 칠한 곳=반투명 주황(폴리곤과 같은 색),
    // 안 칠한 곳=완전 투명. ★ 다른 비트맵과 달리 계속 WritePixels로 갱신해야 하므로 Freeze()하지 않는다.
    private WriteableBitmap? _brushBitmap;
    private bool _brushHasContent;
    // 매직브러쉬(색상 유사 확장)가 참조하는 원본 픽셀(RGB24, 정규화 좌표 아님 — 이미지 픽셀 그대로).
    private byte[]? _rgb;
    private int _rgbStride;

    private string? _imagesRoot, _currentImagePath;
    private int _imgW, _imgH;
    public int ImageWidth => _imgW;
    public int ImageHeight => _imgH;

    private SegTool _tool = SegTool.Polygon;
    public SegTool Tool { get => _tool; set => SetField(ref _tool, value); }

    private BrushShape _brushShape = BrushShape.Circle;
    public BrushShape BrushShape { get => _brushShape; set => SetField(ref _brushShape, value); }

    private double _brushSize = 24;
    public double BrushSize { get => _brushSize; set => SetField(ref _brushSize, Math.Clamp(value, 2, 250)); }

    private bool _isErasing;
    public bool IsErasing { get => _isErasing; set => SetField(ref _isErasing, value); }

    // 매직브러쉬 허용치 — 클릭 지점 색과 채널별(R/G/B) 최대 차이가 이 값 이하인 인접 픽셀까지 확장(0~255 스케일).
    private int _magicTolerance = 28;
    public int MagicTolerance { get => _magicTolerance; set => SetField(ref _magicTolerance, Math.Clamp(value, 1, 120)); }

    private ImageSource? _brushOverlay;
    public ImageSource? BrushOverlay { get => _brushOverlay; private set => SetField(ref _brushOverlay, value); }

    private string _status = "① 이미지 폴더를 여세요.";
    public string Status { get => _status; private set => SetField(ref _status, value); }

    private string _folderInfo = "";
    public string FolderInfo { get => _folderInfo; private set => SetField(ref _folderInfo, value); }

    private ThumbItem? _selectedThumb;
    public ThumbItem? SelectedThumb
    {
        get => _selectedThumb;
        set { if (SetField(ref _selectedThumb, value) && value != null) LoadImage(value.Path); }
    }

    private ImageSource? _image;
    public ImageSource? Image { get => _image; private set => SetField(ref _image, value); }

    private ImageSource? _maskOverlay;
    public ImageSource? MaskOverlay { get => _maskOverlay; private set => SetField(ref _maskOverlay, value); }

    private bool _hasFolder;
    public bool HasFolder { get => _hasFolder; private set => SetField(ref _hasFolder, value); }

    // 폴리곤이든 브러쉬든 뭐든 하나라도 칠해졌는지(사이드바 체크리스트 표시용).
    // 지우개로 브러쉬를 부분 지웠을 때 정확히 "완전히 비었는지"까지는 추적하지 않는다(매 스트로크마다
    // 전체 스캔은 낭비 — ClearBrush()로 명시 초기화하면 정확히 false로 돌아옴). 저장되는 실제 마스크
    // 내용(SaveMask)은 이 플래그와 무관하게 항상 정확하다.
    private bool _anyMaskDrawn;
    public bool AnyMaskDrawn { get => _anyMaskDrawn; private set => SetField(ref _anyMaskDrawn, value); }

    private bool _hasExistingMask;
    public bool HasExistingMask { get => _hasExistingMask; private set => SetField(ref _hasExistingMask, value); }

    private bool _saved;
    public bool Saved { get => _saved; private set => SetField(ref _saved, value); }

    public void OpenFolder(string folder)
    {
        var images = LabelingEngine.ListImages(folder);
        if (images.Count == 0)
        {
            Status = "선택한 폴더에 이미지가 없습니다.";
            HasFolder = false;
            return;
        }
        _imagesRoot = folder;
        LoadThumbnails(images);
        HasFolder = true;
        FolderInfo = $"{images.Count}장";
        Status = "② 이미지 위에서 클릭으로 점을 찍어 폴리곤을 그리세요(더블클릭=닫기).";
        RefreshLabeledCount();
        RefreshDraftModelStatus();

        if (Thumbnails.Count > 0)
        {
            _selectedThumb = Thumbnails[0]; OnPropertyChanged(nameof(SelectedThumb));
            LoadImage(Thumbnails[0].Path);
        }
    }

    private void LoadThumbnails(List<string> images)
    {
        Thumbnails.Clear();
        foreach (var f in images.Take(300))
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

    // train/data/masks/<stem>.png 존재 여부로 "이미 라벨링된 이미지"를 표시(참고용).
    private string? MaskPathFor(string imagePath)
    {
        if (_projectRoot == null) return null;
        var stem = Path.GetFileNameWithoutExtension(imagePath);
        return Path.Combine(_projectRoot, "train", "data", "masks", stem + ".png");
    }

    // "이 이미지에서 뭔가 실제로 조작(추가/삭제/칠하기/지우기/AI초안/Undo)을 했는지" — AnyMaskDrawn
    // ("지금 화면에 내용이 있는지")과는 다르다. 예전엔 SaveCurrent가 AnyMaskDrawn만 봐서, "브러쉬
    // 전체 지우기"로 화면을 완전히 비우면(AnyMaskDrawn=false가 됨) "아무 것도 안 그렸다"로 오판해
    // 자동저장을 건너뛰었다 — 그 결과 지운 게 디스크엔 반영 안 되고, 다시 열면 지우기 전 내용이
    // 그대로 남아있었다(실제 버그 리포트: "삭제했는데 삭제가 안 됨"/"저장했는데 지운 게 다시 나옴").
    private bool _touched;

    // 다른 이미지로 넘어가거나 창을 닫기 전에 지금 작업 중인(아직 "마스크 저장" 안 누른) 조작을
    // 자동 저장한다(라벨링 탭의 SaveCurrent와 동일 원칙 — 저장 버튼을 깜빡해도 유실 방지).
    // 이미 저장된 상태(Saved=true)이거나 애초에 아무 것도 안 건드렸으면 아무 일도 하지 않는다
    // (빈 화면을 훑어보기만 했는데 '결함 없음'으로 조용히 저장되는 것 방지) — 단, "건드렸는데
    // 결과가 비어있는"(전체 지우기 등) 경우는 _touched=true라 정확히 저장된다.
    public event Action<string>? SaveFailed;   // 자동저장 실패 — 조용히 묻히지 않게 View에 알림

    public void SaveCurrent()
    {
        if (Saved || !_touched) return;
        var err = SaveMask();
        if (err != null) SaveFailed?.Invoke(err);
    }

    private void LoadImage(string path)
    {
        SaveCurrent();   // 이전 이미지의 미저장 작업 보호(라벨링 탭 LoadImage와 동일 순서)
        try
        {
            var decoder = BitmapDecoder.Create(new Uri(path), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            var frame = decoder.Frames[0];
            _imgW = frame.PixelWidth; _imgH = frame.PixelHeight;
            frame.Freeze();
            Image = frame;
            _currentImagePath = path;
            _polygons.Clear();

            // 매직브러쉬용 원본 픽셀(RGB24) 캐시 — 폴리곤/브러쉬는 정규화 좌표라 원본 픽셀이 안 필요하지만
            // 색상 유사도 확장은 실제 픽셀값을 읽어야 함.
            var rgb24 = new FormatConvertedBitmap(decoder.Frames[0], PixelFormats.Rgb24, null, 0);
            rgb24.Freeze();
            _rgbStride = _imgW * 3;
            _rgb = new byte[_rgbStride * _imgH];
            rgb24.CopyPixels(_rgb, _rgbStride, 0);

            // 브러쉬 레이어는 이미지마다 새로 시작(폴리곤과 동일 원칙 — 이전 이미지의 칠이 남으면 안 됨).
            _brushBitmap = null;
            _brushHasContent = false;
            BrushOverlay = null;
            _undoStack.Clear();
            OnPropertyChanged(nameof(CanUndo));
            _touched = false;
            RefreshPolygonList();

            // 이미 저장된 마스크가 있으면 회색 참고용이 아니라 브러쉬 레이어로 직접 불러와 즉시
            // 이어서 다듬을 수 있게 한다("다시 칠하기 어렵다"는 피드백 반영 — 예전엔 매번 새로
            // 그려야 했음). 폴리곤으로는 못 되돌리지만(래스터→벡터 역변환 불가), 브러쉬/지우개로
            // 자유롭게 고칠 수 있으니 실질적으로 더 유연하다.
            var maskPath = MaskPathFor(path);
            HasExistingMask = maskPath != null && File.Exists(maskPath);
            if (HasExistingMask) LoadExistingMaskIntoBrush(maskPath!);

            AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
            Saved = HasExistingMask;   // 방금 불러온 내용은 디스크와 이미 일치 — 뭔가 더 그려야 Saved=false로 바뀜

            Status = HasExistingMask
                ? $"{Path.GetFileName(path)}  ({_imgW}x{_imgH}) — 이전에 그린 마스크를 불러왔습니다. 브러쉬로 이어서 다듬으세요."
                : $"{Path.GetFileName(path)}  ({_imgW}x{_imgH})";
        }
        catch (Exception ex)
        {
            Status = $"이미지 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // 기존 마스크 PNG(그레이스케일, 127 초과=대상)를 브러쉬 레이어에 그대로 채워 넣어 바로
    // 편집 가능하게 한다. 실행 취소 스택에는 안 남김(이미지를 막 연 시점의 "원래 상태"이지,
    // 사용자가 한 "동작"이 아니므로 — Ctrl+Z로 이것까지 지워지면 오히려 당황스러움).
    private void LoadExistingMaskIntoBrush(string maskPath)
    {
        try
        {
            var dec = BitmapDecoder.Create(new Uri(maskPath), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            var frame = new FormatConvertedBitmap(dec.Frames[0], PixelFormats.Gray8, null, 0);
            int w = frame.PixelWidth, h = frame.PixelHeight;
            if (w != _imgW || h != _imgH) return;   // 크기가 안 맞는 드문 경우 — 안전하게 건너뜀(새로 그리면 됨)
            var gray = new byte[w * h];
            frame.CopyPixels(gray, w, 0);

            EnsureBrushBitmap();
            var buf = new byte[w * h * 4];
            bool any = false;
            for (int i = 0; i < w * h; i++)
            {
                if (gray[i] <= 127) continue;
                any = true;
                int o = i * 4;
                buf[o] = 30; buf[o + 1] = 90; buf[o + 2] = 255; buf[o + 3] = 110;   // 폴리곤/브러쉬와 동일한 주황
            }
            _brushBitmap!.WritePixels(new Int32Rect(0, 0, w, h), buf, w * 4, 0);
            _brushHasContent = any;
        }
        catch { /* 실패해도 그냥 새로 그리면 되므로 조용히 무시 */ }
    }

    // 픽셀 좌표(View가 letterbox 보정을 마친 값) 리스트를 정규화해 폴리곤으로 추가.
    // 3점 미만이면(선/점) 무시 — 폴리곤이 아님.
    public void AddPolygonPixel(IReadOnlyList<(double X, double Y)> pixelPoints)
    {
        if (_imgW <= 0 || _imgH <= 0 || pixelPoints.Count < 3) return;
        var norm = pixelPoints.Select(p => (
            X: Math.Clamp(p.X / _imgW, 0.0, 1.0),
            Y: Math.Clamp(p.Y / _imgH, 0.0, 1.0))).ToList();
        _polygons.Add(norm);
        PushUndo(new UndoAction { Type = UndoActionType.PolygonAdd, PolygonIndex = _polygons.Count - 1 });
        AnyMaskDrawn = true;
        Saved = false;
        _touched = true;
        RefreshPolygonList();
    }

    public void DeletePolygon(int index)
    {
        if (index < 0 || index >= _polygons.Count) return;
        PushUndo(new UndoAction { Type = UndoActionType.PolygonDelete, PolygonIndex = index, Polygon = _polygons[index] });
        _polygons.RemoveAt(index);
        AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
        Saved = false;
        _touched = true;
        RefreshPolygonList();
    }

    // ===== 브러쉬(자유형 칠하기) =====

    private void EnsureBrushBitmap()
    {
        if (_brushBitmap != null && _brushBitmap.PixelWidth == _imgW && _brushBitmap.PixelHeight == _imgH) return;
        _brushBitmap = new WriteableBitmap(Math.Max(1, _imgW), Math.Max(1, _imgH), 96, 96, PixelFormats.Bgra32, null);
        BrushOverlay = _brushBitmap;
    }

    // 이미지 픽셀 좌표(px,py) 중심으로 브러쉬 도장을 한 번 찍는다(원형/사각형, BrushSize 지름).
    // 지우개 모드면 해당 영역을 투명(0)으로, 아니면 폴리곤과 같은 반투명 주황으로 칠한다.
    public void PaintAt(double px, double py)
    {
        if (_imgW <= 0 || _imgH <= 0) return;
        EnsureBrushBitmap();
        int r = Math.Max(1, (int)Math.Round(BrushSize / 2.0));
        int cx = (int)Math.Round(px), cy = (int)Math.Round(py);
        int x0 = Math.Max(0, cx - r), x1 = Math.Min(_imgW - 1, cx + r);
        int y0 = Math.Max(0, cy - r), y1 = Math.Min(_imgH - 1, cy + r);
        if (x1 < x0 || y1 < y0) return;
        int w = x1 - x0 + 1, h = y1 - y0 + 1;

        var buf = new byte[w * h * 4];
        _brushBitmap!.CopyPixels(new Int32Rect(x0, y0, w, h), buf, w * 4, 0);

        bool erase = IsErasing;
        bool circle = BrushShape == BrushShape.Circle;
        int r2 = r * r;
        for (int y = 0; y < h; y++)
        {
            int iy = y0 + y;
            int dy2 = (iy - cy) * (iy - cy);
            for (int x = 0; x < w; x++)
            {
                int ix = x0 + x;
                bool inside = circle ? (dy2 + (ix - cx) * (ix - cx)) <= r2 : true;
                if (!inside) continue;
                int o = (y * w + x) * 4;
                if (erase) { buf[o] = 0; buf[o + 1] = 0; buf[o + 2] = 0; buf[o + 3] = 0; }
                else { buf[o] = 30; buf[o + 1] = 90; buf[o + 2] = 255; buf[o + 3] = 110; }   // BGRA, 폴리곤 채움과 동일 색
            }
        }
        _brushBitmap.WritePixels(new Int32Rect(x0, y0, w, h), buf, w * 4, 0);
        if (!erase) _brushHasContent = true;
        AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
        Saved = false;
        _touched = true;
    }

    // 드래그 중 빠른 마우스 이동으로 점 사이가 끊기지 않도록, 직전 위치→현재 위치를 보간해 도장을 여러 번 찍는다.
    public void PaintStroke(double x0, double y0, double x1, double y1)
    {
        double dx = x1 - x0, dy = y1 - y0;
        double dist = Math.Sqrt(dx * dx + dy * dy);
        double step = Math.Max(1.0, BrushSize / 3.0);
        int n = Math.Max(1, (int)(dist / step));
        for (int i = 1; i <= n; i++)
        {
            double t = (double)i / n;
            PaintAt(x0 + dx * t, y0 + dy * t);
        }
    }

    // 브러쉬로 칠한 것만 전부 지운다(폴리곤은 건드리지 않음). View가 확인창을 띄우긴 하지만,
    // 실행 취소 스택에도 남겨 Ctrl+Z로 되돌릴 수 있게 한다(확인 후 마음이 바뀌는 경우 대비).
    public void ClearBrush()
    {
        if (_brushBitmap == null) return;
        int w = _brushBitmap.PixelWidth, h = _brushBitmap.PixelHeight;
        var prev = new byte[w * h * 4];
        _brushBitmap.CopyPixels(prev, w * 4, 0);
        PushUndo(new UndoAction { Type = UndoActionType.BrushEdit, PrevBrushPixels = prev, PrevBrushHasContent = _brushHasContent });

        var empty = new byte[w * h * 4];
        _brushBitmap.WritePixels(new Int32Rect(0, 0, w, h), empty, w * 4, 0);
        _brushHasContent = false;
        AnyMaskDrawn = _polygons.Count > 0;
        Saved = false;
        _touched = true;   // ★ 지워서 비어있어도(AnyMaskDrawn=false) "건드렸다"는 사실은 남겨야
        // SaveCurrent()가 이 결과를 정확히 자동저장한다(예전 버그: 지운 게 저장 안 되고 되살아남).
    }

    // ===== 매직브러쉬(색상 유사도 기반 자동 확장) =====
    // 클릭 지점 픽셀 색을 기준으로, 4방향 인접 픽셀 중 채널별 최대 차이가 MagicTolerance 이하인
    // 영역을 플러드필로 확장해 브러쉬 레이어에 칠한다(지우개 모드면 반대로 지운다). 새 모델 불필요 —
    // 원본 이미지 픽셀만으로 동작하는 고전적 "매직 완드" 방식.
    public void MagicFill(double px, double py)
    {
        if (_rgb == null || _imgW <= 0 || _imgH <= 0) return;
        int sx = (int)Math.Round(px), sy = (int)Math.Round(py);
        if (sx < 0 || sy < 0 || sx >= _imgW || sy >= _imgH) return;

        int SeedIdx(int x, int y) => y * _rgbStride + x * 3;
        int si = SeedIdx(sx, sy);
        byte sr = _rgb[si], sg = _rgb[si + 1], sb = _rgb[si + 2];
        int tol = MagicTolerance;

        var visited = new bool[_imgW * _imgH];
        var stack = new Stack<(int x, int y)>();
        stack.Push((sx, sy));
        visited[sy * _imgW + sx] = true;
        int minX = sx, maxX = sx, minY = sy, maxY = sy;

        while (stack.Count > 0)
        {
            var (x, y) = stack.Pop();
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;

            TryVisit(x - 1, y); TryVisit(x + 1, y); TryVisit(x, y - 1); TryVisit(x, y + 1);
        }

        void TryVisit(int nx, int ny)
        {
            if (nx < 0 || ny < 0 || nx >= _imgW || ny >= _imgH) return;
            int ni = ny * _imgW + nx;
            if (visited[ni]) return;
            int pi = SeedIdx(nx, ny);
            int dr = Math.Abs(_rgb![pi] - sr), dg = Math.Abs(_rgb[pi + 1] - sg), db = Math.Abs(_rgb[pi + 2] - sb);
            if (Math.Max(dr, Math.Max(dg, db)) > tol) return;
            visited[ni] = true;
            stack.Push((nx, ny));
        }

        EnsureBrushBitmap();

        // 매직브러쉬는 클릭 한 번 = 되돌리기 한 단위(브러쉬 드래그처럼 View가 Begin을 따로 호출하지
        // 않으므로 여기서 채우기 직전 전체 스냅샷을 직접 남긴다).
        var fullPrev = new byte[_imgW * _imgH * 4];
        _brushBitmap!.CopyPixels(fullPrev, _imgW * 4, 0);
        PushUndo(new UndoAction { Type = UndoActionType.BrushEdit, PrevBrushPixels = fullPrev, PrevBrushHasContent = _brushHasContent });

        int w = maxX - minX + 1, h = maxY - minY + 1;
        var buf = new byte[w * h * 4];
        _brushBitmap.CopyPixels(new Int32Rect(minX, minY, w, h), buf, w * 4, 0);
        bool erase = IsErasing;
        for (int y = 0; y < h; y++)
        {
            for (int x = 0; x < w; x++)
            {
                if (!visited[(minY + y) * _imgW + (minX + x)]) continue;
                int o = (y * w + x) * 4;
                if (erase) { buf[o] = 0; buf[o + 1] = 0; buf[o + 2] = 0; buf[o + 3] = 0; }
                else { buf[o] = 30; buf[o + 1] = 90; buf[o + 2] = 255; buf[o + 3] = 110; }
            }
        }
        _brushBitmap.WritePixels(new Int32Rect(minX, minY, w, h), buf, w * 4, 0);
        if (!erase) _brushHasContent = true;
        AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
        Saved = false;
        _touched = true;
    }

    private void RefreshPolygonList()
    {
        PolygonItems.Clear();
        for (int i = 0; i < _polygons.Count; i++)
            PolygonItems.Add(new PolygonItem { Index = i, Label = $"폴리곤 {i + 1} ({_polygons[i].Count}점)" });
        BuildOverlay();
    }

    // 완성된 폴리곤들을 반투명 채움으로 그려 화면에 보여준다(그리기 중인 점선은 View가 별도로 그림).
    private void BuildOverlay()
    {
        if (_imgW <= 0 || _imgH <= 0) { return; }
        var group = new DrawingGroup();
        // 투명 전체 사각형으로 DrawingImage 경계를 원본 크기에 고정(라벨링 탭에서 겪은
        // "박스 하나뿐이면 좌표 어긋남" 버그와 동일한 원인 — 여기서도 선제 방어).
        group.Children.Add(new GeometryDrawing(Brushes.Transparent, null, new RectangleGeometry(new Rect(0, 0, _imgW, _imgH))));
        var fill = new SolidColorBrush(Color.FromArgb(110, 255, 90, 30));
        var pen = new Pen(new SolidColorBrush(Color.FromRgb(255, 140, 30)), Math.Max(1.5, _imgW / 500.0));
        foreach (var poly in _polygons)
        {
            if (poly.Count < 3) continue;
            var figure = new PathFigure { StartPoint = new Point(poly[0].X * _imgW, poly[0].Y * _imgH), IsClosed = true };
            for (int i = 1; i < poly.Count; i++)
                figure.Segments.Add(new LineSegment(new Point(poly[i].X * _imgW, poly[i].Y * _imgH), true));
            var geo = new PathGeometry(new[] { figure });
            group.Children.Add(new GeometryDrawing(fill, pen, geo));
        }
        var img = new DrawingImage(group);
        img.Freeze();
        MaskOverlay = _polygons.Count > 0 ? img : null;
    }

    // 폴리곤들을 채운 이진 마스크 PNG로 저장. train/data/images에 원본이 없으면 복사도 함께
    // (train.py가 파일명 stem으로 이미지/마스크를 매칭하므로 같은 폴더 구조를 보장해야 함).
    public string? SaveMask()
    {
        if (_projectRoot == null || _currentImagePath == null || _imgW <= 0 || _imgH <= 0)
            return "이미지를 먼저 여세요.";
        try
        {
            var imagesDir = Path.Combine(_projectRoot, "train", "data", "images");
            var masksDir = Path.Combine(_projectRoot, "train", "data", "masks");
            Directory.CreateDirectory(imagesDir);
            Directory.CreateDirectory(masksDir);

            var stem = Path.GetFileNameWithoutExtension(_currentImagePath);
            var ext = Path.GetExtension(_currentImagePath);
            var dstImage = Path.Combine(imagesDir, stem + ext);
            if (!File.Exists(dstImage) &&
                !string.Equals(Path.GetFullPath(dstImage), Path.GetFullPath(_currentImagePath), StringComparison.OrdinalIgnoreCase))
                File.Copy(_currentImagePath, dstImage, overwrite: false);

            // GDI+로 흑백 마스크를 직접 그린다(train.py는 cv2.imread(..., IMREAD_GRAYSCALE)로
            // 읽으므로 8bpp 인덱스일 필요 없음 — 32bpp라도 R=G=B면 그레이스케일로 정상 해석됨).
            // GetPixel/SetPixel 픽셀별 루프는 큰 이미지(수백만 픽셀)에서 매우 느려 대신 안 씀.
            using var maskBmp = new System.Drawing.Bitmap(_imgW, _imgH, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
            using (var g = System.Drawing.Graphics.FromImage(maskBmp))
            {
                g.Clear(System.Drawing.Color.Black);
                g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.None;   // 이진 마스크는 안티앨리어싱 없이(0/255만)
                using var whiteBrush = new System.Drawing.SolidBrush(System.Drawing.Color.White);
                foreach (var poly in _polygons)
                {
                    if (poly.Count < 3) continue;
                    var pts = poly.Select(p => new System.Drawing.PointF(
                        (float)(p.X * _imgW), (float)(p.Y * _imgH))).ToArray();
                    g.FillPolygon(whiteBrush, pts);
                }
            }

            // 브러쉬로 칠한 영역(알파>0)을 마스크에 OR로 합친다(폴리곤과 독립적으로 저장됐던 레이어).
            if (_brushBitmap != null && _brushBitmap.PixelWidth == _imgW && _brushBitmap.PixelHeight == _imgH)
            {
                var brushBuf = new byte[_imgW * _imgH * 4];
                _brushBitmap.CopyPixels(brushBuf, _imgW * 4, 0);

                var bmpData = maskBmp.LockBits(
                    new System.Drawing.Rectangle(0, 0, _imgW, _imgH),
                    System.Drawing.Imaging.ImageLockMode.ReadWrite,
                    System.Drawing.Imaging.PixelFormat.Format24bppRgb);
                try
                {
                    int stride = bmpData.Stride;
                    var row = new byte[stride];
                    for (int y = 0; y < _imgH; y++)
                    {
                        System.Runtime.InteropServices.Marshal.Copy(bmpData.Scan0 + y * stride, row, 0, stride);
                        int bo = y * _imgW * 4;
                        for (int x = 0; x < _imgW; x++)
                        {
                            byte alpha = brushBuf[bo + x * 4 + 3];   // Bgra32: B,G,R,A
                            if (alpha > 0) { row[x * 3] = 255; row[x * 3 + 1] = 255; row[x * 3 + 2] = 255; }
                        }
                        System.Runtime.InteropServices.Marshal.Copy(row, 0, bmpData.Scan0 + y * stride, stride);
                    }
                }
                finally { maskBmp.UnlockBits(bmpData); }
            }

            var dstMask = Path.Combine(masksDir, stem + ".png");
            maskBmp.Save(dstMask, System.Drawing.Imaging.ImageFormat.Png);

            HasExistingMask = true;
            Saved = true;
            _touched = false;
            var brushNote = _brushHasContent ? " + 브러쉬 칠함" : "";
            Status = $"마스크 저장 완료: {dstMask}  (폴리곤 {_polygons.Count}개{brushNote}, 둘 다 0이면 '결함 없음'으로 저장됨)";
            RefreshLabeledCount();
            return null;
        }
        catch (Exception ex)
        {
            return $"마스크 저장 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // 갤러리에서 여러 장을 골라 한 번에 저장된 마스크를 지운다("AI 초안을 여러 장 적용해봤는데
    // 마음에 안 드는 것들을 한번에 치우고 싶다"는 요청). 저장된 마스크는 폴리곤/브러쉬 구분 없이
    // 이미 평평한 raster라 "브러쉬만" 골라 지울 수 없음 — 사실상 그 이미지를 다시 미라벨링
    // 상태로 되돌리는 동작이다. 이미지 원본(train/data/images 사본)은 남긴다(다시 라벨링할 때
    // 필요하므로) — 지워지는 건 마스크뿐. 되돌릴 수 없어 View가 확인창을 띄운다.
    public (int deleted, string? error) ClearMasksForImages(IReadOnlyList<string> imagePaths)
    {
        if (_projectRoot == null) return (0, "프로젝트 루트를 찾을 수 없습니다.");
        var masksDir = Path.Combine(_projectRoot, "train", "data", "masks");
        int n = 0;
        try
        {
            bool currentAffected = false;
            foreach (var p in imagePaths)
            {
                var stem = Path.GetFileNameWithoutExtension(p);
                var maskPath = Path.Combine(masksDir, stem + ".png");
                if (File.Exists(maskPath)) { File.Delete(maskPath); n++; }
                if (_currentImagePath != null && string.Equals(p, _currentImagePath, StringComparison.OrdinalIgnoreCase))
                    currentAffected = true;
            }

            // 지금 열려있는 이미지가 지운 목록에 포함되면 화면도 즉시 반영(다시 열지 않아도 되게).
            if (currentAffected)
            {
                _polygons.Clear();
                _brushBitmap = null;
                _brushHasContent = false;
                BrushOverlay = null;
                MaskOverlay = null;
                _undoStack.Clear();
                OnPropertyChanged(nameof(CanUndo));
                HasExistingMask = false;
                AnyMaskDrawn = false;
                // 파일이 이미 지워져 디스크와 지금 화면(빈 상태)이 일치하므로 Saved=true, _touched=false
                // (그대로 다른 이미지로 넘어가도 SaveCurrent가 빈 마스크를 새로 만들어내지 않게).
                Saved = true;
                _touched = false;
                RefreshPolygonList();
                Status = "선택한 이미지들의 마스크를 지웠습니다. 새로 그려서 저장하세요.";
            }

            RefreshLabeledCount();
            return (n, null);
        }
        catch (Exception ex)
        {
            return (n, $"마스크 삭제 실패 — {FriendlyError.Describe(ex)}");
        }
    }

    // ===== AI 초안(반자동 라벨링) =====
    // 사장님 요청: "10000장을 해야하는데 100장정도 하고 학습해서... 매직 브러시를 넣으면
    // 좋겠어". 지금까지 손으로 라벨링한 이미지(train/data/images+masks)로 가벼운 세그멘테이션
    // 모델(train/train.py의 UNetLight)을 학습해, 나머지 이미지를 열 때 "AI 초안 채우기"로
    // 예측 마스크를 브러쉬 레이어에 미리 채워두고 사람은 다듬기만 하면 되게 한다.
    // 기존 "세그멘테이션" 탭이 쓰는 train/edge_unet_v2.onnx와는 별개 파일(edge_unet_draft.onnx)
    // 로 내보내 — 이 학습이 그 탭의 데모 모델을 덮어쓰지 않는다.

    private Process? _draftTrainProc;
    private string _draftTrainLog = "";

    private bool _isTrainingDraft;
    public bool IsTrainingDraft { get => _isTrainingDraft; private set => SetField(ref _isTrainingDraft, value); }

    private string _draftTrainStatus = "";
    public string DraftTrainStatus { get => _draftTrainStatus; private set => SetField(ref _draftTrainStatus, value); }

    private bool _hasDraftModel;
    public bool HasDraftModel { get => _hasDraftModel; private set => SetField(ref _hasDraftModel, value); }

    // AI 학습이 실제로 쓰는 범위(train/data/images 전체) — 세그 라벨링을 여러 번, 다른 폴더로
    // 써왔다면 지금 연 폴더와 무관한 옛날 이미지도 섞여 있을 수 있다.
    private int _labeledCount;
    public int LabeledCount { get => _labeledCount; private set => SetField(ref _labeledCount, value); }

    // 그 중 "지금 연 폴더"에서 온 이미지만의 라벨링 개수(진행 상황 표시용 — 사장님 피드백:
    // "왜 24장으로 한다고 하지?? 난 3개만 라벨링을 했거든" — 전체 학습 풀과 이 폴더의 진행률을
    // 헷갈리지 않게 분리해서 보여준다).
    private int _folderLabeledCount;
    public int FolderLabeledCount { get => _folderLabeledCount; private set => SetField(ref _folderLabeledCount, value); }

    private string? DraftModelPath => _projectRoot == null ? null : Path.Combine(_projectRoot, "train", "edge_unet_draft.onnx");

    private void RefreshDraftModelStatus() => HasDraftModel = DraftModelPath != null && File.Exists(DraftModelPath);

    // train/data/images 중 대응하는 마스크까지 있는(=실제로 학습에 쓰일) 이미지 수 +
    // 그 중 지금 연 폴더에서 온 것만 따로 센다.
    private void RefreshLabeledCount()
    {
        if (_projectRoot == null) { LabeledCount = 0; FolderLabeledCount = 0; return; }
        var imagesDir = Path.Combine(_projectRoot, "train", "data", "images");
        var masksDir = Path.Combine(_projectRoot, "train", "data", "masks");
        if (!Directory.Exists(imagesDir)) { LabeledCount = 0; FolderLabeledCount = 0; return; }
        int n = 0;
        foreach (var f in Directory.EnumerateFiles(imagesDir))
        {
            var stem = Path.GetFileNameWithoutExtension(f);
            if (File.Exists(Path.Combine(masksDir, stem + ".png"))) n++;
        }
        LabeledCount = n;

        int nFolder = 0;
        foreach (var t in Thumbnails)
        {
            var stem = Path.GetFileNameWithoutExtension(t.Path);
            if (File.Exists(Path.Combine(masksDir, stem + ".png"))) nFolder++;
        }
        FolderLabeledCount = nFolder;
    }

    // train/train_draft_assist.py(학습+ONNX export 한 번에)를 서브프로세스로 실행.
    // AnomalyViewModel.TrainNewModel과 동일한 패턴(검증된 방식 재사용).
    public void TrainDraftModel()
    {
        if (IsTrainingDraft || _projectRoot == null) return;
        var py = Path.Combine(_projectRoot, "train", ".venv", "Scripts", "python.exe");
        if (!File.Exists(py)) { DraftTrainStatus = $"파이썬을 찾을 수 없습니다: {py}"; return; }
        var script = Path.Combine(_projectRoot, "train", "train_draft_assist.py");
        if (!File.Exists(script)) { DraftTrainStatus = $"학습 스크립트를 찾을 수 없습니다: {script}"; return; }

        var psi = new ProcessStartInfo
        {
            FileName = py,
            Arguments = $"\"{script}\"",
            WorkingDirectory = _projectRoot,
            UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        PythonEnv.ConfigureVenv(psi, Path.Combine(_projectRoot, "train", ".venv"));

        try
        {
            _draftTrainLog = "";
            _draftTrainProc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _draftTrainProc.OutputDataReceived += (_, e) => { if (e.Data != null) OnDraftTrainLine(e.Data); };
            _draftTrainProc.ErrorDataReceived += (_, e) => { if (e.Data != null) OnDraftTrainLine(e.Data); };
            _draftTrainProc.Exited += (_, _) => Application.Current?.Dispatcher.Invoke(OnDraftTrainExited);
            _draftTrainProc.Start();
            _draftTrainProc.BeginOutputReadLine();
            _draftTrainProc.BeginErrorReadLine();
            IsTrainingDraft = true;
            DraftTrainStatus = "학습 시작 — 라이브러리 로딩 중… (처음엔 수 분 걸릴 수 있어요)";
        }
        catch (Exception ex)
        {
            DraftTrainStatus = $"학습 시작 실패: {FriendlyError.Describe(ex)}";
        }
    }

    public void CancelDraftTraining()
    {
        if (_draftTrainProc == null) return;
        try { if (!_draftTrainProc.HasExited) _draftTrainProc.Kill(entireProcessTree: true); } catch { }
        _draftTrainProc = null;
        IsTrainingDraft = false;
        DraftTrainStatus = "학습을 취소했습니다.";
    }

    private void OnDraftTrainLine(string line)
    {
        Application.Current?.Dispatcher.Invoke(() =>
        {
            _draftTrainLog += line + "\n";
            // train_draft_assist.py는 "[1/2] ..."/"[2/2] ..." 단계 안내와 매 epoch마다
            // "Epoch N: train_loss=... val_loss=..."를 출력 — 이 둘만 진행상황으로 보여준다.
            // (tqdm 진행바 갱신 줄도 "Epoch "로 시작하지만 ": train_loss="가 없어 걸러짐 —
            // 안 걸러지면 배치마다 여러 번 리렌더돼 상태 텍스트가 심하게 깜빡였음.)
            if (line.StartsWith("[") || line.Contains(": train_loss=")) DraftTrainStatus = line;
        });
    }

    private void OnDraftTrainExited()
    {
        bool ok = _draftTrainProc?.ExitCode == 0;
        IsTrainingDraft = false;
        _draftTrainProc = null;
        var path = DraftModelPath;
        if (ok && path != null && File.Exists(path))
        {
            DraftTrainStatus = "학습 완료! 다른 이미지에서 'AI 초안 채우기'를 쓸 수 있습니다.";
            _draftEngine?.Dispose(); _draftEngine = null;   // 다음 ApplyAiDraft 때 새 모델로 재로드
            RefreshDraftModelStatus();
            return;
        }

        var logPath = SaveDraftTrainLog();
        var logHint = logPath != null ? $"\n전체 기록: {logPath}" : "";
        if (_draftTrainLog.Contains("No module named"))
            DraftTrainStatus = "필요한 라이브러리가 설치돼 있지 않습니다(torch/opencv 등). 운영가이드의 설치 명령을 먼저 실행하세요." + logHint;
        else if (_draftTrainLog.Contains("CUDA out of memory") || _draftTrainLog.Contains("CUDA error"))
            DraftTrainStatus = "GPU 메모리가 부족합니다. 다른 프로그램(특히 그래픽 사용 프로그램)을 종료하고 다시 시도하세요." + logHint;
        else if (_draftTrainLog.Contains("No images found") || _draftTrainLog.Contains("마스크가"))
            DraftTrainStatus = "라벨링된 이미지가 없습니다. 먼저 폴리곤/브러쉬로 몇 장 이상 그려서 저장하세요." + logHint;
        else
            DraftTrainStatus = "학습 실패 — 로그를 확인하세요." + logHint;
    }

    private string? SaveDraftTrainLog()
    {
        if (_projectRoot == null) return null;
        try
        {
            var dir = Path.Combine(_projectRoot, "logs");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "seg_draft_train.log");
            File.WriteAllText(path, _draftTrainLog);
            return path;
        }
        catch { return null; }
    }

    private EdgeSegmentationEngine? _draftEngine;
    private string? _draftEngineModelPath;

    // 학습된 AI 보조 모델로 지금 열려있는 이미지의 마스크를 예측해 브러쉬 레이어에 채운다
    // (폴리곤은 건드리지 않음 — View가 기존 칠한 내용이 있으면 먼저 확인창을 띄운다).
    // 실행 취소 스택에도 남겨 Ctrl+Z로 되돌릴 수 있다.
    public string? ApplyAiDraft()
    {
        if (_rgb == null || _imgW <= 0 || _imgH <= 0) return "이미지를 먼저 여세요.";
        var path = DraftModelPath;
        if (path == null || !File.Exists(path))
            return "아직 학습된 AI 보조 모델이 없습니다. 먼저 'AI로 학습하기'를 실행하세요.";
        try
        {
            if (_draftEngine == null || _draftEngineModelPath != path)
            {
                _draftEngine?.Dispose();
                _draftEngine = new EdgeSegmentationEngine(path);
                _draftEngineModelPath = path;
            }

            // EdgeSegmentationEngine은 그레이스케일 입력을 기대(train.py의 cv2.IMREAD_GRAYSCALE와
            // 동일 전처리) — 캐시된 RGB24에서 표준 휘도 가중치(OpenCV RGB2GRAY와 동일 계수)로 변환.
            var gray = new byte[_imgW * _imgH];
            for (int i = 0; i < gray.Length; i++)
            {
                int o = i * 3;
                gray[i] = (byte)Math.Clamp(0.299 * _rgb[o] + 0.587 * _rgb[o + 1] + 0.114 * _rgb[o + 2], 0, 255);
            }

            var result = _draftEngine.Run(gray, _imgW, _imgH);

            EnsureBrushBitmap();
            var prev = new byte[_imgW * _imgH * 4];
            _brushBitmap!.CopyPixels(prev, _imgW * 4, 0);
            PushUndo(new UndoAction { Type = UndoActionType.BrushEdit, PrevBrushPixels = prev, PrevBrushHasContent = _brushHasContent });

            // AI 초안은 브러쉬 레이어를 통째로 대체한다(기존 브러쉬 칠은 지워짐 — 폴리곤은 무관).
            var buf = new byte[_imgW * _imgH * 4];
            bool any = false;
            for (int i = 0; i < result.BinaryMask.Length; i++)
            {
                if (result.BinaryMask[i] == 0) continue;
                any = true;
                int o = i * 4;
                buf[o] = 30; buf[o + 1] = 90; buf[o + 2] = 255; buf[o + 3] = 110;
            }
            _brushBitmap.WritePixels(new Int32Rect(0, 0, _imgW, _imgH), buf, _imgW * 4, 0);
            _brushHasContent = any;
            AnyMaskDrawn = _polygons.Count > 0 || _brushHasContent;
            Saved = false;
            _touched = true;
            Status = $"AI 초안 채움({result.InferenceMilliseconds:F0}ms) — 브러쉬/지우개로 다듬은 뒤 저장하세요.";
            return null;
        }
        catch (Exception ex)
        {
            return $"AI 초안 생성 실패 — {FriendlyError.Describe(ex)}";
        }
    }
}
