# NOTES — theory and design decisions

This document explains *why* the project is built the way it is. The code and
this file deliberately say the same thing: run `python check_data.py` for the
facts about the data, read this for the reasoning, and the two will not drift
apart.

---

## 1. The task

Input: a **blank meme template image** (just the picture, no text).
Output: a **two-part caption** — a setup and a punchline, written as
`TOP <sep> BOTTOM`.

The dataset has 300 templates × 3,000 captions = 900,000 captions. The image
alone cannot fully determine the caption: a template like Bad Luck Brian gets
3,000 *different* jokes. So the model's job is to produce a caption that is
*plausible and funny for this image*, not to reproduce the one gold caption.
That is why the evaluation metric matters so much (Section 6).

## 2. The split — the single most important methodology decision

DeepHumor ships three files: `captions_train.txt` (750k), `captions_val.txt`
(75k), `captions_test.txt` (75k). Each template contributes **2,500 train,
250 val, 250 test captions**. Every template appears in every split.

We use exactly these files (`data.py` reads them directly). Two consequences,
and both must be stated honestly in the report:

1. **Templates overlap between splits by design.** The test score measures:
   "how well does the model write *new* jokes for templates it has seen
   during training" — NOT "how well it invents a caption for a template it
   has never seen". The latter problem is a different, much harder task.
2. Why use this split at all, given #1? Because it is the split the original
   project chose, and these files exist specifically so new models can be
   compared against theirs. Comparability with the reference requires their
   split. `check_data.py` verifies the three files are an **exact partition**
   of `captions.txt` (nothing dropped, nothing in two splits at once) so our
   numbers rest on clean bookkeeping.

An earlier loader design split **by template** (240 train / 30 val / 30 test,
zero overlap). That is the "honest generalization" version — but on a blank
template image with no text, a held-out template gives the model almost no
signal, so scores collapse toward random and nothing is comparable to any
published number. Both splits are defensible; one was the reference's, so we
use it and say so.

## 3. Encoders — why they are frozen, and ResNet vs CLIP

An encoder turns a 224×224 image into a sequence of **feature vectors**
(spatial tokens): the image as a tiny grid of descriptors.

* **ResNet-50** sees the image through 50 layers of convolutions. Its final
  feature map is 7×7×2048, which we read as 49 tokens of 2048 dims.
* **CLIP ViT-B/32** splits the image into 7×7 patches, feeds them through a
  ViT transformer, and we take its 50 output vectors (49 patches + 1 CLS
  token) of 768 dims each.

Both are **frozen** (`requires_grad_(False)`), meaning we download weights
pretrained on ~millions of images and never update them during training.
Reasons:

* The dataset has only 300 images. From scratch, a network has no way to
  learn "what a picture is" from 300 examples. Pretrained backbones already
  encode a general idea of objects, faces, scenes.
* DeepHumor freezes ResNet-50. Matching that makes Run A a faithful baseline.
* Precomputation: because the backbone never changes, we run it **once** over
  the 300 images and cache the features to an `.npz` (`clip_features.npz`,
  `resnet50_features.npz`). Training then reads vectors and never decodes a
  JPEG. This is why a training epoch is cheap (Section 9).

**Why compare ResNet vs CLIP?** Both are frozen, so whatever difference we
see in performance comes from what the two encoders know about the world:
CLIP was trained (on 400M pairs) to match images to *text*, so its features
are deliberately aligned with language. That is a plausible reason a meme
captioner would prefer it — and it is exactly the hypothesis Run A vs Run B
tests.

## 4. Decoders — LSTM vs Transformer

A decoder consumes the image tokens and produces the caption one token at a
time, keeping everything it has written so far in memory (`model.py`:

both implement `forward(memory, input_ids)` for training and `step()` for
generation).

* **LSTM** (Run A, B): a recurrent network. State is a hidden vector updated
  one step at a time; the image enters as the *very first input token* (the
  pooled-image embedding), exactly as DeepHumor's `CaptioningLSTM` does. It
  has no attention mechanism — every word is produced from a fixed-length
  summary of everything before it. Cheap, but long-range structure is
  squeezed through one vector.
* **Transformer decoder** (Run C, D): each new word attends directly over
  the image tokens (cross-attention) and over all words written so far
  (self-attention). Nothing has to squeeze into one vector; the model can,
  at every step, look straight at whichever part of the image matters. This
  is the standard architecture for modern caption models, and DeepHumor's
  best decoder is also a Transformer — so their scores are a fair anchor.

**Why the project compares them:** the professor's rubric explicitly rewards
answering "are RNNs or Transformers better for this task" — *provided* the
comparison is controlled.

## 5. The controlled comparison — one variable at a time

The four runs form a 2×2:

