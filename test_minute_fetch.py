#!/usr/bin/env python3
# test_minute_fetch.py
"""
轻量级分钟数据拉取测试脚本。

直接拉取股票池的分钟K线，不依赖 report 流程，速度快。
适合快速验证数据源连通性、排查失败股票。

用法：
  python test_minute_fetch.py                          # 默认前10只, 5/30/60m, 60天
  python test_minute_fetch.py --max 50 --days 365      # 前50只, 365天
  python test_minute_fetch.py --codes 000001,600519     # 指定股票代码
  python test_minute_fetch.py --all --freq 5,30         # 全部股票, 只拉5/30m
  python test_minute_fetch.py --failed-only             # 只重试上次失败的股票
"""

import os
import sys
import time
import argparse
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import MINUTE_DATA_SOURCE
from data_sources import get_minute_source, MinuteDataSource

POOL_FILE = "output/a_stock_selected.xlsx"
FAILED_LOG = "output/minute_fetch_failed.csv"

# stk_mins 单次最大 8000 行
MAX_ROWS_PER_REQUEST = 8000
# 各周期每日K线数
BARS_PER_DAY = {"1": 240, "5": 48, "15": 16, "30": 8, "60": 4}
# 留 10% 余量，实际每片行数上限
SAFE_ROWS = int(MAX_ROWS_PER_REQUEST * 0.9)  # 7200

STOCK_MINUTE_DIR = "cache/minute"


def _calc_chunk_days(frequency: str) -> int:
    """根据周期计算每次请求的最大天数（留 10% 余量避免超 8000 行）。"""
    bars = BARS_PER_DAY.get(frequency, 48)
    return max(1, SAFE_ROWS // bars)


def fetch_minute_chunked(
    source: MinuteDataSource,
    code: str,
    frequency: str,
    days: int = 60,
    sleep: float = 0.5,
) -> dict:
    """
    分片拉取分钟数据，自动遵守 stk_mins 单次 8000 行限制。

    Returns:
        {"success": bool, "code": str, "frequency": str, "行数": int, "错误": str}
    """
    import os
    from datetime import datetime, timedelta
    import pandas as pd

    code = str(code).zfill(6)
    cache_file = os.path.join(STOCK_MINUTE_DIR, f"{code}_{frequency}m.csv")
    os.makedirs(STOCK_MINUTE_DIR, exist_ok=True)

    # 加载已有缓存
    old_df = pd.DataFrame()
    if os.path.exists(cache_file):
        try:
            old_df = pd.read_csv(cache_file, dtype={"代码": str})
            old_df["datetime"] = pd.to_datetime(old_df["datetime"], errors="coerce")
            old_df = old_df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
            cutoff = datetime.now() - timedelta(days=days)
            old_df = old_df[old_df["datetime"] >= cutoff]
        except Exception:
            old_df = pd.DataFrame()

    # 检查是否已最新
    if not old_df.empty:
        latest_dt = old_df["datetime"].max()
        now = datetime.now()
        close_cutoff = datetime.strptime("14:55", "%H:%M").time()
        if latest_dt.date() == now.date() and latest_dt.time() >= close_cutoff:
            return {"success": True, "code": code, "frequency": frequency,
                    "行数": len(old_df), "状态": "skip", "错误": ""}

    try:
        chunk_days = _calc_chunk_days(frequency)
        now = datetime.now()
        start_dt = now - timedelta(days=days)

        all_chunks = []
        chunk_start = start_dt
        chunk_count = 0

        while chunk_start < now:
            chunk_end = min(chunk_start + timedelta(days=chunk_days), now)
            s = chunk_start.strftime("%Y-%m-%d")
            e = chunk_end.strftime("%Y-%m-%d")

            chunk_df = source.fetch_stock_minute(code, frequency, s, e)
            chunk_count += 1

            if chunk_df is not None and not chunk_df.empty:
                all_chunks.append(chunk_df)

            chunk_start = chunk_end
            if chunk_start < now:
                # 分片间强制至少 0.3s，避免触发限流
                time.sleep(max(sleep, 0.3))

        if all_chunks:
            df_new = pd.concat(all_chunks, ignore_index=True)
        else:
            df_new = pd.DataFrame()

        if df_new.empty:
            if not old_df.empty:
                return {"success": True, "code": code, "frequency": frequency,
                        "行数": len(old_df), "状态": "no_new", "错误": ""}
            return {"success": False, "code": code, "frequency": frequency,
                    "行数": 0, "状态": "empty", "错误": "数据源返回为空"}

        # 合并去重
        if not old_df.empty:
            df = pd.concat([old_df, df_new], ignore_index=True)
        else:
            df = df_new

        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"]).drop_duplicates(subset=["datetime"], keep="last")
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["datetime"] >= cutoff].copy()
        df = df.sort_values("datetime")

        # 保存
        df.to_csv(cache_file, index=False, encoding="utf-8-sig")

        return {"success": True, "code": code, "frequency": frequency,
                "行数": len(df), "状态": "init" if old_df.empty else "incremental",
                "错误": ""}

    except Exception as e:
        return {"success": False, "code": code, "frequency": frequency,
                "行数": len(old_df) if not old_df.empty else 0,
                "状态": "error", "错误": str(e)[:200]}


