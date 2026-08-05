# strategies/chanlun/utils.py
"""
缠论公用工具函数。

包括：MACD计算、均线、量能分析、数据准备。
输入：统一格式的分钟/日线 DataFrame（datetime, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 代码）
输出：追加了技术指标的 DataFrame
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    准备分钟K线数据：类型转换、排序、计算MA/MACD/VOL20。

    输入格式与 minute_data.py 输出一致：
      datetime, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 代码
    """
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 均线
    if "收盘" in df.columns:
        df["MA5"] = df["收盘"].rolling(5).mean()
        df["MA10"] = df["收盘"].rolling(10).mean()
        df["MA20"] = df["收盘"].rolling(20).mean()
        df["MA60"] = df["收盘"].rolling(60).mean()
        df["MA250"] = df["收盘"].rolling(250).mean()

    # 量能
    if "成交量" in df.columns:
        df["VOL5"] = df["成交量"].rolling(5).mean()
        df["VOL20"] = df["成交量"].shift(1).rolling(20).mean()

    # MACD (12, 26, 9)
    if "收盘" in df.columns:
        ema12 = df["收盘"].ewm(span=12, adjust=False).mean()
        ema26 = df["收盘"].ewm(span=26, adjust=False).mean()
        df["DIF"] = ema12 - ema26
        df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
        df["MACD"] = (df["DIF"] - df["DEA"]) * 2
        df["MACD_柱"] = df["MACD"]  # 别名

    return df


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    独立 MACD 计算，返回 (DIF, DEA, MACD柱)。

    可用于非 DataFrame 场景。
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bar = (dif - dea) * 2
    return dif, dea, macd_bar


def find_golden_cross(dif: pd.Series, dea: pd.Series) -> pd.Series:
    """
    找 MACD 金叉点（DIF 上穿 DEA）。

    Returns: bool Series, True=金叉日
    """
    return (dif > dea) & (dif.shift(1) <= dea.shift(1))


def find_death_cross(dif: pd.Series, dea: pd.Series) -> pd.Series:
    """
    找 MACD 死叉点（DIF 下穿 DEA）。
    """
    return (dif < dea) & (dif.shift(1) >= dea.shift(1))


def find_bottom_divergence(
    df: pd.DataFrame,
    lookback: int = 60,
    price_low_col: str = "最低",
    indicator_col: str = "DIF",
    price_tolerance: float = 0.02,
) -> tuple[bool, dict]:
    """
    检测底背离：价格新低，但指标拒绝新低。

    在最近 lookback 根K线内：
    1. 找两个低点区间（各5根K线的局部最低）
    2. 后一个低点的价格 < 前一个低点（价格新低）
    3. 后一个低点的指标值 > 前一个低点（指标拒绝新低）

    Args:
        df: 含价格列和指标列的 DataFrame
        lookback: 回溯K线数
        price_low_col: 价格列名（通常用"最低"）
        indicator_col: 指标列名（通常用"DIF"）
        price_tolerance: 价格容忍度，两个低点价格差 < tolerance 也视为背离

    Returns:
        (是否底背离, {详情})
    """
    if df is None or len(df) < lookback:
        return False, {}

    recent = df.tail(lookback).copy().reset_index(drop=True)
    n = len(recent)

    # 分前后两半找局部最低
    mid = n // 2
    first_half = recent.iloc[:mid]
    second_half = recent.iloc[mid:]

    if len(first_half) < 5 or len(second_half) < 5:
        return False, {}

    # 前段：找指标最低值的位置（-20~-10根附近）
    first_indicator_min_idx = first_half[indicator_col].idxmin()
    first_price_at_indicator_min = first_half.loc[first_indicator_min_idx, price_low_col]
    first_indicator_val = first_half.loc[first_indicator_min_idx, indicator_col]

    # 后段：找价格最低值的位置（近10根内）
    second_price_min_idx = second_half[price_low_col].idxmin()
    second_price_val = second_half.loc[second_price_min_idx, price_low_col]
    second_indicator_val = second_half.loc[second_price_min_idx, indicator_col]

    # 价格新低（后段低点 < 前段低点 × (1+tolerance)）
    price_new_low = second_price_val < first_price_at_indicator_min * (1 + price_tolerance)

    # 指标拒绝新低（后段低点对应的指标 > 前段低点对应的指标）
    indicator_no_new_low = second_indicator_val > first_indicator_val

    is_divergence = price_new_low and indicator_no_new_low

    details = {
        "first_idx": first_indicator_min_idx,
        "second_idx": second_price_min_idx,
        "first_price": round(float(first_price_at_indicator_min), 4),
        "second_price": round(float(second_price_val), 4),
        "first_indicator": round(float(first_indicator_val), 6),
        "second_indicator": round(float(second_indicator_val), 6),
        "price_new_low": price_new_low,
        "indicator_no_new_low": indicator_no_new_low,
    }

    return is_divergence, details


