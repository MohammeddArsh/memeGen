"""Caption one image from a checkpoint, optionally rendering the overlay."""
import argparse
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont

import data
from encoders import build_encoder, ENCODER_DIMS
from model import build_model, generate

# Impact is the meme font. DeepHumor uses it; falling back to Arial changes
# the look of every rendered sample in the report.
IMPACT_CANDIDATES = (
    "impact.ttf", "/Library/Fonts/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size):
    for name in IMPACT_CANDIDATES:
        if Path(name).exists():
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="path to a template image")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--strategy", default="greedy", choices=["greedy", "sample"])
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--overlay", help="output path for the rendered caption")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    device = args.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    a = dict(ckpt["args"])
    tok = data.build_tokenizer()
    model = build_model(a["decoder"], len(tok), data.PAD_ID,
                        ENCODER_DIMS[a["encoder"]], a).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    tfm, fwd, _ = build_encoder(a["encoder"], device)
    img = Image.open(args.image).convert("RGB")
    with torch.no_grad():
        feat = fwd(tfm(img).unsqueeze(0).to(device))   # (1, N, D)

    top, bottom = generate(
        model, feat, tok, max_new=a["max_length"], strategy=args.strategy,
        temperature=args.temperature, top_k=args.top_k or None,
        device=device, seed=args.seed,
    )
    print(f"TOP:    {top}")
    print(f"BOTTOM: {bottom}")

    if args.overlay:
        canvas = Image.open(args.image).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        W, H = canvas.size
        font = load_font(int(W * 0.09))
        stroke = int(W * 0.012) + 2

        def centered(text, y):
            w = draw.textlength(text, font=font)
            draw.text(((W - w) / 2, y), text, fill="white", font=font,
                      stroke_width=stroke, stroke_fill="black")

        if top:
            centered(top, int(H * 0.02))
        if bottom:
            centered(bottom, int(H - H * 0.16))
        canvas.save(args.overlay)
        print(f"overlay saved -> {args.overlay}")


if __name__ == "__main__":
    main()
