#!/usr/bin/env python
"""Single-stock manual range pattern matching."""

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.runner import match_single_stock_pattern


def parse_days(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(',') if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="单股票指定区间形态匹配")
    parser.add_argument("--code", required=True, help="模板股票代码")
    parser.add_argument("--date-start", required=True, help="模板开始日期 YYYY-MM-DD")
    parser.add_argument("--date-end", required=True, help="模板结束日期 YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=20, help="窗口天数，默认20")
    parser.add_argument("--threshold", type=float, default=0.60, help="相似度阈值，默认0.60")
    parser.add_argument("--top-k", type=int, default=20, help="输出前K只，默认20")
    parser.add_argument("--hold-days", default="1,3,5,10", help="回测持有天数")
    parser.add_argument("--recent-windows", type=int, default=3, help="每只候选股取最近N个窗口")
    parser.add_argument("--workers", type=int, default=1, help="候选扫描并发线程数，建议4~8；默认1表示单线程")
    parser.add_argument("--candidate-file", default="", help="候选股票文件，支持xlsx/csv，包含代码列")
    parser.add_argument("--use-selected-file", action="store_true", help="优先使用 output/a_stock_selected.xlsx 作为候选池")
    parser.add_argument("--backtest-scope", choices=["all_candidates", "topk"], default="all_candidates", help="回测范围，默认全部候选")
    parser.add_argument("--skip-backtest", action="store_true", help="只做当前相似度扫描，不执行历史回测，速度更快")
    parser.add_argument("--fee-bps", type=float, default=0.0, help="单笔往返费用，bps，例如 6")
    parser.add_argument("--slippage-bps", type=float, default=0.0, help="买卖滑点，bps")
    parser.add_argument("--output-dir", default="output/ml_similarity", help="输出目录")
    args = parser.parse_args()

    result = match_single_stock_pattern(
        template_code=args.code,
        date_start=args.date_start,
        date_end=args.date_end,
        lookback=args.lookback,
        similarity_threshold=args.threshold,
        top_k=args.top_k,
        hold_days_list=parse_days(args.hold_days),
        recent_windows=args.recent_windows,
        output_dir=args.output_dir,
        candidate_file=args.candidate_file or None,
        use_selected_file=args.use_selected_file,
        backtest_scope=args.backtest_scope,
        skip_backtest=args.skip_backtest,
        workers=args.workers,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )
    if result.get("report_path"):
        print(f"完成，报告：{result['report_path']}")


if __name__ == "__main__":
    main()
