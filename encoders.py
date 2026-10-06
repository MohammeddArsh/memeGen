"""Frozen image encoders -> per-image feature caches.

Training never touches a JPEG. Each encoder is run once over the 300 images
and the result is written to an .npz keyed by filename; a run then reads
vectors and never decodes pixels again.

Caches are named per encoder because encoders disagree on two things that
would otherwise corrupt a comparison silently: the normalisation each
backbone expects, and the shape of what comes out.
"""
import os

import numpy as np
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image
from transformers import CLIPImageProcessor, CLIPVisionModel

ENCODERS = ("clip", "resnet50")
CLIP_ID = "openai/clip-vit-base-patch32"

# 224px -> CLIP B/32: 7x7 patches + 1 CLS. ResNet50 layer4: 7x7 spatial.
FEATURE_SHAPES = {"clip": (50, 768), "resnet50": (49, 2048)}
ENCODER_DIMS = {"clip": 768, "resnet50": 2048}


def build_encoder(name, device):
    """Frozen backbone -> (transform, forward_fn, feature_dim).

    The forward function always returns a stack of spatial tokens, (B, N, D).
    ResNet's global average pool and CLIP's CLS token are deliberately NOT
    applied here: pooling is the decoder's choice, so that changing the
    decoder is the only thing that changes between runs.
    """
    if name == "clip":
        proc = CLIPImageProcessor.from_pretrained(CLIP_ID)
        net = CLIPVisionModel.from_pretrained(CLIP_ID)
        mean, std = proc.image_mean, proc.image_std

        def fwd(batch):
            return net(batch).last_hidden_state        # (B, 50, 768)

        dim = int(net.config.hidden_size)

    elif name == "resnet50":
        from torchvision.models import ResNet50_Weights, resnet50
        net = resnet50(weights=ResNet50_Weights.IMAGENET1K_V1)
        net = nn.Sequential(*list(net.children())[:-2])   # drop avgpool + fc
        mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]

        def fwd(batch):
            f = net(batch)                               # (B, 2048, 7, 7)
            return f.flatten(2).transpose(1, 2)          # (B, 49, 2048)

        dim = 2048

    else:
        raise ValueError(f"unknown encoder {name!r}, expected one of {ENCODERS}")

    net.requires_grad_(False).eval().to(device)
    tfm = T.Compose([
        T.Resize(224),
        T.CenterCrop(224),
        T.ToTensor(),
        T.Normalize(mean=mean, std=std),
    ])
    return tfm, fwd, dim


def precompute_features(image_dir, cache_path, encoder, device, batch=64):
    """Run the encoder over every JPEG once -> {filename: (N, dim)}."""
    cache_path = os.fspath(cache_path)
    if os.path.exists(cache_path):
        data = np.load(cache_path, allow_pickle=True)
        feats = {k: data[k] for k in data.files}
        # A stale cache from a different encoder would train on wrong features
        # for hours before anything looked wrong, so fail loudly instead.
        sample = next(iter(feats.values()))
        if sample.shape != FEATURE_SHAPES[encoder]:
            raise ValueError(
                f"{cache_path} holds features shaped {sample.shape} but "
                f"encoder {encoder!r} produces {expected}; delete the file"
            )
        return feats

    tfm, fwd, dim = build_encoder(encoder, device)
    names = sorted(n for n in os.listdir(image_dir) if n.endswith(".jpg"))
    feats = {}
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        tensors = []
        for n in chunk:
            img = Image.open(os.path.join(image_dir, n)).convert("RGB")
            tensors.append(tfm(img))
        pix = torch.stack(tensors).to(device)
        with torch.no_grad():
            out = fwd(pix).cpu()
        for j, n in enumerate(chunk):
            feats[n] = out[j].numpy()
        print(f"  encoded {i + len(chunk)}/{len(names)}", flush=True)

    np.savez_compressed(cache_path, **feats)
    return feats


def features_to_tensor(features, image_files, device):
    """Stack the cache in dataset index order.

    image_files is data.list_images() order, which is also the order
    MemeDataset assigns int indices from -- so index i in a batch is
    row i here. Anything else pairs captions with the wrong image.
    """
    missing = [f for f in image_files if f not in features]
    assert not missing, f"cache is missing {len(missing)} images, e.g. {missing[:3]}"
    arr = np.stack([features[f] for f in image_files])
    return torch.tensor(arr, device=device).float()
