import os
import torch
import argparse
from train import UNetLight, BEST_PATH

"""
best.pt -> edge_unet.onnx (동적 배치)
ONNX 입력 이름: "input"
ONNX 출력 이름: "output"
동적 배치 축: 0
"""
DEFAULT_OUT = os.path.join(os.path.dirname(__file__), "edge_unet.onnx")


def load_model(device="cpu"):
    model = UNetLight(in_ch=1, out_ch=1, base_c=32)
    ckpt = torch.load(BEST_PATH, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.to(device)
    model.eval()
    return model


def export_onnx(out_path=DEFAULT_OUT, opset=18):
    device = "cpu"
    model = load_model(device=device)

    dummy = torch.randn(1, 1, 512, 512, device=device)  # batch dim dynamic, but dummy uses 1
    input_names = ["input"]
    output_names = ["output"]
    dynamic_axes = {"input": {0: "batch"}, "output": {0: "batch"}}

    torch.onnx.export(
        model,
        dummy,
        out_path,
        verbose=False,
        opset_version=opset,
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        do_constant_folding=True,
    )
    print(f"Exported ONNX model to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", "-o", default=DEFAULT_OUT, help="Output ONNX path")
    args = parser.parse_args()
    export_onnx(args.out)