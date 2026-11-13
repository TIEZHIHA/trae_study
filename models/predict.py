# -*- coding: utf-8 -*-
"""模型推理封装：加载 best_model.pt，输出实体片段与意图。"""
from pathlib import Path

import torch

import config
from models.intent_textcnn import TextCNN
from models.ner_bilstm import BiLSTMNER

UNK_ID = 1


class MedicalModel:
    def __init__(self, ckpt):
        self.vocab = ckpt["vocab"]
        self.ner_labels = ckpt["ner_labels"]
        self.intent_labels = ckpt["intent_labels"]
        self.best_ner_f1 = ckpt.get("best_ner_f1", 0.0)
        self.best_intent_acc = ckpt.get("best_intent_acc", 0.0)

        self.ner = BiLSTMNER(len(self.vocab), len(self.ner_labels))
        self.ner.load_state_dict(ckpt["ner_state"])
        self.ner.eval()

        self.intent = TextCNN(len(self.vocab), len(self.intent_labels))
        self.intent.load_state_dict(ckpt["intent_state"])
        self.intent.eval()

    @classmethod
    def load(cls, path=None):
        """模型不存在或加载失败返回 None，由调用方回退规则。"""
        p = Path(path or config.MODEL_PATH)
        if not p.exists():
            return None
        try:
            try:
                ckpt = torch.load(p, map_location="cpu", weights_only=False)
            except TypeError:                       # 兼容 torch 1.x
                ckpt = torch.load(p, map_location="cpu")
            return cls(ckpt)
        except Exception:
            return None

    def _ids(self, text):
        return torch.tensor([[self.vocab.get(c, UNK_ID) for c in text]], dtype=torch.long)

    @torch.no_grad()
    def predict_entity(self, text):
        """
        返回 {"surface", "label", "conf", "start", "end"}；
        无实体返回 None。置信度取片段内各字概率的最小值（更保守）。
        """
        if not text:
            return None
        logits = self.ner(self._ids(text))
        probs = torch.softmax(logits, dim=-1)[0]
        tags = logits.argmax(-1)[0].tolist()

        best = None
        start = None
        for i, t in enumerate(tags + [0]):
            name = self.ner_labels[t] if t < len(self.ner_labels) else "O"
            if name == "B-Disease" and start is None:
                start = i
            elif name == "I-Disease" and start is not None:
                continue
            else:
                if start is not None:
                    conf = min(float(probs[j][tags[j]]) for j in range(start, i))
                    if best is None or conf > best["conf"]:
                        best = {"surface": text[start:i], "label": "Disease",
                                "conf": round(conf, 4), "start": start, "end": i}
                    start = None
        return best

    @torch.no_grad()
    def predict_intent(self, text):
        """返回 (intent, 置信度)。"""
        if not text:
            return None, 0.0
        logits = self.intent(self._ids(text))
        probs = torch.softmax(logits, dim=-1)[0]
        idx = int(probs.argmax())
        return self.intent_labels[idx], round(float(probs[idx]), 4)
