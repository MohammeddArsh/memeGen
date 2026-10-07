"""Training entry point.

Every run is fully described by its args, which are written into the
checkpoint. eval.py rebuilds the model from that dict, so a checkpoint can
never be evaluated as a different architecture than it was trained as.
"""
import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

import data
from encoders import precompute_features, features_to_tensor
from model import build_model, count_params

DATA_DIR = Path(__file__).parent / "memes900k"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--encoder", default="clip", choices=["clip", "resnet50"])
    ap.add_argument("--decoder", default="transformer",
                    choices=["transformer", "lstm"])
    # None -> filled from decoder defaults below, so overriding only one
    # hyperparameter never accidentally holds another at the wrong default.
    ap.add_argument("--embed-dim", type=int, default=None)
    ap.add_argument("--layers", type=int, default=None)
    ap.add_argument("--heads", type=int, default=None)
    ap.add_argument("--hidden-size", type=int, default=None)
    ap.add_argument("--max-length", type=int, default=None)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--subsample", type=int, default=200_000,
                    help="training rows to sample; 0 = use all 750k")
    ap.add_argument("--epochs", type=int, default=1,
                    help="budget is epochs x steps-per-epoch; with subsample "
                         "200k and batch 32 that is 1 epoch = 6250 steps")
    ap.add_argument("--max-steps", type=int, default=0,
                    help="hard cap per run; cannot exceed the epoch budget")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-samples", type=int, default=8000,
                    help="rows for checkpoint selection only; reported "
                         "numbers come from eval.py on the full split")
    ap.add_argument("--save-every", type=int, default=1000)
    ap.add_argument("--log-every", type=int, default=100)
    ap.add_argument("--eval-every", type=int, default=2000)
    ap.add_argument("--device", default=None)
    ap.add_argument("--out", default=None, help="checkpoint directory")
    args = ap.parse_args()

    if args.embed_dim is None:
        args.embed_dim = 512 if args.decoder == "transformer" else 256
    if args.layers is None:
        args.layers = 6 if args.decoder == "transformer" else 2
    if args.heads is None:
        args.heads = 8
    if args.hidden_size is None:
        args.hidden_size = 512
    if args.max_length is None:
        args.max_length = data.MAX_LENGTH   # keep dataset and model in step
    if args.out is None:
        args.out = f"checkpoints/{args.encoder}_{args.decoder}"
    return args


def seed_everything(seed):
    torch.manual_seed(seed)
    random.seed(seed)
    if torch.backends.mps.is_available():
        torch.mps.manual_seed(seed)


def make_loader(rows, image_files, tok, args, shuffle, subsample=None):
    ds = data.MemeDataset(rows, tok, image_files, args.max_length)
    if subsample and subsample < len(ds):
        idx = random.Random(args.seed).sample(range(len(ds)), subsample)
        ds = _Subset(ds, idx)
    return DataLoader(
        ds, batch_size=args.batch_size, shuffle=shuffle, num_workers=0,
        collate_fn=lambda b: data.collate(b, args.max_length),
        generator=torch.Generator().manual_seed(args.seed),
    )


class _Subset:
    """Index subset that keeps data.collate's (idx, ids) contract."""

    def __init__(self, ds, idx):
        self.ds, self.idx = ds, idx

    def __len__(self):
        return len(self.idx)

    def __getitem__(self, i):
        return self.ds[self.idx[i]]


def rows_from_split(split):
    """Official split file -> parsed rows with an 'image' key."""
    mapping = data.load_template_map()
    rows = data.parse_captions(DATA_DIR / f"captions_{split}.txt")
    for r in rows:
        r["image"] = mapping[r["template"]]
    return rows


