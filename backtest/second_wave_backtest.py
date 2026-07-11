#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
二波策略回测：二波埋伏 + 二波形态
目标：触发后持有1/2/3/5/10/15/20/30天，哪个周期的收益率最高？
"""

import os
import sys
import warnings
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

# 把父目录加入 sys.path，方便 import strategy 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy import prepare_hist_data
from strategies.daily_strategies import SecondWaveAmbushStrategy, SecondWaveStrategy

warnings.filterwarnings("ignore")

# ===================== 配置 =====================
HIST_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "hist")

# 持有周期（交易日）
HOLD_DAYS = [1, 2, 3, 5, 10, 15, 20, 30]

# 策略实例
STRATEGIES = {
    "二波埋伏": SecondWaveAmbushStrategy(),
    "二波形态": SecondWaveStrategy(),
}


def load_all_stocks(cache_dir: str) -> dict[str, pd.DataFrame]:
    """加载缓存中所有股票日线数据"""
    files = [f for f in os.listdir(cache_dir) if f.endswith(".csv")]
    stocks = {}
    for f in files:
        code = f.replace(".csv", "")
        try:
            df = pd.read_csv(os.path.join(cache_dir, f))
            if len(df) < 120:  # 至少需要120根K线（prepare_hist_data 需要60日滚动窗口）
                continue
            stocks[code] = df
        except Exception:
            continue
    print(f"加载了 {len(stocks)} 只股票")
    return stocks


def backtest_stock(code: str, df: pd.DataFrame) -> list[dict]:
    """
    对单只股票做回测：
    - 逐日检查策略是否触发
    - 记录触发后 N 天的前瞻收益率
    """
    # 1) 计算特征
    try:
        df_feat = prepare_hist_data(df.copy())
    except Exception:
        return []

    n = len(df_feat)
    results = []

    for i in range(n):
        # 最后 30 天无法算完全部持有收益，只回测到倒数第 31 天
        if i >= n - max(HOLD_DAYS) - 1:
            break

        # 必须有第一波涨幅字段（即 prepare_hist_data 已对这一天赋值）
        if pd.isna(df_feat.at[i, "第一波涨幅"]):
            continue

        row = df_feat.iloc[i]
        date = str(row.get("日期", ""))[:10]

        for strat_name, strat in STRATEGIES.items():
            try:
                hit = strat.match(row)
            except Exception:
                continue

            if not hit:
                continue

            # 触发当天的收盘价
            entry_close = float(row["收盘"])
            if entry_close <= 0:
                continue

            # 计算 N 天前瞻收益
            rec = {
                "股票代码": code,
                "策略": strat_name,
                "触发日期": date,
                "入场收盘价": round(entry_close, 2),
            }
            for d in HOLD_DAYS:
                fut_idx = i + d
                if fut_idx >= n:
                    rec[f"持有{d}天收益"] = np.nan
                else:
                    fut_close = float(df_feat.at[fut_idx, "收盘"])
                    ret = (fut_close / entry_close - 1) * 100
                    rec[f"持有{d}天收益"] = round(ret, 2)
            results.append(rec)

    return results


def print_summary(all_results: list[dict]):
    """汇总统计"""
    if not all_results:
        print("\n❌ 没有任何触发记录！")
        return

    df = pd.DataFrame(all_results)

    print("\n" + "=" * 80)
    print("二波策略回测汇总")
    print("=" * 80)

    for strat_name in ["二波埋伏", "二波形态"]:
        sub = df[df["策略"] == strat_name]
        if len(sub) == 0:
            print(f"\n### {strat_name} — 无触发")
            continue

        print(f"\n### {strat_name} — 触发 {len(sub)} 次")

        for d in HOLD_DAYS:
            col = f"持有{d}天收益"
            vals = sub[col].dropna()
            if len(vals) == 0:
                continue

            win_rate = (vals > 0).sum() / len(vals) * 100
            avg_ret = vals.mean()
            med_ret = vals.median()
            max_ret = vals.max()
            min_ret = vals.min()

            print(
                f"  持有 {d:>2}d │ "
                f"胜率 {win_rate:5.1f}% │ "
                f"均值 {avg_ret:+6.2f}% │ "
                f"中位数 {med_ret:+6.2f}% │ "
                f"最大 {max_ret:+6.2f}% │ "
                f"最小 {min_ret:+6.2f}% │ "
                f"样本 {len(vals)}"
            )

    # ---- 最优持有周期推荐 ----
    print("\n" + "-" * 60)
    print("🎯 最优持有周期推荐（按平均收益）")
    print("-" * 60)
    for strat_name in ["二波埋伏", "二波形态"]:
        sub = df[df["策略"] == strat_name]
        if len(sub) == 0:
            continue
        best_d = None
        best_avg = -999
        for d in HOLD_DAYS:
            col = f"持有{d}天收益"
            vals = sub[col].dropna()
            if len(vals) > 0 and vals.mean() > best_avg:
                best_avg = vals.mean()
                best_d = d
        if best_d:
            print(f"  {strat_name}: 持有 {best_d} 天，平均收益 {best_avg:+.2f}%")

    # ---- 全部触发记录写入 CSV ----
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "backtest_second_wave.csv",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n📄 详细记录已保存：{out_path}")


def main():
    print("=" * 60)
    print("二波策略回测工具")
    print(f"回测日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"持有周期: {HOLD_DAYS} 天")
    print("=" * 60)

    # 1) 加载缓存
    stocks = load_all_stocks(HIST_CACHE_DIR)
    if not stocks:
        print("❌ 缓存目录为空，请先运行 strategy.py 获取历史数据")
        return

    # 2) 逐只回测
    all_results = []
    total = len(stocks)
    for idx, (code, df) in enumerate(stocks.items(), 1):
        if idx % 100 == 0 or idx == total:
            print(f"  进度: {idx}/{total} ({idx/total*100:.0f}%) — 已触发 {len(all_results)} 次")
        results = backtest_stock(code, df)
        all_results.extend(results)

    # 3) 汇总输出
    print_summary(all_results)


if __name__ == "__main__":
    main()
