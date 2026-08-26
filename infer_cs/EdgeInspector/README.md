# EdgeInspector — 엣지 세그멘테이션 결과 뷰어 (WPF, C#)

`train/`에서 학습·export한 U-Net 에지 세그멘테이션 ONNX 모델(`edge_unet_v2.onnx`)을
Python 서버 없이 C#에서 직접 로드해 추론하고, 원본 이미지 위에 마스크를 겹쳐 눈으로
바로 확인하기 위한 독립 뷰어 앱이다.

## 왜 이렇게 만들었나

- `train/`(학습)과 VisionStudio(Python 엔진 추론)는 이미 역할이 나뉘어 있지만, 학습
  결과가 실제로 잘 나오는지 GPU 학습 PC에서 바로바로 확인할 뷰어가 없었다.
- VisionStudio의 `studio/`(WPF, MVVM, `Grpc` 클라이언트, `ImageView` 오버레이 컨트롤)와
  나중에 합칠 것을 감안해 **WPF + MVVM(.NET 8.0-windows)** 구조를 그대로 따랐다
  (`ViewModels/`, `Models/`). 다만 EdgeAI에는 아직 Python gRPC 엔진 서버가 없으므로,
  이 앱은 **Microsoft.ML.OnnxRuntime으로 C#에서 직접 추론**한다(gRPC 없음).

## 구조

- `Models/EdgeSegmentationEngine.cs` — ONNX 세션 어댑터. 입력 `input` [1,1,512,512]
  그레이스케일(0~1 정규화) → 출력 `output` 로짓 → sigmoid → threshold. 전처리(그레이스케일
  변환, 512x512 양선형 리사이즈)와 후처리(원본 크기로 복원)는 `train/infer_debug.py`의
  `preprocess_cv2`/`postprocess_and_save`와 같은 순서를 따른다(완전한 수치 동일성은 아님 —
  cv2.resize와 WPF 쪽 리사이즈 구현 차이로 미세한 오차가 있을 수 있음. 학습 결과를 눈으로
  검토하는 용도로 충분하며, Jetson 배포용 수치 동일성 검증은 VisionStudio 쪽 L0/L1/L2
  게이트를 따로 거친다).
- `ViewModels/MainViewModel.cs` — 모델/이미지 로드, 추론 실행, threshold 슬라이더에 따른
  재계산, 오버레이 비트맵 생성.
- `MainWindow.xaml` — 좌측: 원본+마스크 오버레이, 우측: 확률 맵. 상단에 모델/이미지 열기
  버튼과 threshold 슬라이더.

## 실행

```
dotnet build infer_cs/EdgeInspector/EdgeInspector.csproj -c Release
dotnet run --project infer_cs/EdgeInspector/EdgeInspector.csproj
```

앱 시작 시 `train/edge_unet_v2.onnx`가 있으면 자동으로 로드한다(프로젝트 루트를
`train/`+`infer_cs/`가 모두 있는 상위 폴더로 자동 탐색하므로 빌드 위치와 무관하게 동작).
"이미지 열기"로 `train/data/images/*.bmp`를 열면 바로 추론 결과가 오버레이된다.

## 예제 일괄 실행 (`--examples`)

`vision_detect/example_usage.py`처럼, 창을 띄우지 않고 `train/data/images/` 전체를
한 번에 돌려 결과를 바로 확인할 수 있다.

```
dotnet run --project infer_cs/EdgeInspector -- --examples
```

- `Examples/ExampleRunner.cs`가 이미지마다 오버레이/확률맵 PNG 2장씩을
  `infer_cs/EdgeInspector/examples_out/`에 저장하고, 파일별 추론 시간·에지 비율을
  콘솔 표로 출력한다.
- 24개 샘플 기준 평균 추론 ~144ms(CPU), 평균 에지 비율 ~2.95%로 전 이미지가 고르게
  나오는지 한눈에 검토 가능(특정 이미지만 에지 비율이 튀면 마스크/데이터 문제 의심).

## 향후 VisionStudio 합류 시 참고

- 지금은 `EdgeSegmentationEngine`이 onnxruntime을 직접 감싸지만, VisionStudio 쪽은
  Python 엔진이 추론을 전담하고 스튜디오는 gRPC(`EngineClient.cs`)만 호출하는 구조다.
  합류 시점에는 이 C# 추론 로직을 걷어내고 `EngineClient` 경유로 바꾸거나, 반대로 이
  모델을 VisionStudio 엔진의 새 Node(예: `EdgeSegmentationNode`, PatchCore/Anomalib
  계열과 같은 자리)로 이식하는 두 방향 중 하나를 정해야 한다 — 지금은 확정하지 않음.
