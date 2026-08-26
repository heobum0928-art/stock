# EdgeAI 새 PC 셋업 가이드

다른 PC(집/노트북/작업실 등)에서 EdgeAI를 처음 받아 쓸 때. 이미 쓰던 PC는
`update.bat` 더블클릭 한 번이면 최신화된다(아래 "이미 쓰던 PC" 참고).

## 사전 설치 (한 번만)

- **Git** — https://git-scm.com
- **Python 3.11** (py launcher 포함) — https://python.org  ※ 3.12+ 말고 3.11 권장(torch cu121 호환)
- **.NET 8 SDK** (뷰어 빌드용) — https://dotnet.microsoft.com
- **NVIDIA GPU 드라이버 + CUDA 12.1 호환** (학습용, 없으면 CPU로도 되지만 느림)

## 1) 클론

```cmd
cd C:\
git clone https://github.com/heobum0928-art/EdgeAI.git EdgeAI
cd EdgeAI
```
(private repo면 GitHub 로그인 창이 한 번 뜬다.)

## 2) 학습 환경(train\.venv) 만들기

```cmd
py -3.11 -m venv train\.venv
train\.venv\Scripts\python.exe -m pip install --upgrade pip

:: PyTorch (CUDA 12.1). GPU 없으면 https://pytorch.org 에서 CPU 버전 명령으로 대체
train\.venv\Scripts\python.exe -m pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 --index-url https://download.pytorch.org/whl/cu121

:: 학습/추론/도구 의존성
train\.venv\Scripts\python.exe -m pip install ultralytics onnx onnxruntime pillow pyyaml numpy roboflow kaggle
train\.venv\Scripts\python.exe -m pip install opencv-python==4.10.0.84
```

> ⚠️ **opencv-python은 반드시 4.10.0.84로 고정.** 최신(5.x 베타)은 웹캠 데모 트랙바가
> "NULL window"로 죽고, `opencv-python-headless`가 같이 깔리면 창이 안 뜬다. 둘 중 하나만.

## 3) 확인

```cmd
:: 학습 도구 import 확인
train\.venv\Scripts\python.exe -c "import ultralytics, cv2, onnxruntime; print('OK')"

:: 뷰어 빌드
dotnet build infer_cs\EdgeInspector\EdgeInspector.csproj -c Debug
```

## 4) 실행

```cmd
:: 뷰어 (탭: 에지 세그멘테이션 / YOLO 검출)
dotnet run --project infer_cs\EdgeInspector

:: 학습 마법사 (비전공자용 GUI — 폴더 고르고 버튼 하나)
train\.venv\Scripts\python.exe examples\_common\training_wizard.py

:: 라벨링 도구 (라벨 없는 이미지에 박스 그리기)
train\.venv\Scripts\python.exe examples\_common\labeling_tool.py

:: 웹캠 실시간 데모
cd examples\video_demo
..\..\train\.venv\Scripts\python.exe live_demo.py --preset person
```

---

## 이미 쓰던 PC — 최신화

`update.bat` 더블클릭. (git pull + 뷰어 빌드까지 한 번에.) 끝.

로컬에서 직접 고친 파일이 있어 `git pull`이 충돌나면, 그 파일을 백업 후
`git stash` 하거나 충돌을 해결한다.

---

## 참고: git에 안 올라가는 것들 (재생성 필요)

용량이 큰 것들은 git에서 제외돼 있다(`.gitignore`). 새 PC에선 필요할 때 아래로 재획득:

- **학습 환경** `train\.venv\` → 위 2)번 절차
- **외부 데이터셋 원본**(examples/DeepPCB, *.rar/*.zip, NEU-DET 등) → 각 `examples/<도메인>/README.md`의 다운로드 절차
- **학습 산출물**(`runs/`, `*.onnx`, `*.pt`, `examples_out/`) → 마법사/CLI로 재학습하거나
  각 도메인 README의 재현 절차. 뷰어에서 보려면 해당 도메인의 `.onnx`가 있어야 한다.
- **API 키**(`.claude/settings.local.json`) → 개인 설정, 공유 안 됨. Roboflow/Kaggle 키는 각자 발급.
