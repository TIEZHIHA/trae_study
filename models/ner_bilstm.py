# -*- coding: utf-8 -*-
"""BiLSTM 字符级命名实体识别（BIO 标注，实体类型 Disease）。"""
import torch
import torch.nn as nn


class BiLSTMNER(nn.Module):
    def __init__(self, vocab_size, n_labels, emb_dim=64, hidden=96, dropout=0.2):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.lstm = nn.LSTM(emb_dim, hidden, batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden * 2, n_labels)

    def forward(self, x, lengths=None):
        # x: [B, T] -> logits [B, T, C]
        emb = self.dropout(self.embedding(x))
        out, _ = self.lstm(emb)
        return self.fc(self.dropout(out))
