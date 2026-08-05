#!/usr/bin/env python3
"""
测试 Tushare 分钟数据接口权限（stk_mins / idx_mins）

用途：申请了 stk_mins 和 idx_mins 权限后，跑这个脚本确认接口可用。
用法：
  python test_index_api.py
  python test_index_api.py --stock-only      # 只测个股分钟
  python test_index_api.py --index-only      # 只测指数分钟
  python test_index_api.py --freq 5,30,60    # 指定测试周期
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import disable_proxy, get_tushare_pro

disable_proxy()
pro = get_tushare_pro()

# ── 测试目标 ──────────────────────────────────────────────
# 个股：选沪市深市各2只代表性股票
TEST_STOCKS = [
    ("000001.SZ", "平安银行"),
    ("000858.SZ", "五粮液"),
    ("600519.SH", "贵州茅台"),
    ("688981.SH", "中芯国际"),
]

# 四大指数
TEST_INDICES = [
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000688.SH", "科创50"),
]

# 默认测试周期
DEFAULT_FREQS = ["5", "30", "60"]

# 测试时间范围（最近 3 个交易日，避免数据量过大）
END_DATE = datetime.now()
START_DATE = END_DATE - timedelta(days=5)


def fmt_date(d: datetime, with_time: str = "09:00:00") -> str:
    return d.strftime("%Y-%m-%d") + f" {with_time}"


def fmt_date_end(d: datetime) -> str:
    return d.strftime("%Y-%m-%d") + " 15:30:00"


def test_stk_mins(freqs: list[str]) -> dict:
    """测试个股分钟线 stk_mins 接口"""
    print("\n" + "=" * 70)
    print(f"🧪 测试 stk_mins（个股分钟，周期: {freqs}）")
    print("=" * 70)

    results = {}
    for ts_code, name in TEST_STOCKS:
        code = ts_code.split(".")[0]
        for freq in freqs:
            label = f"{name}({code}) {freq}min"
            try:
                df = pro.stk_mins(
                    ts_code=ts_code,
                    asset="E",
                    freq=f"{freq}min",
                    start_date=fmt_date(START_DATE),
                    end_date=fmt_date_end(END_DATE),
                )
                if df is not None and not df.empty:
                    cols = list(df.columns)
                    dt_min = df["trade_time"].min() if "trade_time" in df.columns else "?"
                    dt_max = df["trade_time"].max() if "trade_time" in df.columns else "?"
                    print(f"  ✅ {label}: {len(df)} 行 | 列: {cols}")
                    print(f"     时间范围: {str(dt_min)[:16]} ~ {str(dt_max)[:16]}")
                    # 打印前2行样例
                    sample = df.head(2).to_dict(orient="records")
                    for i, s in enumerate(sample):
                        print(f"     [{i}] {s}")
                else:
                    print(f"  ⚠️  {label}: 返回空数据")
                results[f"{code}_{freq}min"] = True
            except Exception as e:
                err = str(e)
                if "权限" in err or "无权" in err or "permission" in err.lower():
                    print(f"  🔴 {label}: ❌ 无权限! 需在 https://tushare.pro 申请 stk_mins")
                elif "频率" in err or "过快" in err:
                    print(f"  ⏳ {label}: 限流 — 等60秒重试")
                else:
                    print(f"  ❌ {label}: {err[:200]}")
                results[f"{code}_{freq}min"] = False
    return results


def test_idx_mins(freqs: list[str]) -> dict:
    """测试指数分钟线 idx_mins 接口"""
    print("\n" + "=" * 70)
    print(f"🧪 测试 idx_mins（指数分钟，周期: {freqs}）")
    print("=" * 70)

    results = {}
    for ts_code, name in TEST_INDICES:
        for freq in freqs:
            label = f"{name}({ts_code}) {freq}min"
            try:
                df = pro.idx_mins(
                    ts_code=ts_code,
                    freq=f"{freq}min",
                    start_date=fmt_date(START_DATE),
                    end_date=fmt_date_end(END_DATE),
                )
                if df is not None and not df.empty:
                    cols = list(df.columns)
                    dt_col = "trade_time" if "trade_time" in df.columns else df.columns[0]
                    dt_min = df[dt_col].min() if dt_col in df.columns else "?"
                    dt_max = df[dt_col].max() if dt_col in df.columns else "?"
                    print(f"  ✅ {label}: {len(df)} 行 | 列: {cols}")
                    print(f"     时间范围: {str(dt_min)[:16]} ~ {str(dt_max)[:16]}")
                    # 打印前2行样例
                    sample = df.head(2).to_dict(orient="records")
                    for i, s in enumerate(sample):
                        print(f"     [{i}] {s}")
                else:
                    print(f"  ⚠️  {label}: 返回空数据")
                results[f"{ts_code}_{freq}min"] = True
            except Exception as e:
                err = str(e)
                if "权限" in err or "无权" in err or "permission" in err.lower():
                    print(f"  🔴 {label}: ❌ 无权限! 需在 https://tushare.pro 申请 idx_mins")
                elif "频率" in err or "过快" in err:
                    print(f"  ⏳ {label}: 限流 — 等60秒重试")
                else:
                    print(f"  ❌ {label}: {err[:200]}")
                results[f"{ts_code}_{freq}min"] = False
    return results


def test_index_daily() -> dict:
    """测试指数日线 index_daily（一般都有权限，作为对照组）"""
    print("\n" + "=" * 70)
    print(f"🧪 测试 index_daily（指数日线，对照组）")
    print("=" * 70)

    results = {}
    for ts_code, name in TEST_INDICES:
        try:
            df = pro.index_daily(
                ts_code=ts_code,
                start_date=START_DATE.strftime("%Y%m%d"),
                end_date=END_DATE.strftime("%Y%m%d"),
            )
            if df is not None and not df.empty:
                print(f"  ✅ {name}({ts_code}): {len(df)} 行 | 列: {list(df.columns)}")
                results[ts_code] = True
            else:
                print(f"  ⚠️  {name}({ts_code}): 返回空数据")
                results[ts_code] = False
        except Exception as e:
            print(f"  ❌ {name}({ts_code}): {str(e)[:200]}")
            results[ts_code] = False
    return results


def print_summary(stock_results: dict, index_results: dict, daily_results: dict):
    """打印汇总"""
    print("\n" + "=" * 70)
    print("📊 测试汇总")
    print("=" * 70)

    # stk_mins 汇总
    stk_ok = sum(1 for v in stock_results.values() if v)
    stk_total = len(stock_results)
    status_stk = "✅ 全部通过" if stk_ok == stk_total else f"⚠️  {stk_ok}/{stk_total} 通过"
    print(f"  stk_mins（个股分钟）: {status_stk}")

    # idx_mins 汇总
    idx_ok = sum(1 for v in index_results.values() if v)
    idx_total = len(index_results)
    status_idx = "✅ 全部通过" if idx_ok == idx_total else f"⚠️  {idx_ok}/{idx_total} 通过"
    print(f"  idx_mins（指数分钟）: {status_idx}")

    # index_daily 汇总
    daily_ok = sum(1 for v in daily_results.values() if v)
    daily_total = len(daily_results)
    status_daily = "✅ 全部通过" if daily_ok == daily_total else f"⚠️  {daily_ok}/{daily_total} 通过"
    print(f"  index_daily（指数日线）: {status_daily}")

    # 结论
    print()
    if stk_ok == stk_total and idx_ok == idx_total:
        print("🎉 所有分钟数据接口权限正常，可以开始下载!")
    elif stk_ok == 0 and idx_ok == 0:
        print("🔴 stk_mins 和 idx_mins 都无权限，请先到 https://tushare.pro 申请")
        print("   登录 → 个人中心 → 接口权限 → 搜索 stk_mins / idx_mins → 申请")
    else:
        if stk_ok == 0:
            print("🔴 stk_mins 无权限 → 个股分钟数据暂时无法使用")
        if idx_ok == 0:
            print("🔴 idx_mins 无权限 → 指数分钟数据暂时无法使用（日线仍可用）")
        if 0 < stk_ok < stk_total:
            print("⚠️  stk_mins 部分通过，检查上述失败的具体原因")
        if 0 < idx_ok < idx_total:
            print("⚠️  idx_mins 部分通过，检查上述失败的具体原因")


def main():
    parser = argparse.ArgumentParser(description="测试 Tushare 分钟数据接口权限")
    parser.add_argument("--stock-only", action="store_true", help="只测个股分钟")
    parser.add_argument("--index-only", action="store_true", help="只测指数分钟")
    parser.add_argument("--freq", type=str, default="5,30,60", help="测试周期，逗号分隔")
    args = parser.parse_args()

    freqs = [f.strip() for f in args.freq.split(",")]

    stock_results = {}
    index_results = {}
    daily_results = {}

    if not args.index_only:
        stock_results = test_stk_mins(freqs)
        # 限流等待
        import time
        time.sleep(3)

    if not args.stock_only:
        index_results = test_idx_mins(freqs)
        time.sleep(2)
        daily_results = test_index_daily()

    print_summary(stock_results, index_results, daily_results)


if __name__ == "__main__":
    main()

