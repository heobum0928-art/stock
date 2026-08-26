using System.Diagnostics;
using System.Linq;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace EdgeInspector.Models;

public sealed class YoloDetection
{
    public required int ClassId { get; init; }
    public required string ClassName { get; init; }
    public required float Score { get; init; }
    // 원본 이미지 픽셀 좌표 기준 박스(좌상단 x1,y1 / 우하단 x2,y2)
    public required float X1 { get; init; }
    public required float Y1 { get; init; }
    public required float X2 { get; init; }
    public required float Y2 { get; init; }
}

public sealed class YoloResult
{
    public required List<YoloDetection> Detections { get; init; }
    public required double InferenceMilliseconds { get; init; }
}

// Ultralytics YOLOv8/v11(end2end=False) ONNX 전용 검출 엔진.
// 입력 "images"[1,3,640,640], 출력 [1,4+nc,N]. 디코드 로직은 vision_detect/yolo_decode.py의
// letterbox/decode_detections/finalize_detections를 C#으로 이식한 것(같은 알고리즘: letterbox
// → transpose → 클래스 argmax → NMS → letterbox 역변환). NMS는 onnxruntime에 없어 그리디 IoU로 구현.
public sealed class YoloDetectionEngine : IDisposable
{
    // 입력 정사각 크기. 640 하드코딩이 아니라 ONNX 메타데이터에서 실제 크기를 읽는다
    // (학습 마법사 "빠르게 확인만" 모드는 480으로 export하므로 — verify_yolo.py와 동일한 자동 감지).
    private readonly int _inputSize;

    private readonly InferenceSession _session;
    private readonly string _inputName;
    private readonly string _outputName;
    private readonly IReadOnlyList<string> _classNames;

    public string ModelPath { get; }

    public YoloDetectionEngine(string modelPath, IReadOnlyList<string> classNames)
    {
        ModelPath = modelPath;
        _classNames = classNames;
        _session = new InferenceSession(modelPath);
        _inputName = _session.InputMetadata.Keys.First();
        _outputName = _session.OutputMetadata.Keys.First();

        // 입력 shape [1,3,H,W]에서 H(=W 가정)를 읽는다. 동적(-1)이거나 못 읽으면 640.
        var dims = _session.InputMetadata[_inputName].Dimensions;
        int size = (dims != null && dims.Length == 4 && dims[2] > 0) ? dims[2] : 640;
        _inputSize = size;
    }