| | LSTM | Transformer |
|---|---|---|
| **ResNet-50** | A (DeepHumor baseline) | D |
| **CLIP** | B | C |

* B − A = what the encoder change does (decoder held fixed).
* C − B = what the decoder change does (encoder held fixed).
* C − A = everything the project improved over DeepHumor.

Only one thing differs between neighbours, and everything else is shared:
the split, the tokenizer, `MAX_LENGTH=64`, the optimizer, the seed, the
decoding algorithm, the metrics script, the checkpoint format. That is what
makes "A is worse than C *because of the encoder/decoder*" a sound claim.

## 6. Metrics — BLEU vs perplexity, and what each can and cannot claim

Two numbers are reported for every run (`eval.py`):

* **Perplexity** = exp(teacher-forced cross-entropy loss). It is cheap and
  runs on all 75,000 test rows. But it measures the model's *prediction
  confidence under teacher forcing*, not the quality of its generated text —
  and it is only comparable *within* this project, because it depends on the
  tokenizer/vocabulary. DeepHumor builds its vocabulary from the dataset; we
  use GPT-2's byte-pair encoding. So we explicitly do **not** report
  "perplexity 42.3 vs DeepHumor's 41.7" — that claim would be false.
* **BLEU** (sacrebleu, corpus-level) compares *generated* text to the gold
  captions. It is tokenizer-independent, so it is the number that can be
  compared across projects. It is more expensive (one full decode per row),
  so it is run on a fixed, seeded sample — the *same* rows with the *same*
  seed for every model, making it a fair comparison.

**The point this project adds over DeepHumor:** their released code never
evaluates generation at all. Their only metric is teacher-forced perplexity;
their `generate()` exists only for a demo notebook. So we can honestly state:
*we evaluate the thing the model is built to do, on a held-out test set, and
we measure the two sides of quality separately.*

## 7. Decoding — greedy, and why it must be the same everywhere

Generation is iterative: pick a token, feed it back, repeat. Three common
strategies:

* **Greedy**: at each step take the single highest-probability token.
  Deterministic — the same run always gives the same caption.
* **Sampling**: draw from the probability distribution (optionally
  temperature-scaled / top-k-filtered). Fun for demos, but two runs give
  different captions, and score then depends on the random draw.
* **Beam search**: keep several candidate captions at once and extend them,
  choosing the set with the best joint score. Deterministic and usually
  higher-scoring, but more code and slower.

DeepHumor's `beam.py` calls itself "beam search" but actually draws tokens
with `torch.multinomial` — i.e. it is unseeded **sampling** in disguise,
which makes their demo scores unreproducible across runs.

Our decision: **every reported number uses greedy decoding**, implemented
once in `model.generate_batch()` and shared by every model and every run.
Reasons:
- The professor's rubric warns that comparing two models with *different*
  decoding algorithms is invalid — you could no longer distinguish "better
  model" from "nicer decoder". One shared greedy loop removes the entire
  class of problem.
- Greedy is deterministic, so our eval is reproducible line-by-line.
- Sampling stays available (`--strategy sample`) purely as a demo feature
  for `caption.py`, and can be swept later to show "does decoding matter".

## 8. Why the tokenizer choice matters

We use GPT-2's byte-level BPE tokenizer (50,257 tokens), extended with four
special tokens: `<bos> <sep> <pad> <eos>`. A caption becomes
`<bos> TOP <sep> BOTTOM <eos>`.

* Byte-level BPE needs no vocabulary built from our data and no rare-token
  handling; it can always express any word.
* `<sep>` keeps the setup/punchline structure in-band, so the model learns to
  place the ` <sep> ` naturally rather than us forcing a boundary.
* Consequence to remember: because the tokenizer isn't ours, tokenizer-based
  comparisons with DeepHumor (which builds its own vocab) are invalid — this
  is the same point as Section 6's perplexity caveat, in another coat.

We measured token lengths over the full dataset: 99.9th percentile is 40
tokens, max 66. `MAX_LENGTH = 64` absorbs essentially everything while keeping
sequences short enough to train fast; it is a swept hyperparameter only in
that shrinking it (e.g. to 40) is a legitimate speed/quality tradeoff to
measure.

## 9. Training mechanics — what each piece is for

* **Teacher forcing + cross-entropy loss.** At every position we feed the
  *gold* previous token (`padded[:, :-1]`) and ask the model to predict the
  next (`padded[:, 1:]`). Tokens past the real caption are masked with
  `ignore_index=pad_id` so padding contributes nothing. Teacher forcing
  trains quickly but creates **exposure bias**: at inference the model feeds
  its *own* previous tokens, which it never saw during training. This is a
  known gap (Section 10, one thing to try).
