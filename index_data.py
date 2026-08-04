#!/usr/bin/env python3
# index_data.py
"""
指数数据下载器。

拉取四大指数（上证、深证、创业板、科创50）的日线和分钟数据，
存入 cache/index/ 目录，与个股缓存完全隔离。

目录结构：
    cache/index/
    ├── daily/
    │   ├── SH000001.csv    # 上证指数
    │   ├── SZ399001.csv    # 深证成指
    │   ├── SZ399006.csv    # 创业板指
    │   └── SH000688.csv    # 科创50
    └── minute/
        ├── SH000001_5m.csv
        ├── SH000001_30m.csv
        ├── SH000001_60m.csv
        └── ...

用法：
  python index_data.py                          # 更新指数日线+分钟
  python index_data.py --daily-only             # 只更新日线
  python index_data.py --days 365               # 保留365天

集成到 main.py:
  from index_data import update_index_cache
  update_index_cache(days=365)
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_sources import get_index_source, IndexDataSource
from data_sources.base import MINUTE_COLUMNS, DAILY_COLUMNS

INDEX_CACHE_DIR = "cache/index"
INDEX_DAILY_DIR = os.path.join(INDEX_CACHE_DIR, "daily")
INDEX_MINUTE_DIR = os.path.join(INDEX_CACHE_DIR, "minute")
DEFAULT_INDEX_DAYS = 365
INDEX_MINUTE_FREQS = ["5", "30", "60"]


def _load_cache(cache_file: str, days: int, time_col: str = "datetime") -> pd.DataFrame:
    """加载本地缓存。"""
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
        df = df.dropna(subset=[time_col]).drop_duplicates(subset=[time_col], keep="last")
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df[time_col] >= cutoff].copy()
        return df.sort_values(time_col)
    except Exception:
        return pd.DataFrame()


def _save_cache(df: pd.DataFrame, cache_file: str, time_col: str = "datetime"):
    """保存缓存。"""
    df = df.sort_values(time_col).drop_duplicates(subset=[time_col], keep="last")
    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def update_index_daily(
    source: IndexDataSource | None = None,
    days: int = DEFAULT_INDEX_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    更新四大指数日线数据。

    Returns:
        {index_key: DataFrame} 每个指数的日线数据
    """
    if source is None:
        source = get_index_source()

    os.makedirs(INDEX_DAILY_DIR, exist_ok=True)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    results = {}

    print(f"\n{'='*70}")
    print(f"📊 指数日线更新（数据源: {source.name()}）")
    print(f"{'='*70}")

    for index_key, info in IndexDataSource.INDEX_MAP.items():
        name = info["name"]
        cache_file = os.path.join(INDEX_DAILY_DIR, f"{index_key}.csv")

        old_df = _load_cache(cache_file, days, time_col="date")

        # 检查是否已更新到最近
        if not old_df.empty:
            latest_date = pd.to_datetime(old_df["date"].max(), errors="coerce")
            today = datetime.now().date()
            if latest_date.date() == today:
                print(f"  ✅ {name} ({index_key}): 已是最新 ({len(old_df)} 行)")
                results[index_key] = old_df
                continue

        try:
            df_new = source.fetch_index_daily(index_key, start_date, end_date)

            if df_new is None or df_new.empty:
                if not old_df.empty:
                    print(f"  ⚠️  {name} ({index_key}): 无新数据, 保留旧缓存 ({len(old_df)} 行)")
                    results[index_key] = old_df
                else:
                    print(f"  ❌ {name} ({index_key}): 无数据")
                continue

            # 合并去重
            if not old_df.empty:
                df = pd.concat([old_df, df_new], ignore_index=True)
            else:
                df = df_new

            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")
            cutoff = datetime.now() - timedelta(days=days)
            df = df[df["date"] >= cutoff].copy()

            _save_cache(df, cache_file, time_col="date")
            print(f"  ✅ {name} ({index_key}): {len(df)} 行 ({len(old_df)}→{len(df)})")
            results[index_key] = df

        except Exception as e:
            err = str(e)[:120]
            print(f"  ❌ {name} ({index_key}): {err}")
            if not old_df.empty:
                results[index_key] = old_df

    return results


