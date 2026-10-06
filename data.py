"""M1: parse memes900k, return (image_index, token_ids) for the official split.

Run `check_data.py` to verify every invariant before moving to M2.

The split is the dataset's own captions_{train,val,test}.txt (750k/75k/75k),
not a split we invent. DeepHumor ships those files specifically so that new
models can be compared against theirs, so our headline numbers use them.
"""
from pathlib import Path

import torch
import torchvision.transforms as T
from PIL import Image
from torch.utils.data import Dataset
from transformers import CLIPImageProcessor, GPT2Tokenizer

# data.py lives in memeGen/, and memes900k/ sits next to it.
DATA_DIR = Path(__file__).parent / "memes900k"
IMAGE_SIZE = 224

# Measured over all 900k rows: max is 66 tokens, 99.9th percentile is 40.
MAX_LENGTH = 64

SPLITS = ("train", "val", "test")

# The pad id is only known once the tokenizer exists (it is 50260, but that
# is an artifact of add_special_tokens ordering, not a constant). build_tokenizer
# assigns it, so PAD_ID is None until a tokenizer has been built.
PAD_ID = None


def build_tokenizer():
    """GPT2 byte-level BPE, plus our 4 special tokens.

    Must be called exactly once per process, before anything uses pad_id:
    adding specials bumps vocab from 50257 -> 50261, so every embedding
    layer must be sized to 50261 or the pad row will be out of range.
    """
    global PAD_ID
    tok = GPT2Tokenizer.from_pretrained("gpt2")
    tok.add_special_tokens({
        "bos_token": "<bos>",   # 50257
        "eos_token": "<eos>",   # 50258
        "sep_token": "<sep>",   # 50259
        "pad_token": "<pad>",   # 50260
    })
    # Before this call GPT2 has bos_token_id == eos_token_id == 50256.
    # Afterwards they are distinct, which is what lets decode() tell them apart.
    PAD_ID = tok.pad_token_id   # 50260, published to the module for collate()
    return tok


def list_images(image_dir=None):
    """The one canonical image order.

    Every feature cache and every dataset index is built from this list, so
    a disagreement here would silently pair captions with the wrong image.
    """
    d = image_dir or (DATA_DIR / "images")
    return sorted(f.name for f in d.iterdir() if f.suffix == ".jpg")


def load_template_map():
    """templates.txt -> {template name: image filename}.

    File layout is `name <tab> slug <tab> url`. We take the filename out of
    the url, exactly as DeepHumor's MemeDataset does (url.split('/')[-1]).
    Verified: 300 templates, every filename resolves, no image left unreferenced.
    This replaced an earlier slugify() + OVERRIDES approach that needed 4
    special cases for names slugify() could not round-trip.
    """
    mapping = {}
    with open(DATA_DIR / "templates.txt", encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 3:
                continue
            mapping[cols[0].strip()] = cols[2].split("/")[-1]

    files = set(list_images())
    unresolved = [t for t, fn in mapping.items() if fn not in files]
    orphans = sorted(files - set(mapping.values()))
    assert len(mapping) == 300, f"expected 300 templates, got {len(mapping)}"
    assert not unresolved, f"unresolved templates: {unresolved}"
    assert not orphans, f"orphan images: {orphans}"
    return mapping


def parse_captions(path):
    """caption file -> rows of {template, text1, text2, caption}.

    Format is 3 tab-separated columns, ' <sep> ' inside column 3. Column 2 is
    a numeric id we never use. captions.txt and the three split files share
    this layout, so one parser handles all four.
    """
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            text1, text2 = cols[2].split(" <sep> ")
            rows.append({
                "template": cols[0].strip(),
                "text1": text1.strip(),
                "text2": text2.strip(),
                "caption": f"{text1.strip()} <sep> {text2.strip()}",
            })
    return rows


def load_images(image_dir, image_files, device="cpu"):
    """Decode all 300 JPEGs once -> (300, 3, 224, 224) normalised tensor.

    CLIP's mean/std rather than 0.5/0.5: the frozen encoder in M2 expects
    that distribution, so normalising here keeps image features consistent
    between precompute and inference. Training itself never calls this --
    it reads precomputed features instead.
    """
    proc = CLIPImageProcessor.from_pretrained("openai/clip-vit-base-patch32")
    mean = torch.tensor(proc.image_mean).view(3, 1, 1)
    std = torch.tensor(proc.image_std).view(3, 1, 1)
    tfm = T.Compose([
        T.Resize((IMAGE_SIZE, IMAGE_SIZE)),
        T.ToTensor(),
        T.Normalize(mean, std),
    ])
    out = []
    for f in image_files:
        img = Image.open(image_dir / f).convert("RGB")   # JPEGs are already RGB
        out.append(tfm(img))
    return torch.stack(out).to(device)


class MemeDataset(Dataset):
    """Rows -> (image_index, token_ids).

    max_length is threaded through rather than read from the module constant
    because it is a swept hyperparameter: the tokenizer, the pad width and the
    decoder's positional table must all agree, and the model side only sees
    the number train.py passes to build_model.
    """

    def __init__(self, rows, tokenizer, image_files, max_length=MAX_LENGTH):
        self.rows = rows
        self.tok = tokenizer
        self.max_length = max_length
        # rows reference images by filename; the loader needs an int index
        self.file_to_idx = {f: i for i, f in enumerate(image_files)}

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        ids = self.tok.encode(
            r["caption"], add_special_tokens=False,
            max_length=self.max_length - 2,     # leave room for bos + eos
            truncation=True,
        )
        full = [self.tok.bos_token_id, *ids, self.tok.eos_token_id]
        # Returns an int, not pixels. __getitem__ runs 750,000 times; decoding
        # a JPEG per call would take days. Decoding 300 JPEGs once does not.
        return self.file_to_idx[r["image"]], torch.tensor(full, dtype=torch.long)


def collate(batch, max_length=MAX_LENGTH):
    """Variable-length sequences -> fixed (B, max_length) with a length mask.

    Padding is required because torch.stack only accepts identical shapes.
    """
    img_idx = torch.tensor([b[0] for b in batch], dtype=torch.long)
    padded = torch.full((len(batch), max_length), PAD_ID, dtype=torch.long)
    lens = torch.zeros(len(batch), dtype=torch.long)
    for j, (_, seq) in enumerate(batch):
        n = min(len(seq), max_length)
        padded[j, :n] = seq[:n]
        lens[j] = n - 1          # you predict positions 0..n-2
    return img_idx, padded, lens


def build(split, tokenizer, max_length=MAX_LENGTH):
    """One call for the training loop: ds, mapping, image_files = build('train', tok)."""
    assert split in SPLITS, f"unknown split {split!r}, expected one of {SPLITS}"
    mapping = load_template_map()
    image_files = list_images()
    rows = parse_captions(DATA_DIR / f"captions_{split}.txt")
    for r in rows:
        r["image"] = mapping[r["template"]]
    return MemeDataset(rows, tokenizer, image_files, max_length), mapping, image_files
