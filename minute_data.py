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
DEFAULT_FREQUENCIES = ["30", "60"]  # 缠论/背离只用 30m 和 60m，5m 已废弃
DEFAULT_MINUTE_DAYS = 60

# BaoStock/Tushare 都用单线程 + 延时，避免连接冲突和限流
WORKERS = 1


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
        close_cutoff = datetime.strptime("14:55", "%H:%M").time()
        market_open = datetime.strptime("09:30", "%H:%M").time()

        # 情况1: 当天收盘后 → 缓存已覆盖到今天14:55，跳过
        if latest_dt.date() == now.date() and latest_dt.time() >= close_cutoff:
            return {
                "success": True, "code": code, "frequency": frequency,
                "rows": len(old_df), "new_rows": 0,
                "update_mode": "skip", "latest_dt": latest_dt,
                "cache_file": cache_file, "error": "",
            }

        # 情况2: 盘前/盘中（今天还未收盘），缓存是昨天的 → 跳过
        if now.time() < close_cutoff and (now.date() - latest_dt.date()).days <= 1:
            return {
                "success": True, "code": code, "frequency": frequency,
                "rows": len(old_df), "new_rows": 0,
                "update_mode": "skip_premarket", "latest_dt": latest_dt,
                "cache_file": cache_file, "error": "",
            }

    try:
        # 增量更新：如果已有缓存，只拉最新日期之后的数据
        if not old_df.empty:
            last_dt = old_df["datetime"].max()
            start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        # 根据 stk_mins 单次 8000 行限制，自动分片（留 10% 余量）
        _BARS_PER_DAY = {"1": 240, "5": 48, "15": 16, "30": 8, "60": 4}
        _SAFE_ROWS = 7200  # 8000 × 0.9
        bars = _BARS_PER_DAY.get(frequency, 48)
        chunk_days = max(1, _SAFE_ROWS // bars)

        # 计算实际需要拉取的天数（增量更新可能只需1天）
        actual_start = datetime.strptime(start_date, "%Y-%m-%d")
        actual_days = (datetime.now() - actual_start).days + 1

        if actual_days > chunk_days:
            df_new_list = []
            chunk_start = actual_start
            while chunk_start < datetime.now():
                chunk_end = min(chunk_start + timedelta(days=chunk_days), datetime.now())
                s = chunk_start.strftime("%Y-%m-%d")
                e = chunk_end.strftime("%Y-%m-%d")
                chunk_df = source.fetch_stock_minute(code, frequency, s, e)
                if chunk_df is not None and not chunk_df.empty:
                    df_new_list.append(chunk_df)
                chunk_start = chunk_end
                if chunk_start < datetime.now() and MINUTE_DATA_SOURCE == "tushare":
                    time.sleep(0.3)
            df_new = pd.concat(df_new_list, ignore_index=True) if df_new_list else pd.DataFrame()
        else:
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
        for fi, freq in enumerate(frequencies):
            # Tushare 需要延时避免限流，BaoStock 不需要
            if fi > 0 and MINUTE_DATA_SOURCE == "tushare":
                time.sleep(0.3)
            r = fetch_one_stock_minute(source, code, freq, minute_days)
            details.append(r)
            if r["success"]:
                success_count += 1
            else:
                failed_count += 1

        # 收集失败详情
        failed_details = [d for d in details if not d["success"]]

        with lock:
            finished[0] += 1
            i = finished[0]
            elapsed = time.time() - start_time
            remain = (total - i) * elapsed / i if i > 0 else 0
            print(
                f"  进度: {i}/{total} | {code} | "
                f"成功: {success_count} | 失败: {failed_count} | "
                f"剩余: {remain/60:.1f}min" + " " * 20,
                end="\r", flush=True,
            )

        # 即时打印失败信息
        if failed_details:
            lines = []
            for fd in failed_details:
                freq_label = f"{fd.get('frequency', '')}m"
                err = fd.get("error", "未知错误")
                lines.append(f"  ❌ {code} {freq_label}: {err}")
            # 先换行再打印，避免覆盖进度条
            print()
            for line in lines:
                print(line)

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
        for ci, code in enumerate(codes):
            if ci > 0 and MINUTE_DATA_SOURCE == "tushare":
                time.sleep(0.2)  # Tushare 需要股票间延时
            _update_one(code)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(_update_one, codes))

    print()

    # ================================================================
    # 第一轮结束后，重试所有失败的 (代码, 周期) 组合
    # ================================================================
    failed_pairs = [
        (r["代码"], r["周期"].replace("m", ""))
        for r in result_rows
        if not r["是否成功"]
    ]

    if failed_pairs:
        print(f"\n🔄 第一轮失败 {len(failed_pairs)} 条，开始重试...")
        retry_success = 0
        retry_fail = 0

        for ri, (code, freq) in enumerate(failed_pairs):
            if ri > 0 and MINUTE_DATA_SOURCE == "tushare":
                time.sleep(0.5)  # Tushare 重试间隔
            r = fetch_one_stock_minute(source, code, freq, minute_days)
            # 更新 result_rows 中对应的记录
            for i, row in enumerate(result_rows):
                if row["代码"] == code and row["周期"] == f"{freq}m":
                    result_rows[i] = {
                        "代码": r.get("code", code),
                        "周期": f"{r.get('frequency', '')}m",
                        "是否成功": r.get("success"),
                        "数据行数": r.get("rows", 0) or 0,
                        "新增行数": r.get("new_rows", 0) or 0,
                        "更新方式": r.get("update_mode", ""),
                        "最新时间": str(r.get("latest_dt", "")) if r.get("latest_dt") is not None else "",
                        "缓存文件": r.get("cache_file", ""),
                        "错误信息": r.get("error", ""),
                    }
                    break

            if r["success"]:
                retry_success += 1
                print(f"  ✅ 重试成功: {code} {freq}m")
            else:
                retry_fail += 1
                print(f"  ❌ 重试仍失败: {code} {freq}m | {r.get('error', '?')}")

        # 更新计数
        success_count += retry_success
        failed_count = failed_count - retry_success + retry_fail
        print(f"  重试结果: 成功 {retry_success}, 仍失败 {retry_fail}")

    elapsed = time.time() - start_time
    result_df = pd.DataFrame(result_rows)

    print(f"✅ 个股分钟数据更新完成，耗时 {elapsed/60:.1f} 分钟")
    print(f"   成功: {success_count} 周期 | 失败: {failed_count} 周期")

    # 打印失败汇总
    if not result_df.empty:
        failed_df = result_df[result_df["是否成功"] == False]
        if not failed_df.empty:
            print(f"\n{'='*70}")
            print(f"⚠️ 失败明细 ({len(failed_df)} 条):")
            print(f"{'='*70}")
            for _, row in failed_df.iterrows():
                print(f"  {row['代码']} {row['周期']}: {row['错误信息']}")

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
