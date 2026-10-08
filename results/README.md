# Experiment log

Every run writes its metrics here via `eval.py --out`:

```bash
python eval.py --checkpoint checkpoints/<encoder>_<decoder>/best.pt \
    --split test --out results/<run>.json \
    --samples-out results/samples_<run>.json
```

Metrics go to `<run>.json`; `samples_<run>.json` holds the 5k gold/predicted
pairs (feeds the report gallery).

Each JSON records: split, encoder, decoder, perplexity, BLEU, the checkpoint
step, the sample seed, and the model hyperparameters — everything needed to
reproduce the row.

Sweep rule (see NOTES.md §10): every config in this table shares the same
step budget, seed, decoding (greedy) and metrics, so the rows are comparable.
Do not add a row with a different budget and treat it as comparable.

The 6k-step "screening" rows are a **separate tier**: they rank which
hyperparameter knob helps (one knob changed per row) and are never compared
against a 1-epoch ladder row. Only the full-budget 1-epoch (6,250-step)
**confirmation** run enters the headline results alongside the three ladder
runs.

## Log — 2026-10-07

Budget: 1 epoch = 6,250 steps (subsample 200k, batch 32, grad-accum 4, lr
3e-4, seed 42). Decoding: greedy. eval: 75k-row perplexity, BLEU on 5k
seeded test rows.

### Ladder + confirmation (headline tier)

| JSON file | Run | Encoder | Decoder | Config | Test ppl | Test BLEU |
| --- | --- | --- | --- | --- | --- | --- |
| `resnet50_lstm.json` | A | resnet50 | lstm | base | 255.47 | 2.13 |
| `clip_lstm.json` | B | clip | lstm | base | 259.72 | 8.92 |
| `clip_transformer.json` | C | clip | transformer | base | 71.51 | 14.57 |
| `clip_transformer_emb768.json` | D | clip | transformer | embed 768 | 68.39 | 14.36 |

### Screening tier (6k steps, selection metric = val loss only)

| Config | val loss | rank | verdict |
| --- | --- | --- | --- |
| emb_768 | 4.2907 | 1 | winner → confirmation |
| maxlen_40 | 4.3389 | 2 | ~neutral |
| lr_1e-3 | 4.3508 | 3 | ~neutral |
| layers_4 | 4.3521 | 4 | ~neutral |
| emb_256 | 4.5291 | 5 | hurts |
| lr_1e-4 | 4.6464 | 6 | hurts |
| base (implicit, 1 epoch) | 4.3420 | — | reference |

Notes:
- Screening rows are **not** compared against the headline tier (different
  budget: 6,000 vs 6,250 steps) — they only rank knobs.
- The confirmation run (D) improved perplexity but not BLEU over base (C);
  see README.md Results for the interpretation.

## Log — 2026-10-08 (extended training, 3 epochs)

Separate tier: every architecture retrained for 3 epochs = 18,750 steps
(subsample 200k, batch 32, grad-accum 4, lr 3e-4, seed 42; chain:
`long_ladder.sh`). Same greedy decoding and metrics as the headline tier.
Reported independently — **do not compare these rows against the 1-epoch
table.**

| JSON file | Run | Encoder | Decoder | Config | Test ppl | Test BLEU |
| --- | --- | --- | --- | --- | --- | --- |
| `resnet50_transformer.json` | D | resnet50 | transformer | base, 1 epoch | 72.70 | 14.50 |
| `long_resnet50_lstm.json` | A′ | resnet50 | lstm | base | 115.93 | 13.36 |
| `long_clip_lstm.json` | B′ | clip | lstm | base | 120.66 | 12.16 |
| `long_clip_transformer.json` | C′ | clip | transformer | base | 54.75 | 14.38 |
| `long_resnet50_transformer.json` | D′ | resnet50 | transformer | base | 55.53 | 14.63 |
| `long_clip_transformer_emb768.json` | E′ | clip | transformer | embed 768 | 55.21 | 14.66 |

(`resnet50_transformer.json` is Run D at 1 epoch, included here because it was
produced by the same `long_ladder.sh` chain; it belongs to the 1-epoch tier.)

Notes:
- Transformer decoders cluster at 14.38–14.66 BLEU; encoder and embedding
  size wash out at this budget.
- Val loss order (C′ < E′ < D′) does not match BLEU order (E′ > D′ > C′).
- Samples for all six runs are in `samples_*.json` (5,000 pairs each).