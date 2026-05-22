#!/usr/bin/env python
"""
自动模板形态相似度扫描入口。

用法示例：
  python cli/ml_similarity.py --template 002179 --template-mode auto --threshold 0.55 --top-k 20 --recent-windows 1 --workers 8
  python cli/ml_similarity.py --template 002179,600535,002265 --template-mode auto --threshold 0.55 --top-k 30 --recent-windows 1 --workers 8
"""

from __future__ import annotations

import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import DEFAULT_LOOKBACK, list_cached_codes, normalize_code, try_load_stock_name_map
from ml_engine.runner import find_similar_stocks


def _parse_codes(raw: str) -> list[str]:
    return [normalize_code(x) for x in raw.split(",") if x.strip()]


def _auto_select_templates(top_n: int = 10) -> list[str]:
    """简单自动选择最近阶段涨幅较高的股票作为模板。"""
    from ml_engine.pattern_extract import load_hist_cache

    rows = []
    for code in list_cached_codes():
        try:
            df = load_hist_cache(code)
            if df is None or df.empty or len(df) < 80:
                continue
            df = df.sort_values("日期").reset_index(drop=True)
            close = df["收盘"].astype(float)
            start = float(close.iloc[-60]) if len(close) >= 60 else float(close.iloc[0])
            end = float(close.iloc[-1])
            if start <= 0:
                continue
            ret60 = (end / start - 1.0) * 100.0
            rows.append((code, ret60))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in rows[:top_n]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="自动提取模板股票启动形态，并扫描 cache/hist 股票池当前相似形态",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python cli/ml_similarity.py --template 002179 --template-mode auto --threshold 0.55 --top-k 20 --recent-windows 1 --workers 8
  python cli/ml_similarity.py --template 002179,600535,002265 --template-mode auto --threshold 0.55 --top-k 30 --recent-windows 1 --workers 8
  python cli/ml_similarity.py --auto-template --auto-top-n 10 --template-mode auto --threshold 0.55 --top-k 30 --workers 8

说明：
  cache/hist 目录默认就是候选股票池。
  --template-mode auto 会优先自动识别模板股票的启动前窗口；识别不到时退回最近窗口。
        """,
    )
    parser.add_argument("--template", type=str, default="", help="模板股票代码，多个用英文逗号分隔，如 002179,600535")
    parser.add_argument("--auto-template", action="store_true", help="自动选择最近60日涨幅靠前的股票作为模板")
    parser.add_argument("--auto-top-n", type=int, default=10, help="自动模板股票数量，默认10")
    parser.add_argument("--template-mode", type=str, default="auto",
                        choices=["auto", "prelaunch", "launch", "both", "recent", "all"],
                        help="模板提取模式：auto/prelaunch/launch/both/recent/all，默认auto")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK, help="形态窗口长度，默认20个交易日")
    parser.add_argument("--threshold", type=float, default=0.60, help="相似度阈值，默认0.60")
    parser.add_argument("--top-k", type=int, default=50, help="输出前K只股票，默认50")
    parser.add_argument("--recent-windows", type=int, default=3, help="每只候选股提取最近几个窗口，默认3；只看当前用1")
    parser.add_argument("--template-recent-n", type=int, default=3, help="每只模板股最多提取几个模板窗口，默认3")
    parser.add_argument("--candidate-file", type=str, default="", help="可选候选股票文件，默认不用；不填则扫描 cache/hist")
    parser.add_argument("--use-selected-file", action="store_true", help="使用 output/a_stock_selected.xlsx 作为候选池")
    parser.add_argument("--output-dir", type=str, default="output/ml_similarity", help="输出目录")
    parser.add_argument("--workers", type=int, default=1, help="候选扫描并发线程数，Windows建议4或8")

    args = parser.parse_args()

    if args.auto_template:
        template_codes = _auto_select_templates(args.auto_top_n)
    elif args.template:
        template_codes = _parse_codes(args.template)
    else:
        print("错误：请使用 --template 指定模板股票，或使用 --auto-template 自动选择模板。")
        sys.exit(1)

    all_codes = set(list_cached_codes())
    template_codes = [c for c in template_codes if c in all_codes]
    if not template_codes:
        print("错误：模板股票在 cache/hist 中没有找到缓存数据。")
        sys.exit(1)

    name_map = try_load_stock_name_map()
    print("模板股票：")
    for code in template_codes:
        print(f"  {code} {name_map.get(code, '')}")

    stock_df = find_similar_stocks(
        template_codes=template_codes,
        candidate_codes=None,
        lookback=args.lookback,
        min_similarity=args.threshold,
        top_k=args.top_k,
        output_dir=args.output_dir,
        template_mode=args.template_mode,
        recent_windows=args.recent_windows,
        template_recent_n=args.template_recent_n,
        candidate_file=args.candidate_file or None,
        use_selected_file=args.use_selected_file,
        workers=args.workers,
    )

    if stock_df is None or stock_df.empty:
        print(f"
无匹配结果，建议降低阈值，例如 --threshold 0.45")
        return

    print("
" + "=" * 80)
    print(f"Top {len(stock_df)} 相似股票")
    print("=" * 80)
    for _, row in stock_df.iterrows():
        code = row.get("代码", "")
        name = row.get("名称", "")
        avg_sim = row.get("平均相似度%", 0)
        max_sim = row.get("最大相似度%", 0)
        count = int(row.get("匹配次数", 0))
        print(f"  {code} {name}: 平均{avg_sim}% 最大{max_sim}% 匹配{count}次")


if __name__ == "__main__":
    main()