* **Tied input/output embeddings** (Transformer only): `lm_head.weight =
  token_emb.weight`. The vector used to *represent* a token and the vector
  used to *predict* it are the same, halving embedding params and typically
  helping. The LSTM cannot tie them because its prediction head reads the
  hidden size (512) while the input embedding is 256-dim.
* **AdamW + weight decay ~1e-4**: standard modern optimizer; the W = weight
  decay separate from Adam's adaptive moments.
* **Linear warmup**: `lr * min(1, step/warmup)`. Transformer training is
  fragile with a large initial LR; the first 500 steps ramp up instead.
* **Gradient clipping at 1.0**: caps the L2 norm of the gradient, preventing
  one bad batch from blowing up the weights.
* **Subsampling (200k of 750k train rows) + 1-epoch budget**: every ladder and
  confirmation run uses the same effective setup (batch 32, grad-accum 4 →
  effective 128; subsample 200k), so **one epoch = 200k/32 = 6,250 steps** is
  the standard budget for a run (roughly 30-50 min on MPS). Setting
  `--max-steps` above that cannot help because `--epochs` defaults to 1;
  the budget is really "epochs × steps-per-epoch". Screening rows cap at
  6,000 steps, just below one epoch. Using all 750k rows is itself a swept
  experiment ("more data helps?").
* **Seeding + checkpoint args dict**: every random source is seeded and every
  checkpoint stores the full args. A checkpoint can only be evaluated as the
  architecture it was trained as, and a run can be replayed exactly.
* **Validation loss** during training is a coarse signal (a fixed 8k-row
  slice) used only to pick `best.pt`; the real numbers come from `eval.py`
  on the full split. This distinction is printed in code and must be kept in
  the report.

## 10. The hyperparameter sweep — hypothesis per knob

All sweep runs share the same decoding (greedy) and the same metrics. The
design has two tiers, and the report must keep them apart:

1. **Screening (6,000 steps).** Six runs, each changing *one* knob from the
   base CLIP+Transformer config (subsample 200k, seed 42): learning rate
   {1e-4, 3e-4, 1e-3}, embed-dim {256, 512, 768}, layers {4, 6}, max-length
   {40, 64} (the already-run value is the implicit baseline row). They rank
   the knobs by val loss and are **not comparable** to the full-budget
   ladder — different budget.
2. **Confirmation (1 epoch = 6,250 steps = the ladder budget).** The best
   screening config is re-run at the same budget as the ladder so the winner
   enters the headline table on equal footing.

Hypotheses per knob, and what each result would mean:

* **learning rate** {1e-4, 3e-4, 1e-3}: the classic "too slow / works / too
  large to converge". Expect a curve with a clear best.
* **embed-dim**: capacity. Too small = underfit (loss plateaus high); too
  large = overfit (train loss good, BLEU sticks). Expect a tradeoff, not
  monotonic improvement. Note ffn-dim is held at 2048 so this is genuinely
  one knob.
* **layers** (4 vs 6): deeper = more capacity + slower. Small data means the
  gain should saturate quickly.
* **max-length** {40, 64}: shorter captions truncate the few percent of
  captions past 40 tokens and train faster; measure whether that hurts BLEU.

The rubric is not served by *many runs*; it is served by *many controlled
runs with a documented result*. Every config is one row in `results/`.

## 11. What used to be different, and why it changed

* **Template→image mapping.** An earlier version slugified template names
  and needed four `OVERRIDES` for `ñ` and punctuation. DeepHumor instead
  takes the filename from the `templates.txt` URL. That maps 300/300 with
  zero special cases, so we match it (fewer hacky divergences, `data.py`).
* **Split.** Was template-level (240/30/30); now the official caption-level
  split. Consequences in Section 2.
* **Evaluation.** Previously: `torch.multinomial` sampling, torch never
  seeded, defaulting to 800 examples on val. Now: shared seeded greedy, a
  fixed sample, full-split perplexity + BLEU, test default (`eval.py`).

## 12. Known limitations, said plainly

* **Seen templates only.** Scores say nothing about never-seen templates
  (the 60-template held-out split is a different, harder task we are not
  currently reporting).
* **BLEU on memes is harsh.** Meme captures are by design *not* near-duplicate
  gold captions; two equally funny captions get BLEU ~0. Our numbers are
  therefore low in absolute terms and meaningful mainly *between our runs*.
  This is the honest reading and it is exactly why perplexity is also
  reported.
* **Perplexity is ours-only**, not comparable to DeepHumor's (tokenizer).
* **A blank template genuinely underdetermines the caption** — 3,000 distinct
  correct captions exist per template. No model can "solve" this; it can only
  learn the template's style and produce probable jokes.