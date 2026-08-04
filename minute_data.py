#!/usr/bin/env python3
# minute_data.py
"""
个股分钟数据下载器。

根据 config.MINUTE_DATA_SOURCE 自动选择 Baostock 或 Tushare，
输出统一格式到 cache/minute/ 目录。

用法：
  python minute_data.py                          # 更新前200只股票的5/30/60分钟
  python minute_data.py --all                    # 更新全部股票池
  python minute_data.py --max 500 --freq 5,30    # 只更新5和30分钟
  python minute_data.py --days 60                # 只保留最近60天

集成到 main.py:
  from minute_data import update_stock_minute_cache
  update_stock_minute_cache(stock_df, max_stocks=0, minute_days=365)
"""

import os
import sys
import time
import argparse
import traceback
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import MINUTE_DATA_SOURCE
from data_sources import get_minute_source, MinuteDataSource
from data_sources.base import MINUTE_COLUMNS

STOCK_MINUTE_DIR = "cache/minute"
DEFAULT_FREQUENCIES = ["5", "30", "60"]
DEFAULT_MINUTE_DAYS = 365

# BaoStock 单线程即可（免费不限制），Tushare 可用多线程但有限速
WORKERS = 1 if MINUTE_DATA_SOURCE == "baostock" else 2


def _load_existing_cache(cache_file: str, days: int) -> pd.DataFrame:
    """加载本地已有的分钟缓存，截断到最近 days 天。"""
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["datetime"] >= cutoff].copy()
        return df.sort_values("datetime")
    except Exception:
        return pd.DataFrame()


def _save_cache(df: pd.DataFrame, cache_file: str):
    """保存分钟缓存到 CSV。"""
    df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def fetch_one_stock_minute(
    source: MinuteDataSource,
    code: str,
    frequency: str,
    days: int = DEFAULT_MINUTE_DAYS,
) -> dict:
    """
    拉取单只股票单个周期的分钟数据，与本地缓存合并。

    返回状态字典，与现有 calibrate_minute_cache_after_market 的格式兼容。
    """
    code = str(code).zfill(6)
    cache_file = os.path.join(STOCK_MINUTE_DIR, f"{code}_{frequency}m.csv")
    os.makedirs(STOCK_MINUTE_DIR, exist_ok=True)

    old_df = _load_existing_cache(cache_file, days)

    # 如果缓存已更新到最近，跳过
    if not old_df.empty:
        latest_dt = old_df["datetime"].max()
        now = datetime.now()
        # 当天 14:55 之后且缓存已覆盖到今天14:55，认为已是最新
        close_cutoff = datetime.strptime("14:55", "%H:%M").time()
        if latest_dt.date() == now.date() and latest_dt.time() >= close_cutoff:
            return {
                "success": True, "code": code, "frequency": frequency,
                "rows": len(old_df), "new_rows": 0,
                "update_mode": "skip", "latest_dt": latest_dt,
                "cache_file": cache_file, "error": "",
            }

    try:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        df_new = source.fetch_stock_minute(code, frequency, start_date, end_date)

        if df_new is None or df_new.empty:
            if not old_df.empty:
                return {
                    "success": True, "code": code, "frequency": frequency,
                    "rows": len(old_df), "new_rows": 0,
                    "update_mode": "no_new", "latest_dt": old_df["datetime"].max(),
                    "cache_file": cache_file, "error": "",
                }
            return {
                "success": False, "code": code, "frequency": frequency,
                "rows": 0, "new_rows": 0, "update_mode": "error",
                "latest_dt": None, "cache_file": cache_file,
                "error": "数据源返回为空",
            }

        # 合并去重
        if not old_df.empty:
            df = pd.concat([old_df, df_new], ignore_index=True)
        else:
            df = df_new

        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["datetime"] >= cutoff].copy()

        _save_cache(df, cache_file)

        old_count = len(old_df)
        new_count = len(df) - old_count if old_count > 0 else len(df)
        latest_after = df["datetime"].max()

        return {
            "success": True, "code": code, "frequency": frequency,
            "rows": len(df), "new_rows": max(0, new_count),
            "update_mode": "init" if old_df.empty else "incremental",
            "latest_dt": latest_after,
            "cache_file": cache_file, "error": "",
        }

    except Exception as e:
        return {
            "success": False, "code": code, "frequency": frequency,
            "rows": len(old_df) if not old_df.empty else 0, "new_rows": 0,
            "update_mode": "error", "latest_dt": None,
            "cache_file": cache_file, "error": str(e)[:200],
        }


