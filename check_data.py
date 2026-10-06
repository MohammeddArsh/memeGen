"""The M1 gate. Run: python check_data.py  -> ALL CHECKS PASSED means M2 is safe."""
import torch

from data import (
    DATA_DIR,
    IMAGE_SIZE,
    MAX_LENGTH,
    SPLITS,
    build,
    build_tokenizer,
    collate,
    load_images,
    load_template_map,
    parse_captions,
)

tok = build_tokenizer()

print("=" * 62)
print("1. PARSING AND MAPPING")
print("=" * 62)
rows = parse_captions(DATA_DIR / "captions.txt")
mapping = load_template_map()
print(f"   parsed   {len(rows):,} captions")
print(f"   mapped   {len(mapping)} templates  (0 overrides needed)")
assert len(rows) == 900_000, "caption count is not 900k"
assert len(mapping) == 300, "did not map all 300 templates"

print()
print("=" * 62)
print("2. OFFICIAL SPLIT PARTITIONS THE DATA CLEANLY")
print("=" * 62)
from collections import Counter
counts = {}
sets = {}
for name in SPLITS:
    r = parse_captions(DATA_DIR / f"captions_{name}.txt")
    counts[name] = len(r)
    sets[name] = Counter((x["template"], x["caption"]) for x in r)
    tpls = {x["template"] for x in r}
    print(f"   {name:5s} {len(tpls):>3} templates  {counts[name]:>7,} captions")
    assert len(tpls) == 300, f"{name}: expected all 300 templates, got {len(tpls)}"
assert counts == {"train": 750_000, "val": 75_000, "test": 75_000}, counts

# The three files must be an exact partition of captions.txt: nothing dropped,
# nothing duplicated, nothing in two splits at once. Without this, a caption
# could be trained on and tested on without anyone noticing.
full = Counter((r["template"], r["caption"]) for r in rows)
combined = sets["train"] + sets["val"] + sets["test"]
assert combined == full, "the three split files do not exactly partition captions.txt"
print("   train + val + test == captions.txt exactly, no duplicates dropped  OK")

for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
    shared = set(sets[a]) & set(sets[b])
    assert not shared, f"LEAK: {len(shared)} captions appear in both {a} and {b}"
print("   no caption appears in two splits                              OK")

# Intentionally NOT zero. DeepHumor's split is caption-level: every template
# is present in all three splits, so the model scores on NEW captions of
# templates it has already seen. This is by design and must be stated in the
# report -- it is not generalisation to unseen templates.
print("   template overlap train/val/test: 300/300/300  (by design, caption-level)")

print()
print("=" * 62)
print("3. DATASET ITEMS")
print("=" * 62)
ds, mapping, image_files = build("train", tok)
print(f"   len(ds)   {len(ds):,}")
assert len(ds) == 750_000, "train dataset must hold 750k rows"

idx, ids = ds[0]
print(f"   ds[0]     idx={idx} ({type(idx).__name__})  ids.shape={tuple(ids.shape)}")
assert isinstance(idx, int), "image must be an int index, not pixels"
assert len(ids) <= MAX_LENGTH, f"sequence longer than MAX_LENGTH: {len(ids)}"

decoded = tok.decode(ids.tolist())
print(f"   decoded   {decoded!r}")
assert decoded.startswith(tok.bos_token), "missing <bos> at start"
assert decoded.endswith(tok.eos_token), "missing <eos> at end"
assert tok.sep_token in decoded, "missing <sep>"

print()
print("   longest caption after truncation, over 2000 samples:")
longest = max(len(ds[i][1]) for i in range(2000))
print(f"     max={longest}  (MAX_LENGTH={MAX_LENGTH})")
assert longest <= MAX_LENGTH, "something exceeds MAX_LENGTH"

print()
print("=" * 62)
print("4. IMAGE TENSOR")
print("=" * 62)
imgs = load_images(DATA_DIR / "images", image_files)
print(f"   shape={tuple(imgs.shape)}  dtype={imgs.dtype}")
assert tuple(imgs.shape) == (300, 3, IMAGE_SIZE, IMAGE_SIZE)
assert imgs.dim() == 4, "expected (N, C, H, W)"
print(f"   mean={imgs.mean().item():.4f}  std={imgs.std().item():.4f}   (CLIP-normalised)")

print()
print("=" * 62)
print("5. COLLATE")
print("=" * 62)
batch = [ds[i] for i in range(4)]
img_idx, padded, lens = collate(batch)
print(f"   img_idx {tuple(img_idx.shape)}   padded {tuple(padded.shape)}   lens {tuple(lens.shape)}")
assert tuple(padded.shape) == (4, MAX_LENGTH), "padding did not reach MAX_LENGTH"
assert padded.dtype == torch.long, "collate must emit long tensors"
for j in range(4):
    assert bool((padded[j][lens[j] + 1:] == tok.pad_token_id).all()), \
        f"row {j}: everything after the real tokens must be pad"
    assert padded[j][0].item() == tok.bos_token_id, f"row {j}: must start with bos"
print("   padding all-pad after each real length  OK")
print("   every row starts with <bos>             OK")

print()
print("=" * 62)
print("ALL CHECKS PASSED -> start M2")
print("=" * 62)
