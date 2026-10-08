"""Caption one image from a checkpoint, optionally rendering the overlay."""
import argparse
import os
import random
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

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


def wrap_text(draw, text, font, max_width):
    """Greedy word wrap so long captions stay inside the image."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text, max_width, max_height, start_size):
    """Shrink the font until the wrapped block fits the allotted box."""
    size = start_size
    while size > 10:
        font = load_font(size)
        lines = wrap_text(draw, text, font, max_width)
        line_h = int(size * 1.15)
        widest = max(draw.textlength(line, font=font) for line in lines)
        if len(lines) * line_h <= max_height and widest <= max_width:
            return font, lines, line_h
        size = int(size * 0.9)
    font = load_font(size)
    return font, wrap_text(draw, text, font, max_width), int(size * 1.15)


def draw_block(draw, text, font, lines, line_h, W, anchor_y, bottom=False):
    stroke = int(W * 0.012) + 2

    def line_at(text_line, y):
        w = draw.textlength(text_line, font=font)
        draw.text(((W - w) / 2, y), text_line, fill="white", font=font,
                  stroke_width=stroke, stroke_fill="black")

    if bottom:
        y = anchor_y - len(lines) * line_h
    else:
        y = anchor_y
    for text_line in lines:
        line_at(text_line, y)
        y += line_h


def render_captioned(image_path, top, bottom):
    """Meme image with the generated caption overlaid, as a PIL image."""
    canvas = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    W, H = canvas.size
    margin_x = int(W * 0.04)
    max_w = W - 2 * margin_x
    box_h = int(H * 0.42)
    base = int(W * 0.09)

    if top:
        font, lines, lh = fit_text(draw, top, max_w, box_h, base)
        draw_block(draw, top, font, lines, lh, W, int(H * 0.02))
    if bottom:
        font, lines, lh = fit_text(draw, bottom, max_w, box_h, base)
        draw_block(draw, bottom, font, lines, lh, W, int(H * 0.98), bottom=True)
    return canvas


def overlay(image_path, top, bottom, out_path):
    render_captioned(image_path, top, bottom).save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="path to a template image")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--strategy", default="greedy", choices=["greedy", "sample"])
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0,
                    help="-1 = random seed (demo sampling); 0 = reproducible")
    ap.add_argument("--overlay", help="output path for the rendered caption")
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    if args.seed < 0:
        args.seed = random.randrange(2 ** 31)
        print(f"(random seed {args.seed})")

    device = args.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    a = dict(ckpt["args"])
    tok = data.build_tokenizer()
    model = build_model(a["decoder"], len(tok), data.PAD_ID,
                        ENCODER_DIMS[a["encoder"]], a).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    import transformers
    transformers.logging.set_verbosity_error()   # silence the load report
    transformers.utils.logging.disable_progress_bar()   # silence weights bar
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
        overlay(args.image, top, bottom, args.overlay)
        print(f"overlay saved -> {args.overlay}")


if __name__ == "__main__":
    main()
