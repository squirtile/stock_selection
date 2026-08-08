# strategies/index_divergence.py
"""
大盘指数底背离策略（30分钟级别）。

检测四大指数（上证/深证/科创/创业）的30分钟 MACD 底背离，
作为市场环境的多空过滤器。

指数底背离信号可用于：
- 大盘环境判断：底背离 → 市场可能见底，适合开仓
- 风险控制：大盘未见底背离时不重仓

数据来源：cache/index/minute/{index_key}_30m.csv
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from .chanlun.utils import prepare_data, find_bottom_divergence, find_macd_golden_cross_divergence


# ── 指数定义 ──────────────────────────────────────────────
INDEX_MAP = {
    "SH000001": {"name": "上证指数", "ts_code": "000001.SH"},
    "SZ399001": {"name": "深证成指", "ts_code": "399001.SZ"},
    "SZ399006": {"name": "创业板指", "ts_code": "399006.SZ"},
    "SH000688": {"name": "科创50",   "ts_code": "000688.SH"},
}

INDEX_MINUTE_DIR = "cache/index/minute"
INDEX_DAILY_DIR = "cache/index/daily"


def _load_index_minute(index_key: str, frequency: str = "30") -> pd.DataFrame:
    """加载指数分钟缓存。"""
    cache_file = os.path.join(INDEX_MINUTE_DIR, f"{index_key}_{frequency}m.csv")
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        return df
    except Exception:
        return pd.DataFrame()


def _load_index_daily(index_key: str) -> pd.DataFrame:
    """加载指数日线缓存。"""
    cache_file = os.path.join(INDEX_DAILY_DIR, f"{index_key}.csv")
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        return df
    except Exception:
        return pd.DataFrame()


@pd.api.extensions.register_dataframe_accessor("divergence")
class _DivergenceAccessor:
    """DataFrame 扩展：快速检测底背离（内部用）"""
    def __init__(self, pandas_obj):
        self._obj = pandas_obj

    def bottom(self) -> Tuple[bool, dict]:
        return find_bottom_divergence(self._obj)

    def golden_cross_bottom(self) -> Tuple[bool, dict]:
        return find_macd_golden_cross_divergence(self._obj)


# ══════════════════════════════════════════════════════════════════
# 单指数底背离检测
# ══════════════════════════════════════════════════════════════════

def check_single_index_divergence(
    index_key: str,
    lookback_bars: int = 60,
    frequency: str = "30",
) -> dict:
    """
    检测单个指数的分钟级底背离。

    Args:
        index_key: "SH000001" / "SZ399001" / "SZ399006" / "SH000688"
        lookback_bars: 回溯K线数
        frequency: K线周期，"30" 或 "60"

    Returns:
        {
            "index_key": "SH000001",
            "index_name": "上证指数",
            "has_data": True/False,
            "bottom_divergence": True/False,       # DIF底背离
            "golden_cross_divergence": True/False,  # 金叉底背离
            "trend": "up"/"down"/"neutral",
            "details": {...},
            "latest_price": 3822.28,
            "latest_time": "2026-08-04 15:00:00",
        }
    """
    info = INDEX_MAP.get(index_key, {})
    name = info.get("name", index_key)

    # 加载数据
    df = _load_index_minute(index_key, frequency)
    if df is None or df.empty:
        return {
            "index_key": index_key, "index_name": name,
            "has_data": False, "bottom_divergence": False,
            "golden_cross_divergence": False, "trend": "neutral",
            "details": {}, "latest_price": 0, "latest_time": "",
        }

    # 准备数据（计算MA/MACD）
    df = prepare_data(df)
    if df is None or len(df) < lookback_bars:
        return {
            "index_key": index_key, "index_name": name,
            "has_data": True, "bottom_divergence": False,
            "golden_cross_divergence": False, "trend": "neutral",
            "details": {}, "latest_price": float(df["收盘"].iloc[-1]) if len(df) > 0 else 0,
            "latest_time": str(df["datetime"].iloc[-1]) if len(df) > 0 else "",
        }

    # DIF 底背离
    is_div, div_details = find_bottom_divergence(df, lookback=lookback_bars)

    # MACD 金叉底背离
    is_gc_div, gc_details = find_macd_golden_cross_divergence(df)

    # 简单趋势判断
    latest = df.iloc[-1]
    if pd.notna(latest.get("MA5")) and pd.notna(latest.get("MA20")):
        if latest["MA5"] > latest["MA20"]:
            trend = "up"
        elif latest["MA5"] < latest["MA20"]:
            trend = "down"
        else:
            trend = "neutral"
    else:
        trend = "neutral"

    return {
        "index_key": index_key,
        "index_name": name,
        "has_data": True,
        "bottom_divergence": is_div,
        "golden_cross_divergence": is_gc_div,
        "trend": trend,
        "details": {
            "divergence": div_details,
            "golden_cross": gc_details,
        },
        "latest_price": round(float(latest["收盘"]), 2),
        "latest_time": str(latest.get("datetime", "")),
    }


# ══════════════════════════════════════════════════════════════════
# 全市场底背离扫描
# ══════════════════════════════════════════════════════════════════

def scan_all_index_divergence() -> Dict[str, dict]:
    """
    扫描四大指数的30分钟底背离。

    Returns:
        {index_key: divergence_result, ...}
    """
    results = {}
    for index_key in INDEX_MAP:
        results[index_key] = check_single_index_divergence(index_key)
    return results


def market_bottom_signal(results: Dict[str, dict]) -> Tuple[bool, str]:
    """
    综合判断市场底部信号。

    规则：
    - ≥3个指数出现背离 → 强底部信号
    - ≥2个指数出现背离 → 中等底部信号
    - ≥1个指数出现背离 → 弱底部信号
    - 0个 → 无信号

    Returns:
        (是否有底部信号, 信号描述)
    """
    # 按指数计数：一个指数只要出现任一种背离就算1个
    div_idx_count = sum(1 for r in results.values() if r.get("bottom_divergence"))
    gc_idx_count = sum(1 for r in results.values() if r.get("golden_cross_divergence"))
    # 去重：同一个指数可能同时有底背离+金叉背离，只算一次
    affected_indices = sum(
        1 for r in results.values()
        if r.get("bottom_divergence") or r.get("golden_cross_divergence")
    )

    # 拼接描述
    parts = []
    if div_idx_count > 0:
        parts.append(f"{div_idx_count}个DIF底背离")
    if gc_idx_count > 0:
        parts.append(f"{gc_idx_count}个金叉背离")
    detail = "，".join(parts) if parts else "无"

    if affected_indices >= 3:
        return True, f"🔴 强底部信号: {affected_indices}个指数（{detail}）"
    elif affected_indices >= 2:
        return True, f"🟡 中等底部信号: {affected_indices}个指数（{detail}）"
    elif affected_indices >= 1:
        return True, f"🟢 弱底部信号: {affected_indices}个指数（{detail}）"
    else:
        return False, "无底部信号"


def print_divergence_report(results: Dict[str, dict]):
    """打印底背离报告。"""
    print("\n" + "=" * 70)
    print("📊 大盘指数 30分钟 底背离扫描")
    print("=" * 70)

    for index_key, r in results.items():
        name = r["index_name"]
        price = r.get("latest_price", 0)
        has_div = "🔴 底背离" if r["bottom_divergence"] else ""
        has_gc = "🟡 金叉背离" if r["golden_cross_divergence"] else ""
        trend = r.get("trend", "")
        trend_icon = {"up": "📈", "down": "📉", "neutral": "➡️"}.get(trend, "")
        status = " | ".join(filter(None, [has_div, has_gc]))
        if not status:
            status = "✅ 无背离"

        print(f"  {name:6s} | 价格: {price:>10.2f} | {trend_icon} {trend:>4s} | {status}")

    has_signal, desc = market_bottom_signal(results)
    print(f"\n  综合判断: {desc}")
    print("=" * 70)


# ══════════════════════════════════════════════════════════════════
# 作为分钟策略集成到 registry
# ══════════════════════════════════════════════════════════════════

class IndexDivergenceFilter:
    """
    指数底背离过滤器。

    用于 main.py / daily_report.py 的盘后分析，作为市场环境判断依据。

    用法：
      from strategies.index_divergence import IndexDivergenceFilter
      f = IndexDivergenceFilter()
      result = f.check()
      if result["has_bottom_signal"]:
          print("大盘见底，可以积极选股")
    """

    name = "指数底背离过滤器"
    description = "基于四大指数30分钟MACD底背离判断大盘底部"

    def check(self) -> dict:
        results = scan_all_index_divergence()
        has_signal, desc = market_bottom_signal(results)
        return {
            "has_bottom_signal": has_signal,
            "description": desc,
            "indices": results,
        }
