using System.Diagnostics;
using System.Linq;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace EdgeInspector.Models;

public sealed class EdgeSegmentationResult
{
    public required byte[] ProbabilityMap { get; init; } // 0-255, 원본 이미지 크기
    public required byte[] BinaryMask { get; init; }      // 0/255, 원본 이미지 크기
    public required int Width { get; init; }
    public required int Height { get; init; }
    public required double InferenceMilliseconds { get; init; }
}

// train/export_onnx.py 산출물(edge_unet*.onnx) 전용 어댑터.
// 입력 "input" [1,1,512,512] 그레이스케일 0..1, 출력 "output" 로짓 -> sigmoid -> threshold.
// 전처리/후처리는 train/infer_debug.py의 preprocess_cv2/postprocess_and_save와 동일한 순서를 따른다.
public sealed class EdgeSegmentationEngine : IDisposable
{
    private const int InputSize = 512;

    private readonly InferenceSession _session;

    public string ModelPath { get; }

    public EdgeSegmentationEngine(string modelPath)
    {
        ModelPath = modelPath;
        _session = new InferenceSession(modelPath);
    }

    public EdgeSegmentationResult Run(byte[] grayscale, int width, int height, double threshold = 0.5)
    {
        if (width <= 0 || height <= 0)
            throw new ArgumentException($"width/height는 양수여야 합니다 (width={width}, height={height})");
        // (long) 곱셈 — 초대형 이미지에서 int 오버플로로 가드가 뚫리거나 에러 메시지가
        // 음수/이상값이 되는 것 방지.
        long expected = (long)width * height;
        if (grayscale.Length != expected)
            throw new ArgumentException(
                $"grayscale 배열 길이({grayscale.Length})가 width*height({expected})와 다릅니다");

        var srcFloat = new float[grayscale.Length];
        for (int i = 0; i < grayscale.Length; i++)
            srcFloat[i] = grayscale[i];

        var resized = BilinearResize(srcFloat, width, height, InputSize, InputSize);

        var input = new DenseTensor<float>(new[] { 1, 1, InputSize, InputSize });
        for (int i = 0; i < resized.Length; i++)
            input[0, 0, i / InputSize, i % InputSize] = resized[i] / 255f;

        var inputs = new List<NamedOnnxValue> { NamedOnnxValue.CreateFromTensor("input", input) };

        var sw = Stopwatch.StartNew();
        using var outputs = _session.Run(inputs);
        sw.Stop();

        var logits = outputs.First(o => o.Name == "output").AsTensor<float>();

        // 출력이 [1,1,H,W](4D) / [1,H,W](3D) / [1,1*H*W](평탄) 어느 형태든 되게,
        // 텐서를 순서대로 평탄하게 훑어(GetValue) 인덱스로 접근한다.
        var flat = logits.ToArray();
        var probSmall = new float[InputSize * InputSize];
        for (int i = 0; i < probSmall.Length && i < flat.Length; i++)
            probSmall[i] = Sigmoid(flat[i]);

        var probFull = BilinearResize(probSmall, InputSize, InputSize, width, height);

        var probMap = new byte[width * height];
        var binMask = new byte[width * height];
        for (int i = 0; i < probFull.Length; i++)
        {
            probMap[i] = (byte)Math.Clamp(probFull[i] * 255f, 0, 255);
            binMask[i] = probFull[i] >= threshold ? (byte)255 : (byte)0;
        }

        return new EdgeSegmentationResult
        {
            ProbabilityMap = probMap,
            BinaryMask = binMask,
            Width = width,
            Height = height,
            InferenceMilliseconds = sw.Elapsed.TotalMilliseconds,
        };
    }

    // 이미 계산된 확률맵(ProbabilityMap, 0-255 byte)으로 이진화만 다시 한다 — ONNX
    // 재실행이나 리사이즈 없음. 슬라이더로 threshold만 바꿀 때, 전체 재추론(리사이즈→
    // ONNX→리사이즈)을 매번 반복하던 버벅임을 없애기 위함(MainViewModel.Threshold 참고).
    // ProbabilityMap이 float(0..1)을 byte(0..255)로 양자화한 값이라 경계에서 1/255
    // 미만의 오차가 생길 수 있으나, 미리보기 오버레이 용도라 무시 가능한 수준이다.
    public static byte[] ApplyThreshold(byte[] probabilityMap, double threshold)
    {
        var mask = new byte[probabilityMap.Length];
        byte thr = (byte)Math.Clamp(threshold * 255.0, 0, 255);
        for (int i = 0; i < probabilityMap.Length; i++)
            mask[i] = probabilityMap[i] >= thr ? (byte)255 : (byte)0;
        return mask;
    }