def find_macd_golden_cross_divergence(
    df: pd.DataFrame,
    max_golden_cross_gap: int = 55,
    min_golden_cross_gap: int = 8,
    dif_improve_ratio: float = 0.15,
) -> tuple[bool, dict]:
    """
    检测 MACD 金叉底背离（日线 MACDGoldenCrossDivergenceStrategy 的30分钟版本）。

    逻辑：
    1. 找到最近两次 MACD 金叉
    2. 后一次金叉的 DIF > 前一次（DIF 底部抬高）
    3. 后一次金叉前价格更低 → 底背离

    Returns:
        (是否金叉底背离, {详情})
    """
    if df is None or len(df) < 60:
        return False, {}

    golden_cross = find_golden_cross(df["DIF"], df["DEA"])
    cross_indices = df.index[golden_cross].tolist()

    if len(cross_indices) < 2:
        return False, {}

    # 最近两次金叉
    rec1_idx = cross_indices[-1]  # 最近一次
    rec2_idx = cross_indices[-2]  # 倒数第二次

    # 检查间隔
    gap = rec1_idx - rec2_idx
    if gap < min_golden_cross_gap or gap > max_golden_cross_gap:
        return False, {}

    rec1_dif = float(df.loc[rec1_idx, "DIF"])
    rec2_dif = float(df.loc[rec2_idx, "DIF"])

    # DIF 抬高
    if rec2_dif == 0:
        return False, {}
    dif_improve = (rec1_dif - rec2_dif) / abs(rec2_dif)
    if dif_improve < dif_improve_ratio:
        return False, {}

    # 价格新低: 最近金叉前5根最低 vs 前次金叉前5根最低
    rec1_low_start = max(0, rec1_idx - 5)
    rec2_low_start = max(0, rec2_idx - 5)
    rec1_low = df.iloc[rec1_low_start:rec1_idx+1]["最低"].min()
    rec2_low = df.iloc[rec2_low_start:rec2_idx+1]["最低"].min()

    if rec2_low <= rec1_low:
        return False, {}

    details = {
        "rec1_golden_cross_idx": rec1_idx,
        "rec2_golden_cross_idx": rec2_idx,
        "rec1_dif": round(rec1_dif, 6),
        "rec2_dif": round(rec2_dif, 6),
        "dif_improve_pct": round(dif_improve * 100, 1),
        "rec1_low": round(float(rec1_low), 4),
        "rec2_low": round(float(rec2_low), 4),
    }

    return True, details


def calc_volume_profile(df: pd.DataFrame) -> dict:
    """
    简单的量价分析。

    Returns: {vol_ratio, is_shrinking, is_expanding, ...}
    """
    if df is None or len(df) < 20:
        return {}

    latest_vol = float(df["成交量"].iloc[-1])
    vol5 = float(df["VOL5"].iloc[-1]) if "VOL5" in df.columns else latest_vol
    vol20 = float(df["VOL20"].iloc[-1]) if "VOL20" in df.columns else latest_vol

    return {
        "latest_vol": latest_vol,
        "vol5": vol5,
        "vol20": vol20,
        "vol_ratio_5": round(latest_vol / vol5, 2) if vol5 > 0 else 0,
        "vol_ratio_20": round(latest_vol / vol20, 2) if vol20 > 0 else 0,
        "is_expanding": latest_vol > vol5 * 1.2 if vol5 > 0 else False,
        "is_shrinking": latest_vol < vol5 * 0.6 if vol5 > 0 else False,
    }
