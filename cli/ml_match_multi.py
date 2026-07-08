#!/usr/bin/env python
"""
多股票 + 各自时间段 → 提取形态 → 训练ML模型 → 生成.pkl

用法示例：
  # 方式1：统一日期范围（所有股票同一时间段）
  python cli/ml_match_multi.py --codes 600288,000938,002350 \
      --date-start 2026-06-20 --date-end 2026-07-08

  # 方式2：选股日期 + 回看天数（最推荐！朋友哪天选的，往前看多少天）
  python cli/ml_match_multi.py --codes 600288,000938,002350 \
      --pick-date 2026-07-08 --lookback-days 20

  # 方式3：每只股票各自指定时间段
  python cli/ml_match_multi.py --stocks "600288:2026-06-20:2026-07-08,000938:2026-06-15:2026-07-08"

  # 完整流水线：训练 + 扫描 + 回测
  python cli/ml_match_multi.py --codes 600288,000938,002350 \
      --pick-date 2026-07-08 --lookback-days 20 --full-pipeline

输出：output/ml_strategies/ 目录下的 .pkl 模型文件 + 同花顺选股txt
"""

import argparse
import os
import sys

import pandas as pd
from tabulate import tabulate

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.runner import train_model_from_date_ranges, find_similar_stocks
from ml_engine.eval import compute_ml_backtest, summarize_ml_by_hold_days
from ml_engine.pattern_extract import list_cached_codes, normalize_code


def apply_strategy_filter(codes: list[str]) -> pd.DataFrame:
    """策略共振过滤：对每只股票取最新日线，跑全部日线策略，只保留命中≥1条的。

    Returns:
        DataFrame with columns: 代码, 名称, 命中策略
    """
    from strategy import prepare_hist_data
    from strategies import evaluate_daily_strategies
    from ml_engine.pattern_extract import try_load_stock_name_map

    name_map = try_load_stock_name_map()
    results = []

    for code in codes:
        try:
            file_path = os.path.join(PROJECT_ROOT, "cache", "hist", f"{code}_bs.csv")
            if not os.path.exists(file_path):
                continue
            df = pd.read_csv(file_path, dtype={"代码": str})
            if df.empty or "日期" not in df.columns:
                continue
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.dropna(subset=["日期"]).sort_values("日期")

            # 用 prepare_hist_data 算指标
            df = prepare_hist_data(df)
            latest = df.iloc[-1]

            # 跑全部日线策略
            signals = evaluate_daily_strategies(latest)
            if signals:
                strategy_names = [s.strategy_name for s in signals]
                name = name_map.get(normalize_code(code), "")
                results.append({
                    "代码": normalize_code(code),
                    "名称": name,
                    "命中策略": ", ".join(strategy_names),
                    "命中数": len(signals),
                })
        except Exception:
            continue

    return pd.DataFrame(results).sort_values("命中数", ascending=False) if results else pd.DataFrame()


def parse_stock_ranges(
    codes: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    pick_date: str | None = None,
    lookback_days: int = 20,
    stocks_spec: str | None = None,
) -> list[dict]:
    """解析股票+时间段输入，返回统一格式的列表。

    支持三种输入方式（优先级：stocks_spec > pick_date > date_start/end）：
    - stocks_spec: "600288:2026-06-20:2026-07-08,000938:2026-06-15:2026-07-08"
    - pick_date + lookback_days + codes: 自动计算 date_start = pick_date - lookback_days
    - date_start + date_end + codes: 统一时间段
    """
    if stocks_spec:
        result = []
        for item in stocks_spec.split(","):
            parts = item.strip().split(":")
            if len(parts) != 3:
                raise ValueError(f"格式错误: '{item}'，应为 代码:开始日期:结束日期")
            result.append({
                "code": parts[0].strip(),
                "date_start": parts[1].strip(),
                "date_end": parts[2].strip(),
            })
        return result

    if not codes:
        raise ValueError("请提供 --codes 或 --stocks 参数")

    code_list = [c.strip() for c in codes.split(",") if c.strip()]

    if pick_date:
        end = pd.Timestamp(pick_date)
        start = end - pd.Timedelta(days=lookback_days)
        date_start = start.strftime("%Y-%m-%d")
        date_end = end.strftime("%Y-%m-%d")

    if not date_start or not date_end:
        raise ValueError("请提供 --date-start/--date-end 或 --pick-date")

    return [
        {"code": code, "date_start": date_start, "date_end": date_end}
        for code in code_list
    ]


