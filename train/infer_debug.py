import os
import cv2
import numpy as np
import torch
from train import UNetLight, IMG_SIZE, BEST_PATH

"""
단일 이미지로 PyTorch 모델을 사용해 디버깅하는 스크립트.
전처리(CV2)와 후처리(시그모이드, threshold 0.5)는 C#과 동일하게 구현되어 있다.
사용법:
  python infer_debug.py --image path/to/input.png --out_dir debug_out
"""
import argparse


def preprocess_cv2(img_path: str, target_size=IMG_SIZE):
    # 그레이스케일 읽기
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"Cannot read {img_path}")
    orig_h, orig_w = img.shape[:2]
    # resize (bilinear)
    img_resized = cv2.resize(img, (target_size, target_size), interpolation=cv2.INTER_LINEAR)
    img_f = img_resized.astype(np.float32) / 255.0
    # NCHW
    tensor = np.expand_dims(img_f, 0).astype(np.float32)  # 1,H,W
    tensor = np.expand_dims(tensor, 0)  # 1,1,H,W
    return tensor, (orig_w, orig_h), img  # return original grayscale image too


def postprocess_and_save(prob_map, out_dir, base_name="result"):
    os.makedirs(out_dir, exist_ok=True)
    # prob_map: HxW float32 [0,1]
    prob_vis = (prob_map * 255.0).astype(np.uint8)
    cv2.imwrite(os.path.join(out_dir, f"{base_name}_prob.png"), prob_vis)
    bin_mask = (prob_map >= 0.5).astype(np.uint8) * 255
    cv2.imwrite(os.path.join(out_dir, f"{base_name}_mask.png"), bin_mask)


def run_infer(image_path: str, out_dir: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = UNetLight(in_ch=1, out_ch=1, base_c=32)
    ckpt = torch.load(BEST_PATH, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device).eval()

    tensor, (orig_w, orig_h), orig_img = preprocess_cv2(image_path)
    inp = torch.from_numpy(tensor).to(device)  # shape 1,1,H,W

    with torch.no_grad():
        with torch.cuda.amp.autocast(enabled=(device == "cuda")):
            logits = model(inp)
            probs = torch.sigmoid(logits).cpu().numpy()[0, 0]  # HxW

    # resize prob back to original image size for visualization
    prob_resized = cv2.resize(probs.astype(np.float32), (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
    postprocess_and_save(prob_resized, out_dir, base_name=os.path.splitext(os.path.basename(image_path))[0])

    print(f"Saved debug outputs to {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", "-i", required=True, help="Input image path")
    parser.add_argument("--out_dir", "-o", default="debug_out", help="Output directory for debug images")
    args = parser.parse_args()
    run_infer(args.image, args.out_dir)