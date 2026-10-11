"""Generate all report figures from the committed results.

Reads:
  results/*.json            final metrics (BLEU, perplexity) per run
  results/samples_*.json    gold/predicted pairs for per-sentence BLEU
  checkpoints/*/run.log     training/validation curves
  checkpoints/sweep/best.json  hyperparameter screening ranking

Writes PDF (vector, for LaTeX) and PNG (for docs) into report/figs/.

Usage:  python plots/make_plots.py
"""
import json
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
import sacrebleu

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
CKPT = ROOT / "checkpoints"
OUT = ROOT / "report" / "figs"

plt.rcParams.update({
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
})

C_RESNET = "#D9782D"   # encoder = ResNet-50
C_CLIP = "#3B6FB6"     # encoder = CLIP
C_LSTM = "#8C8C94"     # decoder = LSTM
C_TRF = "#2E7D5B"      # decoder = Transformer
GRID = dict(axis="y", color="#DDDDDD", lw=0.6, zorder=0)


def load(name):
    return json.loads((RESULTS / name).read_text())


# Canonical run table: (label, result file, encoder, decoder, tier)
RUNS = [
    ("A", "resnet50_lstm.json", "resnet50", "lstm", 1),
    ("B", "clip_lstm.json", "clip", "lstm", 1),
    ("C", "clip_transformer.json", "clip", "transformer", 1),
    ("D", "resnet50_transformer.json", "resnet50", "transformer", 1),
    ("E", "clip_transformer_emb768.json", "clip", "transformer", 1),
    ("A'", "long_resnet50_lstm.json", "resnet50", "lstm", 2),
    ("B'", "long_clip_lstm.json", "clip", "lstm", 2),
    ("C'", "long_clip_transformer.json", "clip", "transformer", 2),
    ("D'", "long_resnet50_transformer.json", "resnet50", "transformer", 2),
    ("E'", "long_clip_transformer_emb768.json", "clip", "transformer", 2),
]


def enc_color(e):
    return C_RESNET if e == "resnet50" else C_CLIP


def dec_hatch(d):
    return "//" if d == "lstm" else ""


def enc_short(e):
    return "ResNet-50" if e == "resnet50" else "CLIP"


def save(fig, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{stem}.{ext}")
    plt.close(fig)
    print("wrote", stem)


# ----------------------------------------------------------------------------
# G2: BLEU bars, one panel per tier
# ----------------------------------------------------------------------------
def fig_bleu():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))
    for ax, tier, title in zip(axes, (1, 2), ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        rows = [r for r in RUNS if r[4] == tier]
        labels = [load(r[1])["bleu"] for r in rows]
        xs = np.arange(len(rows))
        bars = ax.bar(xs, labels, width=0.66,
                      color=[enc_color(r[2]) for r in rows],
                      edgecolor="black", lw=0.4,
                      hatch=[dec_hatch(r[3]) for r in rows])
        for b, v in zip(bars, labels):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.25, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=6.4)
        ax.set_xticks(xs)
        ax.set_xticklabels([r[0] for r in rows])
        ax.set_title(title)
        ax.set_ylim(0, 17.5)
        ax.grid(**GRID)
    axes[0].set_ylabel("Test BLEU")
    handles = [Patch(facecolor=C_RESNET, edgecolor="black", label="ResNet-50"),
               Patch(facecolor=C_CLIP, edgecolor="black", label="CLIP"),
               Patch(facecolor="white", edgecolor="black", hatch="//", label="LSTM"),
               Patch(facecolor="white", edgecolor="black", label="Transformer")]
    axes[1].legend(handles=handles, loc="lower right", ncol=2, framealpha=0.9)
    save(fig, "g2_bleu")


# ----------------------------------------------------------------------------
# G3: perplexity bars, one panel per tier
# ----------------------------------------------------------------------------
def fig_ppl():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))
    for ax, tier, title in zip(axes, (1, 2), ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        rows = [r for r in RUNS if r[4] == tier]
        vals = [load(r[1])["perplexity"] for r in rows]
        xs = np.arange(len(rows))
        bars = ax.bar(xs, vals, width=0.66,
                      color=[dec_color(r[3]) for r in rows],
                      edgecolor="black", lw=0.4)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.03, f"{v:.0f}",
                    ha="center", va="bottom", fontsize=6.4)
        ax.set_xticks(xs)
        ax.set_xticklabels([r[0] for r in rows])
        ax.set_yscale("log")
        ax.set_ylim(40, 460)
        ax.set_title(title)
        ax.grid(**GRID)
    axes[0].set_ylabel("Test perplexity (log, lower better)")
    handles = [Patch(facecolor=C_LSTM, edgecolor="black", label="LSTM"),
               Patch(facecolor=C_TRF, edgecolor="black", label="Transformer")]
    axes[1].legend(handles=handles, loc="upper right", ncol=1, framealpha=0.9)
    save(fig, "g3_perplexity")


