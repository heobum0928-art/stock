using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EdgeInspector.Models;

namespace EdgeInspector.ViewModels;

public sealed class MainViewModel : ViewModelBase, IDisposable
{
    private readonly string? _projectRoot;
    private EdgeSegmentationEngine? _engine;
    private byte[]? _grayscale;
    private int _imgWidth;
    private int _imgHeight;

    private bool _loaded;

    public MainViewModel(string? projectRoot = null)
    {
        _projectRoot = projectRoot;
    }

    // 세그 탭 첫 활성화 때 기본 U-Net 모델 로드 + 썸네일 + 첫 샘플 자동 로드.
    public void EnsureLoaded()
    {
        if (_loaded) return;
        _loaded = true;
        if (_projectRoot == null) return;
        var model = Path.Combine(_projectRoot, "train", "edge_unet_v2.onnx");
        if (File.Exists(model)) LoadModel(model);
    }

    public ObservableCollection<ThumbItem> Thumbnails { get; } = new();

    private ThumbItem? _selectedThumb;
    public ThumbItem? SelectedThumb
    {
        get => _selectedThumb;
        set { if (SetField(ref _selectedThumb, value) && value != null) LoadImage(value.Path); }
    }

    public string? SampleDir =>
        _projectRoot != null ? Path.Combine(_projectRoot, "train", "data", "images") : null;

    private void LoadThumbnails()
    {
        Thumbnails.Clear();
        var dir = SampleDir;
        if (dir == null || !Directory.Exists(dir)) return;
        var exts = new[] { ".jpg", ".jpeg", ".png", ".bmp" };
        var files = Directory.EnumerateFiles(dir)
            .Where(f => exts.Contains(Path.GetExtension(f).ToLowerInvariant()))
            .OrderBy(f => f).Take(60);
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

    private string _modelPath = "(모델 없음)";
    public string ModelPath { get => _modelPath; private set => SetField(ref _modelPath, value); }

    private string _imagePath = "(이미지 없음)";
    public string ImagePath { get => _imagePath; private set => SetField(ref _imagePath, value); }

    private string _status = "모델과 이미지를 여세요.";
    public string Status { get => _status; private set => SetField(ref _status, value); }

    private double _threshold = 0.5;
    public double Threshold
    {
        get => _threshold;
        set
        {
            if (!SetField(ref _threshold, value)) return;
            // ★ 성능: threshold만 바뀐 거면 ONNX를 다시 돌릴 필요가 없다 — 이미 계산해둔
            // 확률맵(_lastProbabilityMap)으로 이진화만 다시 한다. 처음 로드처럼 확률맵이
            // 아직 없으면 전체 추론으로 폴백.
            if (_lastProbabilityMap != null) ApplyThresholdOnly();
            else RunInference();
        }
    }

    private byte[]? _lastProbabilityMap;

    private bool _showOverlay = true;
    public bool ShowOverlay { get => _showOverlay; set => SetField(ref _showOverlay, value); }

    private ImageSource? _originalImage;
    public ImageSource? OriginalImage { get => _originalImage; private set => SetField(ref _originalImage, value); }

    private ImageSource? _overlayImage;
    public ImageSource? OverlayImage { get => _overlayImage; private set => SetField(ref _overlayImage, value); }

    private ImageSource? _probabilityImage;
    public ImageSource? ProbabilityImage { get => _probabilityImage; private set => SetField(ref _probabilityImage, value); }

    public void LoadModel(string path)
    {
        try
        {
            _engine?.Dispose();
            _engine = new EdgeSegmentationEngine(path);
            ModelPath = path;
            Status = "모델 로드 완료.";
            LoadThumbnails();
            // 첫 샘플 자동 로드(빈 화면 방지)
            if (_grayscale == null && Thumbnails.Count > 0)
            {
                _selectedThumb = Thumbnails[0]; OnPropertyChanged(nameof(SelectedThumb));
                LoadImage(Thumbnails[0].Path);
            }
            else RunInference();
        }
        catch (Exception ex)
        {
            Status = $"모델 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    public void LoadImage(string path)
    {
        try
        {
            var decoder = BitmapDecoder.Create(new Uri(path), BitmapCreateOptions.None, BitmapCacheOption.OnLoad);
            BitmapSource frame = decoder.Frames[0];
            var gray = new FormatConvertedBitmap(frame, PixelFormats.Gray8, null, 0);
            gray.Freeze();

            _imgWidth = gray.PixelWidth;
            _imgHeight = gray.PixelHeight;
            _grayscale = new byte[_imgWidth * _imgHeight];
            gray.CopyPixels(_grayscale, _imgWidth, 0);

            OriginalImage = gray;
            ImagePath = path;
            Status = $"이미지 로드: {Path.GetFileName(path)} ({_imgWidth}x{_imgHeight})";
            RunInference();
        }
        catch (Exception ex)
        {
            Status = $"이미지 로드 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private void RunInference()
    {
        if (_engine == null || _grayscale == null)
            return;

        try
        {
            var result = _engine.Run(_grayscale, _imgWidth, _imgHeight, Threshold);
            _lastProbabilityMap = result.ProbabilityMap;

            var prob = BitmapSource.Create(_imgWidth, _imgHeight, 96, 96, PixelFormats.Gray8, null, result.ProbabilityMap, _imgWidth);
            prob.Freeze();
            ProbabilityImage = prob;

            var overlay = BuildOverlay(result.BinaryMask, _imgWidth, _imgHeight);
            overlay.Freeze();
            OverlayImage = overlay;

            Status = $"추론 완료: {result.InferenceMilliseconds:F1} ms (threshold={Threshold:F2})";
        }
        catch (Exception ex)
        {
            Status = $"추론 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    // threshold 슬라이더 전용 경량 경로 — ONNX 재실행 없이 캐시된 확률맵으로 이진화만.
    private void ApplyThresholdOnly()
    {
        if (_lastProbabilityMap == null) return;
        try
        {
            var mask = EdgeSegmentationEngine.ApplyThreshold(_lastProbabilityMap, Threshold);
            var overlay = BuildOverlay(mask, _imgWidth, _imgHeight);
            overlay.Freeze();
            OverlayImage = overlay;
            Status = $"임계값 적용: threshold={Threshold:F2}";
        }
        catch (Exception ex)
        {
            Status = $"임계값 적용 실패 — {FriendlyError.Describe(ex)}";
        }
    }

    private static BitmapSource BuildOverlay(byte[] mask, int width, int height)
    {
        var pixels = new byte[width * height * 4]; // BGRA
        for (int i = 0; i < mask.Length; i++)
        {
            if (mask[i] == 0)
                continue;

            int o = i * 4;
            pixels[o + 0] = 0;   // B
            pixels[o + 1] = 0;   // G
            pixels[o + 2] = 255; // R (에지 강조색)
            pixels[o + 3] = 160; // A
        }

        return BitmapSource.Create(width, height, 96, 96, PixelFormats.Bgra32, null, pixels, width * 4);
    }

    public void Dispose() => _engine?.Dispose();
}