def update_index_minute(
    source: IndexDataSource | None = None,
    days: int = DEFAULT_INDEX_DAYS,
    frequencies: list[str] | None = None,
) -> dict:
    """
    更新四大指数分钟数据。

    注意：BaoStock 不支持指数分钟线，此功能仅在数据源为 Tushare 且已开通 idx_mins 权限时可用。

    Returns:
        {index_key: {freq: DataFrame}}
    """
    if source is None:
        source = get_index_source()

    if not source.supports_index_minute():
        print(f"\n⚠️  当前数据源 ({source.name()}) 不支持指数分钟线，跳过。")
        print("   如需指数分钟数据，请将 INDEX_DATA_SOURCE 设为 'tushare' 并开通 idx_mins 权限。")
        return {}

    os.makedirs(INDEX_MINUTE_DIR, exist_ok=True)
    if frequencies is None:
        frequencies = INDEX_MINUTE_FREQS

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    results = {}

    print(f"\n{'='*70}")
    print(f"📊 指数分钟线更新（数据源: {source.name()}）")
    print(f"{'='*70}")

    for index_key, info in IndexDataSource.INDEX_MAP.items():
        name = info["name"]
        results[index_key] = {}

        for freq in frequencies:
            cache_file = os.path.join(INDEX_MINUTE_DIR, f"{index_key}_{freq}m.csv")
            old_df = _load_cache(cache_file, days, time_col="datetime")

            if not old_df.empty:
                latest_dt = old_df["datetime"].max()
                today = datetime.now().date()
                if latest_dt.date() == today:
                    print(f"  ✅ {name} {freq}m: 已是最新 ({len(old_df)} 行)")
                    results[index_key][freq] = old_df
                    continue

            try:
                df_new = source.fetch_index_minute(index_key, freq, start_date, end_date)

                if df_new is None or df_new.empty:
                    if not old_df.empty:
                        results[index_key][freq] = old_df
                    continue

                if not old_df.empty:
                    df = pd.concat([old_df, df_new], ignore_index=True)
                else:
                    df = df_new

                df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
                df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
                cutoff = datetime.now() - timedelta(days=days)
                df = df[df["datetime"] >= cutoff].copy()

                _save_cache(df, cache_file, time_col="datetime")
                new_count = max(0, len(df) - len(old_df))
                print(f"  ✅ {name} {freq}m: {len(df)} 行 (+{new_count})")
                results[index_key][freq] = df

            except Exception as e:
                err = str(e)[:120]
                print(f"  ❌ {name} {freq}m: {err}")
                if not old_df.empty:
                    results[index_key][freq] = old_df

    return results


def update_index_cache(
    days: int = DEFAULT_INDEX_DAYS,
    include_minute: bool = True,
) -> dict:
    """
    一键更新所有指数数据（日线 + 可选分钟）。

    这是供 main.py / daily_report.py 调用的统一入口。
    """
    source = get_index_source()

    print(f"\n{'='*70}")
    print(f"📈 指数数据更新（数据源: {source.name()}）")
    print(f"{'='*70}")

    daily = update_index_daily(source, days=days)

    minute = {}
    if include_minute:
        minute = update_index_minute(source, days=days)

    return {"daily": daily, "minute": minute}


def main():
    parser = argparse.ArgumentParser(description="指数数据下载")
    parser.add_argument("--daily-only", action="store_true", help="只更新日线")
    parser.add_argument("--days", type=int, default=DEFAULT_INDEX_DAYS, help="保留天数")
    parser.add_argument("--freq", type=str, default="5,30,60", help="分钟周期")
    args = parser.parse_args()

    source = get_index_source()

    update_index_daily(source, days=args.days)

    if not args.daily_only:
        freqs = [f.strip() for f in args.freq.split(",")]
        update_index_minute(source, days=args.days, frequencies=freqs)

    print("\n✅ 指数数据更新完成。")


if __name__ == "__main__":
    main()
