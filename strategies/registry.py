from __future__ import annotations

from .base_strategy import BaseDailyStrategy, BaseMinuteStrategy, StrategySignal, MinuteStrategySignal
from .daily_strategies import (
    # BottomVolumeReversalStrategy,
    # BoxBreakoutStrategy,
    # MainBottomVolumeReversalStrategy,
    # MainBoxBreakoutStrategy,
    # MainBullishMAAlignmentStrategy,
    # MainPullbackStartStrategy,
    MainBigYangPullbackNoBreakStrategy,

    # MainChipCleanPlatformTrendStrategy,
    # MainHotStockBollMiddleReboundStrategy,
    # MainLimitBreakReversalStrategy,
    # MainBullishDivergencePlatformBreakStrategy,

    # LongBuildWashBreakoutStrategy,
    
    # VShapeReversalStrategy,
    SecondWaveStrategy,
    AnnualLineBreakStrategy,
    LimitUpPullbackDayTradeStrategy,
)


def get_daily_strategies() -> list[BaseDailyStrategy]:
    """
    日线策略注册表。

    想增加/关闭/调整策略顺序，就改这里。
    主程序、盘中实时扫描、回测都可以共用这一份策略列表。
    """

    return [
        # BoxBreakoutStrategy(),
        # BottomVolumeReversalStrategy(),
        # MainBoxBreakoutStrategy(),
        # MainBottomVolumeReversalStrategy(),
        # MainPullbackStartStrategy(),
        # MainBullishMAAlignmentStrategy(),
        MainBigYangPullbackNoBreakStrategy(),

        # 新增：用户规则 1、3、4、5
        # MainChipCleanPlatformTrendStrategy(),
        # MainHotStockBollMiddleReboundStrategy(),
        # MainLimitBreakReversalStrategy(),
        # MainBullishDivergencePlatformBreakStrategy(),

        # LongBuildWashBreakoutStrategy(),

        # VShapeReversalStrategy(),

        # 二波形态（含4个子条件：回调结构/MACD底背离/地量反弹/平台支撑）
        SecondWaveStrategy(),

        # 年线突破：触及250日线后上穿，连续2天站稳
        AnnualLineBreakStrategy(),

        # 涨停回调一日游：涨停→缩量回调→企稳→尾盘买明天卖
        LimitUpPullbackDayTradeStrategy(),
    ]


def evaluate_daily_strategies(row) -> list[StrategySignal]:
    signals: list[StrategySignal] = []

    for strategy in get_daily_strategies():
        signal = strategy.evaluate(row)
        if signal is not None:
            signals.append(signal)

    return signals


from .minute_strategies import (
    PullbackStartMinuteStrategy,
    PlatformBreakoutMinuteStrategy,
    VolumeReversalMinuteStrategy,
    OneMinuteBuyStrategy,
    check_30m_structure,
)
from .chanlun_strategies import (
    # ChanlunFirstBuyMinuteStrategy,
    ChanlunSecondBuyMinuteStrategy,
    ChanlunThirdBuyMinuteStrategy,
)


def get_minute_strategies() -> list[BaseMinuteStrategy]:
    """
    分钟B点策略注册表。

    现在执行顺序是：
    1. 30分钟趋势过滤：evaluate_minute_strategies() 里统一执行；
    2. 5分钟结构策略 + 缠论买点：先确认结构；
    3. 1分钟精确买点：最后确认入场。
    """

    return [
        # 5分钟结构类B点
        PullbackStartMinuteStrategy(),
        PlatformBreakoutMinuteStrategy(),
        VolumeReversalMinuteStrategy(),

        # 5分钟缠论类B点
        # ChanlunFirstBuyMinuteStrategy(),
        ChanlunSecondBuyMinuteStrategy(),
        ChanlunThirdBuyMinuteStrategy(),

        # 1分钟精确入场确认
        OneMinuteBuyStrategy(),
    ]


def evaluate_minute_strategies(
    row,
    df1,
    df5,
    df30,
    daily_group: str,
    enable_1m_buy: bool = False,
) -> tuple[bool, list[str], str]:
    """
    统一执行分钟级B点策略。

    返回：
    - 是否命中
    - 命中的B点名称列表
    - 30分钟结构说明

    逻辑：
    1. 先用30分钟确认趋势；
    2. 再用5分钟结构策略和缠论策略确认B点类型；
    3. enable_1m_buy=False 时，默认只精确到5分钟级别，仍然保留缠论一买/二买/三买等名称；
    4. enable_1m_buy=True 时，再用1分钟确认精确买点。
    """

    structure_ok, structure_msg = check_30m_structure(df30)
    if not structure_ok:
        return False, [], structure_msg

    five_minute_signals: list[MinuteStrategySignal] = []
    one_minute_hit = False

    for strategy in get_minute_strategies():
        if isinstance(strategy, OneMinuteBuyStrategy):
            if not enable_1m_buy:
                continue
            try:
                one_minute_hit = bool(strategy.match(row, df1, df5, df30))
            except Exception:
                one_minute_hit = False
            continue

        signal = strategy.evaluate(row, df5, df30, daily_group)
        if signal is not None:
            five_minute_signals.append(signal)

    # 必须先有5分钟结构或缠论B点，再看1分钟精确买点。
    # 否则1分钟单独波动太容易产生噪音。
    if not five_minute_signals:
        return False, [], structure_msg

    buy_points = [signal.name for signal in five_minute_signals]

    if enable_1m_buy:
        if not one_minute_hit:
            return False, [], structure_msg + "；1分钟买点未确认"
        buy_points.append("1分钟精确买点")
    else:
        structure_msg = structure_msg + "；已关闭1分钟精确确认，仅确认到5分钟级别"

    return True, buy_points, structure_msg
