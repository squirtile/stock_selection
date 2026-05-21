from __future__ import annotations

import pandas as pd

from .base_strategy import BaseMinuteStrategy


def prepare_minute_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算分钟级B点所需指标。

    这里单独放到策略模块，避免 minute_strategy.py 里既放数据获取又放策略判断。
    后续无论分钟数据来自 BaoStock、Tushare stk_mins、rt_min，还是实时快照合成，
    只要字段统一为：开盘、最高、最低、收盘、成交量、成交额，就可以复用这里的策略。
    """

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])
    df = df.sort_values("datetime")

    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["MA5"] = df["收盘"].rolling(5).mean()
    df["MA10"] = df["收盘"].rolling(10).mean()
    df["MA20"] = df["收盘"].rolling(20).mean()
    df["VOL20"] = df["成交量"].shift(1).rolling(20).mean()

    df["前12根最高"] = df["最高"].shift(1).rolling(12).max()
    df["前12根最低"] = df["最低"].shift(1).rolling(12).min()
    df["前12根振幅"] = df["前12根最高"] / df["前12根最低"] - 1

    return df


def check_30m_structure(df30: pd.DataFrame) -> tuple[bool, str]:
    """
    30分钟结构过滤：判断盘中是否具备基本趋势结构。
    这是分钟B点策略前的公共过滤，不算某一个具体B点。
    """

    df = prepare_minute_data(df30)

    if len(df) < 25:
        return False, "30分钟K线不足"

    latest = df.iloc[-1]

    if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
        return False, "30分钟指标不足"

    cond_ma = latest["收盘"] > latest["MA5"] and latest["MA5"] >= latest["MA10"]
    cond_vol = latest["成交量"] >= latest["VOL20"] * 0.8 if latest["VOL20"] > 0 else False

    if cond_ma and cond_vol:
        return True, "30分钟趋势结构有效"

    return False, "30分钟结构未确认"


class PullbackStartMinuteStrategy(BaseMinuteStrategy):
    """
    5分钟B点1：回踩均线后重新启动。
    适合日线主升趋势类股票。
    """

    name = "5分钟回踩均线启动"
    support_groups = ("主升趋势类",)

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        df = prepare_minute_data(df5)

        if len(df) < 30:
            return False

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        if pd.isna(latest[["MA5", "MA10", "MA20", "VOL20"]]).any():
            return False

        trend_ok = latest["MA5"] > latest["MA10"] > latest["MA20"]
        pullback_ok = (
            prev["最低"] <= prev["MA10"] * 1.01
            or prev["最低"] <= prev["MA20"] * 1.01
        )
        restart_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"]
        volume_ok = latest["成交量"] > latest["VOL20"] * 1.10 if latest["VOL20"] > 0 else False

        return bool(trend_ok and pullback_ok and restart_ok and volume_ok)


class PlatformBreakoutMinuteStrategy(BaseMinuteStrategy):
    """
    5分钟B点2：平台突破确认。
    适合箱体突破、放量启动类股票。
    也作为“其他”分组的保底确认策略。
    """

    name = "5分钟平台突破确认"
    support_groups = ("突破类", "其他")

    def support(self, daily_group: str) -> bool:
        daily_group = "" if daily_group is None else str(daily_group)
        return "突破类" in daily_group or daily_group == "其他"

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        df = prepare_minute_data(df5)

        if len(df) < 30:
            return False

        latest = df.iloc[-1]

        if pd.isna(latest[["前12根最高", "前12根最低", "前12根振幅", "VOL20"]]).any():
            return False

        range_ok = latest["前12根振幅"] <= 0.04
        breakout_ok = latest["收盘"] > latest["前12根最高"]
        volume_ok = latest["成交量"] > latest["VOL20"] * 1.20 if latest["VOL20"] > 0 else False

        return bool(range_ok and breakout_ok and volume_ok)


class VolumeReversalMinuteStrategy(BaseMinuteStrategy):
    """
    5分钟B点3：放量反包确认。
    适合低位放量启动类股票。
    """

    name = "5分钟放量反包确认"
    support_groups = ("放量启动类",)

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        df = prepare_minute_data(df5)

        if len(df) < 30:
            return False

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
            return False

        intrabar_pct = latest["收盘"] / latest["开盘"] - 1 if latest["开盘"] > 0 else 0
        reverse_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"] and intrabar_pct >= 0.005
        volume_ok = latest["成交量"] > latest["VOL20"] * 1.30 if latest["VOL20"] > 0 else False

        return bool(reverse_ok and volume_ok)


class OneMinuteBuyStrategy(BaseMinuteStrategy):
    """
    1分钟入场观察。

    注意：
    - 这个策略不是自动买入依据，只是 30分钟趋势 + 5分钟结构/缠论B点通过后的最后一层触发；
    - 当前版本为保守版，重点过滤弱反抽、追高和单根冲高回落；
    - 建议结合盘口、分时均价线和止损位人工确认。
    """

    name = "1分钟入场观察"
    support_groups = ("主升趋势类", "突破类", "放量启动类", "其他")

    def support(self, daily_group: str) -> bool:
        # 1分钟确认策略对所有已经通过 30分钟和5分钟结构的候选开放
        return True

    def match(self, row: pd.Series, df1: pd.DataFrame, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        df1 = prepare_minute_data(df1)
        df5 = prepare_minute_data(df5)

        if len(df1) < 40 or len(df5) < 20:
            return False

        latest1 = df1.iloc[-1]
        latest5 = df5.iloc[-1]

        if pd.isna(latest1[["MA5", "MA10", "MA20", "VOL20"]]).any():
            return False

        if pd.isna(latest5[["MA5", "MA10", "MA20"]]).any():
            return False

        # 0. 日内涨幅不能太高，避免把1分钟信号变成追高信号。
        daily_pct = pd.to_numeric(row.get("涨跌幅", row.get("今日涨跌幅", pd.NA)), errors="coerce")
        daily_not_too_high = True if pd.isna(daily_pct) else daily_pct < 6.0

        # 1. 1分钟自身结构必须转强：收盘站上MA5/MA10，且MA5明确高于MA10。
        one_min_trend_ok = (
            latest1["收盘"] > latest1["MA5"]
            and latest1["收盘"] > latest1["MA10"]
            and latest1["MA5"] > latest1["MA10"]
        )

        # 2. 不能只突破上一根高点，必须突破最近3根1分钟K线高点。
        recent_3_high = df1["最高"].shift(1).rolling(3).max().iloc[-1]
        one_min_restart_ok = pd.notna(recent_3_high) and latest1["收盘"] > recent_3_high

        # 3. 不能离5分钟MA5太远，避免追涨；同时不能明显低于5分钟MA10。
        not_too_far_from_5m_ma5 = (
            latest5["MA5"] > 0
            and latest5["MA10"] > 0
            and latest1["收盘"] <= latest5["MA5"] * 1.015
            and latest1["收盘"] >= latest5["MA10"] * 0.995
        )

        # 4. 1分钟量能要有效放大，原来的1.05太容易被噪声触发。
        volume_ok = (
            latest1["VOL20"] > 0
            and latest1["成交量"] >= latest1["VOL20"] * 1.20
        )

        # 5. 当前1分钟K线不能是明显长上影，避免冲高回落。
        body = abs(latest1["收盘"] - latest1["开盘"])
        upper_shadow = latest1["最高"] - max(latest1["收盘"], latest1["开盘"])
        candle_ok = upper_shadow <= max(body, latest1["收盘"] * 0.0015) * 1.5

        # 6. 1分钟单根不能太弱，也不能瞬间拉太高。
        intrabar_pct = latest1["收盘"] / latest1["开盘"] - 1 if latest1["开盘"] > 0 else 0
        intrabar_ok = 0.001 <= intrabar_pct <= 0.020

        return bool(
            daily_not_too_high
            and one_min_trend_ok
            and one_min_restart_ok
            and not_too_far_from_5m_ma5
            and volume_ok
            and candle_ok
            and intrabar_ok
        )
