# Train 폴더 설명 (Edge segmentation, U-Net, ONNX export)

폴더 구조
- `train/data/images/*.png` : 입력 그레이스케일 이미지 (원본)
- `train/data/masks/*.png` : 에지 마스크 (edge=255, background=0). 파일명은 이미지와 동일해야 함.
- `train/train.py` : 학습 스크립트 (U-Net 경량화). best 모델은 `train/checkpoints/best.pt`로 저장.
- `train/export_onnx.py` : `best.pt` -> `edge_unet.onnx` 로 변환 (동적 배치).
- `train/infer_debug.py` : 단일 이미지로 PyTorch 추론 디버깅 (prob, mask 저장).

설치 (권장: Python 3.9+ 가상환경)
pip install -r requirements.txt
필요 패키지 예:
- torch, torchvision
- opencv-python
- tqdm
- numpy

실행 순서
1. 데이터 준비
   - `train/data/images/` 와 `train/data/masks/` 에 PNG 파일을 넣으세요.
   - 마스크는 에지 픽셀이 255, 배경 0 이어야 합니다.

2. 학습
   - `python train/train.py`
   - 하이퍼파라미터는 파일 상단에서 조정 가능합니다 (BATCH_SIZE, NUM_EPOCHS 등).
   - 학습은 AMP(자동 혼합 정밀도)를 사용합니다. CUDA가 없으면 CPU로 동작하지만 매우 느립니다.

3. ONNX로 내보내기
   - `python train/export_onnx.py --out train/edge_unet.onnx`
   - 동적 배치(배치 차원 동적)를 지원합니다.

4. PyTorch로 단일 이미지 디버깅
   - `python train/infer_debug.py --image path/to/img.png --out_dir debug_out`
   - `debug_out`에 확률 맵 및 바이너리 마스크가 저장됩니다.

자주 나는 에러 및 해결
- "No images found in train/data/images"  
  -> 파일 경로와 확장자(.png)를 확인하세요.

- CUDA 관련 에러 또는 AMP 문제  
  -> CUDA 드라이버 및 PyTorch CUDA 버전 일치 여부 확인. GPU가 없으면 CPU 모드에서 실행하세요(속도 느림).

- ONNX export에서 opset/연산자 에러  
  -> PyTorch 버전과 ONNX opset 호환성 문제일 수 있습니다. opset_version을 12~14 범위로 바꿔 재시도하세요.

- 모델 로드 오류 (state_dict 불일치)  
  -> 모델 정의가 변경되면 이전 체크포인트와 호환되지 않습니다. 모델 정의를 수정하지 마세요.

주의사항
- PyTorch 측 전처리와 C# 측 전처리는 코드에 명시된 순서와 수치(Interpolation, normalization)를 반드시 동일하게 사용했습니다.