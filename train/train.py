import os
import glob
import random
from typing import List, Tuple

import cv2
import numpy as np
from tqdm import tqdm

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from torch.cuda.amp import autocast, GradScaler
import torch.nn.functional as F
from glob import glob
from pathlib import Path
# -------------------------
# Configuration
# -------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
IMAGE_DIR = os.path.join(DATA_DIR, "images")
MASK_DIR = os.path.join(DATA_DIR, "masks")
SAVE_DIR = os.path.join(os.path.dirname(__file__), "checkpoints")
os.makedirs(SAVE_DIR, exist_ok=True)

IMG_SIZE = 512  # 입력 크기 (정사이즈)
BATCH_SIZE = 8
NUM_EPOCHS = 50
LR = 1e-3
VAL_SPLIT = 0.2
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
BEST_PATH = os.path.join(SAVE_DIR, "best.pt")
SEED = 42

torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)


# -------------------------
# Utilities: Dataset
# -------------------------
class EdgeDataset(Dataset):
    """
    간단한 그레이스케일 이미지 + 에지 마스크 데이터셋.
    전처리는 반드시 C# 전처리와 동일하게 해야 함:
      - cv2.IMREAD_GRAYSCALE
      - cv2.resize(..., interpolation=cv2.INTER_LINEAR)
      - image: float32 / 255.0
      - mask: nearest resize, binary (0 or 1)
    """
    def __init__(self, image_paths: List[str], mask_dir: str, img_size: int = IMG_SIZE):
        self.image_paths = image_paths
        self.mask_dir = mask_dir
        self.img_size = img_size

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_p = self.image_paths[idx]
        stem = os.path.splitext(os.path.basename(img_p))[0]   # 확장자 제거
        mask_p = os.path.join(self.mask_dir, stem + ".png")   # 마스크는 png로 고정
        # 읽기: 그레이스케일
        img = cv2.imread(img_p, cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(mask_p, cv2.IMREAD_GRAYSCALE)
        if img is None or mask is None:
            raise RuntimeError(f"Failed to read {img_p} or {mask_p}")
        # resize: 이미지 bilinear, 마스크 nearest
        img = cv2.resize(img, (self.img_size, self.img_size), interpolation=cv2.INTER_LINEAR)
        mask = cv2.resize(mask, (self.img_size, self.img_size), interpolation=cv2.INTER_NEAREST)
        # normalize
        img = img.astype(np.float32) / 255.0  # [0,1]
        mask = (mask > 127).astype(np.float32)  # 0.0 or 1.0 (원래 edge는 255)
        # To tensor NCHW
        img = np.expand_dims(img, 0)  # 1,H,W
        mask = np.expand_dims(mask, 0)
        return torch.from_numpy(img), torch.from_numpy(mask)


# -------------------------
# Lightweight U-Net
# -------------------------
def conv_block(in_ch, out_ch):
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
        nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
    )


class UNetLight(nn.Module):
    """
    가벼운 U-Net: 입력 1채널, 출력 1채널(logits).
    채널 수는 줄여 속도/메모리 절약.
    """
    def __init__(self, in_ch=1, out_ch=1, base_c=32):
        super().__init__()
        self.enc1 = conv_block(in_ch, base_c)
        self.enc2 = conv_block(base_c, base_c * 2)
        self.enc3 = conv_block(base_c * 2, base_c * 4)

        self.pool = nn.MaxPool2d(2)

        self.bottleneck = conv_block(base_c * 4, base_c * 8)

        self.up3 = nn.ConvTranspose2d(base_c * 8, base_c * 4, kernel_size=2, stride=2)
        self.dec3 = conv_block(base_c * 8, base_c * 4)
        self.up2 = nn.ConvTranspose2d(base_c * 4, base_c * 2, kernel_size=2, stride=2)
        self.dec2 = conv_block(base_c * 4, base_c * 2)
        self.up1 = nn.ConvTranspose2d(base_c * 2, base_c, kernel_size=2, stride=2)
        self.dec1 = conv_block(base_c * 2, base_c)

        self.out_conv = nn.Conv2d(base_c, out_ch, kernel_size=1)

    def forward(self, x):
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        b = self.bottleneck(self.pool(e3))
        d3 = self.up3(b)
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)
        d2 = self.up2(d3)
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)
        d1 = self.up1(d2)
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)
        out = self.out_conv(d1)
        return out  # logits