def update_stock_minute_cache(
    stock_df: pd.DataFrame,
    max_stocks: int = 0,
    minute_days: int = DEFAULT_MINUTE_DAYS,
    frequencies: list[str] | None = None,
    max_workers: int | None = None,
    include_1m: bool = False,
) -> pd.DataFrame:
    """
    批量更新股票池分钟数据。

    Args:
        stock_df: 包含"代码"列的 DataFrame
        max_stocks: 0=全部, N=只更新前N只
        minute_days: 数据保留天数
        frequencies: 周期列表，默认 ["5", "30", "60"]
        max_workers: 并发线程数，BaoStock 自动设为1
        include_1m: 是否包含1分钟

    Returns:
        校准结果 DataFrame
    """
    if stock_df is None or stock_df.empty:
        print("分钟数据更新：股票池为空，跳过。")
        return pd.DataFrame()

    if frequencies is None:
        frequencies = list(DEFAULT_FREQUENCIES)
    if include_1m and "1" not in frequencies:
        frequencies = ["1"] + frequencies

    df = stock_df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    if max_stocks and max_stocks > 0:
        df = df.head(max_stocks).copy()

    total = len(df)
    source = get_minute_source()
    workers = max_workers if max_workers is not None else WORKERS
    workers = max(1, min(workers, total))

    print(f"\n{'='*70}")
    print(f"📊 个股分钟K线更新")
    print(f"{'='*70}")
    print(f"  数据源: {source.name()}")
    print(f"  股票数: {total} 只")
    print(f"  周期: {', '.join(f + 'm' for f in frequencies)}")
    print(f"  范围: 最近 {minute_days} 天")
    print(f"  并发: {workers} 线程")
    print(f"  缓存: {STOCK_MINUTE_DIR}/")

    result_rows = []
    success_count = 0
    failed_count = 0
    start_time = time.time()
    lock = Lock()
    finished = [0]

    codes = [(str(row["代码"]).zfill(6)) for _, row in df.iterrows()]

    def _update_one(code: str):
        nonlocal success_count, failed_count
        details = []
        for freq in frequencies:
            r = fetch_one_stock_minute(source, code, freq, minute_days)
            details.append(r)
            if r["success"]:
                success_count += 1
            else:
                failed_count += 1

        with lock:
            finished[0] += 1
            i = finished[0]
            elapsed = time.time() - start_time
            remain = (total - i) * elapsed / i if i > 0 else 0
            print(
                f"  进度: {i}/{total} | {code} | "
                f"成功: {success_count} | 失败: {failed_count} | "
                f"剩余: {remain/60:.1f}min",
                end="\r", flush=True,
            )

        for detail in details:
            result_rows.append({
                "代码": detail.get("code", code),
                "周期": f"{detail.get('frequency', '')}m",
                "是否成功": detail.get("success"),
                "数据行数": detail.get("rows", 0) or 0,
                "新增行数": detail.get("new_rows", 0) or 0,
                "更新方式": detail.get("update_mode", ""),
                "最新时间": str(detail.get("latest_dt", "")) if detail.get("latest_dt") is not None else "",
                "缓存文件": detail.get("cache_file", ""),
                "错误信息": detail.get("error", ""),
            })

    if workers == 1:
        for code in codes:
            _update_one(code)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(_update_one, codes))

    print()
    elapsed = time.time() - start_time
    result_df = pd.DataFrame(result_rows)

    print(f"✅ 个股分钟数据更新完成，耗时 {elapsed/60:.1f} 分钟")
    print(f"   成功: {success_count} 周期 | 失败: {failed_count} 周期")
    return result_df


def main():
    parser = argparse.ArgumentParser(description="个股分钟数据下载")
    parser.add_argument("--all", action="store_true", help="更新全部股票池")
    parser.add_argument("--max", type=int, default=200, help="最多更新N只, 默认200")
    parser.add_argument("--days", type=int, default=DEFAULT_MINUTE_DAYS, help="保留天数")
    parser.add_argument("--freq", type=str, default="5,30,60", help="周期, 逗号分隔")
    parser.add_argument("--include-1m", action="store_true", help="包含1分钟")
    args = parser.parse_args()

    pool_file = "output/a_stock_selected.xlsx"
    if not os.path.exists(pool_file):
        print(f"❌ 股票池文件不存在: {pool_file}")
        sys.exit(1)

    stock_df = pd.read_excel(pool_file, dtype={"代码": str})

    max_stocks = 0 if args.all else args.max
    freqs = [f.strip() for f in args.freq.split(",")]

    update_stock_minute_cache(
        stock_df,
        max_stocks=max_stocks,
        minute_days=args.days,
        frequencies=freqs,
        include_1m=args.include_1m,
    )


if __name__ == "__main__":
    main()