    private static float Sigmoid(float x) => 1f / (1f + MathF.Exp(-x));

    // ★ 실사용 버그(2026-07-19, AnomalyDetectionEngine에서 먼저 발견한 것과 동일 클래스):
    // 원본(예: 1700x2200)을 InputSize(512x512)로 축소할 때 목적픽셀당 원본 4점만 보는
    // 순수 bilinear를 쓰면, 배율이 클수록(3~4배 이상 축소) 가는 크랙/에지가 4점 샘플링
    // 사이로 빠져 사라질 수 있다. 축소는 면적평균(cv2.INTER_AREA와 동치, 목적픽셀이
    // 덮는 원본 영역 전체 평균)으로, 확대(512→원본 크기로 되돌리는 두 번째 호출)는
    // 기존 bilinear를 유지한다.
    private static float[] BilinearResize(float[] src, int srcW, int srcH, int dstW, int dstH)
    {
        bool downscale = dstW < srcW || dstH < srcH;
        return downscale
            ? AreaResize(src, srcW, srcH, dstW, dstH)
            : BilinearUpscale(src, srcW, srcH, dstW, dstH);
    }

    private static float[] AreaResize(float[] src, int srcW, int srcH, int dstW, int dstH)
    {
        int iw = srcW + 1;
        var integral = new double[iw * (srcH + 1)];
        for (int y = 0; y < srcH; y++)
        {
            double rowSum = 0;
            int rowBase = y * srcW;
            int curr = (y + 1) * iw;
            int prev = y * iw;
            for (int x = 0; x < srcW; x++)
            {
                rowSum += src[rowBase + x];
                integral[curr + x + 1] = integral[prev + x + 1] + rowSum;
            }
        }

        double scaleX = (double)srcW / dstW;
        double scaleY = (double)srcH / dstH;
        var x0s = new int[dstW]; var x1s = new int[dstW];
        for (int dx = 0; dx < dstW; dx++)
        {
            int x0 = (int)Math.Floor(dx * scaleX);
            int x1 = Math.Min((int)Math.Ceiling((dx + 1) * scaleX), srcW);
            if (x1 <= x0) x1 = x0 + 1;
            x0s[dx] = x0; x1s[dx] = x1;
        }

        var dst = new float[dstW * dstH];
        for (int dy = 0; dy < dstH; dy++)
        {
            int y0 = (int)Math.Floor(dy * scaleY);
            int y1 = Math.Min((int)Math.Ceiling((dy + 1) * scaleY), srcH);
            if (y1 <= y0) y1 = y0 + 1;
            int rowA = y0 * iw, rowB = y1 * iw;
            int dstRowBase = dy * dstW;
            for (int dx = 0; dx < dstW; dx++)
            {
                int x0 = x0s[dx], x1 = x1s[dx];
                double sum = integral[rowB + x1] - integral[rowA + x1] - integral[rowB + x0] + integral[rowA + x0];
                int count = (x1 - x0) * (y1 - y0);
                dst[dstRowBase + dx] = (float)(sum / count);
            }
        }
        return dst;
    }

    // cv2.resize(INTER_LINEAR)와 동일한 half-pixel-center 매핑을 쓰는 양선형 리사이즈(확대용).
    private static float[] BilinearUpscale(float[] src, int srcW, int srcH, int dstW, int dstH)
    {
        var dst = new float[dstW * dstH];
        float scaleX = (float)srcW / dstW;
        float scaleY = (float)srcH / dstH;

        for (int dy = 0; dy < dstH; dy++)
        {
            float sy = Math.Clamp((dy + 0.5f) * scaleY - 0.5f, 0, srcH - 1);
            int y0 = (int)MathF.Floor(sy);
            int y1 = Math.Min(y0 + 1, srcH - 1);
            float fy = sy - y0;

            for (int dx = 0; dx < dstW; dx++)
            {
                float sx = Math.Clamp((dx + 0.5f) * scaleX - 0.5f, 0, srcW - 1);
                int x0 = (int)MathF.Floor(sx);
                int x1 = Math.Min(x0 + 1, srcW - 1);
                float fx = sx - x0;

                float top = src[y0 * srcW + x0] * (1 - fx) + src[y0 * srcW + x1] * fx;
                float bottom = src[y1 * srcW + x0] * (1 - fx) + src[y1 * srcW + x1] * fx;
                dst[dy * dstW + dx] = top * (1 - fy) + bottom * fy;
            }
        }

        return dst;
    }

    public void Dispose() => _session.Dispose();
}
