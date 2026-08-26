"""세그 라벨링 탭의 "AI 초안 채우기" 기능용 — 학습 + ONNX 내보내기를 한 번에.

사장님 요청: "10000장을 해야하는데 100장정도 하고 학습해서... 매직 브러시를 넣으면
좋겠어". 지금까지 EdgeInspector "세그 라벨링" 탭에서 손으로 라벨링한
train/data/images + train/data/masks 전체로 train.py(UNetLight)를 학습하고,
export_onnx.py로 ONNX를 내보낸다.

★ 출력 경로는 edge_unet_draft.onnx — 기존 "세그멘테이션" 탭이 쓰는
edge_unet_v2.onnx와는 별개 파일이라 이 학습이 그 모델을 덮어쓰지 않는다.

사용법: train/.venv/Scripts/python.exe train/train_draft_assist.py
(EdgeInspector "세그 라벨링" 탭의 "AI로 학습하기" 버튼이 이 스크립트를 서브프로세스로 실행)
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# cp949(한글 Windows 기본) 콘솔에서 유니코드 문자 출력 시 크래시 방지(smoke_test.py 등과 동일 가드).
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def main():
    print("[1/2] 라벨링된 이미지로 학습 시작…")
    from train import train
    train()

    print("[2/2] ONNX로 내보내는 중…")
    from export_onnx import export_onnx
    out_path = str(HERE / "edge_unet_draft.onnx")
    export_onnx(out_path)
    print(f"완료. ONNX: {out_path}")


if __name__ == "__main__":
    main()