def main():
    parser = argparse.ArgumentParser(
        description="多股票指定时间段 → 训练ML形态模型 → 生成.pkl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 朋友今天选的3只票，回看20天形态
  python cli/ml_match_multi.py --codes 600288,000938,002350 --pick-date 2026-07-08 --lookback-days 20

  # 统一日期范围
  python cli/ml_match_multi.py --codes 600288,000938,002350 --date-start 2026-06-20 --date-end 2026-07-08

  # 每只票不同时间段
  python cli/ml_match_multi.py --stocks "600288:2026-06-20:2026-07-08,000938:2026-06-15:2026-07-08"

  # 完整流水线（训练+扫描+回测）
  python cli/ml_match_multi.py --codes 600288,000938,002350 --pick-date 2026-07-08 --full-pipeline
        """,
    )

    # 输入方式
    input_group = parser.add_argument_group("输入方式（三选一）")
    input_group.add_argument("--stocks", default="", help="每只股票单独时间段: 代码:开始:结束,代码:开始:结束")
    input_group.add_argument("--codes", default="", help="股票代码，逗号分隔（配合--date-start/--date-end或--pick-date）")
    input_group.add_argument("--date-start", default="", help="统一开始日期 YYYY-MM-DD")
    input_group.add_argument("--date-end", default="", help="统一结束日期 YYYY-MM-DD")
    input_group.add_argument("--pick-date", default="", help="选股日期 YYYY-MM-DD（配合--lookback-days自动计算date-start）")
    input_group.add_argument("--lookback-days", type=int, default=20, help="从pick-date往前看多少天，默认20")

    # 模型参数
    model_group = parser.add_argument_group("模型参数")
    model_group.add_argument("--window", type=int, default=20, help="形态窗口天数，默认20")
    model_group.add_argument("--horizon", type=int, default=5, help="预测未来N天，默认5")
    model_group.add_argument("--target", type=float, default=5.0, help="目标涨幅%%，默认5.0")
    model_group.add_argument("--use-pca", action="store_true", help="使用PCA降维")
    model_group.add_argument("--output-dir", default="output/ml_strategies", help="模型输出目录，默认 output/ml_strategies")
    model_group.add_argument("--no-supplement", action="store_true", help="不从其他股票补充负样本")

    # 完整流水线
    pipeline_group = parser.add_argument_group("完整流水线（训练后自动扫描+回测）")
    pipeline_group.add_argument("--full-pipeline", action="store_true", help="训练后自动执行相似度扫描+回测")
    pipeline_group.add_argument("--threshold", type=float, default=0.65, help="相似度阈值，默认0.65")
    pipeline_group.add_argument("--top-k", type=int, default=20, help="输出前K只，默认20")
    pipeline_group.add_argument("--hold-days", default="1,3,5,10", help="回测持有天数，默认1,3,5,10")
    pipeline_group.add_argument("--workers", type=int, default=4, help="扫描并发线程数，默认4")
    pipeline_group.add_argument("--strategy-filter", action="store_true", help="策略共振过滤：只保留同时命中日线策略的票，大幅减少数量")

    args = parser.parse_args()

    # 解析股票+时间段
    stock_ranges = parse_stock_ranges(
        codes=args.codes or None,
        date_start=args.date_start or None,
        date_end=args.date_end or None,
        pick_date=args.pick_date or None,
        lookback_days=args.lookback_days,
        stocks_spec=args.stocks or None,
    )

    if not stock_ranges:
        print("错误：未能解析任何股票和时间段。请检查输入参数。")
        sys.exit(1)

    print(f"\n📊 多股票时间段 → ML模型训练")
    print(f"  模板股票: {len(stock_ranges)} 只")
    for item in stock_ranges:
        print(f"    {normalize_code(item['code'])}: {item['date_start']} ~ {item['date_end']}")
    print(f"  窗口: {args.window}天 | 预测: {args.horizon}天 | 目标涨幅: {args.target}%")
    print()

    # 训练模型
    model, stats = train_model_from_date_ranges(
        stock_ranges=stock_ranges,
        lookback=args.window,
        forward_horizon=args.horizon,
        target_pct=args.target,
        use_pca=args.use_pca,
        model_dir=args.output_dir,
        supplement_negatives=not args.no_supplement,
    )

    print(f"\n✅ 完成！模型: {stats['model_path']}")

    # 完整流水线
    if args.full_pipeline:
        print(f"\n{'=' * 60}")
        print("🚀 完整流水线：相似度扫描 + 回测")
        print("=" * 60)

        template_codes = [normalize_code(item["code"]) for item in stock_ranges]
        hold_days_list = [int(x.strip()) for x in args.hold_days.split(",") if x.strip()]

        # Step A: 相似度扫描
        date_start = stock_ranges[0]["date_start"]
        date_end = stock_ranges[0]["date_end"]
        similarity_df = find_similar_stocks(
            template_codes=template_codes,
            lookback=args.window,
            min_similarity=args.threshold,
            top_k=args.top_k,
            date_start=date_start,
            date_end=date_end,
            workers=args.workers,
        )

        if not similarity_df.empty:
            # —— 策略共振过滤 ——
            if args.strategy_filter:
                print(f"\n  🔍 策略共振过滤：检查 {len(similarity_df)} 只相似票是否命中日线策略...")
                sim_codes = similarity_df["代码"].tolist()
                strategy_hits = apply_strategy_filter(sim_codes)

                if not strategy_hits.empty:
                    # 只保留命中策略的票
                    hit_codes = set(strategy_hits["代码"].tolist())
                    similarity_df = similarity_df[similarity_df["代码"].isin(hit_codes)].copy()

                    print(f"  ✅ 共振票: {len(similarity_df)}/{len(sim_codes)} 只（同时命中日线策略）")
                    print(tabulate(strategy_hits, headers="keys", tablefmt="simple", showindex=False))
                else:
                    print(f"  ⚠️ 无一命中策略共振，保留原始相似度结果")
                print()

            print(f"\n  Top {min(10, len(similarity_df))} 相似股票:")
            top_show = similarity_df.head(10)[["代码", "名称", "平均相似度%"]].copy()
            top_show["平均相似度%"] = top_show["平均相似度%"].apply(lambda x: f"{x}%")
            print(tabulate(top_show, headers="keys", tablefmt="simple", showindex=False))

            # —— 写入同花顺格式 txt ——
            safe_codes = "_".join(template_codes[:4])
            ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            txt_filename = f"同花顺_{safe_codes}_{ts}.txt"
            txt_path = os.path.join(args.output_dir, txt_filename)

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"策略模板: {', '.join(template_codes)} | {date_start}~{date_end}\n")
                f.write(f"相似度阈值: {args.threshold*100:.0f}% | 窗口: {args.window}天 | 生成时间: {ts}\n")
                f.write("=" * 50 + "\n\n")
                for _, row in similarity_df.iterrows():
                    name = row.get("名称", "")
                    sim = row["平均相似度%"]
                    f.write(f"    {row['代码']} {name}: 相似度 {sim}%\n")

            print(f"\n  📄 同花顺选股列表已保存: {txt_path}")

        # Step B: ML回测
        print(f"\n  ML模型回测 (持有: {hold_days_list} 天)...")
        backtest_codes = similarity_df["代码"].tolist() if not similarity_df.empty else list_cached_codes()[:100]
        trades = compute_ml_backtest(model, backtest_codes, hold_days_list=hold_days_list)
        if not trades.empty:
            summary = summarize_ml_by_hold_days(trades)
            # 格式化百分比列
            pct_cols = ["胜率%", "平均收益率%", "中位数收益率%", "最大单笔收益%", "最大单笔亏损%", "平均盈利%", "平均亏损%"]
            for col in pct_cols:
                if col in summary.columns:
                    summary[col] = summary[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
            if "盈亏比" in summary.columns:
                summary["盈亏比"] = summary["盈亏比"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "-")
            print()
            print(tabulate(summary, headers="keys", tablefmt="grid", showindex=False, numalign="right", stralign="right"))


if __name__ == "__main__":
    main()
