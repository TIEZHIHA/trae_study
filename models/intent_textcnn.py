# -*- coding: utf-8 -*-
"""TextCNN 字符级意图分类（卷积核 2/3/4，最大池化后全连接）。"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class TextCNN(nn.Module):
    def __init__(self, vocab_size, n_classes, emb_dim=64, n_filters=64, dropout=0.3):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.convs = nn.ModuleList([
            nn.Conv1d(emb_dim, n_filters, k) for k in (2, 3, 4)
        ])
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(n_filters * 3, n_classes)

    def forward(self, x):
        # x: [B, T] -> logits [B, C]
        emb = self.embedding(x).transpose(1, 2)          # [B, E, T]
        feats = []
        for conv in self.convs:
            h = F.relu(conv(emb))                        # [B, F, T-k+1]
            feats.append(F.adaptive_max_pool1d(h, 1).squeeze(-1))
        out = self.dropout(torch.cat(feats, dim=1))
        return self.fc(out)