def dec_color(d):
    return C_LSTM if d == "lstm" else C_TRF


# ----------------------------------------------------------------------------
# G4: BLEU vs perplexity scatter (decoupling)
# ----------------------------------------------------------------------------
def fig_scatter():
    fig, ax = plt.subplots(figsize=(4.6, 3.3))
    offsets = {
        "A":  (5, 3, "left", "bottom"),
        "B":  (5, 3, "left", "bottom"),
        "C":  (-7, 4, "right", "bottom"),
        "D":  (7, 2, "left", "bottom"),
        "E":  (-7, -5, "right", "top"),
        "A'": (0, 6, "center", "bottom"),
        "B'": (6, 1, "left", "center"),
        "C'": (0, -8, "center", "top"),
        "D'": (8, 4, "left", "bottom"),
        "E'": (-8, 2, "right", "center"),
    }
    for label, f, enc, dec, tier in RUNS:
        d = load(f)
        mark = "o" if tier == 1 else "^"
        ax.scatter(d["perplexity"], d["bleu"], s=42, marker=mark,
                   color=enc_color(enc), edgecolor="black", lw=0.4, zorder=3)
        dx, dy, ha, va = offsets.get(label, (5, 3, "left", "bottom"))
        ax.annotate(label, (d["perplexity"], d["bleu"]),
                    textcoords="offset points", xytext=(dx, dy),
                    ha=ha, va=va, fontsize=7)
    ax.set_xscale("log")
    ax.set_xlim(45, 340)
    ax.set_ylim(0.5, 17)
    ax.set_xlabel("Test perplexity (log)")
    ax.set_ylabel("Test BLEU")
    ax.grid(color="#EEEEEE", lw=0.6, zorder=0)
    handles = [Patch(facecolor=C_RESNET, edgecolor="black", label="ResNet-50"),
               Patch(facecolor=C_CLIP, edgecolor="black", label="CLIP"),
               plt.Line2D([], [], ls="", marker="o", color="black", label="1 epoch"),
               plt.Line2D([], [], ls="", marker="^", color="black", label="3 epochs")]
    ax.legend(handles=handles, loc="lower right", ncol=2, framealpha=0.9)
    save(fig, "g4_bleu_vs_ppl")


# ----------------------------------------------------------------------------
# Log parsing for curves
# ----------------------------------------------------------------------------
TRAIN_RE = re.compile(r"^step (\d+) loss ([0-9.]+) ppl ([0-9.]+)")
VAL_RE = re.compile(r"^step (\d+) val_loss ([0-9.]+) val_ppl ([0-9.]+)")


def parse_log(path):
    train, val = [], []
    if not Path(path).exists():
        return train, val
    for line in Path(path).read_text(errors="ignore").splitlines():
        mt = TRAIN_RE.match(line)
        if mt:
            train.append((int(mt.group(1)), float(mt.group(2))))
            continue
        mv = VAL_RE.match(line)
        if mv:
            val.append((int(mv.group(1)), float(mv.group(2))))
    return train, val


LOG_T1 = {
    "A": CKPT / "resnet50_lstm" / "run.log",
    "B": CKPT / "clip_lstm" / "run.log",
    "C": CKPT / "clip_transformer" / "run.log",
    "D": CKPT / "resnet50_transformer" / "run.log",
    "E": CKPT / "sweep" / "best_confirm" / "run.log",
}
LOG_T2 = {
    "A'": CKPT / "long_resnet50_lstm" / "run.log",
    "B'": CKPT / "long_clip_lstm" / "run.log",
    "C'": CKPT / "long_clip_transformer" / "run.log",
    "D'": CKPT / "long_resnet50_transformer" / "run.log",
    "E'": CKPT / "long_clip_transformer_emb768" / "run.log",
}
RUN_META = {r[0]: (r[2], r[3]) for r in RUNS}
LINE_STYLE = {"A": "-", "B": "-", "C": "-", "D": "-", "E": "--",
              "A'": "-", "B'": "-", "C'": "-", "D'": "-", "E'": "--"}


