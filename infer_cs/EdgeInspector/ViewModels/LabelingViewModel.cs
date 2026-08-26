using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

// 박스 목록 한 줄(우측 패널 표시용).
public sealed class LabelBoxItem
{
    public required int Index { get; init; }
    public required string ClassName { get; init; }
    public required Brush Color { get; init; }
}

// 클래스 목록 한 줄(선택 가능 — 다음에 그릴 박스의 클래스).
public sealed class ClassItem : ViewModelBase
{
    public required int Index { get; init; }
    public required string Name { get; init; }
    public required Brush Color { get; init; }
    private bool _isSelected;
    public bool IsSelected { get => _isSelected; set => SetField(ref _isSelected, value); }
}

// 라벨링 도구(WPF 탭 버전) — 별도 파이썬 tkinter 창 대신 EdgeInspector 안에서 라벨링.
// 순수 로직은 Models/LabelingEngine.cs(labeling_core.py 이식)에 위임하고, 여기는 상태·
// 이미지 전환·오버레이 렌더만 담당한다. 좌표→픽셀 변환은 Views/LabelingView.xaml.cs가
// (마우스 이벤트가 UI 스레드 전용이라) 담당한다.
public sealed class LabelingViewModel : ViewModelBase
{
    private readonly string? _projectRoot;

    public event Action<string>? DatasetExported;   // data.yaml 경로 — 학습 탭으로 전달용
    public event Action<string>? SaveFailed;        // 라벨 자동저장 실패 — 조용히 묻히지 않게 View에 알림

    public LabelingViewModel(string? projectRoot)
    {
        _projectRoot = projectRoot;
    }

    public ObservableCollection<ThumbItem> Thumbnails { get; } = new();
    public ObservableCollection<ClassItem> Classes { get; } = new();
    public ObservableCollection<LabelBoxItem> BoxItems { get; } = new();

    private List<LabelBox> _boxes = new();

    // Ctrl+Z가 "마지막으로 그린 박스"가 아니라 "마지막 동작"을 정확히 되돌리도록 하는
    // 최소한의 액션 히스토리. 목록 중간 박스를 Delete로 지운 뒤 Undo하면, 관계없는
    // 마지막 박스가 아니라 방금 지운 그 박스가 원래 위치(Index)로 되살아나야 한다.
    private enum ActionType { Add, Delete }
    private readonly record struct BoxAction(ActionType Type, int Index, LabelBox Box);
    private readonly List<BoxAction> _history = new();
    private const int MaxHistory = 50;

    private void PushHistory(BoxAction action)
    {
        _history.Add(action);
        if (_history.Count > MaxHistory) _history.RemoveAt(0);
    }

    private string? _imagesRoot, _labelsRoot, _currentImagePath;
    private int _imgW, _imgH;
    public int ImageWidth => _imgW;
    public int ImageHeight => _imgH;

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

    private ImageSource? _boxOverlay;
    public ImageSource? BoxOverlay { get => _boxOverlay; private set => SetField(ref _boxOverlay, value); }

    private bool _hasFolder;
    public bool HasFolder { get => _hasFolder; private set => SetField(ref _hasFolder, value); }

    // 가이드 체크리스트(의식의 흐름 — 폴더열기→클래스확인→박스그리기→내보내기) 진행 상태.
    private bool _anyBoxDrawn;
    public bool AnyBoxDrawn { get => _anyBoxDrawn; private set => SetField(ref _anyBoxDrawn, value); }

    private bool _exported;
    public bool Exported { get => _exported; private set => SetField(ref _exported, value); }

    private string _newClassName = "";
    public string NewClassName { get => _newClassName; set => SetField(ref _newClassName, value); }

    private string _displayName = "";
    public string DisplayName { get => _displayName; set => SetField(ref _displayName, value); }

    private string _outName = "";
    public string OutName { get => _outName; set => SetField(ref _outName, value); }

    public int SelectedClassIndex => Classes.Select((c, i) => (c, i)).FirstOrDefault(t => t.c.IsSelected).i;

