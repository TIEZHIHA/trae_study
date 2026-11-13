# -*- coding: utf-8 -*-
"""
训练入口：BiLSTM NER + TextCNN 意图分类。
运行：
    py -3 -m models.train              # 默认 30 / 25 轮
    py -3 -m models.train --ner-epochs 40

产物：
    models/medical_ner_cls/best_model.pt   仅指标创新高时覆盖
    models/medical_ner_cls/metrics.jsonl   每轮 Loss / F1 / Acc
    models/medical_ner_cls/curves.png      Loss 与 F1/Acc 曲线
"""
import argparse
import json
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

# 允许 `python models/train.py` 与 `python -m models.train` 两种方式
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                    # noqa: E402
from models.dataset import build_training_files   # noqa: E402
from models.intent_textcnn import TextCNN         # noqa: E402
from models.ner_bilstm import BiLSTMNER           # noqa: E402

PAD, UNK = "<pad>", "<unk>"
NER_LABELS = ["O", "B-Disease", "I-Disease"]
SEED = 2026


# ---------------------------------------------------------------- 数据
def load_ner(path):
    samples = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        pairs = [t.rsplit("/", 1) for t in line.split() if "/" in t]
        if pairs:
            samples.append(pairs)
    return samples


def load_intent(path):
    import csv
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("text"):
                rows.append((row["text"], row["intent"]))
    return rows


def build_vocab(ner_samples, intent_samples, min_freq=1):
    freq = {}
    for pairs in ner_samples:
        for ch, _ in pairs:
            freq[ch] = freq.get(ch, 0) + 1
    for text, _ in intent_samples:
        for ch in text:
            freq[ch] = freq.get(ch, 0) + 1
    chars = [c for c, n in freq.items() if n >= min_freq]
    vocab = {PAD: 0, UNK: 1}
    for c in sorted(chars):
        vocab[c] = len(vocab)
    return vocab


class NERDataset(Dataset):
    def __init__(self, samples, vocab):
        self.items = []
        for pairs in samples:
            ids = [vocab.get(ch, 1) for ch, _ in pairs]
            tags = [NER_LABELS.index(tag) if tag in NER_LABELS else 0 for _, tag in pairs]
            self.items.append((ids, tags))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def ner_collate(batch):
    max_len = max(len(x[0]) for x in batch)
    ids = torch.zeros(len(batch), max_len, dtype=torch.long)
    tags = torch.full((len(batch), max_len), -100, dtype=torch.long)
    for i, (seq, tg) in enumerate(batch):
        ids[i, :len(seq)] = torch.tensor(seq)
        tags[i, :len(tg)] = torch.tensor(tg)
    return ids, tags


class IntentDataset(Dataset):
    def __init__(self, samples, vocab, labels):
        self.items = [([vocab.get(c, 1) for c in text], labels.index(intent))
                      for text, intent in samples]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def intent_collate(batch):
    max_len = max(len(x[0]) for x in batch)
    ids = torch.zeros(len(batch), max_len, dtype=torch.long)
    labels = torch.zeros(len(batch), dtype=torch.long)
    for i, (seq, y) in enumerate(batch):
        ids[i, :len(seq)] = torch.tensor(seq)
        labels[i] = y
    return ids, labels


# ---------------------------------------------------------------- 评估
def decode_entities(tag_ids):
    """把标签序列解码成实体片段集合，用于实体级 P/R/F1。"""
    spans, start = set(), None
    for i, t in enumerate(list(tag_ids) + [0]):
        if t == 1:                      # B
            if start is not None:
                spans.add((start, i))
            start = i
        elif t == 2:                    # I
            if start is None:
                start = i
        else:
            if start is not None:
                spans.add((start, i))
                start = None
    return spans


def evaluate_ner(model, loader):
    model.eval()
    tp = fp = fn = 0
    with torch.no_grad():
        for ids, tags in loader:
            pred = model(ids).argmax(-1)
            for i in range(ids.size(0)):
                mask = tags[i] != -100
                gold = decode_entities(tags[i][mask].tolist())
                got = decode_entities(pred[i][mask].tolist())
                tp += len(gold & got)
                fp += len(got - gold)
                fn += len(gold - got)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return (2 * p * r / (p + r) if p + r else 0.0), p, r


