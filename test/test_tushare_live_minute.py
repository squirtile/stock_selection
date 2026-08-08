#!/usr/bin/env python3
"""
测试 Tushare 盘中实时分钟数据获取能力。

测试项目：
  1. rt_min      — 实时分钟线（盘中当天，核心接口）
  2. stk_mins    — 历史分钟K线（历史任意日期，需 stk_mins 权限）
  3. pro_bar (分钟) — pro_bar 通用行情接口的分钟模式

用法：
  python test/test_tushare_live_minute.py
  python test/test_tushare_live_minute.py --code 000001.SZ
  python test/test_tushare_live_minute.py --freq 1MIN,5MIN,30MIN
"""

import sys
import os
import argparse
import time
from datetime import datetime

# 项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts
import pandas as pd

from config import TUSHARE_TOKEN, TUSHARE_HTTP_URL
from data_loader import disable_proxy


def init_pro():
    """初始化 Tushare Pro，使用 config.py 中的 Token 和代理地址。"""
    disable_proxy()

    print(f"Tushare 版本: {ts.__version__}")
    print(f"Token 前缀: {TUSHARE_TOKEN[:8]}...")
    print(f"代理地址:   {TUSHARE_HTTP_URL or '(无)'}")
    print()

    pro = ts.pro_api(TUSHARE_TOKEN, timeout=30)
    if TUSHARE_HTTP_URL:
        pro._DataApi__http_url = TUSHARE_HTTP_URL
    return pro


def test_connection(pro):
    """1. 先测试基本连通性 — stock_basic。"""
    print("=" * 70)
    print("【测试 1】基础连通性 — stock_basic")
    print("=" * 70)
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name")
        if df is not None and not df.empty:
            print(f"✅ 连通正常！获取到 {len(df)} 只股票")
            return df
        else:
            print("❌ stock_basic 返回空")
            return None
    except Exception as e:
        print(f"❌ stock_basic 失败: {e}")
        return None


