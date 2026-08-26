using System.Diagnostics;
using System.Linq;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;

namespace EdgeInspector.Models;

public sealed class AnomalyResult
{
    public required float Score { get; init; }              // 이상 점수(높을수록 이상). anomalib 후처리로 대략 0..1 정규화.
    public required float[] HeatMap { get; init; }          // 0..1 정규화된 이상맵(mapW*mapH)
    public required int MapWidth { get; init; }
    public required int MapHeight { get; init; }
    public required double InferenceMilliseconds { get; init; }
}

// anomalib PatchCore(Engine.export) ONNX 전용 어댑터.
// 입력 "input" [1,3,256,256] RGB, ImageNet 정규화. 출력: pred_score(스칼라),
// anomaly_map[1,1,h,w](히트맵). 후처리(메모리뱅크 거리+정규화)가 그래프에 박혀 있어
// onnxruntime만으로 점수+히트맵이 나온다.
// 전처리는 verify_anomaly.py(=anomalib 기본 PreProcessor)와 일치: 축소는 면적평균(PIL의
// 큰 배율 축소 시 안티에일리어싱과 거의 동일, cv2.INTER_AREA와 동치) + ImageNet mean/std.
// cv2류 보간 불일치 시 전부 이상으로 나오는 anomalib #2303 버그, 그리고 4점 bilinear로
// 축소하면 작은 결함이 씻겨나가 재현율이 떨어지던 버그(2026-07-19) 둘 다 주의.
public sealed class AnomalyDetectionEngine : IDisposable
{
    // ★ 하드코딩 금지 — train_anomaly.py --imgsz로 256이 아닌 다른 해상도(예: 512)로 학습한
    // 모델을 로드하면, 여기서 무조건 256으로 리사이즈해 실제 모델이 기대하는 입력 크기와 어긋나
    // 그래프 안에서 텐서 모양이 안 맞고 그 결과 히트맵 위치/모양이 엉뚱하게 나온다(실사용 버그
    // 리포트: "히트맵 위치가 안 맞는거 같은데" — beadsw_512처럼 256이 아닌 모델에서 재현됨).
    // ONNX 메타데이터에서 실제 입력 크기를 읽어와 그 크기로 리사이즈한다
    // (YoloDetectionEngine의 InputSize 자동감지와 동일 원칙).
    private readonly int _inputW, _inputH;
    private static readonly float[] Mean = { 0.485f, 0.456f, 0.406f };
    private static readonly float[] Std = { 0.229f, 0.224f, 0.225f };

    private readonly InferenceSession _session;
    private readonly string _inputName;
    private readonly string _scoreName;
    private readonly string? _mapName;

    public string ModelPath { get; }

    public AnomalyDetectionEngine(string modelPath)
    {
        ModelPath = modelPath;
        _session = new InferenceSession(modelPath);
        _inputName = _session.InputMetadata.Keys.First();
        var outs = _session.OutputMetadata.Keys.ToList();
        // 출력 이름이 export 버전에 따라 다를 수 있어 이름으로 최대한 안전하게 찾는다.
        _scoreName = outs.FirstOrDefault(n => n.Contains("score", StringComparison.OrdinalIgnoreCase)) ?? outs[0];
        _mapName = outs.FirstOrDefault(n => n.Contains("map", StringComparison.OrdinalIgnoreCase));

        // 입력 텐서의 마지막 두 차원(H,W)을 실제 모델 기준으로 읽는다. 동적 축(-1/0 이하)이면
        // anomalib/PatchCore 기본값인 256으로 안전하게 폴백.
        var dims = _session.InputMetadata[_inputName].Dimensions;
        int h = dims.Length >= 2 ? dims[^2] : -1;
        int w = dims.Length >= 1 ? dims[^1] : -1;
        _inputH = h > 0 ? h : 256;
        _inputW = w > 0 ? w : 256;
    }