def main():
    args = parse_args()
    seed_everything(args.seed)
    device = args.device or ("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"device: {device}")
    print(f"run: encoder={args.encoder} decoder={args.decoder} "
          f"embed_dim={args.embed_dim} layers={args.layers} heads={args.heads} "
          f"hidden={args.hidden_size} lr={args.lr} max_length={args.max_length}")
    print(f"out: {args.out}")

    tok = data.build_tokenizer()
    pad_id = data.PAD_ID

    image_files = data.list_images()
    cache = DATA_DIR / f"{args.encoder}_features.npz"
    feats = precompute_features(DATA_DIR / "images", cache, args.encoder, device)
    feat_tensor = features_to_tensor(feats, image_files, device)
    print(f"features: {cache.name} -> {tuple(feat_tensor.shape)}")

    train_rows = rows_from_split("train")
    train_dl = make_loader(train_rows, image_files, tok, args,
                           shuffle=True, subsample=args.subsample)
    val_rows = rows_from_split("val")[: args.val_samples]
    val_dl = make_loader(val_rows, image_files, tok, args, shuffle=False)
    print(f"train rows: {len(train_dl.dataset):,}  val rows: {len(val_dl.dataset):,}")

    model = build_model(args.decoder, len(tok), pad_id,
                        feat_tensor.shape[-1], vars(args)).to(device)
    print(f"trainable params: {count_params(model):,}")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr,
                            weight_decay=args.weight_decay)

    os.makedirs(args.out, exist_ok=True)
    args_json = dict(vars(args))

    def evaluate():
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for img_idx, padded, _ in val_dl:
                img_idx, padded = img_idx.to(device), padded.to(device)
                logits = model(feat_tensor[img_idx], padded[:, :-1])
                loss = F.cross_entropy(
                    logits.reshape(-1, logits.size(-1)), padded[:, 1:].reshape(-1),
                    ignore_index=pad_id,
                )
                tot += loss.item() * img_idx.size(0)
                n += img_idx.size(0)
        model.train()
        return tot / max(n, 1)

    best_val = float("inf")
    global_step = 0
    running = 0.0
    t0 = time.time()
    model.train()
    opt.zero_grad(set_to_none=True)

    for epoch in range(args.epochs):
        for img_idx, padded, lens in train_dl:
            img_idx, padded = img_idx.to(device), padded.to(device)
            logits = model(feat_tensor[img_idx], padded[:, :-1])
            loss = F.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                padded[:, 1:].reshape(-1),
                ignore_index=pad_id,
            )
            (loss / args.grad_accum).backward()
            running += loss.item()

            if (global_step + 1) % args.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                lr = args.lr * min(1.0, (global_step + 1) / args.warmup)
                opt.param_groups[0]["lr"] = lr
                opt.step()
                opt.zero_grad(set_to_none=True)
            global_step += 1

            if global_step % args.log_every == 0:
                avg = running / args.log_every
                print(f"step {global_step} loss {avg:.4f} ppl {math.exp(avg):.2f} "
                      f"lr {opt.param_groups[0]['lr']:.2e} "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)
                running = 0.0

            if global_step % args.save_every == 0:
                torch.save({"model": model.state_dict(), "step": global_step,
                            "args": args_json},
                           os.path.join(args.out, f"ckpt_{global_step}.pt"))

            if global_step % args.eval_every == 0:
                val = evaluate()
                print(f"step {global_step} val_loss {val:.4f} "
                      f"val_ppl {math.exp(val):.3f} best {min(best_val, val):.4f} "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)
                if val < best_val:
                    best_val = val
                    torch.save({"model": model.state_dict(), "step": global_step,
                                "val_loss": val, "args": args_json},
                               os.path.join(args.out, "best.pt"))

            if args.max_steps and global_step >= args.max_steps:
                break
        if args.max_steps and global_step >= args.max_steps:
            break

    torch.save({"model": model.state_dict(), "step": global_step,
                "args": args_json},
               os.path.join(args.out, "final.pt"))
    print(f"done in {(time.time()-t0)/60:.1f} min, steps {global_step}"
          + (f", best val {best_val:.4f} ppl {math.exp(best_val):.3f}"
             if best_val != float("inf") else ""))


if __name__ == "__main__":
    main()
