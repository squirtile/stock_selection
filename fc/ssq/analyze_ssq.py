"""
双色球历史数据分布分析
======================
分析维度:
  红球: 频次分布、和值分布、跨度分布、奇偶比、大小比、三区比、连号、重号
  蓝球: 频次分布、奇偶分布、大小分布、遗漏统计
  组合: 红蓝组合频次
"""

import pandas as pd
import numpy as np
import os
import sys
from collections import Counter
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "双色球历史开奖数据.csv")


def load_data():
    """加载历史数据"""
    if not os.path.exists(DATA_FILE):
        print(f"数据文件不存在: {DATA_FILE}")
        print("请先运行 fetch_ssq.py 拉取数据")
        sys.exit(1)

    df = pd.read_csv(DATA_FILE, dtype={"期号": str})
    if "开奖日期" in df.columns:
        df["开奖日期"] = pd.to_datetime(df["开奖日期"], errors="coerce")
    return df


def analyze_red_frequency(df):
    """红球频次分布 (1-33)"""
    red_cols = [f"红{i}" for i in range(1, 7)]
    all_reds = []
    for col in red_cols:
        if col in df.columns:
            all_reds.extend(df[col].dropna().astype(int).tolist())

    counter = Counter(all_reds)
    freq = pd.DataFrame(
        {"号码": range(1, 34), "出现次数": [counter.get(i, 0) for i in range(1, 34)]}
    )
    freq["占比"] = freq["出现次数"] / len(df) * 100
    freq["理论占比"] = 6 / 33 * 100  # 每期6/33概率
    freq["偏差"] = freq["占比"] - freq["理论占比"]

    hot = freq.nlargest(10, "出现次数")
    cold = freq.nsmallest(10, "出现次数")

    return freq, hot, cold


def analyze_blue_frequency(df):
    """蓝球频次分布 (1-16)"""
    if "蓝球" not in df.columns:
        return None, None, None

    counter = Counter(df["蓝球"].dropna().astype(int))
    freq = pd.DataFrame(
        {"号码": range(1, 17), "出现次数": [counter.get(i, 0) for i in range(1, 17)]}
    )
    freq["占比"] = freq["出现次数"] / len(df) * 100
    freq["理论占比"] = 1 / 16 * 100
    freq["偏差"] = freq["占比"] - freq["理论占比"]

    hot = freq.nlargest(5, "出现次数")
    cold = freq.nsmallest(5, "出现次数")

    return freq, hot, cold


def analyze_red_sum(df):
    """红球和值分布"""
    if "红球和值" not in df.columns:
        return None
    sums = df["红球和值"].dropna().astype(int)
    stats = {
        "平均和值": sums.mean(),
        "中位数": sums.median(),
        "标准差": sums.std(),
        "最小值": sums.min(),
        "最大值": sums.max(),
        "理论中心": 102,  # (1+33)*6/2 = 102
        "常见区间": f"{int(sums.quantile(0.25))} ~ {int(sums.quantile(0.75))}",
    }
    return stats


def analyze_red_span(df):
    """红球跨度分布"""
    if "红球跨度" not in df.columns:
        return None
    spans = df["红球跨度"].dropna().astype(int)
    stats = {
        "平均跨度": spans.mean(),
        "中位数": spans.median(),
        "最小/最大": f"{spans.min()} / {spans.max()}",
        "密集区间": f"{int(spans.quantile(0.25))} ~ {int(spans.quantile(0.75))}",
    }
    return stats


def analyze_patterns(df):
    """红球奇偶比、大小比、三区比分布"""
    patterns = {}

    for col, name in [("红球奇偶比", "奇偶比"), ("红球大小比", "大小比"), ("红球三区比", "三区比")]:
        if col in df.columns:
            cnt = df[col].value_counts().head(10)
            patterns[name] = cnt.to_dict()

    return patterns


def analyze_blue_omission(df):
    """蓝球遗漏统计: 每个号码上次出现距离现在的期数"""
    if "蓝球" not in df.columns:
        return None

    blue_vals = df["蓝球"].dropna().astype(int).values
    n = len(blue_vals)
    omission = {}
    for num in range(1, 17):
        # 从后往前找最近一次出现
        for i in range(n - 1, -1, -1):
            if blue_vals[i] == num:
                omission[num] = n - 1 - i
                break
        else:
            omission[num] = n  # 从未出现

    return omission