def load_pool(max_stocks: int = 0, codes: list[str] | None = None) -> pd.DataFrame:
    """加载股票池"""
    if codes:
        return pd.DataFrame({"代码": [str(c).zfill(6) for c in codes]})

    if not os.path.exists(POOL_FILE):
        print(f"❌ 股票池文件不存在: {POOL_FILE}")
        sys.exit(1)

    df = pd.read_excel(POOL_FILE, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    if max_stocks and max_stocks > 0:
        df = df.head(max_stocks)
    return df


def load_failed_stocks() -> pd.DataFrame:
    """加载上次失败的股票列表"""
    if not os.path.exists(FAILED_LOG):
        print(f"❌ 失败日志不存在: {FAILED_LOG}")
        sys.exit(1)
    df = pd.read_csv(FAILED_LOG, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)
    codes = df["代码"].unique().tolist()
    print(f"📋 从失败日志加载 {len(codes)} 只股票重试")
    return pd.DataFrame({"代码": codes})


def main():
    parser = argparse.ArgumentParser(description="轻量级分钟数据拉取测试")
    parser.add_argument("--max", type=int, default=10, help="最多拉取N只, 默认10")
    parser.add_argument("--all", action="store_true", help="拉取全部股票池")
    parser.add_argument("--codes", type=str, help="指定股票代码, 逗号分隔")
    parser.add_argument("--days", type=int, default=60, help="数据天数, 默认60")
    parser.add_argument("--freq", type=str, default="30,60", help="周期, 逗号分隔, 默认5,30,60")
    parser.add_argument("--sleep", type=float, default=0.5, help="每次API请求间隔秒数, 默认0.5, 设0不等待")
    parser.add_argument("--failed-only", action="store_true", help="只重试上次失败的股票")
    args = parser.parse_args()

    # 加载股票池
    if args.failed_only:
        stock_df = load_failed_stocks()
    elif args.codes:
        codes_list = [c.strip() for c in args.codes.split(",")]
        stock_df = load_pool(codes=codes_list)
    else:
        max_n = 0 if args.all else args.max
        stock_df = load_pool(max_stocks=max_n)

    freqs = [f.strip() for f in args.freq.split(",")]
    source = get_minute_source()
    total = len(stock_df)

    print(f"\n{'='*60}")
    print(f"🧪 分钟数据拉取测试")
    print(f"{'='*60}")
    print(f"  数据源: {source.name()} ({MINUTE_DATA_SOURCE})")
    print(f"  股票数: {total} 只")
    print(f"  周期: {', '.join(f + 'm' for f in freqs)}")
    print(f"  天数: {args.days} 天")
    print(f"  API限制: 单次≤{MAX_ROWS_PER_REQUEST}行")
    print(f"  分片策略:")
    for f in freqs:
        cd = _calc_chunk_days(f)
        bars = BARS_PER_DAY.get(f, 48)
        print(f"    {f}m: {bars}根/天 → 每片{cd}天 ({cd * bars}行)")
    print(f"  请求间隔: {args.sleep}s")
    print(f"  缓存: {STOCK_MINUTE_DIR}/")
    print()

    results = []
    failed_codes = set()
    start_time = time.time()

    for idx, (_, row) in enumerate(stock_df.iterrows()):
        code = str(row["代码"]).zfill(6)
        stock_failed = False

        for fi, freq in enumerate(freqs):
            if fi > 0 and args.sleep > 0:
                time.sleep(args.sleep)

            r = fetch_minute_chunked(source, code, freq, days=args.days, sleep=args.sleep)
            results.append(r)

            status = "✅" if r["success"] else "❌"
            rows_info = f"{r.get('行数', 0)}行"
            state = r.get("状态", "?")

            if r["success"]:
                print(f"  [{idx+1:4d}/{total}] {status} {code} {freq}m | {rows_info} | {state}")
            else:
                err = r.get("错误", "未知")
                print(f"  [{idx+1:4d}/{total}] {status} {code} {freq}m | {err}")
                stock_failed = True

        if stock_failed:
            failed_codes.add(code)

    elapsed = time.time() - start_time

    # ================================================================
    # 重试失败的
    # ================================================================
    failed_results = [r for r in results if not r["success"]]
    if failed_results:
        print(f"\n🔄 第一轮失败 {len(failed_results)} 条，开始重试...")
        retry_ok = 0

        for ri, fr in enumerate(failed_results):
            # 重试间隔：至少 0.5s，正常用 sleep×2，"请求过快"时额外加 2s 冷却
            retry_sleep = max(0.5, args.sleep * 2)
            err_msg = fr.get("错误", "")
            if "过快" in err_msg or "频率" in err_msg:
                retry_sleep += 2.0
            if ri > 0:
                time.sleep(retry_sleep)
            r = fetch_minute_chunked(source, code, freq, days=args.days, sleep=args.sleep)

            # 替换原结果
            for i, old in enumerate(results):
                if old["code"] == code and old.get("frequency") == freq:
                    results[i] = r
                    break

            if r["success"]:
                retry_ok += 1
                print(f"  ✅ 重试成功: {code} {freq}m | {r.get('行数', 0)}行 | {r.get('状态', '?')}")
            else:
                print(f"  ❌ 重试仍失败: {code} {freq}m | {r.get('错误', '?')}")

        print(f"  重试结果: 成功 {retry_ok}, 仍失败 {len(failed_results) - retry_ok}")

    # 汇总
    total_ops = len(results)
    success_ops = sum(1 for r in results if r["success"])
    failed_ops = total_ops - success_ops

    # 重新统计失败股票
    failed_codes = set(r["code"] for r in results if not r["success"])

    print(f"\n{'='*60}")
    print(f"📊 测试结果汇总")
    print(f"{'='*60}")
    print(f"  总操作: {total_ops} (={total}只 × {len(freqs)}周期)")
    print(f"  成功: {success_ops}")
    print(f"  失败: {failed_ops}")
    print(f"  失败股票: {len(failed_codes)} 只")
    print(f"  耗时: {elapsed:.1f} 秒")

    if failed_codes:
        print(f"\n⚠️ 失败股票列表:")
        for c in sorted(failed_codes):
            stock_fails = [r for r in results if r["code"] == c and not r["success"]]
            for f in stock_fails:
                print(f"  {c} {f.get('frequency', '')}m: {f.get('错误', '?')}")

        # 保存失败日志
        failed_df = pd.DataFrame([
            {"代码": r["code"], "周期": f"{r.get('frequency', '')}m",
             "错误信息": r.get("错误", ""), "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            for r in results if not r["success"]
        ])
        os.makedirs("output", exist_ok=True)
        failed_df.to_csv(FAILED_LOG, index=False, encoding="utf-8-sig")
        print(f"\n💾 失败日志已保存: {FAILED_LOG}")
        print(f"   下次可运行: python test_minute_fetch.py --failed-only")
    else:
        print(f"\n🎉 全部成功，没有失败！")


if __name__ == "__main__":
    main()