    public YoloResult Run(byte[] rgb, int width, int height, float scoreThr = 0.25f, float iouThr = 0.45f)
    {
        if (width <= 0 || height <= 0)
            throw new ArgumentException($"width/height는 양수여야 합니다 (width={width}, height={height})");
        if (rgb.Length != width * height * 3)
            throw new ArgumentException($"rgb 배열 길이({rgb.Length})가 width*height*3({width * height * 3})와 다릅니다");

        // --- letterbox (yolo_decode.letterbox와 동일) ---
        float gain = Math.Min(_inputSize / (float)height, _inputSize / (float)width);
        int newW = Math.Max(1, (int)Math.Round(width * gain));
        int newH = Math.Max(1, (int)Math.Round(height * gain));
        int padLeft = (_inputSize - newW) / 2;
        int padTop = (_inputSize - newH) / 2;

        var input = new DenseTensor<float>(new[] { 1, 3, _inputSize, _inputSize });
        // 패딩 영역은 114/255로 채움(letterbox의 회색 패딩)
        float padVal = 114f / 255f;
        for (int c = 0; c < 3; c++)
            for (int y = 0; y < _inputSize; y++)
                for (int x = 0; x < _inputSize; x++)
                    input[0, c, y, x] = padVal;

        // 원본 → newW×newH 양선형 리사이즈 후 패딩 위치에 배치
        for (int y = 0; y < newH; y++)
        {
            float sy = Math.Clamp((y + 0.5f) * height / newH - 0.5f, 0, height - 1);
            int y0 = (int)MathF.Floor(sy); int y1 = Math.Min(y0 + 1, height - 1); float fy = sy - y0;
            for (int x = 0; x < newW; x++)
            {
                float sx = Math.Clamp((x + 0.5f) * width / newW - 0.5f, 0, width - 1);
                int x0 = (int)MathF.Floor(sx); int x1 = Math.Min(x0 + 1, width - 1); float fx = sx - x0;
                for (int c = 0; c < 3; c++)
                {
                    float p00 = rgb[(y0 * width + x0) * 3 + c], p01 = rgb[(y0 * width + x1) * 3 + c];
                    float p10 = rgb[(y1 * width + x0) * 3 + c], p11 = rgb[(y1 * width + x1) * 3 + c];
                    float top = p00 * (1 - fx) + p01 * fx;
                    float bot = p10 * (1 - fx) + p11 * fx;
                    input[0, c, padTop + y, padLeft + x] = (top * (1 - fy) + bot * fy) / 255f;
                }
            }
        }

        var inputs = new List<NamedOnnxValue> { NamedOnnxValue.CreateFromTensor(_inputName, input) };
        var sw = Stopwatch.StartNew();
        using var outputs = _session.Run(inputs);
        sw.Stop();

        var output = outputs.First(o => o.Name == _outputName).AsTensor<float>();
        // 출력 [1, 4+nc, N]
        int ch = output.Dimensions[1];
        int n = output.Dimensions[2];
        int nc = ch - 4;

        // --- decode (yolo_decode.decode_detections와 동일) ---
        var candidates = new List<(float x1, float y1, float x2, float y2, float score, int cls)>();
        for (int i = 0; i < n; i++)
        {
            int bestCls = 0; float bestScore = 0f;
            for (int c = 0; c < nc; c++)
            {
                float s = output[0, 4 + c, i];
                if (s > bestScore) { bestScore = s; bestCls = c; }
            }
            if (bestScore < Math.Max(scoreThr, 1e-6f)) continue;

            float cx = output[0, 0, i], cy = output[0, 1, i], bw = output[0, 2, i], bh = output[0, 3, i];
            // letterbox 좌표(640) → 원본 좌표 역변환
            float x1 = (cx - bw / 2 - padLeft) / gain;
            float y1 = (cy - bh / 2 - padTop) / gain;
            float x2 = (cx + bw / 2 - padLeft) / gain;
            float y2 = (cy + bh / 2 - padTop) / gain;
            x1 = Math.Clamp(x1, 0, width); x2 = Math.Clamp(x2, 0, width);
            y1 = Math.Clamp(y1, 0, height); y2 = Math.Clamp(y2, 0, height);
            if (x2 - x1 <= 0 || y2 - y1 <= 0) continue;
            candidates.Add((x1, y1, x2, y2, bestScore, bestCls));
        }

        var kept = NonMaxSuppression(candidates, iouThr);

        var dets = kept
            .Where(d => d.score >= scoreThr)
            .OrderByDescending(d => d.score).ThenBy(d => d.x1).ThenBy(d => d.y1)
            .Select(d => new YoloDetection
            {
                ClassId = d.cls,
                ClassName = d.cls < _classNames.Count ? _classNames[d.cls] : $"class_{d.cls}",
                Score = d.score,
                X1 = d.x1, Y1 = d.y1, X2 = d.x2, Y2 = d.y2,
            })
            .ToList();

        return new YoloResult { Detections = dets, InferenceMilliseconds = sw.Elapsed.TotalMilliseconds };
    }

    // 그리디 NMS(클래스 무관 — cv2.dnn.NMSBoxes와 동일하게 전체 박스 대상). 점수 내림차순으로
    // 훑으며 이미 채택된 박스와 IoU가 임계값 넘으면 제거.
    private static List<(float x1, float y1, float x2, float y2, float score, int cls)> NonMaxSuppression(
        List<(float x1, float y1, float x2, float y2, float score, int cls)> boxes, float iouThr)
    {
        var sorted = boxes.OrderByDescending(b => b.score).ToList();
        var kept = new List<(float x1, float y1, float x2, float y2, float score, int cls)>();
        var removed = new bool[sorted.Count];
        for (int i = 0; i < sorted.Count; i++)
        {
            if (removed[i]) continue;
            kept.Add(sorted[i]);
            for (int j = i + 1; j < sorted.Count; j++)
            {
                if (removed[j]) continue;
                if (Iou(sorted[i], sorted[j]) > iouThr) removed[j] = true;
            }
        }
        return kept;
    }

    private static float Iou(
        (float x1, float y1, float x2, float y2, float score, int cls) a,
        (float x1, float y1, float x2, float y2, float score, int cls) b)
    {
        float ix1 = Math.Max(a.x1, b.x1), iy1 = Math.Max(a.y1, b.y1);
        float ix2 = Math.Min(a.x2, b.x2), iy2 = Math.Min(a.y2, b.y2);
        float iw = Math.Max(0, ix2 - ix1), ih = Math.Max(0, iy2 - iy1);
        float inter = iw * ih;
        float areaA = (a.x2 - a.x1) * (a.y2 - a.y1);
        float areaB = (b.x2 - b.x1) * (b.y2 - b.y1);
        float union = areaA + areaB - inter;
        return union <= 0 ? 0 : inter / union;
    }

    public void Dispose() => _session.Dispose();
}