    public AnomalyResult Run(byte[] rgb, int width, int height)
    {
        if (width <= 0 || height <= 0)
            throw new ArgumentException($"width/height는 양수여야 합니다 (width={width}, height={height})");
        if (rgb.Length != (long)width * height * 3)
            throw new ArgumentException($"rgb 배열 길이({rgb.Length})가 width*height*3와 다릅니다");

        // RGB 각 채널을 모델이 실제로 기대하는 크기(_inputW x _inputH)로 양선형 리사이즈 후
        // ImageNet 정규화 → NCHW. (하드코딩 256 아님 — 생성자에서 ONNX 메타데이터로 읽어옴.)
        var input = new DenseTensor<float>(new[] { 1, 3, _inputH, _inputW });
        for (int c = 0; c < 3; c++)
        {
            var chan = ExtractChannel(rgb, width, height, c);
            var resized = BilinearResize(chan, width, height, _inputW, _inputH);
            for (int i = 0; i < resized.Length; i++)
            {
                float v = resized[i] / 255f;
                input[0, c, i / _inputW, i % _inputW] = (v - Mean[c]) / Std[c];
            }
        }

        var inputs = new List<NamedOnnxValue> { NamedOnnxValue.CreateFromTensor(_inputName, input) };
        var sw = Stopwatch.StartNew();
        using var outputs = _session.Run(inputs);
        sw.Stop();

        var score = outputs.First(o => o.Name == _scoreName).AsTensor<float>().ToArray().FirstOrDefault();

        float[] heat; int mapW = 0, mapH = 0;
        if (_mapName != null)
        {
            var mapOut = outputs.First(o => o.Name == _mapName).AsTensor<float>();
            // [1,1,H,W] 형태 가정 — 마지막 두 차원이 공간.
            var dims = mapOut.Dimensions;
            mapH = dims.Length >= 2 ? dims[^2] : 0;
            mapW = dims.Length >= 1 ? dims[^1] : 0;
            var flat = mapOut.ToArray();
            // ★ 로컬(이미지별) min-max 정규화를 쓰지 않는다. ONNX 출력(anomaly_map)은 이미
            // anomalib 후처리(정상 통계 기반 pixel_min/max/threshold — train_anomaly.py 참고)를
            // 거쳐 "절대 기준"으로 나온 값이다(정상 픽셀≈0.1~0.2, 결함 픽셀≈0.5 이상). 여기서
            // 이미지마다 로컬 min-max로 다시 스트레칭하면, 완전히 정상인 이미지조차 "상대적으로
            // 가장 이상한 픽셀"이 강제로 1.0(진한 빨강)이 돼 실제 결함 아닌 곳이 결함처럼
            // 보인다(사용자 보고: "히트맵 위치가 안 맞는 것 같다"). 그냥 0~1로 clamp만 한다.
            heat = new float[flat.Length];
            for (int i = 0; i < flat.Length; i++) heat[i] = Math.Clamp(flat[i], 0f, 1f);
            if (mapW * mapH != heat.Length) { mapW = heat.Length; mapH = 1; }
        }
        else
        {
            heat = Array.Empty<float>();
        }

        return new AnomalyResult
        {
            Score = score,
            HeatMap = heat,
            MapWidth = mapW,
            MapHeight = mapH,
            InferenceMilliseconds = sw.Elapsed.TotalMilliseconds,
        };
    }

    private static float[] ExtractChannel(byte[] rgb, int width, int height, int c)
    {
        var chan = new float[width * height];
        for (int i = 0; i < chan.Length; i++)
            chan[i] = rgb[i * 3 + c];
        return chan;
    }

    // ★ 실사용 버그 발견(2026-07-19): 카메라 원본(예: 1700x2200)을 모델 입력(256x256)으로
    // 6~8배 축소하는 상황에서, 이 함수가 예전엔 "4점 bilinear"(dst 픽셀 하나당 src 4개만
    // 봄)였다 — PIL Image.resize(BILINEAR)는 큰 배율로 축소할 때 안티에일리어싱을 적용해
    // "그 dst 픽셀이 덮는 src 영역 전체"를 평균낸다. 4점만 보면 결함(원본에서 몇 픽셀짜리
    // 얼룩)이 축소 과정에서 샘플링되는 4점 사이로 빠져 사실상 사라져버릴 수 있음 — 실측
    // 결과 파이썬(PIL) 점수가 0.16을 넘는 실제 NG 샘플들이 C# 앱에서는 0.06~0.16으로 낮게
    // 나와 OK로 오판정되는 걸 확인(평균 픽셀차 3.79→면적평균으로 바꾸면 0.92, PIL과 거의
    // 일치). 축소 시엔 "dst 픽셀이 덮는 src 영역 평균"(면적평균, cv2.INTER_AREA와 동치)을
    // 쓰고, 확대(현재 이 엔진에선 발생 안 하지만 안전하게)는 기존 bilinear를 유지한다.
    private static float[] BilinearResize(float[] src, int srcW, int srcH, int dstW, int dstH)
    {
        bool downscale = dstW < srcW || dstH < srcH;
        return downscale
            ? AreaResize(src, srcW, srcH, dstW, dstH)
            : BilinearUpscale(src, srcW, srcH, dstW, dstH);
    }

    // ★ 성능(2026-07-19): 목적픽셀마다 원본 영역을 이중루프로 직접 훑으면(1700x2200→256x256
    // 기준 픽셀당 평균 ~57개 원본픽셀) 앱이 느려진다는 실사용 피드백. 적분영상(summed-area
    // table)을 한 번만 만들면 그 뒤로는 목적픽셀마다 4번의 배열조회로 끝나(O(1) 룩업),
    // 수학적으로 완전히 동일한 면적평균 값을 훨씬 빠르게 낸다(근사 아님 — 정확도 변화 없음).
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

    // cv2/PIL bilinear과 동일한 half-pixel-center 매핑(확대용).
    private static float[] BilinearUpscale(float[] src, int srcW, int srcH, int dstW, int dstH)
    {
        var dst = new float[dstW * dstH];
        float scaleX = (float)srcW / dstW;
        float scaleY = (float)srcH / dstH;
        for (int dy = 0; dy < dstH; dy++)
        {
            float sy = Math.Clamp((dy + 0.5f) * scaleY - 0.5f, 0, srcH - 1);
            int y0 = (int)MathF.Floor(sy); int y1 = Math.Min(y0 + 1, srcH - 1); float fy = sy - y0;
            for (int dx = 0; dx < dstW; dx++)
            {
                float sx = Math.Clamp((dx + 0.5f) * scaleX - 0.5f, 0, srcW - 1);
                int x0 = (int)MathF.Floor(sx); int x1 = Math.Min(x0 + 1, srcW - 1); float fx = sx - x0;
                float top = src[y0 * srcW + x0] * (1 - fx) + src[y0 * srcW + x1] * fx;
                float bot = src[y1 * srcW + x0] * (1 - fx) + src[y1 * srcW + x1] * fx;
                dst[dy * dstW + dx] = top * (1 - fy) + bot * fy;
            }
        }
        return dst;
    }

    public void Dispose() => _session.Dispose();
}
