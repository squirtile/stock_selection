#!/usr/bin/env python
"""Generate full A-share code-name mapping from data_loader.py / Tushare stock_basic.

用法：
    python test/update_stock_name_map.py
    python test/update_stock_name_map.py --output cache/stock_name_map.csv
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_loader import get_tushare_pro, load_stock_basic


def normalize_symbol(value) -> str:
    """Normalize symbol/ts_code to 6-digit stock code."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""

    parts = text.replace("_", ".").replace("-", ".").split(".")
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        if len(digits) >= 6:
            return digits[-6:]

    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else text.zfill(6)[-6:]


def build_stock_name_table() -> pd.DataFrame:
    """Fetch listed A shares and return a clean mapping table."""
    print("正在初始化 Tushare，并拉取 stock_basic 全市场基础信息...")
    pro = get_tushare_pro()
    basic_df = load_stock_basic(pro)

    if basic_df is None or basic_df.empty:
        raise RuntimeError("stock_basic 返回为空，请检查 Tushare Token / 网络 / 代理地址。")

    result = pd.DataFrame()

    if "symbol" in basic_df.columns:
        result["代码"] = basic_df["symbol"].apply(normalize_symbol)
    else:
        result["代码"] = basic_df["ts_code"].apply(normalize_symbol)

    result["名称"] = basic_df["name"].astype(str).str.strip()

    # keep_cols = {
    #     "ts_code": "ts_code",
    #     "area": "地区",
    #     "industry": "行业",
    #     "market": "市场",
    #     "list_date": "上市日期",
    # }
    # for src, dst in keep_cols.items():
    #     if src in basic_df.columns:
    #         result[dst] = basic_df[src]

    # result["更新时间"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    result = result.dropna(subset=["代码", "名称"])
    result = result[result["代码"].astype(str).str.len() == 6]
    result = result.drop_duplicates(subset=["代码"], keep="first")
    result = result.sort_values("代码").reset_index(drop=True)

    return result


def main():
    parser = argparse.ArgumentParser(description="生成全市场股票代码-名称映射表")
    parser.add_argument("--output", default=os.path.join("cache", "stock_name_map.csv"), help="输出 CSV 路径")
    parser.add_argument("--no-xlsx", action="store_true", help="不额外输出 xlsx 文件")
    parser.add_argument("--preview", type=int, default=10, help="打印前 N 行预览")
    args = parser.parse_args()

    table = build_stock_name_table()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n代码名称映射 CSV 已保存：{output_path}")

    if not args.no_xlsx:
        xlsx_path = output_path.with_suffix(".xlsx")
        table.to_excel(xlsx_path, index=False)
        print(f"代码名称映射 Excel 已保存：{xlsx_path}")

    print(f"\n共保存：{len(table)} 条")
    if args.preview > 0:
        print("\n预览：")
        print(table.head(args.preview).to_string(index=False))


if __name__ == "__main__":
    main()