def evaluate_intent(model, loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for ids, y in loader:
            pred = model(ids).argmax(-1)
            correct += int((pred == y).sum())
            total += y.numel()
    return correct / total if total else 0.0


# ---------------------------------------------------------------- 训练
def train(ner_epochs=30, intent_epochs=25, batch_size=32, lr=2e-3):
    random.seed(SEED)
    torch.manual_seed(SEED)

    total_samples = build_training_files()
    ner_samples = load_ner(config.TRAIN_DIR / "ner_bio.txt")
    intent_samples = load_intent(config.TRAIN_DIR / "intent_train.csv")
    intent_labels = sorted({y for _, y in intent_samples})
    vocab = build_vocab(ner_samples, intent_samples)
    print(f"样本：NER {len(ner_samples)} / 意图 {len(intent_samples)}，词表 {len(vocab)}")

    random.shuffle(ner_samples)
    random.shuffle(intent_samples)
    cut_n = max(1, int(len(ner_samples) * 0.15))
    cut_i = max(1, int(len(intent_samples) * 0.15))
    ner_dev = ner_samples[:cut_n]
    ner_train = ner_samples[cut_n:]
    intent_dev = intent_samples[:cut_i]
    intent_train = intent_samples[cut_i:]

    ner_loader = DataLoader(NERDataset(ner_train, vocab), batch_size=batch_size,
                            shuffle=True, collate_fn=ner_collate)
    ner_dev_loader = DataLoader(NERDataset(ner_dev, vocab), batch_size=batch_size,
                                collate_fn=ner_collate)
    intent_loader = DataLoader(IntentDataset(intent_train, vocab, intent_labels),
                               batch_size=batch_size, shuffle=True,
                               collate_fn=intent_collate)
    intent_dev_loader = DataLoader(IntentDataset(intent_dev, vocab, intent_labels),
                                   batch_size=batch_size, collate_fn=intent_collate)

    ner_model = BiLSTMNER(len(vocab), len(NER_LABELS))
    intent_model = TextCNN(len(vocab), len(intent_labels))
    ner_opt = torch.optim.Adam(ner_model.parameters(), lr=lr)
    intent_opt = torch.optim.Adam(intent_model.parameters(), lr=lr)
    ce = nn.CrossEntropyLoss(ignore_index=-100)

    ckpt = {
        "vocab": vocab,
        "ner_labels": NER_LABELS,
        "intent_labels": intent_labels,
        "best_ner_f1": 0.0,
        "best_intent_acc": 0.0,
        "metrics": {},
    }
    metrics_path = config.METRICS_PATH
    metrics_path.write_text("", encoding="utf-8")

    def save():
        torch.save(ckpt, config.MODEL_PATH)

    def log(record):
        with open(metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ---- NER
    for epoch in range(1, ner_epochs + 1):
        ner_model.train()
        total_loss = 0.0
        for ids, tags in ner_loader:
            ner_opt.zero_grad()
            loss = ce(ner_model(ids).view(-1, len(NER_LABELS)), tags.view(-1))
            loss.backward()
            ner_opt.step()
            total_loss += float(loss)
        f1, p, r = evaluate_ner(ner_model, ner_dev_loader)
        log({"stage": "ner", "epoch": epoch, "loss": round(total_loss, 4),
             "f1": round(f1, 4), "precision": round(p, 4), "recall": round(r, 4)})
        print(f"[NER] epoch {epoch:02d} loss={total_loss:.3f} F1={f1:.4f}")
        if f1 > ckpt["best_ner_f1"]:     # 仅指标创新高才覆盖模型
            ckpt["best_ner_f1"] = round(f1, 4)
            ckpt["ner_state"] = ner_model.state_dict()
            save()

    # ---- Intent
    for epoch in range(1, intent_epochs + 1):
        intent_model.train()
        total_loss = 0.0
        for ids, y in intent_loader:
            intent_opt.zero_grad()
            loss = ce(intent_model(ids), y)
            loss.backward()
            intent_opt.step()
            total_loss += float(loss)
        acc = evaluate_intent(intent_model, intent_dev_loader)
        log({"stage": "intent", "epoch": epoch, "loss": round(total_loss, 4),
             "acc": round(acc, 4)})
        print(f"[INTENT] epoch {epoch:02d} loss={total_loss:.3f} Acc={acc:.4f}")
        if acc > ckpt["best_intent_acc"]:
            ckpt["best_intent_acc"] = round(acc, 4)
            ckpt["intent_state"] = intent_model.state_dict()
            save()

    # 保证两个 state 都存在（极端情况下 dev 指标全 0）
    if "ner_state" not in ckpt:
        ckpt["ner_state"] = ner_model.state_dict()
    if "intent_state" not in ckpt:
        ckpt["intent_state"] = intent_model.state_dict()
    ckpt["metrics"] = {"best_ner_f1": ckpt["best_ner_f1"],
                       "best_intent_acc": ckpt["best_intent_acc"],
                       "samples": total_samples}
    save()
    plot_curves(metrics_path)
    print(f"完成：best NER F1={ckpt['best_ner_f1']}，best Intent Acc={ckpt['best_intent_acc']}")
    print(f"模型：{config.MODEL_PATH}")
    return ckpt


def plot_curves(metrics_path):
    """画 Loss 与 F1/Acc 双图，供验收查看指标曲线。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    records = [json.loads(x) for x in
               Path(metrics_path).read_text(encoding="utf-8").splitlines() if x.strip()]
    if not records:
        return
    font_path = "C:/Windows/Fonts/simhei.ttf"
    if Path(font_path).exists():
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams["axes.unicode_minus"] = False

    ner = [r for r in records if r["stage"] == "ner"]
    intent = [r for r in records if r["stage"] == "intent"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), dpi=150)
    if ner:
        axes[0].plot([r["epoch"] for r in ner], [r["loss"] for r in ner],
                     color="#185FA5", label="Loss")
        axes[0].set_title("BiLSTM NER 训练 Loss")
        axes[0].set_xlabel("epoch")
        axes[0].grid(alpha=.25)
        ax2 = axes[0].twinx()
        ax2.plot([r["epoch"] for r in ner], [r["f1"] for r in ner],
                 color="#12a594", label="F1")
        ax2.set_ylim(0, 1.02)
        axes[0].legend(loc="upper right")
        ax2.legend(loc="lower right")
    if intent:
        axes[1].plot([r["epoch"] for r in intent], [r["loss"] for r in intent],
                     color="#185FA5", label="Loss")
        axes[1].set_title("TextCNN 意图分类 Loss / Acc")
        axes[1].set_xlabel("epoch")
        axes[1].grid(alpha=.25)
        ax2 = axes[1].twinx()
        ax2.plot([r["epoch"] for r in intent], [r["acc"] for r in intent],
                 color="#c9821a", label="Acc")
        ax2.set_ylim(0, 1.02)
        axes[1].legend(loc="upper right")
        ax2.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(config.CURVE_PATH)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ner-epochs", type=int, default=30)
    ap.add_argument("--intent-epochs", type=int, default=25)
    args = ap.parse_args()
    train(ner_epochs=args.ner_epochs, intent_epochs=args.intent_epochs)


if __name__ == "__main__":
    main()