# -------------------------
# Loss: BCEWithLogits + Dice
# -------------------------
class DiceLoss(nn.Module):
    def __init__(self, eps=1e-6):
        super().__init__()
        self.eps = eps

    def forward(self, logits, targets):
        # logits: raw output (no sigmoid)
        probs = torch.sigmoid(logits)
        num = 2.0 * (probs * targets).sum(dim=(1, 2, 3))
        den = probs.sum(dim=(1, 2, 3)) + targets.sum(dim=(1, 2, 3)) + self.eps
        dice = 1.0 - (num / den)
        return dice.mean()


# -------------------------
# Training routine
# -------------------------
def train():
    # 데이터 수집
    exts = ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff"]
    all_images = []
    for e in exts:
        all_images += glob(os.path.join(IMAGE_DIR, e))
    all_images = sorted(all_images)
    if len(all_images) == 0:
        raise RuntimeError(f"No images found in {IMAGE_DIR}. Check dataset placement.")

    # 마스크 누락 사전 검증 — 없으면 학습 도중(수십 epoch 진행 후)에야 RuntimeError로
    # 죽으므로, 시작 전에 전부 확인해 몇 시간 낭비를 막는다.
    missing = []
    for p in all_images:
        stem = os.path.splitext(os.path.basename(p))[0]
        if not os.path.exists(os.path.join(MASK_DIR, stem + ".png")):
            missing.append(p)
    if missing:
        sample = "\n  ".join(missing[:5])
        more = f"\n  ...외 {len(missing) - 5}장" if len(missing) > 5 else ""
        raise RuntimeError(
            f"이미지 {len(missing)}/{len(all_images)}장에 대응하는 마스크가 {MASK_DIR}에 없습니다:\n  {sample}{more}\n"
            f"학습을 시작하기 전에 마스크를 만들거나 해당 이미지를 제외하세요.")

    # split — 데이터가 적어도 val이 비지 않게(그래야 best 모델 선택이 의미 있음),
    # 동시에 train도 비지 않게 보장한다. 1장뿐이면 같은 이미지를 train/val로 함께 쓴다.
    random.shuffle(all_images)
    n = len(all_images)
    if n == 1:
        val_list = train_list = all_images
    else:
        n_val = max(1, min(n - 1, round(n * VAL_SPLIT)))   # 1 <= n_val <= n-1
        val_list = all_images[:n_val]
        train_list = all_images[n_val:]

    train_ds = EdgeDataset(train_list, MASK_DIR, img_size=IMG_SIZE)
    val_ds = EdgeDataset(val_list, MASK_DIR, img_size=IMG_SIZE)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0, pin_memory=False)
    val_loader   = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0, pin_memory=False)
    # model, optimizer, loss
    model = UNetLight(in_ch=1, out_ch=1, base_c=32).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)
    bce = nn.BCEWithLogitsLoss()
    dice = DiceLoss()
    use_amp = DEVICE == "cuda"
    scaler = GradScaler(enabled=use_amp)  # AMP 스케일러(CPU에서는 no-op)

    best_val_loss = float("inf")

    for epoch in range(1, NUM_EPOCHS + 1):
        model.train()
        pbar = tqdm(train_loader, desc=f"Epoch {epoch}/{NUM_EPOCHS} Train")
        train_loss_accum = 0.0
        for imgs, masks in pbar:
            imgs = imgs.to(DEVICE, non_blocking=True)
            masks = masks.to(DEVICE, non_blocking=True)
            optimizer.zero_grad()
            with autocast(enabled=use_amp):
                logits = model(imgs)
                loss_bce = bce(logits, masks)
                loss_dice = dice(logits, masks)
                loss = loss_bce + loss_dice
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            train_loss_accum += loss.item() * imgs.size(0)
            pbar.set_postfix({"loss": loss.item()})
        train_loss = train_loss_accum / max(1, len(train_ds))   # val과 동일하게 0분모 방어

        # validation
        model.eval()
        val_loss_accum = 0.0
        with torch.no_grad():
            for imgs, masks in val_loader:
                imgs = imgs.to(DEVICE)
                masks = masks.to(DEVICE)
                with autocast(enabled=use_amp):
                    logits = model(imgs)
                    loss = bce(logits, masks) + dice(logits, masks)
                val_loss_accum += loss.item() * imgs.size(0)
        val_loss = val_loss_accum / max(1, len(val_ds))

        print(f"Epoch {epoch}: train_loss={train_loss:.6f}, val_loss={val_loss:.6f}")

        # best 모델 저장
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save({"model_state_dict": model.state_dict(),
                        "optimizer_state_dict": optimizer.state_dict(),
                        "epoch": epoch,
                        "val_loss": val_loss}, BEST_PATH)
            print(f"Saved best model to {BEST_PATH}")

    print("Training finished.")


if __name__ == "__main__":
    train()