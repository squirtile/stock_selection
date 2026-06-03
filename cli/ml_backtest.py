#!/usr/bin/env python
"""Backtest trained ML model."""

import argparse
import os
import sys
import pandas as pd
from tabulate import tabulate

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import load_candidate_codes
from ml_engine.ml_classifier import MLPatternModel
from ml_engine.eval import compute_ml_backtest, summarize_ml_backtest, summarize_ml_by_hold_days


def parse_days(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(',') if x.strip()]




def normalize_code(code) -> str:
    """统一股票代码为 6 位，兼容 600000.SH / 000001.SZ / 600000。"""
    if pd.isna(code):
        return ""
    text = str(code).strip()
    if not text:
        return ""
    text = text.split(".")[0]
    return text.zfill(6)[-6:]


def build_name_map_from_file(file_path: str) -> dict[str, str]:
    """从候选股票文件中读取 代码 -> 名称 映射；只读明确文件，不扫描目录。"""
    if not file_path or not os.path.exists(file_path):
        return {}

    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path, dtype=str)
        elif ext == ".csv":
            df = pd.read_csv(file_path, dtype=str)
        else:
            return {}
    except Exception as exc:
        print(f"读取股票名称文件失败，跳过名称显示：{file_path}，原因：{exc}")
        return {}

    code_col = next((c for c in ["代码", "code", "ts_code", "证券代码"] if c in df.columns), None)
    name_col = next((c for c in ["名称", "name", "股票名称", "证券简称"] if c in df.columns), None)
    if not code_col or not name_col:
        return {}

    name_map = {}
    for _, row in df[[code_col, name_col]].dropna(subset=[code_col]).iterrows():
        code = normalize_code(row[code_col])
        name = "" if pd.isna(row[name_col]) else str(row[name_col]).strip()
        if code and name:
            name_map[code] = name
    return name_map


def build_name_map(args) -> dict[str, str]:
    """按当前回测股票来源读取名称映射，不改变原有回测逻辑。"""
    candidate_paths = []

    if args.candidate_file:
        candidate_paths.append(args.candidate_file)

    if args.use_selected_file:
        candidate_paths.extend([
            os.path.join("output", "a_stock_selected.xlsx"),
            os.path.join("output", "a_stock_selected.csv"),
        ])

    # 常见股票池文件兜底，只读明确文件，不递归扫描，避免误读大文件卡住。
    candidate_paths.extend([
        os.path.join("output", "a_stock_pool.xlsx"),
        os.path.join("output", "a_stock_pool.csv"),
        os.path.join("output", "stock_pool.xlsx"),
        os.path.join("output", "stock_pool.csv"),
    ])

    name_map = {}
    seen = set()
    for path in candidate_paths:
        if path in seen:
            continue
        seen.add(path)
        name_map.update(build_name_map_from_file(path))
    return name_map


def add_name_column(df: pd.DataFrame, name_map: dict[str, str]) -> pd.DataFrame:
    """只给展示/导出用的 DataFrame 增加名称列，不影响回测计算。"""
    if df is None or df.empty or "代码" not in df.columns or "名称" in df.columns:
        return df

    out = df.copy()
    out.insert(1, "名称", out["代码"].map(lambda x: name_map.get(normalize_code(x), "")))
    return out


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
    parser.add_argument("--include-train-templates", action="store_true", help="回测时不排除训练模板股")
    args = parser.parse_args()

    model = MLPatternModel.load(args.model)

    codes = load_candidate_codes(args.candidate_file or None, default_selected=args.use_selected_file)
    name_map = build_name_map(args)
    if name_map:
        print(f"已加载股票名称映射：{len(name_map)} 条，回测明细打印将显示名称。")


    # 默认自动排除训练模板股，避免训练股参与回测导致结果偏乐观
    train_templates = [str(c).strip().split(".")[0].zfill(6) for c in getattr(model, "template_codes", []) or []]

    if train_templates and not args.include_train_templates:
        before_count = len(codes)
        exclude_set = set(train_templates)
        codes = [str(c).strip().split(".")[0].zfill(6) for c in codes]
        codes = [c for c in codes if c not in exclude_set]
        print(f"已自动排除训练模板股：{','.join(train_templates)}")
        print(f"回测股票池：{before_count} -> {len(codes)}")

    elif train_templates and args.include_train_templates:
        print(f"本次不排除训练模板股：{','.join(train_templates)}")

    else:
        print("当前模型文件未记录训练模板股，无法自动排除。建议重新训练生成新版 pkl。")

    if args.max_stocks:
        codes = codes[:args.max_stocks]

    print(f"开始 ML 回测：股票数 {len(codes)}，阈值 {args.threshold}，持有天数 {args.hold_days}", flush=True)

    trades = compute_ml_backtest(
        model,
        codes,
        parse_days(args.hold_days),
        args.threshold,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
    )

    print("ML 回测计算完成，开始汇总结果...", flush=True)
    if trades.empty:
        print("无交易信号，可降低 --threshold")
        return
    summary = summarize_ml_by_hold_days(trades)
    overall = summarize_ml_backtest(trades)
    display_trades = add_name_column(trades, name_map)
    # print(summary.to_string(index=False))
    print(tabulate(summary, headers="keys", tablefmt="pretty", showindex=False))

    print("\n最大单笔收益明细：")
    best_trades = (
        display_trades.sort_values("收益率%", ascending=False)
        .groupby("持有天数")
        .head(1)
        .sort_values("持有天数")
    )
    print(tabulate(best_trades, headers="keys", tablefmt="pretty", showindex=False))

    print("\n最大单笔亏损明细：")
    worst_trades = (
        display_trades.sort_values("收益率%", ascending=True)
        .groupby("持有天数")
        .head(1)
        .sort_values("持有天数")
    )
    print(tabulate(worst_trades, headers="keys", tablefmt="pretty", showindex=False))

    if not args.output:
        args.output = os.path.join("output/ml_similarity", f"ml_backtest_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="按持有期统计", index=False)
        overall.to_excel(writer, sheet_name="总体统计", index=False)
        display_trades.to_excel(writer, sheet_name="交易明细", index=False)
        best_trades.to_excel(writer, sheet_name="最大收益明细", index=False)
        worst_trades.to_excel(writer, sheet_name="最大亏损明细", index=False)
    print(f"报告已保存: {args.output}")


if __name__ == "__main__":
    main()
