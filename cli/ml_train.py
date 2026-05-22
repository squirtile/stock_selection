#!/usr/bin/env python
"""Train ML pattern model."""

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from cli.ml_similarity import auto_select_templates
from ml_engine.runner import train_model, run_ml_pipeline


def parse_days(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(',') if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="训练 ML 形态模型")
    parser.add_argument("--template", default="", help="模板股票代码，逗号分隔")
    parser.add_argument("--auto-template", action="store_true", help="自动选择近期强势股")
    parser.add_argument("--auto-top-n", type=int, default=20)
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--target", type=float, default=5.0)
    parser.add_argument("--use-pca", action="store_true")
    parser.add_argument("--full-pipeline", action="store_true")
    parser.add_argument("--threshold", type=float, default=0.60)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--hold-days", default="1,3,5,10")
    args = parser.parse_args()

    if args.auto_template:
        template_codes = auto_select_templates(args.auto_top_n)
    elif args.template:
        template_codes = [x.strip() for x in args.template.split(',') if x.strip()]
    else:
        print("请提供 --template 或 --auto-template")
        sys.exit(1)

    if args.full_pipeline:
        run_ml_pipeline(
            template_codes=template_codes,
            lookback=args.lookback,
            forward_horizon=args.horizon,
            target_pct=args.target,
            similarity_threshold=args.threshold,
            hold_days_list=parse_days(args.hold_days),
            top_k=args.top_k,
            use_pca=args.use_pca,
        )
    else:
        train_model(template_codes, lookback=args.lookback, forward_horizon=args.horizon, target_pct=args.target, use_pca=args.use_pca)


if __name__ == "__main__":
    main()
