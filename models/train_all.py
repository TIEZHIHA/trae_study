# -*- coding: utf-8 -*-
"""
训练 + 资产导出一键脚本。
    py -3 -m models.train_all            # 先训练再导出资产
    py -3 -m models.train_all --skip-train
"""
import argparse

import config
from models.train import train


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-train", action="store_true", help="跳过训练，只导出资产")
    ap.add_argument("--ner-epochs", type=int, default=30)
    ap.add_argument("--intent-epochs", type=int, default=25)
    args = ap.parse_args()

    if not args.skip_train:
        train(ner_epochs=args.ner_epochs, intent_epochs=args.intent_epochs)

    import storage
    storage.init_db()
    from resources import export_all
    stats = export_all(with_training=True)
    print("资产导出：", stats)
    print(f"模型：{config.MODEL_PATH}  曲线：{config.CURVE_PATH}")


if __name__ == "__main__":
    main()
