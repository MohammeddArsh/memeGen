"""Caption decoders and the one decoding routine every model shares.

Both decoders implement the same contract:
    forward(memory, input_ids) -> (B, L, vocab)   training
    step(memory, ids)          -> (B, vocab)      one autoregressive step
so that evaluation never needs to know which decoder produced the model.
That is what makes comparing them fair.
"""
import torch
import torch.nn as nn

DECODERS = ("transformer", "lstm")


def _init_weights(m):
    if isinstance(m, nn.Embedding):
        nn.init.normal_(m.weight, mean=0.0, std=0.02)
        if m.padding_idx is not None:
            nn.init.zeros_(m.weight[m.padding_idx])
    elif isinstance(m, nn.Linear):
        nn.init.normal_(m.weight, mean=0.0, std=0.02)
        if m.bias is not None:
            nn.init.zeros_(m.bias)


class TransformerCaptionModel(nn.Module):
    """Cross-attention decoder: attends over every image token at every step.

    embed_dim=512, layers=6, heads=8, ffn=2048 matches DeepHumor's
    Transformer configuration, so Run A/B vs C/D differ in decoder *type*
    rather than decoder *size*.
    """

    def __init__(self, vocab_size, pad_id, embed_dim=512, layers=6, heads=8,
                 ffn_dim=2048, img_dim=768, max_length=64, dropout=0.1):
        super().__init__()
        self.decoder_type = "transformer"
        self.embed_dim = embed_dim
        self.pad_id = pad_id
        self.max_length = max_length
        self.token_emb = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.pos_emb = nn.Embedding(max_length, embed_dim)
        self.img_proj = nn.Linear(img_dim, embed_dim)
        layer = nn.TransformerDecoderLayer(
            d_model=embed_dim, nhead=heads, dim_feedforward=ffn_dim,
            dropout=dropout, batch_first=True, norm_first=True,
        )
        self.decoder = nn.TransformerDecoder(layer, num_layers=layers)
        self.lm_head = nn.Linear(embed_dim, vocab_size, bias=False)
        self.lm_head.weight = self.token_emb.weight   # tying: VxE shared with input emb
        self.apply(_init_weights)
        with torch.no_grad():
            self.token_emb.weight[pad_id].zero_()

    def forward(self, memory, input_ids):
        B, T = input_ids.shape
        memory = self.img_proj(memory)
        tgt = self.token_emb(input_ids) + self.pos_emb.weight[:T].unsqueeze(0)
        mask = torch.triu(
            torch.full((T, T), float("-inf"), device=input_ids.device), diagonal=1
        )
        out = self.decoder(tgt, memory, tgt_mask=mask)
        return self.lm_head(out)

    def step(self, memory, ids):
        return self.forward(memory, ids)[:, -1, :]


class LSTMCaptionModel(nn.Module):
    """Recurrent decoder: the pooled image embedding is the first input token.

    Faithful to DeepHumor's CaptioningLSTM -- no attention, image enters only
    as the first timestep. Global pooling here reproduces their avgpool;
    pooling is the decoder's choice so the encoder stays a pure ablation.
    """

    def __init__(self, vocab_size, pad_id, embed_dim=256, hidden_size=512,
                 num_layers=2, img_dim=768, dropout=0.1):
        super().__init__()
        self.decoder_type = "lstm"
        self.embed_dim = embed_dim
        self.pad_id = pad_id
        self.max_length = None
        self.token_emb = nn.Embedding(vocab_size, embed_dim, padding_idx=pad_id)
        self.img_proj = nn.Linear(img_dim, embed_dim)
        self.lstm = nn.LSTM(
            embed_dim, hidden_size, num_layers=num_layers, batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        # Not tied: lm_head reads hidden_size, the embedding writes embed_dim.
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)
        self.apply(_init_weights)
        with torch.no_grad():
            self.token_emb.weight[pad_id].zero_()

    def forward(self, memory, input_ids):
        img = self.img_proj(memory.mean(dim=1)).unsqueeze(1)      # (B, 1, E)
        x = self.token_emb(input_ids)                             # (B, L, E)
        out, _ = self.lstm(torch.cat([img, x], dim=1))            # (B, 1+L, H)
        # Position p holds state after [img, x_0..x_{p-1}], so position p
        # predicts x_p -- which is exactly logits[t] predicting input_ids[t+1].
        return self.lm_head(out[:, 1:, :])

    def step(self, memory, ids):
        return self.forward(memory, ids)[:, -1, :]


