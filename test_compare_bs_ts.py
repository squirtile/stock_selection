# -*- coding: utf-8 -*-
"""
测试 BaoStock vs Tushare 数据一致性
===================================
对比同一只股票在相同日期范围内的数据，确认：
1. 列名是否完全一致
2. 数值偏差是否在可接受范围内
3. 日期覆盖是否一致

用法：
  python test_compare_bs_ts.py
  python test_compare_bs_ts.py --code 600519  # 指定股票
"""

import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 从 BaoStock 拉取 ──
def fetch_baostock(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """使用 BaoStock 拉取日K（前复权）"""
    try:
        import baostock as bs
        lg = bs.login()
        if getattr(lg, "error_code", None) != "0":
            print(f"  BaoStock 登录失败: {lg.error_msg}")
            return pd.DataFrame()

        if code.startswith(("600", "601", "603", "605")):
            bs_code = f"sh.{code}"
        else:
            bs_code = f"sz.{code}"

        rs = bs.query_history_k_data_plus(
            bs_code,
            fields="date,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )

        if rs.error_code != "0":
            print(f"  BaoStock 查询失败: {rs.error_msg}")
            bs.logout()
            return pd.DataFrame()

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        bs.logout()

        if not data_list:
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)
        df = df.rename(columns={
            "date": "日期", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "volume": "成交量",
            "amount": "成交额", "pctChg": "涨跌幅",
        })
        df["代码"] = code
        for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期")
        return df
    except Exception as e:
        print(f"  BaoStock 异常: {e}")
        return pd.DataFrame()


# ── 从 Tushare 拉取 ──
def fetch_tushare(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """使用 Tushare 拉取日K（前复权）"""
    try:
        from data_loader import get_tushare_pro
        import tushare as ts

        pro = get_tushare_pro()

        if code.startswith(("600", "601", "603", "605")):
            ts_code = f"{code}.SH"
        else:
            ts_code = f"{code}.SZ"

        start_ts = start_date.replace("-", "")
        end_ts = end_date.replace("-", "")

        df = ts.pro_bar(
            ts_code=ts_code, adj='qfq',
            start_date=start_ts, end_date=end_ts,
            api=pro,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={
            "trade_date": "日期", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "vol": "成交量",
            "amount": "成交额", "pct_chg": "涨跌幅",
        })
        df["代码"] = code
        for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d")
        df = df.sort_values("日期")
        return df
    except Exception as e:
        print(f"  Tushare 异常: {e}")
        return pd.DataFrame()


def compare(code: str = "000001", days: int = 60):
    """对比两只数据源"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"📊 对比: {code} | 日期范围: {start_date} ~ {end_date}")
    print(f"{'='*60}")

    print("\n⏳ 拉取 BaoStock...")
    bs_df = fetch_baostock(code, start_date, end_date)
    print(f"  → {len(bs_df)} 条")

    print("\n⏳ 拉取 Tushare...")
    ts_df = fetch_tushare(code, start_date, end_date)
    print(f"  → {len(ts_df)} 条")

    if bs_df.empty:
        print("\n❌ BaoStock 无数据，无法对比")
        return
    if ts_df.empty:
        print("\n❌ Tushare 无数据，无法对比")
        return

    # ── 列名对比 ──
    print(f"\n{'─'*40}")
    print("📋 列名对比")
    print(f"{'─'*40}")
    bs_cols = [c for c in bs_df.columns if c != "代码"]
    ts_cols = [c for c in ts_df.columns if c != "代码"]
    print(f"  BaoStock: {bs_cols}")
    print(f"  Tushare : {ts_cols}")
    print(f"  一致: {'✅' if bs_cols == ts_cols else '❌'}")

    if bs_cols != ts_cols:
        only_bs = set(bs_cols) - set(ts_cols)
        only_ts = set(ts_cols) - set(bs_cols)
        if only_bs: print(f"  仅BS有: {only_bs}")
        if only_ts: print(f"  仅TS有: {only_ts}")

    # ── 日期覆盖对比 ──
    print(f"\n{'─'*40}")
    print("📅 日期覆盖对比")
    print(f"{'─'*40}")
    bs_dates = set(bs_df["日期"].dt.strftime("%Y-%m-%d"))
    ts_dates = set(ts_df["日期"].dt.strftime("%Y-%m-%d"))
    common = sorted(bs_dates & ts_dates)
    only_bs = sorted(bs_dates - ts_dates)
    only_ts = sorted(ts_dates - bs_dates)
    print(f"  共同日期: {len(common)} 天")
    print(f"  仅BS有: {len(only_bs)} 天 {only_bs[-5:] if only_bs else ''}")
    print(f"  仅TS有: {len(only_ts)} 天 {only_ts[-5:] if only_ts else ''}")

    # ── 数值对比（共同日期） ──
    print(f"\n{'─'*40}")
    print("🔢 收盘价对比（共同日期，差异 > 0.5% 才显示）")
    print(f"{'─'*40}")

    bs_idx = bs_df.set_index("日期")
    ts_idx = ts_df.set_index("日期")

    diffs = []
    for d in common:
        bs_close = float(bs_idx.loc[d, "收盘"]) if d in bs_idx.index else None
        ts_close = float(ts_idx.loc[d, "收盘"]) if d in ts_idx.index else None
        if bs_close and ts_close and bs_close != 0:
            diff_pct = abs(ts_close - bs_close) / abs(bs_close) * 100
            diffs.append((d, bs_close, ts_close, diff_pct))

    if diffs:
        big_diffs = [(d, *rest) for d, *rest in diffs if rest[2] > 0.5]
        if big_diffs:
            print(f"  差异 > 0.5% 的天数: {len(big_diffs)}")
            for d, bs_c, ts_c, diff in big_diffs[:5]:
                print(f"    {d}: BS={bs_c:.3f} TS={ts_c:.3f} 差异{diff:.2f}%")
        else:
            print(f"  ✅ 全部 {len(diffs)} 天收盘价差异 < 0.5%")

        max_diff = max(d[3] for d in diffs)
        avg_diff = np.mean([d[3] for d in diffs])
        print(f"\n  最大差异: {max_diff:.3f}%  |  平均差异: {avg_diff:.3f}%")
    else:
        print("  无共同日期可对比")

    # ── 成交量对比 ──
    print(f"\n{'─'*40}")
    print("📊 成交量对比")
    print(f"{'─'*40}")
    vol_diffs = []
    for d in common[:5]:
        bs_v = float(bs_idx.loc[d, "成交量"]) if d in bs_idx.index else None
        ts_v = float(ts_idx.loc[d, "成交量"]) if d in ts_idx.index else None
        if bs_v and ts_v and bs_v != 0:
            diff = abs(ts_v - bs_v) / abs(bs_v) * 100
            vol_diffs.append(diff)
            print(f"    {d}: BS={bs_v:.0f} TS={ts_v:.0f} 差异{diff:.1f}%")
    if vol_diffs:
        print(f"  平均成交量差异: {np.mean(vol_diffs):.1f}%")

    # ── 结论 ──
    print(f"\n{'='*60}")
    print("📝 结论")
    print(f"{'='*60}")
    print(f"  列名一致: {'✅' if bs_cols == ts_cols else '❌'}")
    print(f"  日期覆盖: {'✅ 基本相同' if len(common) >= min(len(bs_dates), len(ts_dates)) * 0.95 else '⚠️ 有差异'}")
    if diffs:
        print(f"  收盘价差异: {'✅ < 0.5%' if max_diff < 0.5 else '⚠️ ' + str(round(max_diff,2)) + '%'} (最大{max_diff:.2f}%)")

    if bs_cols == ts_cols and max_diff < 1.0:
        print(f"\n  ✅ 两源数据基本一致，策略和ML可互换使用")
    else:
        print(f"\n  ⚠️ 存在差异，需注意")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", default="000001", help="股票代码")
    parser.add_argument("--days", type=int, default=60, help="对比天数")
    args = parser.parse_args()

    compare(args.code, args.days)