def fig_val_curves():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9))
    for ax, logs, title in zip(axes, (LOG_T1, LOG_T2),
                               ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        for label, path in logs.items():
            _, val = parse_log(path)
            if not val:
                continue
            xs = [p[0] for p in val]
            ys = [p[1] for p in val]
            enc, dec = RUN_META[label]
            ax.plot(xs, ys, marker="o", ms=3, lw=1.1, ls=LINE_STYLE[label],
                    color=enc_color(enc), label=label)
        ax.set_title(title)
        ax.set_xlabel("step")
        ax.grid(color="#EEEEEE", lw=0.6, zorder=0)
    axes[0].set_ylabel("validation loss")
    axes[1].legend(loc="upper right", ncol=2)
    save(fig, "g5_val_curves")


def fig_train_curves():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9))
    for ax, logs, title in zip(axes, (LOG_T1, LOG_T2),
                               ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        for label, path in logs.items():
            train, _ = parse_log(path)
            if not train:
                continue
            xs = [p[0] for p in train]
            ys = [p[1] for p in train]
            enc, dec = RUN_META[label]
            ax.plot(xs, ys, lw=1.0, ls=LINE_STYLE[label],
                    color=enc_color(enc), label=label, alpha=0.9)
        ax.set_title(title)
        ax.set_xlabel("step")
        ax.set_yscale("log")
        ax.grid(color="#EEEEEE", lw=0.6, zorder=0)
    axes[0].set_ylabel("training loss (log)")
    axes[1].legend(loc="upper right", ncol=2)
    save(fig, "g6_train_curves")


# ----------------------------------------------------------------------------
# G7: hyperparameter screening ranking
# ----------------------------------------------------------------------------
def fig_screening():
    d = json.loads((CKPT / "sweep" / "best.json").read_text())
    base = 4.3420
    ranking = sorted(d["ranking"], key=lambda r: r["val_loss"])
    names = [r["name"] for r in ranking]
    vals = [r["val_loss"] for r in ranking]
    colors = [C_TRF if n == d["winner"] else "#B9B9C0" for n in names]
    fig, ax = plt.subplots(figsize=(4.6, 2.8))
    ys = np.arange(len(names))[::-1]
    ax.barh(ys, vals, color=colors, edgecolor="black", lw=0.4, height=0.66)
    for y, v in zip(ys, vals):
        ax.text(v + 0.006, y, f"{v:.4f}", va="center", fontsize=6.4)
    ax.axvline(base, color="#888", lw=0.8, ls=":")
    ax.text(base, len(names) - 0.3, " base 4.3420", fontsize=6, color="#666",
            va="top")
    ax.set_yticks(ys)
    ax.set_yticklabels(names)
    ax.set_xlim(4.25, 4.72)
    ax.set_xlabel("validation loss @ 6k steps (lower better)")
    ax.grid(**GRID)
    save(fig, "g7_screening")


# ----------------------------------------------------------------------------
# G8: encoder x decoder BLEU heatmaps
# ----------------------------------------------------------------------------
def fig_heatmap():
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.7))
    encs = ["resnet50", "clip"]
    decs = ["lstm", "transformer"]
    for ax, tier, title in zip(axes, (1, 2), ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        M = np.zeros((2, 2))
        for label, f, enc, dec, t in RUNS:
            if t != tier or label == "E" or label == "E'":
                continue
            M[encs.index(enc), decs.index(dec)] = load(f)["bleu"]
        im = ax.imshow(M, cmap="Blues", vmin=0, vmax=16, aspect="auto")
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center",
                        fontsize=9, color="black")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["LSTM", "Transformer"])
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["ResNet-50", "CLIP"])
        ax.set_title(title)
    fig.colorbar(im, ax=axes, fraction=0.046, pad=0.04, label="Test BLEU")
    save(fig, "g8_heatmap")


# ----------------------------------------------------------------------------
# G9: effect decomposition (delta BLEU)
# ----------------------------------------------------------------------------
def fig_effects():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))
    for ax, tier, title in zip(axes, (1, 2), ("Tier 1 (1 epoch)", "Tier 2 (3 epochs)")):
        if tier == 1:
            b = {k: load(f)["bleu"] for k, f in
                 {"A": "resnet50_lstm.json", "B": "clip_lstm.json",
                  "C": "clip_transformer.json", "D": "resnet50_transformer.json"}.items()}
            enc_lstm = b["B"] - b["A"]
            enc_trf = b["C"] - b["D"]
            dec_res = b["D"] - b["A"]
            dec_clip = b["C"] - b["B"]
        else:
            b = {k: load(f)["bleu"] for k, f in
                 {"A": "long_resnet50_lstm.json", "B": "long_clip_lstm.json",
                  "C": "long_clip_transformer.json",
                  "D": "long_resnet50_transformer.json"}.items()}
            enc_lstm = b["B"] - b["A"]
            enc_trf = b["C"] - b["D"]
            dec_res = b["D"] - b["A"]
            dec_clip = b["C"] - b["B"]
        cats = ["Encoder\n(ResNet$\\to$CLIP)\nw/ LSTM",
                "Encoder\n(ResNet$\\to$CLIP)\nw/ Trf.",
                "Decoder\n(LSTM$\\to$Trf.)\nw/ ResNet",
                "Decoder\n(LSTM$\\to$Trf.)\nw/ CLIP"]
        vals = [enc_lstm, enc_trf, dec_res, dec_clip]
        cols = [enc_color("clip"), enc_color("clip"), dec_color("transformer"), dec_color("transformer")]
        xs = np.arange(4)
        bars = ax.bar(xs, vals, width=0.66, color=cols, edgecolor="black", lw=0.4)
        for bar, v in zip(bars, vals):
            off = 0.25 if v >= 0 else -0.25
            ax.text(bar.get_x() + bar.get_width() / 2, v + off, f"{v:+.2f}",
                    ha="center", va="bottom" if v >= 0 else "top", fontsize=6.4)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(xs)
        ax.set_xticklabels(cats, fontsize=6)
        ax.set_title(title)
        ax.grid(**GRID)
    axes[0].set_ylabel("$\\Delta$ test BLEU")
    save(fig, "g9_effects")


