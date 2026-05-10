from __future__ import annotations

import pandas as pd

from .base_strategy import BaseDailyStrategy

class VShapeReversalStrategy(BaseDailyStrategy):
    """N22-V型反转：急跌后放量反弹，最佳持仓4天，胜率67.27%。"""

    name = "V型反转"
    category = "突破反转"

    def match(self, row: pd.Series) -> bool:
        dist_40d = row["收盘"] / row["过去40日最低价"] - 1
        if dist_40d >= 0.15:
            return False
        if row["昨涨跌"] >= -1:
            return False
        return (
            row["涨跌幅"] > 4
            and row["成交量"] > row["过去20日平均成交量"] * 1.8
            and row["收盘"] > row["开盘"]
        )
        
class BoxBreakoutStrategy(BaseDailyStrategy):
    """策略1：箱体突破。"""

    name = "箱体突破"
    category = "突破反转"

    def match(self, row: pd.Series) -> bool:
        return (
            row["收盘"] > row["过去60日最高价"]
            and row["成交量"] > row["过去20日平均成交量"] * 1.3
            and row["过去20日实体振幅"] <= 0.20
        )


class BottomVolumeReversalStrategy(BaseDailyStrategy):
    """策略2：底部放量反转。"""

    name = "底部放量反转"
    category = "突破反转"

    def match(self, row: pd.Series) -> bool:
        distance_from_40d_low = row["收盘"] / row["过去40日最低价"] - 1
        return (
            distance_from_40d_low < 0.20
            and row["涨跌幅"] > 5
            and row["成交量"] > row["过去20日平均成交量"] * 2
        )


class MainBoxBreakoutStrategy(BaseDailyStrategy):
    """主升策略1：股价创60天新高，伴随放量。"""

    name = "主升-箱体突破"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        return (
            row["收盘"] > row["过去60日最高收盘"]
            and row["成交量"] > row["过去20日平均成交量"] * 1.5
        )


class MainBottomVolumeReversalStrategy(BaseDailyStrategy):
    """主升策略2：长期低位 + 突然放量大涨。"""

    name = "主升-底部放量反转"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        distance_from_low = row["收盘"] / row["过去60日最低收盘"] - 1
        return (
            distance_from_low < 0.30
            and row["涨跌幅"] > 5
            and row["成交量"] > row["过去20日平均成交量"] * 2
        )


class MainPullbackStartStrategy(BaseDailyStrategy):
    """主升策略3：缩量回调启动。"""

    name = "主升-缩量回调启动"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        return (
            row["SMA5"] < row["SMA20"]
            and row["SMA60"] > row["SMA60_5日前"]
            and row["收盘"] > row["SMA5"]
            and row["成交量"] > row["过去20日平均成交量"] * 1.5
        )


class MainBullishMAAlignmentStrategy(BaseDailyStrategy):
    """主升策略4：均线多头排列。"""

    name = "主升-均线多头排列"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        return (
            row["SMA5"] > row["SMA10"]
            and row["SMA10"] > row["SMA20"]
            and row["SMA20"] > row["SMA60"]
            and row["涨跌幅"] > 2
            and row["成交量"] > row["过去20日平均成交量"] * 1.2
        )