def test_rt_min(pro, test_code="000001.SZ", freq_list=None):
    """2. 测试 rt_min — 实时分钟数据（盘中当天数据）。"""
    if freq_list is None:
        freq_list = ["1MIN", "5MIN", "30MIN"]

    print()
    print("=" * 70)
    print(f"【测试 2】rt_min — 实时分钟数据（当天盘中）")
    print(f"  测试股票: {test_code}")
    print(f"  当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = {}
    for freq in freq_list:
        print(f"\n--- 请求 {freq} ---")
        try:
            t0 = time.time()
            df = pro.rt_min(ts_code=test_code, freq=freq)
            elapsed = time.time() - t0

            if df is None:
                print(f"  ❌ {freq}: 返回 None（接口不可用或无权限）")
                results[freq] = None
            elif df.empty:
                print(f"  ⚠️  {freq}: 返回空 DataFrame")
                print(f"     可能原因: 非交易时间 / 当天无数据 / 权限不足")
                results[freq] = pd.DataFrame()
            else:
                print(f"  ✅ {freq}: 获取到 {len(df)} 条数据 (耗时 {elapsed:.2f}s)")
                print(f"     字段: {list(df.columns)}")
                print(f"     时间范围: {df.iloc[0].get('time', 'N/A')} ~ {df.iloc[-1].get('time', 'N/A')}")
                # 打印前2行和最后2行
                print(f"     前2行:")
                print(df.head(2).to_string(index=False))
                results[freq] = df
        except Exception as e:
            print(f"  ❌ {freq}: 异常 — {type(e).__name__}: {e}")
            results[freq] = None

    return results


def test_stk_mins(pro, test_code="000001.SZ", freq_list=None):
    """3. 测试 stk_mins — 历史分钟K线（需 stk_mins 权限）。"""
    if freq_list is None:
        freq_list = ["5min", "30min"]

    print()
    print("=" * 70)
    print(f"【测试 3】stk_mins — 历史分钟K线（需 stk_mins 权限）")
    print(f"  测试股票: {test_code}")
    print("=" * 70)

    # 用最近一个交易日
    today = datetime.now().strftime("%Y-%m-%d")

    results = {}
    for freq in freq_list:
        print(f"\n--- 请求 {freq} ---")
        try:
            t0 = time.time()
            df = pro.stk_mins(
                ts_code=test_code,
                freq=freq,
                start_date=f"{today} 09:00:00",
                end_date=f"{today} 16:00:00",
            )
            elapsed = time.time() - t0

            if df is None:
                print(f"  ❌ {freq}: 返回 None（需要 stk_mins 权限）")
                results[freq] = None
            elif df.empty:
                print(f"  ⚠️  {freq}: 返回空 DataFrame（可能非交易日或无权限）")
                results[freq] = pd.DataFrame()
            else:
                print(f"  ✅ {freq}: 获取到 {len(df)} 条数据 (耗时 {elapsed:.2f}s)")
                print(f"     字段: {list(df.columns)}")
                print(df.head(3).to_string(index=False))
                results[freq] = df
        except Exception as e:
            print(f"  ❌ {freq}: 异常 — {type(e).__name__}: {e}")
            results[freq] = None

    return results


def test_pro_bar_minute(pro, test_code="000001.SZ", freq_list=None):
    """4. 测试 pro_bar 分钟模式（通用接口的分钟K线）。"""
    if freq_list is None:
        freq_list = ["5min", "30min"]

    print()
    print("=" * 70)
    print(f"【测试 4】pro_bar 分钟模式")
    print(f"  测试股票: {test_code}")
    print("=" * 70)

    results = {}
    for freq in freq_list:
        print(f"\n--- 请求 {freq} ---")
        try:
            t0 = time.time()
            df = ts.pro_bar(
                api=pro,
                ts_code=test_code,
                freq=freq,
                limit=10,
            )
            elapsed = time.time() - t0

            if df is None:
                print(f"  ❌ {freq}: 返回 None")
                results[freq] = None
            elif df.empty:
                print(f"  ⚠️  {freq}: 返回空 DataFrame")
                results[freq] = pd.DataFrame()
            else:
                print(f"  ✅ {freq}: 获取到 {len(df)} 条数据 (耗时 {elapsed:.2f}s)")
                print(f"     字段: {list(df.columns)}")
                print(df.head(3).to_string(index=False))
                results[freq] = df
        except Exception as e:
            print(f"  ❌ {freq}: 异常 — {type(e).__name__}: {e}")
            results[freq] = None

    return results


def print_summary(rt_min_results, stk_mins_results, pro_bar_results):
    """打印汇总报告。"""
    print()
    print()
    print("=" * 70)
    print("                    测 试 汇 总")
    print("=" * 70)

    # rt_min
    print("\n📊 rt_min (实时分钟线 — 盘中当天数据):")
    if rt_min_results:
        any_ok = any(v is not None and not (isinstance(v, pd.DataFrame) and v.empty) for v in rt_min_results.values())
        if any_ok:
            print("   ✅ 可用！可以获取盘中实时分钟数据")
            for f, df in rt_min_results.items():
                if df is not None and not df.empty:
                    print(f"      {f}: {len(df)} 条")
        else:
            print("   ❌ 不可用。可能原因：")
            print("      1. 当前不是A股交易时间（9:30-15:00）")
            print("      2. Token/代理未开通 rt_min 权限")
            print("      3. 代理地址不可达")
    else:
        print("   ⚠️  未执行")

    # stk_mins
    print("\n📊 stk_mins (历史分钟K线):")
    if stk_mins_results:
        any_ok = any(v is not None and not (isinstance(v, pd.DataFrame) and v.empty) for v in stk_mins_results.values())
        if any_ok:
            print("   ✅ 可用！已开通 stk_mins 权限")
        else:
            print("   ❌ 不可用。stk_mins 是付费权限，需要单独开通")
    else:
        print("   ⚠️  未执行")

    # pro_bar
    print("\n📊 pro_bar 分钟模式:")
    if pro_bar_results:
        any_ok = any(v is not None and not (isinstance(v, pd.DataFrame) and v.empty) for v in pro_bar_results.values())
        if any_ok:
            print("   ✅ 可用！")
        else:
            print("   ❌ 不可用")
    else:
        print("   ⚠️  未执行")

    print()
    print("=" * 70)
    print("💡 提示：")
    print("  - rt_min 只有在交易时间（9:30-15:00）才有数据")
    print("  - stk_mins 是付费权限，大部分免费Token不支持")
    print("  - 如果 rt_min 可用，就可以做盘中实时分钟级策略扫描")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="测试 Tushare 盘中实时分钟数据")
    parser.add_argument("--code", default="000001.SZ", help="测试股票代码 (默认 000001.SZ)")
    parser.add_argument("--freq", default="1MIN,5MIN,30MIN", help="rt_min 频率列表，逗号分隔")
    parser.add_argument("--skip-stk-mins", action="store_true", help="跳过 stk_mins 测试")
    parser.add_argument("--skip-pro-bar", action="store_true", help="跳过 pro_bar 分钟测试")
    args = parser.parse_args()

    freq_list = [f.strip() for f in args.freq.split(",")]

    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║       Tushare 盘中实时分钟数据获取能力测试                        ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    pro = init_pro()

    # 1. 连通性
    stock_df = test_connection(pro)
    if stock_df is None:
        print("\n❌ 基础连通性测试失败，终止后续测试。请检查 Token 和代理地址。")
        return

    # 2. rt_min — 核心：实时分钟数据
    rt_min_results = test_rt_min(pro, args.code, freq_list)

    # 3. stk_mins — 历史分钟K线
    stk_mins_results = None
    if not args.skip_stk_mins:
        mins_freq = [f.replace("MIN", "min").lower() for f in freq_list]
        stk_mins_results = test_stk_mins(pro, args.code, mins_freq)

    # 4. pro_bar 分钟
    pro_bar_results = None
    if not args.skip_pro_bar:
        pb_freq = [f.replace("MIN", "min").lower() for f in freq_list]
        pro_bar_results = test_pro_bar_minute(pro, args.code, pb_freq)

    # 汇总
    print_summary(rt_min_results, stk_mins_results, pro_bar_results)


if __name__ == "__main__":
    main()
