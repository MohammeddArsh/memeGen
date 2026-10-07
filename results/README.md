# Experiment log

Every run writes its metrics here via `eval.py --out`:

```bash
python eval.py --checkpoint checkpoints/<encoder>_<decoder>/best.pt \
    --split test --out results/<run>.json
```

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