    // 클래스별 색 — YoloViewModel과 동일한 황금각 팔레트(도메인 전체에서 시각 일관성).
    private static Color ClassColor(int id)
    {
        double hue = (id * 137.508) % 360.0;
        return HsvToRgb(hue, 0.68, 1.0);
    }
    private static Color HsvToRgb(double h, double s, double v)
    {
        double c = v * s, x = c * (1 - Math.Abs((h / 60.0) % 2 - 1)), m = v - c;
        double r = 0, g = 0, b = 0;
        if (h < 60) { r = c; g = x; } else if (h < 120) { r = x; g = c; } else if (h < 180) { g = c; b = x; }
        else if (h < 240) { g = x; b = c; } else if (h < 300) { r = x; b = c; } else { r = c; b = x; }
        return Color.FromRgb((byte)((r + m) * 255), (byte)((g + m) * 255), (byte)((b + m) * 255));
    }

    public void OpenFolder(string imagesFolder)
    {
        _imagesRoot = imagesFolder;
        _labelsRoot = Path.Combine(Path.GetDirectoryName(imagesFolder.TrimEnd(Path.DirectorySeparatorChar)) ?? imagesFolder,
                                   Path.GetFileName(imagesFolder.TrimEnd(Path.DirectorySeparatorChar)) + "_labels");

        var images = LabelingEngine.ListImages(_imagesRoot);
        if (images.Count == 0)
        {
            Status = "선택한 폴더에 이미지가 없습니다.";
            HasFolder = false;
            return;
        }

        // 이 폴더에서 전에 쓰던 클래스가 있으면(classes.txt) 자동 로드 — 재입력 불필요.
        var existing = LabelingEngine.LoadClassNames(_labelsRoot);
        Classes.Clear();
        var names = existing.Count > 0 ? existing : new List<string> { "class0" };
        for (int i = 0; i < names.Count; i++)
            Classes.Add(new ClassItem { Index = i, Name = names[i], Color = new SolidColorBrush(ClassColor(i)) });
        Classes[0].IsSelected = true;
        LabelingEngine.SaveClassNames(_labelsRoot, names);

        LoadThumbnails(images);
        HasFolder = true;
        OutName = Path.GetFileName(imagesFolder.TrimEnd(Path.DirectorySeparatorChar)).Replace(" ", "_");
        DisplayName = Path.GetFileName(imagesFolder.TrimEnd(Path.DirectorySeparatorChar));
        FolderInfo = $"{images.Count}장 · 클래스 {Classes.Count}종";
        Status = "② 클래스를 확인하고 ③ 이미지 위에 드래그해서 박스를 그리세요.";

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

    public void AddClass(string name)
    {
        name = name.Trim();
        if (string.IsNullOrEmpty(name) || Classes.Any(c => c.Name == name)) return;
        int idx = Classes.Count;
        Classes.Add(new ClassItem { Index = idx, Name = name, Color = new SolidColorBrush(ClassColor(idx)) });
        if (_labelsRoot != null) LabelingEngine.SaveClassNames(_labelsRoot, Classes.Select(c => c.Name).ToList());
    }

    // 이미 있는 클래스와 대소문자·공백만 다른(사실상 같은) 이름을 찾아 돌려준다. 없으면 null.
    // "helmet"과 "Helmet"을 다른 클래스로 만들면 데이터가 둘로 쪼개져 정확도가 떨어지는데,
    // 비전공자는 이걸 눈치채기 어려워 라벨링 단계에서 미리 경고한다(뷰가 확인창을 띄움).
    public string? FindSimilarClass(string name)
    {
        var norm = name.Trim().Replace(" ", "").Replace("_", "").ToLowerInvariant();
        if (norm.Length == 0) return null;
        foreach (var c in Classes)
        {
            var cn = c.Name.Replace(" ", "").Replace("_", "").ToLowerInvariant();
            if (cn == norm && c.Name != name.Trim()) return c.Name;   // 정확히 같은 건 AddClass가 이미 막음
        }
        return null;
    }

    public void SelectClass(ClassItem item)
    {
        foreach (var c in Classes) c.IsSelected = false;
        item.IsSelected = true;
    }

    // 더블클릭으로 클래스 이름 변경(특히 기본값 "class0"을 의미있는 이름으로 바꾸기 위함).
    // ClassItem은 이 컬렉션 안에서만 유효하므로 새 인스턴스로 교체하지 않고 필드를 직접 못
    // 바꾸는 대신(레코드 아님) — Name이 init-only라 리스트에서 통째로 교체한다.
    public void RenameClass(ClassItem item, string newName)
    {
        newName = newName.Trim();
        if (newName.Length == 0 || newName == item.Name) return;
        int idx = Classes.IndexOf(item);
        if (idx < 0) return;
        var replacement = new ClassItem { Index = item.Index, Name = newName, Color = item.Color, IsSelected = item.IsSelected };
        Classes[idx] = replacement;
        if (_labelsRoot != null) LabelingEngine.SaveClassNames(_labelsRoot, Classes.Select(c => c.Name).ToList());
        RefreshBoxes();   // 캔버스/우측 목록의 클래스명 표시 갱신
    }

    private void LoadImage(string path)
    {
        SaveCurrent();   // 이미지 전환 전 이전 이미지 저장(라벨 유실 방지)
        try
        {
            var decoder = BitmapDecoder.Create(new Uri(path), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            var frame = decoder.Frames[0];
            _imgW = frame.PixelWidth; _imgH = frame.PixelHeight;
            frame.Freeze();
            Image = frame;
            _currentImagePath = path;

            var lp = LabelingEngine.LabelPathFor(path, _imagesRoot!, _labelsRoot!);
            _boxes = LabelingEngine.LoadLabels(lp);
            _history.Clear();   // 다른 이미지의 동작 기록은 이 이미지의 Undo에 쓰면 안 됨
            RefreshBoxes();
            Status = $"{Path.GetFileName(path)}  ({_imgW}x{_imgH})";
        }
        catch (Exception ex)
        {
            Status = $"이미지 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // ★ 실사용 버그(2026-07-19): SaveLabels(File.WriteAllText)가 던지는 예외를 여기서
    // 안 잡으면, 이 메서드를 부르는 자리(이미지 전환/창 닫기 등)에 전부 try/catch가
    // 없어서 전역 미처리예외 핸들러까지 올라가 "예상치 못한 문제" 창과 함께 앱이 통째로
    // 종료된다 — 라벨 하나 저장 실패가 세션 전체(다른 이미지 작업 포함) 유실로 번짐.
    public void SaveCurrent()
    {
        if (_currentImagePath == null || _imagesRoot == null || _labelsRoot == null) return;
        var lp = LabelingEngine.LabelPathFor(_currentImagePath, _imagesRoot, _labelsRoot);
        try
        {
            LabelingEngine.SaveLabels(lp, _boxes);
        }
        catch (Exception ex)
        {
            SaveFailed?.Invoke(FriendlyError.Describe(ex));
        }
    }

    // 캔버스(픽셀 좌표)에서 드래그로 만든 박스를 추가. View가 스케일 변환을 마친 좌표를 넘긴다.
    public void AddBoxPixel(double x1, double y1, double x2, double y2)
    {
        if (_imgW <= 0 || _imgH <= 0) return;
        var box = LabelingEngine.PixelToYolo(SelectedClassIndex, x1, y1, x2, y2, _imgW, _imgH);
        if (box.W <= 0 || box.H <= 0) return;
        _boxes.Add(box);
        PushHistory(new BoxAction(ActionType.Add, _boxes.Count - 1, box));
        AnyBoxDrawn = true;
        RefreshBoxes();
    }

    public void DeleteBox(int index)
    {
        if (index < 0 || index >= _boxes.Count) return;
        var box = _boxes[index];
        _boxes.RemoveAt(index);
        PushHistory(new BoxAction(ActionType.Delete, index, box));
        RefreshBoxes();
    }

    // 히스토리 맨 위 동작을 정확히 되돌린다: 마지막이 추가였으면 그 박스를 제거,
    // 마지막이 삭제였으면 지워졌던 박스를 원래 인덱스(Index)에 되살린다. 무관한
    // 마지막 항목을 지우던(예전 버그) 대신, 실제로 실행됐던 동작만 되돌아간다.
    public void UndoLastBox()
    {
        if (_history.Count == 0) return;
        var last = _history[^1];
        _history.RemoveAt(_history.Count - 1);
        if (last.Type == ActionType.Add)
        {
            if (last.Index >= 0 && last.Index < _boxes.Count) _boxes.RemoveAt(last.Index);
        }
        else
        {
            int insertAt = Math.Clamp(last.Index, 0, _boxes.Count);
            _boxes.Insert(insertAt, last.Box);
        }
        RefreshBoxes();
    }

    private void RefreshBoxes()
    {
        BoxItems.Clear();
        for (int i = 0; i < _boxes.Count; i++)
        {
            var b = _boxes[i];
            var name = b.ClsId < Classes.Count ? Classes[b.ClsId].Name : $"class{b.ClsId}";
            BoxItems.Add(new LabelBoxItem { Index = i, ClassName = name, Color = new SolidColorBrush(ClassColor(b.ClsId)) });
        }
        BoxOverlay = BuildOverlay();
    }

    private DrawingImage? BuildOverlay()
    {
        if (_imgW <= 0 || _imgH <= 0) return null;
        var group = new DrawingGroup();
        // 투명한 전체 이미지 사각형을 먼저 그려 DrawingImage 경계를 원본 이미지 크기로 고정한다.
        // 이게 없으면 DrawingImage 크기가 "그려진 박스들의 bounding box"로 자동 축소돼,
        // Stretch=Uniform로 표시될 때 원본 이미지와 다른 비율·위치로 늘어나 박스가 마우스
        // 좌표와 어긋난다(특히 박스 하나만 있을 때 심하게 어긋남).
        group.Children.Add(new GeometryDrawing(Brushes.Transparent, null,
            new RectangleGeometry(new Rect(0, 0, _imgW, _imgH))));
        var typeface = new Typeface("Segoe UI");
        foreach (var b in _boxes)
        {
            var (x1, y1, x2, y2) = LabelingEngine.YoloToPixel(b, _imgW, _imgH);
            var color = ClassColor(b.ClsId);
            var pen = new Pen(new SolidColorBrush(color), Math.Max(1.5, _imgW / 400.0));
            group.Children.Add(new GeometryDrawing(null, pen, new RectangleGeometry(new Rect(x1, y1, x2 - x1, y2 - y1))));
            var name = b.ClsId < Classes.Count ? Classes[b.ClsId].Name : $"class{b.ClsId}";
            var text = new FormattedText(name, System.Globalization.CultureInfo.InvariantCulture,
                FlowDirection.LeftToRight, typeface, Math.Max(10, _imgW / 55.0), Brushes.Black, 1.0);
            double ty = Math.Max(0, y1 - text.Height);
            group.Children.Add(new GeometryDrawing(new SolidColorBrush(color), null,
                new RectangleGeometry(new Rect(x1, ty, text.Width + 4, text.Height))));
            group.Children.Add(new GeometryDrawing(Brushes.Black, null, text.BuildGeometry(new Point(x1 + 2, ty))));
        }
        var img = new DrawingImage(group);
        img.Freeze();
        return img;
    }

    public (string? DataYaml, int Train, int Val, string? Error, string? Warning) Export()
    {
        SaveCurrent();
        if (_imagesRoot == null || _labelsRoot == null || _projectRoot == null)
            return (null, 0, 0, "이미지 폴더를 먼저 여세요.", null);
        var name = OutName.Trim();
        if (name.Length == 0 || !System.Text.RegularExpressions.Regex.IsMatch(name, "^[A-Za-z0-9_]+$"))
            return (null, 0, 0, "산출물 이름은 영문/숫자/밑줄만 됩니다(예: my_office).", null);

        var outDir = Path.Combine(_projectRoot, "examples", name);
        var classNames = Classes.Select(c => c.Name).ToList();
        var result = LabelingEngine.ExportDataset(_imagesRoot, _labelsRoot, classNames, outDir);
        if (result.Error != null) return (null, 0, 0, result.Error, null);
        if (result.DataYaml != null) { DatasetExported?.Invoke(result.DataYaml); Exported = true; }
        Status = $"데이터셋 생성 완료: train {result.Train} / val {result.Val}";
        return (result.DataYaml, result.Train, result.Val, null, result.Warning);
    }
}
