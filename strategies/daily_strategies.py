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


# class MainBoxBreakoutStrategy(BaseDailyStrategy):
#     """主升策略1：股价创60天新高，伴随放量。"""

#     name = "主升-箱体突破"
#     category = "主升"

#     def match(self, row: pd.Series) -> bool:
#         return (
#             row["收盘"] > row["过去60日最高收盘"]
#             and row["成交量"] > row["过去20日平均成交量"] * 1.5
#         )


# class MainBottomVolumeReversalStrategy(BaseDailyStrategy):
#     """主升策略2：长期低位 + 突然放量大涨。"""

#     name = "主升-底部放量反转"
#     category = "主升"

#     def match(self, row: pd.Series) -> bool:
#         distance_from_low = row["收盘"] / row["过去60日最低收盘"] - 1
#         return (
#             distance_from_low < 0.30
#             and row["涨跌幅"] > 5
#             and row["成交量"] > row["过去20日平均成交量"] * 2
#         )


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


class MainBigYangPullbackNoBreakStrategy(BaseDailyStrategy):
    """
    主升策略5：3-5日前大阳启动，随后缩量回调不破10日线。

    逻辑：
    1. 最近5个交易日内，不含今日，出现过涨幅 >= 8%的放量大阳线；
    2. 启动大阳线发生在3-5个交易日前；
    3. 启动大阳线收盘价站上5日线和10日线；
    4. 启动后回撤不深；
    5. 启动后至今，回调阶段不有效跌破10日线；
    6. 回调阶段成交量明显缩小；
    7. 当前仍在10日线附近上方；
    8. 当前涨幅不能过高，避免已经拉板后追高。
    """

    name = "主升-大阳回调不破10日线"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        need_cols = [
            "近5日是否有8点大阳启动",
            "启动大阳距今天数",
            "启动后回撤不深",
            "近5日不破10日线",
            "回调缩量",
            "当前不破10日线",
            "涨跌幅",
        ]

        for col in need_cols:
            if col not in row.index or pd.isna(row[col]):
                return False

        return bool(
            row["近5日是否有8点大阳启动"]
            and 3 <= row["启动大阳距今天数"] <= 5
            and row["启动后回撤不深"]
            and row["近5日不破10日线"]
            and row["回调缩量"]
            and row["当前不破10日线"]
            and row["涨跌幅"] < 9.5
        )
