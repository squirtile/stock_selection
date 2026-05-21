# strategies/chanlun_strategies.py
# 简化缠论分钟级买点策略
#
# 说明：
# 1. 这是一套工程化、可量化运行的简化缠论策略，不是完整缠论原文的逐字复刻；
# 2. 目标是把“一买、二买、三买”接入你现在的分钟级B点模块；
# 3. 输入数据兼容当前 minute_strategy.py 的分钟K线字段：datetime、开盘、最高、最低、收盘、成交量、成交额；
# 4. 这三个策略都继承 BaseMinuteStrategy，可在 strategies/registry.py 统一注册和开关。

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .base_strategy import BaseMinuteStrategy
from .minute_strategies import prepare_minute_data


@dataclass
class ChanlunStroke:
    """简化笔结构。"""

    start_index: int
    end_index: int
    start_time: object
    end_time: object
    direction: str  # up / down
    start_price: float
    end_price: float
    high: float
    low: float
    bars: int
    macd_area: float


@dataclass
class ChanlunPivot:
    """简化中枢结构。"""

    start_index: int
    end_index: int
    lower: float
    upper: float
    high: float
    low: float


class ChanlunMixin:
    """
    缠论公共工具。

    主要包括：
    - K线去包含
    - 分型识别
    - 笔生成
    - 中枢识别
    - MACD力度辅助计算
    """

    support_groups = ("主升趋势类", "突破类", "放量启动类", "其他")

    def support(self, daily_group: str) -> bool:
        """缠论买点默认对所有日线分组开放。"""
        return True

    def prepare_chanlun_data(self, df: pd.DataFrame) -> pd.DataFrame:
        data = prepare_minute_data(df)

        if data is None or data.empty:
            return pd.DataFrame()

        data = data.copy().reset_index(drop=True)

        # MACD 用于简化背驰力度判断。
        ema12 = data["收盘"].ewm(span=12, adjust=False).mean()
        ema26 = data["收盘"].ewm(span=26, adjust=False).mean()
        data["DIF"] = ema12 - ema26
        data["DEA"] = data["DIF"].ewm(span=9, adjust=False).mean()
        data["MACD"] = (data["DIF"] - data["DEA"]) * 2

        return data

    def remove_include(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        简化K线包含处理。

        上升方向合并：高点取高，低点取高。
        下降方向合并：高点取低，低点取低。
        """

        if df is None or len(df) < 3:
            return df.copy() if df is not None else pd.DataFrame()

        rows = []

        for _, row in df.iterrows():
            item = row.to_dict()

            if not rows:
                rows.append(item)
                continue

            prev = rows[-1]
            prev_high = prev["最高"]
            prev_low = prev["最低"]
            cur_high = item["最高"]
            cur_low = item["最低"]

            is_include = (
                (cur_high <= prev_high and cur_low >= prev_low)
                or (cur_high >= prev_high and cur_low <= prev_low)
            )

            if not is_include:
                rows.append(item)
                continue

            if len(rows) >= 2:
                before = rows[-2]
                direction_up = prev["最高"] >= before["最高"]
            else:
                direction_up = item["收盘"] >= prev["收盘"]

            merged = prev.copy()

            if direction_up:
                merged["最高"] = max(prev_high, cur_high)
                merged["最低"] = max(prev_low, cur_low)
            else:
                merged["最高"] = min(prev_high, cur_high)
                merged["最低"] = min(prev_low, cur_low)

            merged["datetime"] = item.get("datetime", prev.get("datetime"))
            merged["收盘"] = item.get("收盘", prev.get("收盘"))
            merged["成交量"] = prev.get("成交量", 0) + item.get("成交量", 0)

            if "成交额" in item:
                merged["成交额"] = prev.get("成交额", 0) + item.get("成交额", 0)

            rows[-1] = merged

        return pd.DataFrame(rows).reset_index(drop=True)

    def find_fractals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        顶/底分型识别。
        """

        data = df.copy().reset_index(drop=True)
        data["分型"] = ""

        if len(data) < 5:
            return data

        for i in range(1, len(data) - 1):
            left = data.iloc[i - 1]
            mid = data.iloc[i]
            right = data.iloc[i + 1]

            top = (
                mid["最高"] > left["最高"]
                and mid["最高"] > right["最高"]
                and mid["最低"] >= left["最低"]
                and mid["最低"] >= right["最低"]
            )

            bottom = (
                mid["最低"] < left["最低"]
                and mid["最低"] < right["最低"]
                and mid["最高"] <= left["最高"]
                and mid["最高"] <= right["最高"]
            )

            if top:
                data.at[i, "分型"] = "顶"
            elif bottom:
                data.at[i, "分型"] = "底"

        return data

    def build_strokes(self, df: pd.DataFrame) -> List[ChanlunStroke]:
        """
        由顶/底分型生成简化笔。
        """

        if df is None or df.empty or "分型" not in df.columns:
            return []

        fractals = []

        for i, row in df.iterrows():
            ftype = row.get("分型", "")
            if ftype not in {"顶", "底"}:
                continue

            price = row["最高"] if ftype == "顶" else row["最低"]
            fractals.append(
                {
                    "index": i,
                    "type": ftype,
                    "price": float(price),
                    "time": row.get("datetime", i),
                }
            )

        if len(fractals) < 2:
            return []

        # 连续同类分型，保留更极端的那个。
        cleaned = []
        for item in fractals:
            if not cleaned:
                cleaned.append(item)
                continue

            last = cleaned[-1]
            if item["type"] == last["type"]:
                if item["type"] == "顶" and item["price"] > last["price"]:
                    cleaned[-1] = item
                elif item["type"] == "底" and item["price"] < last["price"]:
                    cleaned[-1] = item
            else:
                cleaned.append(item)

        strokes: List[ChanlunStroke] = []

        for prev, cur in zip(cleaned[:-1], cleaned[1:]):
            if abs(cur["index"] - prev["index"]) < 3:
                continue

            if prev["type"] == "底" and cur["type"] == "顶":
                direction = "up"
            elif prev["type"] == "顶" and cur["type"] == "底":
                direction = "down"
            else:
                continue

            start_i = int(prev["index"])
            end_i = int(cur["index"])
            segment = df.iloc[min(start_i, end_i): max(start_i, end_i) + 1]

            if "MACD" in segment.columns:
                if direction == "down":
                    macd_area = float(segment["MACD"].clip(upper=0).abs().sum())
                else:
                    macd_area = float(segment["MACD"].clip(lower=0).sum())
            else:
                macd_area = 0.0

            strokes.append(
                ChanlunStroke(
                    start_index=start_i,
                    end_index=end_i,
                    start_time=prev["time"],
                    end_time=cur["time"],
                    direction=direction,
                    start_price=float(prev["price"]),
                    end_price=float(cur["price"]),
                    high=float(segment["最高"].max()),
                    low=float(segment["最低"].min()),
                    bars=len(segment),
                    macd_area=macd_area,
                )
            )

        return strokes

    def find_latest_pivot(self, strokes: List[ChanlunStroke]) -> Optional[ChanlunPivot]:
        """
        最近连续3笔存在价格区间重叠，则视为中枢。
        """

        if len(strokes) < 3:
            return None

        latest_pivot = None

        for i in range(0, len(strokes) - 2):
            group = strokes[i:i + 3]
            lower = max(s.low for s in group)
            upper = min(s.high for s in group)

            if lower <= upper:
                latest_pivot = ChanlunPivot(
                    start_index=group[0].start_index,
                    end_index=group[-1].end_index,
                    lower=float(lower),
                    upper=float(upper),
                    high=float(max(s.high for s in group)),
                    low=float(min(s.low for s in group)),
                )

        return latest_pivot

    def get_chanlun_context(self, df5: pd.DataFrame):
        raw = self.prepare_chanlun_data(df5)

        if raw is None or raw.empty:
            return raw, pd.DataFrame(), []

        no_include = self.remove_include(raw)
        no_include = self.prepare_chanlun_data(no_include)
        fractal_df = self.find_fractals(no_include)
        strokes = self.build_strokes(fractal_df)

        return raw, fractal_df, strokes

    def check_5m_trend_guard(self, raw: pd.DataFrame) -> bool:
        """
        缠论买点的统一趋势保护。

        目的：过滤5分钟均线下方的弱反抽，避免把下跌中继误判为一买/二买/三买。
        """
        if raw is None or len(raw) < 30:
            return False

        latest = raw.iloc[-1]

        if pd.isna(latest[["MA5", "MA10", "MA20", "VOL20"]]).any():
            return False

        price_ok = latest["收盘"] > latest["MA10"] and latest["收盘"] > latest["MA20"]
        ma_structure_ok = latest["MA5"] >= latest["MA10"] * 0.998
        ma5_slope_ok = latest["MA5"] > raw["MA5"].iloc[-4]
        ma10_slope_ok = latest["MA10"] >= raw["MA10"].iloc[-4] * 0.998

        # 当前价格不能离最近一小时高点太远，过滤一路下跌后的弱反抽。
        recent_12_high_close = raw["收盘"].iloc[-12:].max()
        not_weak_rebound = latest["收盘"] >= recent_12_high_close * 0.985

        return bool(price_ok and ma_structure_ok and ma5_slope_ok and ma10_slope_ok and not_weak_rebound)


class ChanlunFirstBuyMinuteStrategy(ChanlunMixin, BaseMinuteStrategy):
    enabled = False

    """
    缠论一买：下跌末端背驰后的反转买点。

    工程化定义：
    1. 最近存在两段下跌笔；
    2. 后一段下跌创新低，但MACD下跌力度不再放大；
    3. 最新5分钟K线重新站上MA5，并突破前一根高点；
    4. 成交量温和放大。

    注意：一买偏左侧，风险最大，建议作为辅助信号看待。
    """

    name = "缠论一买B点"

    def __init__(
        self,
        min_bars: int = 80,
        min_down_strokes: int = 2,
        divergence_ratio: float = 0.85,
        volume_multiplier: float = 1.20,
    ):
        self.min_bars = min_bars
        self.min_down_strokes = min_down_strokes
        self.divergence_ratio = divergence_ratio
        self.volume_multiplier = volume_multiplier

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        raw, _, strokes = self.get_chanlun_context(df5)

        if raw is None or len(raw) < self.min_bars:
            return False

        if not self.check_5m_trend_guard(raw):
            return False

        down_strokes = [s for s in strokes if s.direction == "down"]
        if len(down_strokes) < self.min_down_strokes:
            return False

        prev_down = down_strokes[-2]
        last_down = down_strokes[-1]

        latest = raw.iloc[-1]
        prev = raw.iloc[-2]

        # 价格创新低，但MACD绿柱面积没有同步放大，认为出现简化底背驰。
        price_new_low = last_down.low < prev_down.low
        macd_weaker = last_down.macd_area <= prev_down.macd_area * self.divergence_ratio

        ma_recover = (
            pd.notna(latest.get("MA5"))
            and pd.notna(latest.get("MA10"))
            and latest["收盘"] > latest["MA5"]
            and latest["MA5"] >= latest["MA10"] * 0.998
        )

        recent_high = raw["最高"].shift(1).rolling(6).max().iloc[-1]
        restart = pd.notna(recent_high) and latest["收盘"] > recent_high

        vol20 = latest.get("VOL20")
        volume_ok = pd.notna(vol20) and vol20 > 0 and latest["成交量"] >= vol20 * self.volume_multiplier

        return bool(price_new_low and macd_weaker and ma_recover and restart and volume_ok)


class ChanlunSecondBuyMinuteStrategy(ChanlunMixin, BaseMinuteStrategy):
    """
    缠论二买：一买反弹后的回踩确认。

    工程化定义：
    1. 近一段出现反弹后回调；
    2. 回调低点不跌破前低；
    3. 最新5分钟K线重新站上MA5，并突破前一根高点；
    4. 成交量放大。
    """

    name = "缠论二买B点"

    def __init__(
        self,
        min_bars: int = 70,
        low_tolerance: float = 0.005,
        volume_multiplier: float = 1.20,
    ):
        self.min_bars = min_bars
        self.low_tolerance = low_tolerance
        self.volume_multiplier = volume_multiplier

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        raw, _, strokes = self.get_chanlun_context(df5)

        if raw is None or len(raw) < self.min_bars or len(strokes) < 4:
            return False

        if not self.check_5m_trend_guard(raw):
            return False

        latest = raw.iloc[-1]
        prev = raw.iloc[-2]

        # 最近30根低点不明显跌破前30根低点，作为“二买不创新低”的量化近似。
        recent_low = float(raw["最低"].iloc[-30:].min())
        prior_low = float(raw["最低"].iloc[-60:-30].min()) if len(raw) >= 60 else float(raw["最低"].iloc[:-30].min())
        no_new_low = recent_low >= prior_low * (1 - self.low_tolerance)

        ma_recover = pd.notna(latest.get("MA5")) and latest["收盘"] > latest["MA5"]
        restart = latest["收盘"] > prev["最高"]

        vol20 = latest.get("VOL20")
        volume_ok = pd.notna(vol20) and vol20 > 0 and latest["成交量"] >= vol20 * self.volume_multiplier

        # 最近最后一笔最好是向上，表示回踩后重新反弹。
        last_stroke_up = strokes[-1].direction == "up"

        return bool(no_new_low and ma_recover and restart and volume_ok and last_stroke_up)


class ChanlunThirdBuyMinuteStrategy(ChanlunMixin, BaseMinuteStrategy):
    """
    缠论三买：突破中枢后的回踩确认。

    工程化定义：
    1. 最近多笔形成中枢；
    2. 中枢后曾向上离开；
    3. 当前回踩不明显跌回中枢上沿；
    4. 最新5分钟K线重新站上MA5，并突破前一根高点；
    5. 成交量温和放大。

    这一个最适合你当前“日线主升候选 + 分钟B点确认”的工程。
    """

    name = "缠论三买B点"

    def __init__(
        self,
        min_bars: int = 80,
        min_strokes: int = 5,
        pullback_tolerance: float = 0.01,
        breakout_pct: float = 0.015,
        volume_multiplier: float = 1.15,
    ):
        self.min_bars = min_bars
        self.min_strokes = min_strokes
        self.pullback_tolerance = pullback_tolerance
        self.breakout_pct = breakout_pct
        self.volume_multiplier = volume_multiplier

    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        raw, _, strokes = self.get_chanlun_context(df5)

        if raw is None or len(raw) < self.min_bars or len(strokes) < self.min_strokes:
            return False

        if not self.check_5m_trend_guard(raw):
            return False

        pivot = self.find_latest_pivot(strokes)
        if pivot is None:
            return False

        latest = raw.iloc[-1]
        prev = raw.iloc[-2]

        after_start = min(pivot.end_index + 1, len(raw) - 1)
        after_pivot_df = raw.iloc[after_start:].copy()

        if after_pivot_df.empty:
            return False

        after_high = float(after_pivot_df["最高"].max())
        latest_low = float(latest["最低"])

        breakout_ok = after_high > pivot.upper * (1 + self.breakout_pct)
        pullback_ok = latest_low >= pivot.upper * (1 - self.pullback_tolerance)

        ma_recover = (
            pd.notna(latest.get("MA5"))
            and pd.notna(latest.get("MA10"))
            and pd.notna(latest.get("MA20"))
            and latest["收盘"] > latest["MA5"]
            and latest["收盘"] > latest["MA10"]
            and latest["收盘"] > latest["MA20"]
            and latest["MA5"] >= latest["MA10"] * 0.998
        )

        recent_high = raw["最高"].shift(1).rolling(6).max().iloc[-1]
        restart = pd.notna(recent_high) and latest["收盘"] > recent_high

        vol20 = latest.get("VOL20")
        volume_ok = pd.notna(vol20) and vol20 > 0 and latest["成交量"] >= vol20 * self.volume_multiplier

        return bool(breakout_ok and pullback_ok and ma_recover and restart and volume_ok)