def analyze_consecutive(df):
    """连号统计: 红球中出现连续号码的比例"""
    red_cols = [f"红{i}" for i in range(1, 7)]
    consecutive_count = 0
    for _, row in df.iterrows():
        reds = sorted(
            [int(row[c]) for c in red_cols if c in row.index and pd.notna(row[c])]
        )
        if len(reds) >= 2:
            for j in range(len(reds) - 1):
                if reds[j + 1] - reds[j] == 1:
                    consecutive_count += 1
                    break
    return {
        "含连号期数": consecutive_count,
        "总期数": len(df),
        "连号比例": f"{consecutive_count / len(df) * 100:.1f}%",
    }


def print_summary(df):
    """打印完整分析报告"""
    total = len(df)
    date_range = (
        f"{df['开奖日期'].min().strftime('%Y-%m-%d')} ~ "
        f"{df['开奖日期'].max().strftime('%Y-%m-%d')}"
    )

    print("=" * 60)
    print("  双色球 历史数据分布分析")
    print("=" * 60)
    print(f"  总期数: {total}  日期范围: {date_range}")
    print()

    # ── 红球频次 ──
    freq, hot, cold = analyze_red_frequency(df)
    print("【红球频次 TOP 10 (热号)】")
    for _, r in hot.iterrows():
        bar = "█" * int(r["出现次数"] / hot["出现次数"].max() * 20)
        print(f"  {int(r['号码']):02d}  {int(r['出现次数']):4d}次 ({r['占比']:.1f}%) {bar}")
    print()
    print("【红球频次 BOTTOM 10 (冷号)】")
    for _, r in cold.iterrows():
        print(f"  {int(r['号码']):02d}  {int(r['出现次数']):4d}次 ({r['占比']:.1f}%)")
    print()

    # ── 蓝球频次 ──
    bfreq, bhot, bcold = analyze_blue_frequency(df)
    if bfreq is not None:
        print("【蓝球频次分布】")
        hot_str = ", ".join(f"{int(r['号码']):02d}({int(r['出现次数'])}次)" for _, r in bhot.iterrows())
        cold_str = ", ".join(f"{int(r['号码']):02d}({int(r['出现次数'])}次)" for _, r in bcold.iterrows())
        print(f"  热号: {hot_str}")
        print(f"  冷号: {cold_str}")
        print()

    # ── 和值 ──
    sum_stats = analyze_red_sum(df)
    if sum_stats:
        print("【红球和值分布】")
        for k, v in sum_stats.items():
            print(f"  {k}: {v}")
        print()

    # ── 跨度 ──
    span_stats = analyze_red_span(df)
    if span_stats:
        print("【红球跨度分布】")
        for k, v in span_stats.items():
            print(f"  {k}: {v}")
        print()

    # ── 奇偶/大小/三区 ──
    patterns = analyze_patterns(df)
    print("【形态分布 TOP 5】")
    for name, dist in patterns.items():
        top_items = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:5]
        items_str = " | ".join(f"{k}({v}次)" for k, v in top_items)
        print(f"  {name}: {items_str}")
    print()

    # ── 连号 ──
    cons = analyze_consecutive(df)
    print("【连号统计】")
    for k, v in cons.items():
        print(f"  {k}: {v}")
    print()

    # ── 蓝球遗漏 ──
    omission = analyze_blue_omission(df)
    if omission:
        print("【蓝球当前遗漏 (距上次出现期数)】")
        sorted_om = sorted(omission.items(), key=lambda x: x[1], reverse=True)
        for num, miss in sorted_om[:10]:
            bar = "█" * min(miss, 30)
            print(f"  {num:02d}  遗漏 {miss:3d} 期 {bar}")
        print()


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="双色球数据分析")
    parser.add_argument("--brief", action="store_true", help="简要输出")
    args = parser.parse_args()

    df = load_data()
    print_summary(df)
