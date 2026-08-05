# strategies/minute_divergence.py
"""
个股分钟底背离策略（30分钟级别）。

基于30分钟 MACD 检测底部背离，作为日线策略信号的分钟级确认。

与日线 MACDGoldenCrossDivergenceStrategy 的区别：
- 日线版本：基于日K线的双金叉 DIF/价格背离，中长线信号
- 分钟版本：基于30分钟K线，更灵敏，适合短线/波段确认

两种检测模式：
1. DIF 底背离：价格新低但 DIF 拒绝新低（标准底背离）
2. MACD 金叉底背离：两次金叉间 DIF 抬高 + 价格降低（与日线策略一致）
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import pandas as pd
import numpy as np

from .base_strategy import BaseMinuteStrategy, MinuteStrategySignal
from .chanlun.utils import (
    prepare_data,
    find_bottom_divergence,
    find_macd_golden_cross_divergence,
)

STOCK_MINUTE_DIR = "cache/minute"


def _load_stock_minute(code: str, frequency: str = "30") -> pd.DataFrame:
    """加载个股分钟缓存。"""
    code = str(code).zfill(6)
    cache_file = os.path.join(STOCK_MINUTE_DIR, f"{code}_{frequency}m.csv")
    if not os.path.exists(cache_file):
        return pd.DataFrame()
    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        return df
    except Exception:
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════
# 30分钟 DIF 底背离策略
# ══════════════════════════════════════════════════════════════════

class MinuteDIFDivergenceStrategy(BaseMinuteStrategy):
    """
    30分钟 DIF 底背离策略。

    检测30分钟级别 MACD DIF 与价格的底背离：
    - 价格创近60根K线新低
    - DIF 拒绝跟随新低（比前低点的 DIF 更高）
    - 站上 MA5 / MA10
    - 放量确认

    适用场景：日线策略信号发出后，用分钟底背离做B点确认。
    """

    name = "30分钟DIF底背离"
    support_groups = ("突破反转", "底背离", "主升趋势类", "放量启动类", "突破类", "其他")

    def __init__(
        self,
        lookback_bars: int = 60,
        volume_multiplier: float = 1.15,
    ):
        self.lookback_bars = lookback_bars
        self.volume_multiplier = volume_multiplier

    def support(self, daily_group: str) -> bool:
        return True  # 对所有日线分组开放

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        """
        检测30分钟 DIF 底背离。

        使用 df30 数据（忽略 df5）。
        """
        df = prepare_data(df30)
        if df is None or len(df) < self.lookback_bars:
            return False

        # DIF 底背离检测
        is_div, details = find_bottom_divergence(df, lookback=self.lookback_bars)
        if not is_div:
            return False

        # 站上 MA5
        latest = df.iloc[-1]
        if pd.isna(latest.get("MA5")) or latest["收盘"] <= latest["MA5"]:
            return False

        # MA5 趋势：不能是加速下跌
        if pd.isna(latest.get("MA10")):
            return False

        # 放量确认
        vol20 = latest.get("VOL20")
        if pd.isna(vol20) or vol20 <= 0:
            return False
        if latest["成交量"] < vol20 * self.volume_multiplier:
            return False

        return True

    def evaluate(
        self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame,
        daily_group: str = ""
    ) -> Optional[MinuteStrategySignal]:
        if not self.enabled:
            return None
        try:
            if self.match(row, df5, df30):
                df = prepare_data(df30)
                _, details = find_bottom_divergence(df, lookback=self.lookback_bars)
                dif_rise = details.get("second_indicator", 0) - details.get("first_indicator", 0)
                return MinuteStrategySignal(
                    name=self.name,
                    group=daily_group,
                    reason=f"DIF底背离(DIF抬高{dif_rise:+.4f})",
                )
        except Exception:
            return None
        return None


# ══════════════════════════════════════════════════════════════════
# 30分钟 MACD 金叉底背离策略
# ══════════════════════════════════════════════════════════════════

class MinuteGoldenCrossDivergenceStrategy(BaseMinuteStrategy):
    """
    30分钟 MACD 金叉底背离策略。

    逻辑与日线 MACDGoldenCrossDivergenceStrategy 一致，但应用于30分钟级别：
    1. 找到最近两次30分钟 MACD 金叉
    2. 后一次金叉的 DIF > 前一次（DIF 抬高 ≥ 15%）
    3. 后一次金叉前价格最低 < 前一次（价格新低）
    4. 今日 DIF > DEA（金叉结构保持）
    5. 站上 MA5 / MA10
    6. 放量确认

    比 DIF 底背离更严格（需要两次金叉结构），信号量更少但质量更高。
    """

    name = "30分钟MACD金叉底背离"
    support_groups = ("突破反转", "底背离", "主升趋势类", "放量启动类", "突破类", "其他")

    def __init__(
        self,
        max_golden_cross_gap: int = 55,
        min_golden_cross_gap: int = 5,
        dif_improve_ratio: float = 0.12,
        volume_multiplier: float = 1.20,
    ):
        self.max_golden_cross_gap = max_golden_cross_gap
        self.min_golden_cross_gap = min_golden_cross_gap
        self.dif_improve_ratio = dif_improve_ratio
        self.volume_multiplier = volume_multiplier

    def support(self, daily_group: str) -> bool:
        return True

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        df = prepare_data(df30)
        if df is None or len(df) < 60:
            return False

        # 金叉底背离检测
        is_div, details = find_macd_golden_cross_divergence(
            df,
            max_golden_cross_gap=self.max_golden_cross_gap,
            min_golden_cross_gap=self.min_golden_cross_gap,
            dif_improve_ratio=self.dif_improve_ratio,
        )
        if not is_div:
            return False

        # 今日 DIF > DEA（金叉结构保持）
        latest = df.iloc[-1]
        if pd.isna(latest.get("DIF")) or pd.isna(latest.get("DEA")):
            return False
        if latest["DIF"] <= latest["DEA"]:
            return False

        # DIF 在底部区域（零轴下方或刚上零轴）
        if latest["DIF"] > 0.5:
            return False

        # 站上 MA5
        if pd.isna(latest.get("MA5")) or latest["收盘"] <= latest["MA5"]:
            return False

        # MA5 在 MA10 上方或接近
        if pd.isna(latest.get("MA10")):
            return False

        # 放量确认
        vol20 = latest.get("VOL20")
        if pd.isna(vol20) or vol20 <= 0:
            return False
        if latest["成交量"] < vol20 * self.volume_multiplier:
            return False

        # 非涨停追高
        pct = float(row.get("涨跌幅", 0)) if "涨跌幅" in row.index else 0
        if pct >= 9.5:
            return False

        return True

    def evaluate(
        self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame,
        daily_group: str = ""
    ) -> Optional[MinuteStrategySignal]:
        if not self.enabled:
            return None
        try:
            if self.match(row, df5, df30):
                df = prepare_data(df30)
                _, details = find_macd_golden_cross_divergence(df)
                dif_improve = details.get("dif_improve_pct", 0)
                return MinuteStrategySignal(
                    name=self.name,
                    group=daily_group,
                    reason=f"金叉底背离(DIF抬高{dif_improve:.0f}%)",
                )
        except Exception:
            return None
        return None


# ══════════════════════════════════════════════════════════════════
# 便捷函数：单股分钟底背离检测
# ══════════════════════════════════════════════════════════════════

def check_stock_minute_divergence(code: str, frequency: str = "30") -> dict:
    """
    检测单只股票的分钟底背离（不依赖策略框架，可直接调用）。

    Args:
        code: 股票代码
        frequency: 分钟周期，"30" 或 "60"

    Returns:
        {
            "code": "000001",
            "has_data": True/False,
            "dif_divergence": True/False,
            "golden_cross_divergence": True/False,
            "latest_price": 11.44,
            "latest_time": "2026-08-04 15:00:00",
        }
    """
    code = str(code).zfill(6)
    df = _load_stock_minute(code, frequency)

    if df is None or df.empty:
        return {"code": code, "has_data": False}

    df = prepare_data(df)
    if df is None or len(df) < 60:
        return {"code": code, "has_data": True, "bars": len(df),
                "dif_divergence": False, "golden_cross_divergence": False}

    is_dif_div, _ = find_bottom_divergence(df)
    is_gc_div, _ = find_macd_golden_cross_divergence(df)

    latest = df.iloc[-1]
    return {
        "code": code,
        "has_data": True,
        "bars": len(df),
        "dif_divergence": is_dif_div,
        "golden_cross_divergence": is_gc_div,
        "latest_price": round(float(latest["收盘"]), 2),
        "latest_time": str(latest.get("datetime", "")),
    }