def build_model(decoder, vocab_size, pad_id, img_dim, cfg):
    """decoder -> an initialised model. cfg is the flat hyperparameter dict."""
    if decoder == "transformer":
        return TransformerCaptionModel(
            vocab_size=vocab_size, pad_id=pad_id, img_dim=img_dim,
            embed_dim=cfg["embed_dim"], layers=cfg["layers"],
            heads=cfg["heads"], max_length=cfg["max_length"],
        )
    if decoder == "lstm":
        return LSTMCaptionModel(
            vocab_size=vocab_size, pad_id=pad_id, img_dim=img_dim,
            embed_dim=cfg["embed_dim"], hidden_size=cfg["hidden_size"],
            num_layers=cfg["layers"],
        )
    raise ValueError(f"unknown decoder {decoder!r}, expected one of {DECODERS}")


def _split_caption(text):
    """'<bos>TOP <sep> BOT<eos>' -> (TOP, BOT). Falls back to one line."""
    text = text.replace("<bos>", "").replace("<eos>", "").strip()
    if "<sep>" in text:
        top, bottom = text.split("<sep>", 1)
        return top.strip(), bottom.strip()
    return text.strip(), ""


@torch.no_grad()
def generate_batch(model, memory, tokenizer, max_new, strategy="greedy",
                   temperature=1.0, top_k=None, device="cpu", seed=None):
    """Autoregressive decode for a batch. Greedy is the default.

    Finished rows are frozen at <eos> so the batch stays rectangular while
    the others keep decoding; each row is then cut at its first <eos>.
    """
    if seed is not None:
        torch.manual_seed(seed)
    B = memory.shape[0]
    bos, eos = tokenizer.bos_token_id, tokenizer.eos_token_id
    ids = torch.full((B, 1), bos, device=device, dtype=torch.long)
    done = torch.zeros(B, dtype=torch.bool, device=device)

    for _ in range(max_new):
        logits = model.step(memory, ids)
        if strategy == "greedy":
            nxt = logits.argmax(dim=-1)
        elif strategy == "sample":
            logits = logits / temperature
            if top_k:
                k = min(top_k, logits.size(-1))
                v, _ = torch.topk(logits, k)
                logits = logits.masked_fill(logits < v[:, [-1]], float("-inf"))
            nxt = torch.multinomial(torch.softmax(logits, dim=-1), 1).squeeze(1)
        else:
            raise ValueError(f"unknown strategy {strategy!r}")

        done |= (nxt == eos)
        nxt = torch.where(done, eos, nxt)
        ids = torch.cat([ids, nxt.unsqueeze(1)], dim=1)
        if bool(done.all()):
            break

    outs = []
    for i in range(B):
        row = ids[i].tolist()
        if eos in row:
            row = row[: row.index(eos) + 1]
        outs.append(_split_caption(tokenizer.decode(row, skip_special_tokens=False)))
    return outs


@torch.no_grad()
def generate(model, memory, tokenizer, max_new, strategy="greedy",
             temperature=1.0, top_k=None, device="cpu", seed=None):
    """Greedy is the evaluation default and the comparison standard.

    DeepHumor calls its routine "beam search" but draws tokens with
    torch.multinomial, which makes their scores a lottery across runs.
    We keep sampling behind strategy='sample' for diversity demos only;
    every reported number is greedy, so re-running eval reproduces it.
    """
    if seed is not None:
        torch.manual_seed(seed)
    ids = torch.tensor([[tokenizer.bos_token_id]], device=device)
    for _ in range(max_new):
        logits = model.step(memory, ids)
        if strategy == "greedy":
            nxt = int(logits.argmax(dim=-1).item())
        elif strategy == "sample":
            logits = logits / temperature
            if top_k:
                k = min(top_k, logits.size(-1))
                v, _ = torch.topk(logits, k)
                logits = logits.masked_fill(logits < v[:, [-1]], float("-inf"))
            nxt = int(torch.multinomial(torch.softmax(logits, dim=-1), 1).item())
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
        if nxt == tokenizer.eos_token_id:
            break
        ids = torch.cat([ids, torch.tensor([[nxt]], device=device)], dim=1)
    text = tokenizer.decode(ids[0].tolist(), skip_special_tokens=False)
    return _split_caption(text)


def count_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
