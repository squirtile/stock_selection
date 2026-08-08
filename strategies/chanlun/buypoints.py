# strategies/chanlun/buypoints.py
"""
缠论买卖点策略（30分钟级别）。

基于 identify.analyze() 输出的 ChanlunContext，判断一买/二买/三买。

一买(1B): 下跌趋势末端，底背驰 → 左侧买入
二买(2B): 一买反弹后回踩不创新低 → 确认买入
三买(3B): 突破中枢后回踩不跌回中枢上沿 → 趋势跟随
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

from .structures import (
    Stroke, Segment, Pivot, TrendAnalysis, BuyPoint, SellPoint, ChanlunContext,
)
from .identify import analyze
from .utils import find_bottom_divergence


# ══════════════════════════════════════════════════════════════════
# 一买 (1B): 底背驰反转
# ══════════════════════════════════════════════════════════════════

def detect_first_buy(
    ctx: ChanlunContext,
    divergence_ratio: float = 0.85,
    volume_multiplier: float = 1.20,
) -> Optional[BuyPoint]:
    """
    检测一买（底背驰反转）。

    条件：
    1. 最近是下跌趋势或盘整偏空
    2. 存在至少2段下跌笔
    3. 后一段创新低但 MACD 面积 ≤ 前一段 × divergence_ratio（背驰）
    4. 价格重新站上 MA5/MA10
    5. 突破前6根K线高点
    6. 放量确认

    Args:
        ctx: 缠论上下文
        divergence_ratio: 背驰阈值（越小越严格，0.85=后段MACD面积只有前段85%以内）
        volume_multiplier: 量能倍数

    Returns:
        BuyPoint or None
    """
    raw = ctx.df_raw
    strokes = ctx.strokes
    if raw is None or len(raw) < 80 or len(strokes) < 2:
        return None

    # 取最后2段下跌笔
    down_strokes = [s for s in strokes if s.direction == "down"]
    if len(down_strokes) < 2:
        return None

    prev_down = down_strokes[-2]
    last_down = down_strokes[-1]

    # 价格新低
    if last_down.low >= prev_down.low * 0.995:  # 没有明显新低
        return None

    # MACD面积背驰（力竭）
    macd_weaker = last_down.macd_area <= prev_down.macd_area * divergence_ratio
    if not macd_weaker:
        return None

    # 反弹确认
    latest = raw.iloc[-1]
    if pd.isna(latest.get("MA5")) or pd.isna(latest.get("MA10")):
        return None

    # 站上 MA5
    if latest["收盘"] <= latest["MA5"]:
        return None

    # MA5 >= MA10（短期趋势转强）
    if latest["MA5"] < latest["MA10"] * 0.998:
        return None

    # 突破前6根高点
    recent_6_high = raw["最高"].shift(1).rolling(6).max().iloc[-1]
    if pd.isna(recent_6_high) or latest["收盘"] <= recent_6_high:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0:
        return None
    if latest["成交量"] < vol20 * volume_multiplier:
        return None

    confidence = 0.6  # 一买置信度偏低（左侧）
    if macd_weaker and last_down.macd_area <= prev_down.macd_area * 0.5:
        confidence = 0.8  # 明显背驰

    return BuyPoint(
        type="1B",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        confidence=confidence,
        reason=f"底背驰: MACD面积 {last_down.macd_area:.1f}↓ vs {prev_down.macd_area:.1f}",
    )


# ══════════════════════════════════════════════════════════════════
# 二买 (2B): 回踩不创新低
# ══════════════════════════════════════════════════════════════════

def detect_second_buy(
    ctx: ChanlunContext,
    low_tolerance: float = 0.005,
    volume_multiplier: float = 1.20,
) -> Optional[BuyPoint]:
    """
    检测二买（回踩确认）。

    条件：
    1. 存在至少4笔（意味着有反弹+回踩的结构）
    2. 最近30根低点 ≥ 前30根低点（未创新低）
    3. 价格站上 MA5
    4. 突破前一根K线高点（启动确认）
    5. 放量
    6. 最后一笔方向向上

    Args:
        ctx: 缠论上下文
        low_tolerance: 低点容忍度
        volume_multiplier: 量能倍数
    """
    raw = ctx.df_raw
    strokes = ctx.strokes
    if raw is None or len(raw) < 70 or len(strokes) < 4:
        return None

    # 价格未创新低
    recent_low = float(raw["最低"].iloc[-30:].min())
    prior_low = float(raw["最低"].iloc[-60:-30].min()) if len(raw) >= 60 else float(raw["最低"].iloc[:-30].min())
    if recent_low < prior_low * (1 - low_tolerance):
        return None

    # 站上MA5
    latest = raw.iloc[-1]
    if pd.isna(latest.get("MA5")) or latest["收盘"] <= latest["MA5"]:
        return None

    # 突破前一根高点
    prev = raw.iloc[-2]
    if latest["收盘"] <= prev["最高"]:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0 or latest["成交量"] < vol20 * volume_multiplier:
        return None

    # 最后一笔向上
    if strokes[-1].direction != "up":
        return None

    confidence = 0.75  # 二买置信度中等（比一买更可靠）

    return BuyPoint(
        type="2B",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        confidence=confidence,
        reason=f"回踩不创新低: 近30低{recent_low:.2f} ≥ 前低{prior_low:.2f}",
    )


# ══════════════════════════════════════════════════════════════════
# 三买 (3B): 中枢上方回踩确认
# ══════════════════════════════════════════════════════════════════

def detect_third_buy(
    ctx: ChanlunContext,
    pullback_tolerance: float = 0.01,
    breakout_pct: float = 0.015,
    volume_multiplier: float = 1.15,
) -> Optional[BuyPoint]:
    """
    检测三买（中枢上方回踩确认）。

    条件：
    1. 存在中枢
    2. 中枢后价格曾突破中枢上沿（离开中枢）
    3. 当前回踩最低 ≥ 中枢上沿 × (1 - tolerance)（未跌回中枢）
    4. MA5 > MA10 > MA20（多头排列）
    5. 站上MA5且突破前6根高点
    6. 放量

    这是最适合"日线主升 + 分钟B点确认"的策略。
    """
    raw = ctx.df_raw
    pivots = ctx.pivots
    if raw is None or len(raw) < 80 or not pivots:
        return None

    pivot = pivots[-1]  # 最近的中枢

    # 中枢后有K线（曾离开中枢）
    pivot_end_idx = pivot.end_segment_idx
    # 找到中枢对应的原始K线索引
    if not ctx.strokes:
        return None
    # 取最后一个参与中枢的线段的最后一笔的结束索引
    last_seg = pivot.segments[-1] if pivot.segments else None
    if last_seg is None or not last_seg.strokes:
        return None
    end_k_idx = last_seg.strokes[-1].end_index

    if end_k_idx + 5 >= len(raw):
        return None  # 中枢后K线不够

    after_pivot = raw.iloc[end_k_idx + 1:].copy()
    if after_pivot.empty or len(after_pivot) < 5:
        return None

    after_high = float(after_pivot["最高"].max())
    latest = raw.iloc[-1]
    latest_low = float(latest["最低"])

    # 曾突破中枢上沿
    if after_high <= pivot.zg * (1 + breakout_pct):
        return None

    # 回踩未跌回中枢
    if latest_low < pivot.zg * (1 - pullback_tolerance):
        return None

    # MA多头排列
    if pd.isna(latest.get("MA5")) or pd.isna(latest.get("MA10")) or pd.isna(latest.get("MA20")):
        return None
    if not (latest["MA5"] > latest["MA10"] > latest["MA20"]):
        return None

    # 站上MA5
    if latest["收盘"] <= latest["MA5"]:
        return None

    # 突破前6根高点
    recent_6_high = raw["最高"].shift(1).rolling(6).max().iloc[-1]
    if pd.isna(recent_6_high) or latest["收盘"] <= recent_6_high:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0 or latest["成交量"] < vol20 * volume_multiplier:
        return None

    confidence = 0.85  # 三买置信度最高（趋势跟随）

    return BuyPoint(
        type="3B",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        pivot=pivot,
        confidence=confidence,
        reason=f"三买: 中枢上沿{pivot.zg:.1f}, 回踩低{latest_low:.1f}, 突破高{after_high:.1f}",
    )


# ══════════════════════════════════════════════════════════════════
# 一键检测所有买卖点
# ══════════════════════════════════════════════════════════════════

def detect_all_buy_points(
    df30: pd.DataFrame,
    enable_1b: bool = True,
    enable_2b: bool = True,
    enable_3b: bool = True,
) -> Tuple[ChanlunContext, List[BuyPoint]]:
    """
    一键检测30分钟级别的所有缠论买卖点。

    Args:
        df30: 30分钟K线 DataFrame
        enable_1b/2b/3b: 开关

    Returns:
        (缠论上下文, 买卖点列表)
    """
    ctx = analyze(df30)
    buy_points: List[BuyPoint] = []

    if enable_1b:
        bp = detect_first_buy(ctx)
        if bp:
            buy_points.append(bp)

    if enable_2b:
        bp = detect_second_buy(ctx)
        if bp:
            buy_points.append(bp)

    if enable_3b:
        bp = detect_third_buy(ctx)
        if bp:
            buy_points.append(bp)

    ctx.buy_points = buy_points
    return ctx, buy_points


# ══════════════════════════════════════════════════════════════════
# 卖点检测（与买点镜像对称）
# ══════════════════════════════════════════════════════════════════

def detect_first_sell(
    ctx: ChanlunContext,
    divergence_ratio: float = 0.85,
    volume_multiplier: float = 1.20,
) -> Optional[SellPoint]:
    """
    检测一卖（顶背驰反转）。

    条件（与一买镜像）：
    1. 存在至少2段上涨笔
    2. 后一段创新高但 MACD 面积 ≤ 前一段 × divergence_ratio（顶背驰）
    3. 价格跌破 MA5
    4. 跌破前6根K线低点
    5. 放量确认
    """
    raw = ctx.df_raw
    strokes = ctx.strokes
    if raw is None or len(raw) < 80 or len(strokes) < 2:
        return None

    up_strokes = [s for s in strokes if s.direction == "up"]
    if len(up_strokes) < 2:
        return None

    prev_up = up_strokes[-2]
    last_up = up_strokes[-1]

    # 价格新高
    if last_up.high <= prev_up.high * 1.005:
        return None

    # MACD面积顶背驰（力竭）
    macd_weaker = last_up.macd_area <= prev_up.macd_area * divergence_ratio
    if not macd_weaker:
        return None

    # 回落确认
    latest = raw.iloc[-1]
    if pd.isna(latest.get("MA5")) or pd.isna(latest.get("MA10")):
        return None

    # 跌破 MA5
    if latest["收盘"] >= latest["MA5"]:
        return None

    # MA5 <= MA10（短期趋势转弱）
    if latest["MA5"] > latest["MA10"] * 1.002:
        return None

    # 跌破前6根低点
    recent_6_low = raw["最低"].shift(1).rolling(6).min().iloc[-1]
    if pd.isna(recent_6_low) or latest["收盘"] >= recent_6_low:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0 or latest["成交量"] < vol20 * volume_multiplier:
        return None

    confidence = 0.60
    if macd_weaker and last_up.macd_area <= prev_up.macd_area * 0.5:
        confidence = 0.80

    return SellPoint(
        type="1S",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        confidence=confidence,
        reason=f"顶背驰: MACD面积 {last_up.macd_area:.1f}↓ vs {prev_up.macd_area:.1f}",
    )


def detect_second_sell(
    ctx: ChanlunContext,
    high_tolerance: float = 0.005,
    volume_multiplier: float = 1.20,
) -> Optional[SellPoint]:
    """
    检测二卖（反弹不创新高）。

    条件（与二买镜像）：
    1. 存在至少4笔
    2. 最近30根高点 ≤ 前30根高点（未创新高）
    3. 价格跌破 MA5
    4. 跌破前一根K线低点
    5. 放量
    6. 最后一笔方向向下
    """
    raw = ctx.df_raw
    strokes = ctx.strokes
    if raw is None or len(raw) < 70 or len(strokes) < 4:
        return None

    # 价格未创新高
    recent_high = float(raw["最高"].iloc[-30:].max())
    prior_high = float(raw["最高"].iloc[-60:-30].max()) if len(raw) >= 60 else float(raw["最高"].iloc[:-30].max())
    if recent_high > prior_high * (1 + high_tolerance):
        return None

    # 跌破MA5
    latest = raw.iloc[-1]
    if pd.isna(latest.get("MA5")) or latest["收盘"] >= latest["MA5"]:
        return None

    # 跌破前一根低点
    prev = raw.iloc[-2]
    if latest["收盘"] >= prev["最低"]:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0 or latest["成交量"] < vol20 * volume_multiplier:
        return None

    # 最后一笔向下
    if strokes[-1].direction != "down":
        return None

    confidence = 0.75

    return SellPoint(
        type="2S",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        confidence=confidence,
        reason=f"反弹不创新高: 近30高{recent_high:.2f} ≤ 前高{prior_high:.2f}",
    )


def detect_third_sell(
    ctx: ChanlunContext,
    rally_tolerance: float = 0.01,
    breakdown_pct: float = 0.015,
    volume_multiplier: float = 1.15,
) -> Optional[SellPoint]:
    """
    检测三卖（中枢下方反弹确认）。

    条件（与三买镜像）：
    1. 存在中枢
    2. 中枢后价格曾跌破中枢下沿
    3. 当前反弹最高 ≤ 中枢下沿 × (1 + tolerance)（未站回中枢）
    4. MA5 < MA10 < MA20（空头排列）
    5. 跌破MA5且跌破前6根低点
    6. 放量
    """
    raw = ctx.df_raw
    pivots = ctx.pivots
    if raw is None or len(raw) < 80 or not pivots:
        return None

    pivot = pivots[-1]

    if not ctx.strokes:
        return None
    last_seg = pivot.segments[-1] if pivot.segments else None
    if last_seg is None or not last_seg.strokes:
        return None
    end_k_idx = last_seg.strokes[-1].end_index

    if end_k_idx + 5 >= len(raw):
        return None

    after_pivot = raw.iloc[end_k_idx + 1:].copy()
    if after_pivot.empty or len(after_pivot) < 5:
        return None

    after_low = float(after_pivot["最低"].min())
    latest = raw.iloc[-1]
    latest_high = float(latest["最高"])

    # 曾跌破中枢下沿
    if after_low >= pivot.zd * (1 - breakdown_pct):
        return None

    # 反弹未站回中枢
    if latest_high > pivot.zd * (1 + rally_tolerance):
        return None

    # MA空头排列
    if pd.isna(latest.get("MA5")) or pd.isna(latest.get("MA10")) or pd.isna(latest.get("MA20")):
        return None
    if not (latest["MA5"] < latest["MA10"] < latest["MA20"]):
        return None

    # 跌破MA5
    if latest["收盘"] >= latest["MA5"]:
        return None

    # 跌破前6根低点
    recent_6_low = raw["最低"].shift(1).rolling(6).min().iloc[-1]
    if pd.isna(recent_6_low) or latest["收盘"] >= recent_6_low:
        return None

    # 放量
    vol20 = latest.get("VOL20")
    if pd.isna(vol20) or vol20 <= 0 or latest["成交量"] < vol20 * volume_multiplier:
        return None

    confidence = 0.85

    return SellPoint(
        type="3S",
        index=len(raw) - 1,
        time=latest.get("datetime"),
        price=float(latest["收盘"]),
        pivot=pivot,
        confidence=confidence,
        reason=f"三卖: 中枢下沿{pivot.zd:.1f}, 反弹高{latest_high:.1f}, 跌破低{after_low:.1f}",
    )


# ══════════════════════════════════════════════════════════════════
# 一键检测所有卖点
# ══════════════════════════════════════════════════════════════════

def detect_all_sell_points(
    df30: pd.DataFrame,
    enable_1s: bool = True,
    enable_2s: bool = True,
    enable_3s: bool = True,
) -> Tuple[ChanlunContext, List[SellPoint]]:
    """
    一键检测30分钟级别的所有缠论卖点。

    Args:
        df30: K线 DataFrame
        enable_1s/2s/3s: 开关

    Returns:
        (缠论上下文, 卖点列表)
    """
    ctx = analyze(df30)
    sell_points: List[SellPoint] = []

    if enable_1s:
        sp = detect_first_sell(ctx)
        if sp:
            sell_points.append(sp)

    if enable_2s:
        sp = detect_second_sell(ctx)
        if sp:
            sell_points.append(sp)

    if enable_3s:
        sp = detect_third_sell(ctx)
        if sp:
            sell_points.append(sp)

    ctx.sell_points = sell_points
    return ctx, sell_points
