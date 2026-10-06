# memes900k — meme captioning

Image-to-text model that captions meme templates, built on the **memes900k**
dataset (900,000 memes, 300 templates). Trained with frozen visual encoders
(CLIP ViT-B/32, ResNet-50) and generative decoders (Transformer, LSTM), and
evaluated with BLEU on the dataset's official test split.

The reference this project improves on is [DeepHumor](https://github.com/ilya16/deephumor),
whose only metric is teacher-forced perplexity. This project additionally
evaluates *generated* captions (BLEU) on a held-out test set with one shared
greedy decoder across every model, and pinned dependencies.

## Dataset

The dataset ships as `memes900k.zip` (~45 MB). Extract it before running any
code:

```bash
unzip memes900k.zip     # -> memes900k/  (gitignored)
```

| File | Rows | Description |
| --- | --- | --- |
| `captions.txt` | 900,000 | All captions, concatenated from the splits |
| `captions_train.txt` | 750,000 | Training split (caption-level) |
| `captions_val.txt` | 75,000 | Validation split |
| `captions_test.txt` | 75,000 | Test split |
| `templates.txt` | 300 | `name <tab> slug <tab> image url` |
| `images/` | 300 | Template JPEGs, named `<slug>.jpg` |

Caption rows are tab-separated: `<template name> <meme id> <setup> <sep> <punchline>`.
The split is **caption-level** (DeepHumor's official swap): every template
appears in all three splits, so the model is scored on new captions of
templates it has seen, not on unseen templates.

`check_data.py` verifies the loader before any training:

```bash
python check_data.py     # endswith: ALL CHECKS PASSED -> start M2
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Train

Every run is a `<encoder> x <decoder>` pair. The ablation ladder is
ResNet-50/CLIP `<->` LSTM/Transformer, all with the same decoding and metrics:

```bash
# Run A — DeepHumor-style baseline (ResNet-50 + LSTM)
python train.py --encoder resnet50 --decoder lstm

# Run B — encoder ablation          (CLIP + LSTM)
python train.py --encoder clip --decoder lstm

# Run C — CLIP + Transformer (project headline)
python train.py --encoder clip --decoder transformer --subsample 200000
```

Checkpoints (model + the full args dict) go to `checkpoints/<encoder>_<decoder>/`,
selected by validation loss. Seeds, subsample and every hyperparameter are
CLI flags; `--help` lists them.

## Eval

```bash
python eval.py --checkpoint checkpoints/clip_transformer/best.pt --split test
```

Reports two numbers that answer different questions:

- **Perplexity** — teacher-forced, over the full 75k-row split. Cheap, but
  only comparable *within this project* (the reference uses a dataset-built
  vocabulary; this project uses GPT2 byte-pair encoding).
- **BLEU** — sacrebleu corpus BLEU on a fixed, seeded sample of generated
  captions. Tokenizer-independent, so it is the number that speaks to other
  captioning work. All reported numbers use the **greedy** decoder so results
  are reproducible run-to-run.

## Caption individually

```bash
python caption.py --image memes900k/images/king-penguin.jpg \
    --checkpoint checkpoints/clip_transformer/best.pt --overlay out.jpg
```

## Files

| File | Purpose |
| --- | --- |
| `data.py` | Official-split loader + `check_data.py` gate |
| `encoders.py` | Frozen CLIP / ResNet-50 feature extraction to `.npz` |
| `model.py` | Transformer + LSTM decoders, shared greedy decode |
| `train.py` | Training loop (AdamW, warmup, grad clip, val selection) |
| `eval.py` | Perplexity (full split) + BLEU (seeded sample) |
| `caption.py` | Single-image inference with Impact overlay |
| `NOTES.md` | Theory and every design decision made |

## Results

| Run | Encoder | Decoder | Test BLEU | Test perplexity |
| --- | --- | --- | --- | --- |
| A | ResNet-50 | LSTM | _pending_ | _pending_ |
| B | CLIP | LSTM | _pending_ | _pending_ |
| C | CLIP | Transformer | _pending_ | _pending_ |

Hyperparameter sweeps are logged in `results/`.

## Note on the split

The official split shares templates across train/val/test *by design*: each
template has 2,500 training captions, 250 validation captions and 250 test
captions. A correct reading of the test score is "how well the model writes
new jokes for templates it has seen", not "how well it captions an unseen
meme template". This is stated here so the code and the report cannot say
different things.