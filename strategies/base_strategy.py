from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategySignal:
    """
    单个策略命中结果。

    name: 策略名称，例如：箱体突破
    category: 策略分类，例如：突破反转 / 主升
    reason: 可选说明，方便后续导出或调试
    """

    name: str
    category: str
    reason: str = ""


class BaseDailyStrategy(ABC):
    """
    日线策略基类。

    新增策略时只需要：
    1. 继承 BaseDailyStrategy
    2. 设置 name / category / group / enabled
    3. 实现 match(row)
    4. 在 strategies/registry.py 里注册
    """

    name: str = "未命名策略"
    category: str = "其他"
    group: str = ""          # 策略分组，如"趋势跟踪"/"回调买入"/"突破"，用于小程序多级标签
    enabled: bool = True

    @abstractmethod
    def match(self, row: pd.Series) -> bool:
        """判断最新一根K线是否命中策略。"""
        raise NotImplementedError

    def evaluate(self, row: pd.Series) -> StrategySignal | None:
        if not self.enabled:
            return None

        try:
            if self.match(row):
                return StrategySignal(name=self.name, category=self.category)
        except Exception:
            return None

        return None

@dataclass(frozen=True)
class MinuteStrategySignal:
    """
    单个分钟级B点策略命中结果。

    name: B点名称，例如：5分钟回踩均线启动
    group: 适用的日线分组，例如：主升趋势类 / 突破类 / 放量启动类
    reason: 可选说明，方便后续导出或调试
    """

    name: str
    group: str = "其他"
    reason: str = ""


class BaseMinuteStrategy(ABC):
    """
    分钟级B点策略基类。

    新增分钟B点策略时只需要：
    1. 继承 BaseMinuteStrategy
    2. 设置 name/support_groups/enabled
    3. 实现 match(row, df5, df30)
    4. 在 strategies/registry.py 的 get_minute_strategies() 里注册

    注意：
    - row 是日线信号股票的行数据，用来读取日线分组、名称、行业等信息。
    - df5 / df30 是已经计算好分钟指标的 5分钟 / 30分钟 DataFrame。
    """

    name: str = "未命名分钟策略"
    support_groups: tuple[str, ...] = ("其他",)
    enabled: bool = True

    def support(self, daily_group: str) -> bool:
        daily_group = "" if daily_group is None else str(daily_group)

        # “其他”策略只在没有明确分组时触发，避免过度泛化。
        if self.support_groups == ("其他",):
            return daily_group == "其他"

        return any(group in daily_group for group in self.support_groups)

    @abstractmethod
    def match(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame) -> bool:
        """判断最新分钟K线是否命中B点。"""
        raise NotImplementedError

    def evaluate(self, row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame, daily_group: str) -> MinuteStrategySignal | None:
        if not self.enabled:
            return None

        if not self.support(daily_group):
            return None

        try:
            if self.match(row, df5, df30):
                return MinuteStrategySignal(name=self.name, group="、".join(self.support_groups))
        except Exception:
            return None

        return None

