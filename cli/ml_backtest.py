#!/usr/bin/env python
"""Backtest trained ML model."""

import argparse
import os
import sys
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import load_candidate_codes
from ml_engine.ml_classifier import MLPatternModel
from ml_engine.eval import compute_ml_backtest, summarize_ml_backtest, summarize_ml_by_hold_days


def parse_days(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(',') if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="ML模型历史回测")
    parser.add_argument("--model", required=True)
    parser.add_argument("--hold-days", default="1,3,5,10")
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--candidate-file", default="")
    parser.add_argument("--use-selected-file", action="store_true")
    parser.add_argument("--max-stocks", type=int, default=0)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    model = MLPatternModel.load(args.model)
    codes = load_candidate_codes(args.candidate_file or None, default_selected=args.use_selected_file)
    if args.max_stocks:
        codes = codes[:args.max_stocks]
    trades = compute_ml_backtest(model, codes, parse_days(args.hold_days), args.threshold, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
    if trades.empty:
        print("无交易信号，可降低 --threshold")
        return
    summary = summarize_ml_by_hold_days(trades)
    overall = summarize_ml_backtest(trades)
    print(summary.to_string(index=False))
    if not args.output:
        args.output = os.path.join("output/ml_similarity", f"ml_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="按持有期统计", index=False)
        overall.to_excel(writer, sheet_name="总体统计", index=False)
        trades.to_excel(writer, sheet_name="交易明细", index=False)
    print(f"报告已保存: {args.output}")


if __name__ == "__main__":
    main()