# ----------------------------------------------------------------------------
# G10: per-sentence BLEU (how harsh BLEU is)
# ----------------------------------------------------------------------------
SENT_SETS = [
    ("ResNet+LSTM", "samples_long_resnet50_lstm.json"),
    ("CLIP+LSTM", "samples_long_clip_lstm.json"),
    ("CLIP+Transformer", "samples_long_clip_transformer.json"),
    ("best (E')", "samples_long_clip_transformer_emb768.json"),
]


def sentence_bleu(pred, gold):
    pred = pred.replace(" <sep> ", " ").strip()
    gold = gold.replace(" <sep> ", " ").strip()
    return sacrebleu.sentence_bleu(pred, [gold]).score


def fig_sentence_bleu():
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.9))
    ax = axes[0]
    zero_frac = []
    for name, f in SENT_SETS:
        rows = json.loads((RESULTS / f).read_text())
        scores = np.array([sentence_bleu(r["pred"], r["gold"]) for r in rows])
        scores = np.sort(scores)
        y = np.arange(1, len(scores) + 1) / len(scores)
        ax.plot(scores, y, lw=1.2, label=name)
        zero_frac.append((name, float((scores < 1e-9).mean()) * 100))
    ax.set_xlabel("sentence BLEU")
    ax.set_ylabel("cumulative fraction")
    ax.set_title("Per-sentence BLEU (ECDF)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1.02)
    ax.grid(color="#EEEEEE", lw=0.6, zorder=0)
    ax.legend(loc="lower right")

    ax = axes[1]
    names = [z[0] for z in zero_frac]
    fracs = [z[1] for z in zero_frac]
    xs = np.arange(len(names))
    bars = ax.bar(xs, fracs, width=0.62, color=["#B0B0B8", "#B0B0B8", C_TRF, C_TRF],
                  edgecolor="black", lw=0.4)
    for bar, v in zip(bars, fracs):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.8, f"{v:.0f}%",
                ha="center", va="bottom", fontsize=6.6)
    ax.set_xticks(xs)
    ax.set_xticklabels(names, rotation=15, ha="right")
    ax.set_ylabel("captions with BLEU = 0 (%)")
    ax.set_ylim(0, max(fracs) * 1.25)
    ax.grid(**GRID)
    save(fig, "g10_sentence_bleu")


# ----------------------------------------------------------------------------
# G11: dataset composition
# ----------------------------------------------------------------------------
def fig_dataset():
    fig, ax = plt.subplots(figsize=(4.4, 2.7))
    names = ["Train", "Validation", "Test"]
    vals = [750000, 75000, 75000]
    per = [2500, 250, 250]
    xs = np.arange(3)
    bars = ax.bar(xs, vals, width=0.62, color=["#3B6FB6", "#7FA6D4", "#B9CDE6"],
                  edgecolor="black", lw=0.4)
    for bar, v, p in zip(bars, vals, per):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 12000,
                f"{v:,}\n({p}/template)", ha="center", va="bottom", fontsize=6.3)
    ax.set_xticks(xs)
    ax.set_xticklabels(names)
    ax.set_ylabel("caption rows")
    ax.set_ylim(0, 870000)
    ax.set_title("memes900k caption-level split (300 templates)")
    ax.grid(**GRID)
    save(fig, "g11_dataset")


def main():
    fig_bleu()
    fig_ppl()
    fig_scatter()
    fig_val_curves()
    fig_train_curves()
    fig_screening()
    fig_heatmap()
    fig_effects()
    fig_sentence_bleu()
    fig_dataset()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
