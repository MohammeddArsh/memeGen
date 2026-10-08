"""Contact-sheet gallery: meme template + generated caption + gold caption.

Reads the gold/predicted pairs written by `eval.py --samples-out` and renders
a grid of distinct templates, so the report can show generated captions in
situ next to what a human wrote for the same template.

Usage:
    python showcase.py --samples results/samples_long_clip_transformer_emb768.json \
        --out showcase/long_clip_transformer_emb768.png --n 12 --cols 4
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import caption

DATA_IMAGES = Path(__file__).parent / "memes900k" / "images"
CARD_W, CARD_H, IMG_H, PAD = 340, 452, 300, 8
BG = (18, 18, 20)
FG = (235, 235, 235)
GOLD = (150, 150, 156)
NAME = (120, 170, 255)

BODY_FONTS = ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc", "Arial.ttf")


def body_font(size):
    for name in BODY_FONTS:
        if Path(name).exists():
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
    return ImageFont.load_default()


def wrap(draw, text, font, max_w, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "\u2026"
    return lines


def split_pred(pred):
    if " <sep> " in pred:
        top, bottom = pred.split(" <sep> ", 1)
        return top, bottom
    return pred, ""


def make_card(sample):
    meme = caption.render_captioned(DATA_IMAGES / sample["image"],
                                    *split_pred(sample["pred"]))
    meme.thumbnail((CARD_W - 2 * PAD, IMG_H - 2 * PAD), Image.LANCZOS)
    card = Image.new("RGB", (CARD_W, CARD_H), BG)
    card.paste(meme, (PAD + (CARD_W - 2 * PAD - meme.width) // 2,
                      PAD + (IMG_H - 2 * PAD - meme.height) // 2))
    d = ImageDraw.Draw(card)
    f, fg = body_font(15), body_font(13)
    inner = CARD_W - 2 * PAD
    y = IMG_H + PAD
    d.text((PAD, y), sample["template"][:38], fill=NAME, font=fg)
    y += 21
    for line in wrap(d, "G:  " + sample["gold"], f, inner, 2):
        d.text((PAD, y), line, fill=GOLD, font=f)
        y += 18
    y += 5
    pretty = sample["pred"].replace(" <sep> ", "  /  ")
    for line in wrap(d, "P:  " + pretty, f, inner, 2):
        d.text((PAD, y), line, fill=FG, font=f)
        y += 18
    return card


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=12, help="cards in the sheet")
    ap.add_argument("--cols", type=int, default=4)
    args = ap.parse_args()

    samples = json.loads(Path(args.samples).read_text())
    chosen, seen = [], set()
    for s in samples:
        if s["template"] in seen:
            continue
        seen.add(s["template"])
        chosen.append(s)
        if len(chosen) >= args.n:
            break

    cards = [make_card(s) for s in chosen]
    cols = min(args.cols, len(cards))
    rows = (len(cards) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * CARD_W, rows * CARD_H), (0, 0, 0))
    for i, card in enumerate(cards):
        sheet.paste(card, ((i % cols) * CARD_W, (i // cols) * CARD_H))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"{len(cards)} cards ({len(seen)} templates) -> {out} "
          f"({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
