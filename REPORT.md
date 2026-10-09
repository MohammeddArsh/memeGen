# Meme Captioning on memes900k: An Ablation of Visual Encoders and Caption Decoders

**Course assignment — final report**
Author: _Mohammed Arsh_
Date: 2026-10-09

## Abstract

We build an image-to-text model that writes captions for meme templates,
trained on **memes900k** (900,000 memes over 300 templates extracted from
meme-generator.com). The reference system is
[DeepHumor](https://github.com/ilya16/deephumor), which reports only
teacher-forced perplexity and never evaluates on a test set. This project
makes the comparison rigorous: we run a controlled **2×2 ablation** over two
frozen visual encoders (ResNet-50, CLIP ViT-B/32) and two decoders (LSTM,
Transformer), decode generated captions with **one shared greedy decoder**,
and report **BLEU** (comparable across tokenizers) alongside perplexity
(comparable only within our runs). We then add a second, self-contained tier
trained for 3 epochs, matching the reference's longer-run budget.

The main findings are that the **decoder architecture dominates**: a
Transformer decoder reaches ~14.5 test BLEU while an LSTM at a short budget
collapses. With enough training the LSTM recovers to 12–13 BLEU but still
trails. Behind a Transformer decoder, **the encoder and embedding size wash
out** — all four configurations land in 14.38–14.66 BLEU. Finally,
**perplexity and BLEU decouple**: three epochs roughly halve perplexity while
BLEU stays flat, the clearest evidence in the project that teacher-forced fit
and free-running generation measure different things.

## 1. Goal and relation to the reference

The task is: given a meme template image, generate the two caption lines a
human would write (the setup and the punchline). The reference codebase,
DeepHumor, trains a frozen ResNet-50 + LSTM (and a Transformer variant) and
evaluates with **teacher-forced perplexity only**, on a validation split,
never on a test set. It also uses an unseeded `torch.multinomial` "beam
search" whose output changes between calls, and unpinned dependencies.

We keep its core modeling choices (frozen visual features, small autoregressive
decoders) but fix the evaluation methodology so that claims are defensible:

1. Evaluate on the dataset's **official test split**.
2. Report **BLEU** on generated captions, a tokenizer-independent number,
   in addition to perplexity.
3. Use **one decoder (greedy) for every model**, so a BLEU difference is
   attributable to the model, not to sampling noise.

We deliberately do not build a direct row of "DeepHumor's pretrained model
with our metrics": the released code has no test evaluation and its
sampling is unseeded, so such a row could not be reproduced or compared
fairly. The comparison is therefore methodological — same task, better
evaluation — plus an ablation that isolates encoder and decoder.

## 2. Data

`memes900k` contains 900,000 caption rows across 300 meme templates (a row is
`<template> <meme-id> <setup> <sep> <punchline>`). Each template has an
associated JPEG in `images/`, mapped from the template name via the image URL
in `templates.txt` (this maps 300/300 with no special cases).

We use the reference's **official caption-level split**:

| Split | Rows | Per template |
| --- | --- | --- |
| Train | 750,000 | 2,500 |
| Validation | 75,000 | 250 |
| Test | 75,000 | 250 |

**The split is caption-level, not template-level.** Every template appears in
all three splits. The correct reading of a test score is therefore *"how well
the model writes new jokes for templates it has seen"*, **not** *"how well it
captions an unseen template"*. We state this explicitly because it bounds
every claim below and because the code and this report must not disagree.
`check_data.py` verifies the partition (750k/75k/75k, no overlap) before any
training.

## 3. Method

**Visual encoders (frozen).** Both encoders are used purely as feature
extractors and never fine-tuned, matching DeepHumor and keeping training
cheap.

- **ResNet-50** (ImageNet weights): the final convolutional feature map,
  reshaped to a 49×2048 sequence.
- **CLIP ViT-B/32** (OpenAI): the patch tokens, a 50×768 sequence.

Features are precomputed once per template (300 images) and cached to `.npz`.

**Decoders.** Two autoregressive decoders over the visual sequence, each
producing the caption lines:

- **LSTM** (hidden 512, 2 layers, embedding 256): the visual features are
  mean-pooled to one vector and used as the initial hidden state.
- **Transformer** (6 layers, 8 heads, hidden 512, feed-forward 2048,
  embedding 512): the visual features are the encoder memory; a causal
  decoder attends to it. Input and output embeddings are **tied**.

**The controlled comparison.** The 2×2 is: ResNet-50/CLIP × LSTM/Transformer.
Comparing across a row isolates the encoder; comparing down a column isolates
the decoder. Every model shares the same data, seed, budget, and greedy
decoder.

## 4. Experimental setup

| Setting | Value |
| --- | --- |
| Budget (tier 1) | 1 epoch = 6,250 steps |
| Budget (tier 2) | 3 epochs = 18,750 steps |
| Optimizer | AdamW, lr 3e-4, weight decay 1e-4 |
| Batch | 32, gradient accumulation 4 (effective 128) |
| Warm-up / clipping | 500 steps linear / grad-norm 1.0 |
| Train subsample | 200,000 rows, seed 42 |
| Decoding (reported) | greedy, seed 0, fixed 5,000-row test sample |
| Perplexity | teacher-forced, all 75,000 test rows |

**Why one epoch is 6,250 steps.** With batch 32 and a 200k-row subsample,
one epoch is `200,000 / 32 = 6,250` steps. `train.py`'s `--epochs` defaults to
1, so `--max-steps` above one epoch has no effect — the budget is really
"epochs × steps-per-epoch". Tier 2 uses `--epochs 3`.

**Metrics.** *Perplexity* is `exp(mean per-token NLL)` under teacher forcing.
It is cheap but is **not comparable to DeepHumor's**, because DeepHumor builds
its vocabulary from the dataset while we use GPT-2 byte-pair encoding. *BLEU*
is sacrebleu corpus BLEU on generated captions; because it compares text, not
probabilities, it is the number that speaks across tokenizers. All reported
numbers use greedy decoding so a row is reproducible.

**Hyperparameter screening.** Before the headline runs we screened six
one-knob changes to the CLIP+Transformer base at 6,000 steps, ranked by
validation loss (the gradient signal), and confirmed the winner at the full
1-epoch budget:

| Config | val loss | verdict |
| --- | --- | --- |
| embed 768 | 4.2907 | winner → confirmed |
| max-len 40 | 4.3389 | ~neutral |
| lr 1e-3 | 4.3508 | ~neutral |
| layers 4 | 4.3521 | ~neutral |
| embed 256 | 4.5291 | hurts |
| lr 1e-4 | 4.6464 | hurts |
| base (reference) | 4.3420 | — |

The screening rows are a separate tier (6,000 steps) and are never compared
against the full-budget rows; only the confirmation enters the headline table.

## 5. Results

### 5.1 Tier 1 — 1 epoch (6,250 steps)

| Run | Encoder | Decoder | Test BLEU | Test perplexity |
| --- | --- | --- | --- | --- |
| A | ResNet-50 | LSTM | 2.13 | 255.5 |
| B | CLIP | LSTM | 8.92 | 259.7 |
| C | CLIP | Transformer | **14.57** | 71.5 |
| D | ResNet-50 | Transformer | 14.50 | 72.7 |
| E (confirmation) | CLIP | Transformer (embed 768) | 14.36 | **68.4** |

Reading the 2×2 (A→B isolates the encoder, C→D mirrors it; B→C and A→D
isolate the decoder):

- **The decoder dominates.** LSTM → Transformer gains **+5.65 BLEU** with CLIP
  (B→C) and **+12.37** with ResNet-50 (A→D). No other single choice comes
  close.
- **The encoder only matters when the decoder is weak.** CLIP lifts the LSTM
  by **+6.79 BLEU** (A→B) but leaves the Transformer flat (**−0.07**, C→D). A
  strong visual encoder and a strong decoder are partly redundant.
- **Embedding capacity (row E)** improves perplexity (71.5 → 68.4) but not
  BLEU (14.57 → 14.36): a better next-token fit does not automatically produce
  better free-running jokes.

### 5.2 Tier 2 — 3 epochs (18,750 steps)

Self-contained tier, reported on its own terms; not compared against 5.1.

| Run | Encoder | Decoder | Test BLEU | Test perplexity |
| --- | --- | --- | --- | --- |
| A′ | ResNet-50 | LSTM | 13.36 | 115.9 |
| B′ | CLIP | LSTM | 12.16 | 120.7 |
| C′ | CLIP | Transformer | 14.38 | 54.7 |
| D′ | ResNet-50 | Transformer | 14.63 | 55.5 |
| E′ | CLIP | Transformer (embed 768) | **14.66** | 55.2 |

- **The Transformer decoders form a tight cluster** (14.38–14.66 BLEU) across
  both encoders and both embedding sizes. At this budget, encoder choice and
  embedding size are noise; only the decoder architecture moves the number.
- **The LSTMs converge to 12–13 BLEU** — well above their short-budget result
  — but still trail the Transformer cluster by ~1.5–2.5 BLEU. Their failure at
  a short budget was largely a convergence-speed effect.
- **Validation loss does not rank BLEU.** Val loss orders C′ < E′ < D′, while
  BLEU orders E′ > D′ > C′. Teacher-forced fit and free-run generation are
  only loosely coupled.

### 5.3 The central observation: perplexity ≠ BLEU

Across both tiers, reducing teacher-forced perplexity does not reliably
improve generated-caption quality. Three epochs roughly halve perplexity
(e.g. CLIP+Transformer 71.5 → 54.7) while BLEU is flat (14.57 → 14.38). This
is the **exposure-bias gap**: training always feeds the gold previous token,
but generation feeds the model its own, so a model can become a better
teacher-forced predictor without becoming a better generator. It is also the
reason the two metrics are reported together rather than one alone.

## 6. Qualitative results

`showcase/` contains contact sheets (12 distinct templates per model) showing
each meme rendered with the model's generated caption, next to the human
(gold) caption for the same template. For example, the best run
(`long_clip_transformer_emb768`) produces fluent, template-appropriate lines
such as *"I just got a new girlfriend / aaaand it's gone"* for
`and-its-gone`, while the short-budget LSTM output degenerates into repeated
fragments. The sheets are regenerated by:

```bash
python showcase.py --samples results/samples_long_clip_transformer_emb768.json \
    --out showcase/long_clip_transformer_emb768.png --n 12 --cols 4
```

A single caption can be produced interactively with `./demo.sh` (random
template, best checkpoint) or `python caption.py --image ... --checkpoint ...`.

## 7. Limitations

- **Seen templates only.** The split is caption-level, so scores say nothing
  about never-seen templates. A held-out (60-template) split is a different,
  harder task and is not reported here.
- **BLEU is harsh for memes.** Captions are jokes, not translations; two
  equally funny captions can share almost no words and score near zero. Our
  BLEU is therefore low in absolute terms and meaningful mainly *between our
  runs*. This is precisely why perplexity is reported as well.
- **Perplexity is ours-only.** It is not comparable to DeepHumor's because of
  the tokenizer difference.
- **The task is underdetermined.** A blank template admits thousands of valid
  captions; no model can "solve" it, only learn the template's style and emit
  probable jokes. Human-level BLEU is not the right target.
- **Exposure bias remains open.** We diagnose it and measure it; we do not fix
  it (e.g. scheduled sampling / RL finetuning are the natural next steps).

## 8. Reproducibility

- **Environment.** Python 3.10, PyTorch (MPS), torchvision, transformers,
  sacrebleu, numpy, pillow, tqdm — pinned in `requirements.txt`.
- **Offline.** Training and evaluation run fully offline; all model weights
  (GPT-2 tokenizer, CLIP, ResNet-50) are cached locally.
- **Determinism.** Training seeds the data order and the model; evaluation
  uses a fixed 5,000-row test sample and greedy decoding, so reported rows are
  reproducible. `caption.py --strategy sample --seed -1` opts into fresh
  sampling for demos only.
- **Artifacts.** Each run's metrics are a JSON in `results/` recording split,
  encoder, decoder, perplexity, BLEU, checkpoint step, seed, and
  hyperparameters. Checkpoints store the full argument dictionary, so a run
  can be replayed exactly and a checkpoint can only be evaluated as the
  architecture it was trained as.
- **Commands.** Training: `python train.py --encoder <e> --decoder <d>
  [--epochs N]`. Evaluation: `python eval.py --checkpoint <ckpt> --split test
  --out results/<run>.json`. `check_data.py` gates the loader before training.

## 9. Conclusion

On memes900k, the choice that matters most is the **decoder**: a Transformer
decoder is far ahead of an LSTM at a short budget and stays ahead once both
converge. Given a Transformer decoder, the **visual encoder and embedding size
barely matter** (14.38–14.66 BLEU across ResNet-50/CLIP and 512/768). And the
**number DeepHumor optimizes — perplexity — does not track caption quality**:
halving it with more training leaves BLEU flat. The project's contribution is
therefore less a new state of the art than a clean, controlled, and
reproducible measurement of which design choices matter for this task — with
the evaluation methodology (test split, shared greedy decoder, BLEU +
perplexity) that makes such a claim checkable.
