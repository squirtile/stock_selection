from __future__ import annotations

import pandas as pd

from .base_strategy import BaseDailyStrategy, StrategySignal

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


# ======================================================================================
# 用户新增日线策略：1、3、4、5
# 说明：
# - 只基于当前 row 已有字段判断，不改上游数据计算逻辑；
# - 如果存在筹码、换手、九转、反包等扩展字段，则优先使用；
# - 如果不存在扩展字段，则使用均线、量能、平台位等日线字段做兜底判断。
# ======================================================================================


def _num(row: pd.Series, *names: str, default: float = float("nan")) -> float:
    """安全读取数值字段，兼容字段缺失/空值/字符串。"""
    for name in names:
        if name in row.index:
            value = pd.to_numeric(row.get(name), errors="coerce")
            if pd.notna(value):
                try:
                    return float(value)
                except Exception:
                    continue
    return default


def _bool(row: pd.Series, *names: str, default: bool = False) -> bool:
    """安全读取布尔字段，兼容 1/0、True/False、是/否。"""
    for name in names:
        if name not in row.index or pd.isna(row.get(name)):
            continue
        value = row.get(name)
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "是", "有", "命中"}:
            return True
        if text in {"0", "false", "no", "n", "否", "无", "未命中"}:
            return False
    return default


def _has_any_col(row: pd.Series, names: list[str]) -> bool:
    return any(name in row.index and pd.notna(row.get(name)) for name in names)


class MainChipCleanPlatformTrendStrategy(BaseDailyStrategy):
    """
    新增策略1：底部筹码干净集中 + K线趋势向上。

    对应你的规则：
    1. 90%筹码集中度<10%，70%筹码集中度<5%；
    2. 上部套牢盘少或无，底部筹码峰集中可放宽；
    3. K线趋势向上，最好突破或接近平台线。

    字段兼容：
    - 有筹码字段时：优先使用筹码集中度/上方套牢盘；
    - 没有筹码字段时：用近20日实体振幅、距离60日低点、均线趋势做兜底。
    """

    name = "主升-筹码干净趋势"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        close = _num(row, "收盘", "最新价")
        volume = _num(row, "成交量")
        avg_vol20 = _num(row, "过去20日平均成交量")
        ma5 = _num(row, "SMA5", "MA5")
        ma10 = _num(row, "SMA10", "MA10")
        ma20 = _num(row, "SMA20", "MA20")
        ma60 = _num(row, "SMA60", "MA60")
        high60 = _num(row, "过去60日最高收盘", "过去60日最高价")
        low60 = _num(row, "过去60日最低收盘", "过去60日最低价")
        amp20 = _num(row, "过去20日实体振幅", "近20日实体振幅", default=float("nan"))
        pct = _num(row, "涨跌幅", default=0.0)

        if pd.isna(close) or close <= 0:
            return False

        # 1) 筹码干净：有筹码字段就用真实筹码；没有就用“低位+收敛”近似。
        chip90 = _num(row, "90%筹码集中度", "筹码90集中度", "chip90_concentration")
        chip70 = _num(row, "70%筹码集中度", "筹码70集中度", "chip70_concentration")
        upper_trapped = _num(row, "上方套牢盘比例", "上部套牢盘比例", "upper_trapped_ratio")
        bottom_chip = _bool(row, "底部筹码集中", "底部筹码峰集中", "bottom_chip_concentrated")

        has_chip_data = _has_any_col(row, [
            "90%筹码集中度", "筹码90集中度", "chip90_concentration",
            "70%筹码集中度", "筹码70集中度", "chip70_concentration",
            "上方套牢盘比例", "上部套牢盘比例", "upper_trapped_ratio",
            "底部筹码集中", "底部筹码峰集中", "bottom_chip_concentrated",
        ])

        if has_chip_data:
            chip_clean = (
                (pd.notna(chip90) and chip90 < 10)
                or (pd.notna(chip70) and chip70 < 5)
                or bottom_chip
            )
            upper_ok = pd.isna(upper_trapped) or upper_trapped <= 25 or bottom_chip
        else:
            # 没有筹码数据时的兜底：近20日振幅收敛 + 仍处在60日低位启动区。
            low_position = pd.notna(low60) and low60 > 0 and close / low60 - 1 <= 0.50
            range_clean = pd.notna(amp20) and amp20 <= 0.25
            chip_clean = low_position or range_clean
            upper_ok = True

        # 2) 趋势向上：短均线转强，或者已经站上20日线。
        trend_ok = False
        if all(pd.notna(x) and x > 0 for x in [ma5, ma10, ma20]):
            trend_ok = (close >= ma5 and ma5 >= ma10 * 0.995 and close >= ma20 * 0.98)
        if pd.notna(ma60) and ma60 > 0 and pd.notna(ma20) and ma20 > 0:
            trend_ok = trend_ok and ma20 >= ma60 * 0.95

        # 3) 平台观察：突破60日最高收盘，或者距离60日平台不远。
        platform_ok = True
        if pd.notna(high60) and high60 > 0:
            platform_ok = close >= high60 * 0.96

        # 4) 量能不能太差，不强制必须2倍量。
        volume_ok = True
        if pd.notna(volume) and pd.notna(avg_vol20) and avg_vol20 > 0:
            volume_ok = volume >= avg_vol20 * 0.85

        # 5) 避免当天已经接近涨停追高。
        not_too_high_today = pct < 9.5

        return bool(chip_clean and upper_ok and trend_ok and platform_ok and volume_ok and not_too_high_today)


class MainHotStockBollMiddleReboundStrategy(BaseDailyStrategy):
    """
    新增策略3：热门票回踩20日线/布林中轨反弹。

    对应你的规则：
    快到20日 + 布林中轨重叠的热门票做反弹。

    字段兼容：
    - 如果有“布林中轨/BOLL_MID”，优先判断收盘价接近布林中轨；
    - 如果没有布林字段，则用 SMA20/MA20 代替；
    - 热门票用近15日涨停次数、近20日涨幅、是否热门票等字段判断。
    """

    name = "主升-热门20日线反弹-布林中轨反弹"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        close = _num(row, "收盘", "最新价")
        open_ = _num(row, "开盘")
        low = _num(row, "最低", "最低价")
        pct = _num(row, "涨跌幅", default=0.0)
        volume = _num(row, "成交量")
        avg_vol20 = _num(row, "过去20日平均成交量")
        ma5 = _num(row, "SMA5", "MA5")
        ma10 = _num(row, "SMA10", "MA10")
        ma20 = _num(row, "SMA20", "MA20")
        ma60 = _num(row, "SMA60", "MA60")
        boll_mid = _num(row, "布林中轨", "BOLL_MID", "boll_mid", "BOLL中轨", default=ma20)

        if pd.isna(close) or close <= 0 or pd.isna(ma20) or ma20 <= 0:
            return False

        # 热门票：近期有涨停/强势涨幅/人工标记热门，满足其一。
        limit_count = _num(row, "近15日涨停次数", "近20日涨停次数", "15日涨停", default=0.0)
        ret20 = _num(row, "近20日涨幅%", "近20日涨幅", default=float("nan"))
        hot_flag = _bool(row, "热门票", "是否热门", "hot_stock")
        hot_ok = hot_flag or limit_count >= 1 or (pd.notna(ret20) and ret20 >= 15)

        # 20日线和布林中轨重叠：如果没有布林字段，boll_mid=ma20，则自然通过。
        boll_overlap = pd.notna(boll_mid) and boll_mid > 0 and abs(boll_mid / ma20 - 1) <= 0.025

        # 回踩：最低价触碰20日线/中轨附近，收盘重新站回中轨附近或上方。
        touch_ma20 = pd.notna(low) and low <= ma20 * 1.025 and close >= ma20 * 0.985
        touch_boll_mid = pd.notna(boll_mid) and boll_mid > 0 and pd.notna(low) and low <= boll_mid * 1.025 and close >= boll_mid * 0.985
        pullback_ok = touch_ma20 or touch_boll_mid

        # 反弹确认：阳线/涨幅转正/站上短均线，满足偏保守组合。
        candle_ok = (pd.notna(open_) and close > open_) or pct > 1.0
        recover_ok = candle_ok and (pd.isna(ma5) or close >= ma5 * 0.98) and pct < 8.5

        # 趋势不能坏：20日线不应明显低于60日线，或者收盘仍在60日线上方。
        trend_ok = True
        if pd.notna(ma60) and ma60 > 0:
            trend_ok = ma20 >= ma60 * 0.96 or close >= ma60

        volume_ok = True
        if pd.notna(volume) and pd.notna(avg_vol20) and avg_vol20 > 0:
            # 反弹不要求巨量，但不能明显无量。
            volume_ok = volume >= avg_vol20 * 0.70

        return bool(hot_ok and boll_overlap and pullback_ok and recover_ok and trend_ok and volume_ok)


class MainLimitBreakReversalStrategy(BaseDailyStrategy):
    """
    新增策略4：涨停断板巨阴后的2-8天反包观察。

    对应你的规则：
    1. 涨停票突然放量巨阴断板；
    2. 一板附近放量看5/10日线，二板以上看反包；
    3. 调整2-8天；
    4. 换手率5-20%较好，>25%短期风险；
    5. 原则只参与第一次反包，反包不过三。

    该策略依赖上游预计算字段较多。如果没有“断板/调整天数/反包次数”等字段，默认不触发，避免误判。
    """

    name = "主升-断板调整反包"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        # 必须有涨停/断板相关字段，否则纯 row 无法可靠识别“断板后第几天”。
        has_break_cols = _has_any_col(row, [
            "断板后调整天数", "涨停后调整天数", "距断板天数", "启动大阳距今天数",
            "是否涨停断板", "涨停后放量巨阴", "是否巨阴断板",
        ])
        if not has_break_cols:
            return False

        limit_count = _num(row, "近15日涨停次数", "近10日涨停次数", "连板数", "15日涨停", default=0.0)
        has_limit = limit_count >= 1 or _bool(row, "近期有涨停", "是否涨停断板", "涨停后放量巨阴", "是否巨阴断板")
        if not has_limit:
            return False

        adjust_days = _num(row, "断板后调整天数", "涨停后调整天数", "距断板天数", "启动大阳距今天数")
        if pd.isna(adjust_days) or not (2 <= adjust_days <= 5):
            return False

        close = _num(row, "收盘", "最新价")
        open_ = _num(row, "开盘")
        pct = _num(row, "涨跌幅", default=0.0)
        volume = _num(row, "成交量")
        avg_vol20 = _num(row, "过去20日平均成交量")
        ma5 = _num(row, "SMA5", "MA5")
        ma10 = _num(row, "SMA10", "MA10")
        ma20 = _num(row, "SMA20", "MA20")

        if pd.isna(close) or close <= 0:
            return False

        # 一板附近看5/10日线，二板以上允许看10/20日线。
        if limit_count <= 1:
            ma_support = (
                (pd.notna(ma5) and ma5 > 0 and close >= ma5 * 0.985)
                or (pd.notna(ma10) and ma10 > 0 and close >= ma10 * 0.985)
            )
        else:
            ma_support = (
                (pd.notna(ma10) and ma10 > 0 and close >= ma10 * 0.98)
                or (pd.notna(ma20) and ma20 > 0 and close >= ma20 * 0.98)
            )

        # 反包确认：有预计算字段则优先；否则用阳线+涨幅+放量近似。
        reversal_flag = _bool(row, "今日反包", "反包信号", "是否反包")
        candle_reversal = pd.notna(open_) and close > open_ and pct >= 2.0
        volume_ok = True
        if pd.notna(volume) and pd.notna(avg_vol20) and avg_vol20 > 0:
            volume_ok = volume >= avg_vol20 * 1.05
        reversal_ok = reversal_flag or (candle_reversal and volume_ok)

        reversal_count = _num(row, "反包次数", "近期反包次数", default=1.0)
        reversal_count_ok = pd.isna(reversal_count) or reversal_count < 3

        turnover = _num(row, "换手率", "turnover", default=float("nan"))
        turnover_ok = pd.isna(turnover) or (5 <= turnover <= 25)

        td_seq = _num(row, "神奇九转", "九转序号", "TD九转", "td_seq", default=float("nan"))
        td_ok = pd.isna(td_seq) or td_seq < 9

        return bool(ma_support and reversal_ok and reversal_count_ok and turnover_ok and td_ok and pct < 9.8)


class MainBullishDivergencePlatformBreakStrategy(BaseDailyStrategy):
    """
    新增策略5：均线多头发散 + 刚突破前平台压制 + 九转低风险。

    对应你的规则：
    K线多头发散，刚突破前平台压制，结合神奇九转位置。
    """

    name = "主升-多头发散平台突破"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        close = _num(row, "收盘", "最新价")
        pct = _num(row, "涨跌幅", default=0.0)
        volume = _num(row, "成交量")
        avg_vol20 = _num(row, "过去20日平均成交量")
        ma5 = _num(row, "SMA5", "MA5")
        ma10 = _num(row, "SMA10", "MA10")
        ma20 = _num(row, "SMA20", "MA20")
        ma60 = _num(row, "SMA60", "MA60")
        high20 = _num(row, "过去20日最高收盘", "过去20日最高价")
        high30 = _num(row, "过去30日最高收盘", "过去30日最高价")
        high60 = _num(row, "过去60日最高收盘", "过去60日最高价")

        if pd.isna(close) or close <= 0:
            return False

        ma_ok = all(pd.notna(x) and x > 0 for x in [ma5, ma10, ma20])
        if not ma_ok:
            return False

        # 均线多头发散：短中期均线多头，20日线相对60日线不能太弱。
        bullish_ma = ma5 > ma10 > ma20
        if pd.notna(ma60) and ma60 > 0:
            bullish_ma = bullish_ma and ma20 >= ma60 * 0.98

        # 平台突破：优先20/30日平台，其次60日平台。
        platform_candidates = [x for x in [high20, high30, high60] if pd.notna(x) and x > 0]
        if not platform_candidates:
            return False
        platform = min(platform_candidates)  # 先突破较近平台，避免过于苛刻。
        break_platform = close > platform

        # 刚突破：涨幅不能太夸张，避免已经连续加速后追高。
        just_break = 1.0 <= pct < 9.5

        volume_ok = True
        if pd.notna(volume) and pd.notna(avg_vol20) and avg_vol20 > 0:
            volume_ok = volume >= avg_vol20 * 1.15

        turnover = _num(row, "换手率", "turnover", default=float("nan"))
        turnover_ok = pd.isna(turnover) or turnover <= 25

        td_seq = _num(row, "神奇九转", "九转序号", "TD九转", "td_seq", default=float("nan"))
        # 7之前暂时不算高位风险；>=9直接过滤。
        td_ok = pd.isna(td_seq) or td_seq < 9

        return bool(bullish_ma and break_platform and just_break and volume_ok and turnover_ok and td_ok)


class LongBuildWashBreakoutStrategy(BaseDailyStrategy):
    """
    长庄建仓洗盘后阶梯突破策略

    目标形态：
    1. 类似金安国纪：长期建仓、洗盘、阶梯式突破；
    2. 排除火炬电子这类短期垂直加速、高位巨震、涨幅过大的票；
    3. 要求趋势慢慢抬高，而不是几天连续暴力拉升。
    """

    name = "长庄-建仓洗盘阶梯突破"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        need_cols = [
            "收盘",
            "涨跌幅",
            "建仓区间最高价",
            "建仓平台振幅",
            "洗盘区间最高价",
            "洗盘区间振幅",
            "近15日涨停次数",
            "近15日5点大阳次数",
            "近5日是否突破建仓平台",
            "近5日平均成交量",
            "建仓后基准成交量",

            # 新增过滤字段
            "近10日涨幅",
            "近20日涨幅",
            "近60日涨幅",
            "近10日5点大阳次数",
            "近20日5点大阳次数",
            "距离20日线乖离",
            "距离60日线乖离",
            "SMA20近10日涨幅",
            "SMA60近20日涨幅",
            "近20日高位巨震次数",
            "近20日最大区间涨幅",
            "近60日最大区间涨幅",
            "是否阶梯趋势",
        ]

        for col in need_cols:
            if col not in row.index or pd.isna(row[col]):
                return False

        close = float(row["收盘"])
        pct = float(row["涨跌幅"])

        build_high = float(row["建仓区间最高价"])
        build_range_pct = float(row["建仓平台振幅"])

        wash_high = float(row["洗盘区间最高价"])
        wash_range_pct = float(row["洗盘区间振幅"])

        limit_up_count = float(row["近15日涨停次数"])
        big_yang_count_15 = float(row["近15日5点大阳次数"])

        recent_vol = float(row["近5日平均成交量"])
        base_vol = float(row["建仓后基准成交量"])

        ret10 = float(row["近10日涨幅"])
        ret20 = float(row["近20日涨幅"])
        ret60 = float(row["近60日涨幅"])

        big_yang_10 = float(row["近10日5点大阳次数"])
        big_yang_20 = float(row["近20日5点大阳次数"])

        dist_ma20 = float(row["距离20日线乖离"])
        dist_ma60 = float(row["距离60日线乖离"])

        ma20_slope = float(row["SMA20近10日涨幅"])
        ma60_slope = float(row["SMA60近20日涨幅"])

        shock_count = float(row["近20日高位巨震次数"])
        range20 = float(row["近20日最大区间涨幅"])
        range60 = float(row["近60日最大区间涨幅"])

        if close <= 0 or build_high <= 0 or wash_high <= 0:
            return False

        # 1. 建仓平台不能太乱
        # 金安国纪这种长期平台可以有波动，但不能是暴涨暴跌型。
        is_build_platform = build_range_pct <= 0.55

        # 2. 洗盘区间允许略宽，但不能已经提前走妖
        is_long_wash = wash_range_pct <= 0.90

        # 3. 近期必须突破建仓平台
        recent_breakout = bool(row["近5日是否突破建仓平台"])

        # 4. 当前不能离建仓平台太远
        # 原来 1.18 太宽，容易收进火炬电子这种已经高潮的票。
        not_overextended_from_build = close <= build_high * 1.12

        # 5. 当前不能离整个洗盘区间高点太远
        not_too_high_from_wash = close <= wash_high * 1.18

        # 6. 近期有人气，但不能过热
        # 目标是“有2-3个涨停/大阳吸引人气”，不是10天内天天暴拉。
        has_popularity = (
            1 <= limit_up_count <= 3
            or 2 <= big_yang_count_15 <= 4
        )

        not_too_hot = (
            big_yang_10 <= 3
            and big_yang_20 <= 6
        )

        # 7. 排除短期垂直加速
        # 火炬电子这种会被这里过滤。
        not_vertical_acceleration = (
            ret10 <= 0.45
            and ret20 <= 0.75
            and range20 <= 0.90
        )

        # 8. 允许中期强势，但不能60日已经翻太多
        # 金安国纪这类趋势可以强，但不是短期刚竖起来。
        medium_trend_not_crazy = (
            ret60 <= 1.60
            and range60 <= 2.00
        )

        # 9. 必须是阶梯式趋势
        stair_trend = bool(row["是否阶梯趋势"])

        # 10. 均线要慢慢抬高
        ma_slow_up = (
            ma20_slope > 0
            and ma60_slope > 0
            and ma20_slope <= 0.35
        )

        # 11. 当前不能距离均线过远
        not_far_from_ma = (
            dist_ma20 <= 0.25
            and dist_ma60 <= 0.70
        )

        # 12. 过滤高位巨震
        no_high_shock = shock_count <= 2

        # 13. 量能确认：近期量能比平台期放大
        volume_ok = True
        if base_vol > 0:
            volume_ok = recent_vol >= base_vol * 1.15

        # 14. 当天不能接近涨停追高
        not_limit_chasing = pct < 8.5

        return bool(
            is_build_platform
            and is_long_wash
            and recent_breakout
            and not_overextended_from_build
            and not_too_high_from_wash
            and has_popularity
            and not_too_hot
            and not_vertical_acceleration
            and medium_trend_not_crazy
            and stair_trend
            and ma_slow_up
            and not_far_from_ma
            and no_high_shock
            and volume_ok
            and not_limit_chasing
        )



# ======================================================================================
# 二波形态策略（合并版）
# 样本：天创时尚603608、福达合金、黄河旋风600172
#
# 内部包含 4 个子条件，全部在 match() 中一次性检查：
#   子条件① 回调结构：第一波大涨 → 阶梯式回调 → 缩量企稳
#   子条件② MACD底背离：价格低位 + DIF拒绝新低或金叉
#   子条件③ 地量反弹：缩量到极致 + 首日放量阳线
#   子条件④ 平台支撑：回调到前期筹码平台附近
#
# 至少命中子条件①才算命中，子条件②③④为加分项。
# reason 字段会标注命中了哪些子条件，方便复盘。
# ======================================================================================

class SecondWaveStrategy(BaseDailyStrategy):
    """
    二波形态：第一波大涨 → 阶梯回调 → 缩量企稳 → 二波启动。

    命中条件：至少命中子条件①（回调结构），其余子条件为加分项。
    """

    name = "二波形态"
    category = "主升"

    # ------------------------------------------------------------------
    # 子条件①：回调结构（核心，必须命中）
    # ------------------------------------------------------------------
    @staticmethod
    def _check_pullback_structure(row: pd.Series) -> tuple[bool, str]:
        """第一波涨幅够 + 回调充分且阶梯式 + 缩量企稳 + 今日启动"""
        fields = [
            "收盘", "涨跌幅", "成交量", "开盘",
            "近5日平均成交量", "近5日最高收盘",
            "SMA5", "SMA10", "SMA20", "SMA60",
            "过去20日平均成交量",
            "第一波涨幅", "从高点回调幅度", "距前高空间",
            "缩量比5日", "MA5趋势", "阶梯式回调",
        ]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False, "字段缺失"

        close  = float(row["收盘"])
        open_  = float(row["开盘"])
        pct    = float(row["涨跌幅"])
        vol    = float(row["成交量"])
        vol5   = float(row["近5日平均成交量"])
        ma5    = float(row["SMA5"])
        ma20   = float(row["SMA20"])
        ma60   = float(row["SMA60"])

        wave   = float(row["第一波涨幅"])
        dd     = float(row["从高点回调幅度"])
        room   = float(row["距前高空间"])
        shrink = float(row["缩量比5日"])
        ma5_d  = float(row["MA5趋势"])
        stair  = bool(row["阶梯式回调"])

        if close <= 0 or ma20 <= 0 or ma60 <= 0:
            return False, "价格或均线异常"

        # ① 第一波大涨过：涨幅 >= 25%（过滤小波动，只要真正涨过的）
        if wave < 0.25:
            return False, f"第一波涨幅不足({wave*100:.0f}%)"

        # ② 回调 18%~35%（用户指定18-30%，放宽上限到35%容错）
        #    dd = 当前价/第一波峰值 - 1，负数=在峰下面
        max_dd = 0.35
        if dd > -0.18:
            return False, f"回调不足({dd*100:.0f}%，需≥18%)"
        if dd < -max_dd:
            return False, f"回调过深({dd*100:.0f}%，需≤35%)"

        # ③ 中期均线支撑：MA20不能明显低于MA60，收盘不能跌破MA60太多
        if close < ma60 * 0.85:
            return False, "收盘跌破MA60超15%"
        if ma20 < ma60 * 0.88:
            return False, "MA20明显低于MA60"

        # ④ 缩量确认：回调期量 <= 第一波均量（回调缩量是洗盘特征）
        if shrink > 1.20:
            return False, f"回调期未缩量(量比{shrink*100:.0f}%)"

        # ⑤ 阶梯式回调（非必须，但非阶梯时需更严格站上MA5和MA10）
        if not stair:
            if close < ma5 or close < ma10:
                return False, "非阶梯回调且未站上MA5/MA10"

        # ⑥ 企稳信号：站上MA5，MA5走平或向上
        if close < ma5 * 0.97:
            return False, "未企稳(收盘低于MA5)"
        if ma5_d < -0.03 * close:
            return False, "MA5仍在下行"

        # ⑦ 距前高还有上涨空间（≥8%）
        if room < 0.08:
            return False, f"距前高太近({room*100:.0f}%)"

        # ⑧ 二波启动确认
        # ⑧a 涨幅 0.3%~9.5%（温和启动，不限涨停）
        if pct < 0.3 or pct >= 9.5:
            return False, f"涨幅不匹配({pct*100:.1f}%)"
        # ⑧b 阳线
        if close <= open_:
            return False, "非阳线"
        # ⑧c 放量：今日量 > 近5日均量 × 1.1
        if vol < vol5 * 1.1:
            return False, f"未放量(量比{vol/vol5:.1f})"

        return True, "✓"

        return True, "✓"

    # ------------------------------------------------------------------
    # 子条件②：MACD底背离确认
    # ------------------------------------------------------------------
    @staticmethod
    def _check_macd_divergence(row: pd.Series) -> tuple[bool, str]:
        fields = ["MACD底背离", "DIF金叉", "DIF", "涨跌幅"]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False, ""

        divergence   = bool(row["MACD底背离"])
        golden_cross = bool(row["DIF金叉"])
        dif          = float(row["DIF"])
        pct          = float(row["涨跌幅"])

        if not divergence and not golden_cross:
            return False, ""

        # DIF在零轴下方或刚上零轴
        if dif > 0.5:
            return False, ""

        if pct >= 9.5:
            return False, ""

        tags = []
        if divergence:
            tags.append("底背离")
        if golden_cross:
            tags.append("金叉")
        return True, "+".join(tags)

    # ------------------------------------------------------------------
    # 子条件③：地量反弹
    # ------------------------------------------------------------------
    @staticmethod
    def _check_volume_dry_up(row: pd.Series) -> tuple[bool, str]:
        fields = [
            "收盘", "涨跌幅", "成交量", "开盘",
            "缩量比5日", "缩量比10日",
            "过去20日平均成交量", "SMA5", "SMA10",
        ]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False, ""

        close   = float(row["收盘"])
        open_   = float(row["开盘"])
        pct     = float(row["涨跌幅"])
        vol     = float(row["成交量"])
        avg20   = float(row["过去20日平均成交量"])
        ma5     = float(row["SMA5"])
        ma10    = float(row["SMA10"])
        s5      = float(row["缩量比5日"])
        s10     = float(row["缩量比10日"])

        # 地量：5日或10日缩量到峰值的25%以下
        if s5 > 0.25 and s10 > 0.25:
            return False, ""

        # 首日放量：今日量 > 近5日均量 × 1.8
        est_5d = avg20 * 0.35  # 地量阶段的近似5日均量
        if vol < est_5d * 1.8:
            return False, ""

        # 阳线
        if close <= open_:
            return False, ""

        # 温和涨幅 2%~7%
        if pct < 2.0 or pct > 7.0:
            return False, ""

        # 站上短期均线
        if close < ma5 or close < ma10 * 0.99:
            return False, ""

        return True, "地量反弹"

    # ------------------------------------------------------------------
    # 子条件④：前期平台支撑
    # ------------------------------------------------------------------
    @staticmethod
    def _check_platform_support(row: pd.Series) -> tuple[bool, str]:
        fields = [
            "收盘", "涨跌幅", "成交量",
            "SMA5", "SMA20", "SMA60",
            "过去20日平均成交量",
            "从高点回调幅度", "接近前期平台", "缩量比5日",
        ]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False, ""

        close     = float(row["收盘"])
        pct       = float(row["涨跌幅"])
        vol       = float(row["成交量"])
        avg20     = float(row["过去20日平均成交量"])
        ma5       = float(row["SMA5"])
        ma20      = float(row["SMA20"])
        ma60      = float(row["SMA60"])
        dd        = float(row["从高点回调幅度"])
        shrink    = float(row["缩量比5日"])
        near_plat = bool(row["接近前期平台"])

        if dd > -0.15:
            return False, ""
        if not near_plat:
            return False, ""
        if shrink > 0.50:
            return False, ""
        if close < ma5:
            return False, ""
        if close < ma60 * 0.95 or ma20 < ma60 * 0.97:
            return False, ""
        if vol < avg20 * 0.70:
            return False, ""
        if pct >= 9.5:
            return False, ""

        return True, "平台支撑"

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def match(self, row: pd.Series) -> bool:
        """至少命中子条件①（回调结构）才算命中。"""
        ok, _ = self._check_pullback_structure(row)
        return ok

    def evaluate(self, row: pd.Series) -> StrategySignal | None:
        if not self.enabled:
            return None

        try:
            # 依次检查 4 个子条件
            r1, t1 = self._check_pullback_structure(row)
            r2, t2 = self._check_macd_divergence(row)
            r3, t3 = self._check_volume_dry_up(row)
            r4, t4 = self._check_platform_support(row)

            # 至少命中子条件①
            if not r1:
                return None

            # 组装命中标签
            parts = []
            if r1:
                parts.append("回调结构")
            if r2:
                parts.append(f"MACD({t2})")
            if r3:
                parts.append(t3)
            if r4:
                parts.append(t4)

            hit_count = sum([r1, r2, r3, r4])
            reason = " + ".join(parts)
            if hit_count >= 3:
                reason = f"【强】{reason}"
            elif hit_count == 2:
                reason = f"【中】{reason}"
            else:
                reason = f"【弱】{reason}"

            return StrategySignal(name=self.name, category=self.category, reason=reason)

        except Exception:
            return None


# ======================================================================================
# 二波埋伏策略
# 与 SecondWaveStrategy（二波形态）的区别：
#   二波形态 = 回调到位 + 今日启动确认（放量阳线）→ 追启动日
#   二波埋伏 = 回调到位 + 缩量企稳 + 尚未拉升      → 提前埋伏
# ======================================================================================

class SecondWaveAmbushStrategy(BaseDailyStrategy):
    """
    二波埋伏：回调到位 + 缩量企稳 → 等待二波启动。

    命中条件：满足回调结构 + 确认尚未拉升（今日涨幅温和、未放量）。
    与二波形态互补：埋伏策略先选池，启动日再用二波形态确认加仓。
    """

    name = "二波埋伏"
    category = "主升"

    # ------------------------------------------------------------------
    # 埋伏条件：回调结构（不含启动确认）+ 反启动过滤
    # ------------------------------------------------------------------
    @staticmethod
    def _check_ambush_structure(row: pd.Series) -> tuple[bool, str]:
        """回调到位 + 缩量企稳 + 确认尚未拉升"""
        fields = [
            "收盘", "涨跌幅", "成交量", "开盘",
            "近5日平均成交量",
            "SMA5", "SMA10", "SMA20", "SMA60",
            "第一波涨幅", "从高点回调幅度", "距前高空间",
            "缩量比5日", "MA5趋势", "阶梯式回调",
            "昨日涨跌幅",
        ]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False, "字段缺失"

        close   = float(row["收盘"])
        pct     = float(row["涨跌幅"])
        vol     = float(row["成交量"])
        vol5    = float(row["近5日平均成交量"])
        ma5     = float(row["SMA5"])
        ma10    = float(row["SMA10"])
        ma20    = float(row["SMA20"])
        ma60    = float(row["SMA60"])

        wave    = float(row["第一波涨幅"])
        dd      = float(row["从高点回调幅度"])
        room    = float(row["距前高空间"])
        shrink  = float(row["缩量比5日"])
        ma5_d   = float(row["MA5趋势"])
        stair   = bool(row["阶梯式回调"])

        yesterday_pct = float(row["昨日涨跌幅"])

        if close <= 0 or ma20 <= 0 or ma60 <= 0:
            return False, "价格或均线异常"

        # ① 第一波大涨过：涨幅 >= 25%
        if wave < 0.25:
            return False, f"第一波涨幅不足({wave*100:.0f}%)"

        # ② 回调 18%~35%
        max_dd = 0.35
        if dd > -0.18:
            return False, f"回调不足({dd*100:.0f}%，需≥18%)"
        if dd < -max_dd:
            return False, f"回调过深({dd*100:.0f}%，需≤35%)"

        # ③ 中期均线支撑
        if close < ma60 * 0.85:
            return False, "收盘跌破MA60超15%"
        if ma20 < ma60 * 0.88:
            return False, "MA20明显低于MA60"

        # ④ 缩量确认
        if shrink > 1.20:
            return False, f"回调期未缩量(量比{shrink*100:.0f}%)"

        # ⑤ 阶梯式回调或站上均线
        if not stair:
            if close < ma5 or close < ma10:
                return False, "非阶梯回调且未站上MA5/MA10"

        # ⑥ 企稳信号：收盘在MA5附近（±3%），MA5不再下行
        if close < ma5 * 0.97:
            return False, "未企稳(收盘低于MA5)"
        if ma5_d < -0.03 * close:
            return False, "MA5仍在下行"

        # ⑦ 距前高还有上涨空间（≥12%，比启动策略更保守，留足安全垫）
        if room < 0.12:
            return False, f"距前高太近({room*100:.0f}%)"

        # ⑧ 反启动过滤：确认尚未拉升（与二波形态互补）
        # ⑧a 今日涨幅 -2% ~ +2.5%（温和波动，非启动日）
        if pct < -2.0:
            return False, f"今日跌幅过大({pct*100:.1f}%)"
        if pct >= 2.5:
            return False, f"今日涨幅偏大({pct*100:.1f}%)，可能已在启动"
        # ⑧b 昨日也未大涨（<5%，排除连续拉升中）
        if yesterday_pct >= 5.0:
            return False, f"昨日涨幅过大({yesterday_pct*100:.1f}%)"
        # ⑧c 今日不放量（量 < 5日均量 × 1.3，确认不是偷偷启动）
        if vol > vol5 * 1.3:
            return False, f"今日放量(量比{vol/vol5:.1f})，可能已在启动"

        return True, "✓"

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def match(self, row: pd.Series) -> bool:
        ok, _ = self._check_ambush_structure(row)
        return ok

    def evaluate(self, row: pd.Series) -> StrategySignal | None:
        if not self.enabled:
            return None

        try:
            r1, t1 = self._check_ambush_structure(row)
            r2, t2 = SecondWaveStrategy._check_macd_divergence(row)
            r3, t3 = SecondWaveStrategy._check_volume_dry_up(row)
            r4, t4 = SecondWaveStrategy._check_platform_support(row)

            if not r1:
                return None

            parts = ["回调到位"]
            if r2:
                parts.append(f"MACD({t2})")
            if r3:
                parts.append(t3)
            if r4:
                parts.append(t4)

            hit_count = sum([r1, r2, r3, r4])
            reason = " + ".join(parts)
            if hit_count >= 3:
                reason = f"【强】{reason}"
            elif hit_count == 2:
                reason = f"【中】{reason}"
            else:
                reason = f"【弱】{reason}"

            return StrategySignal(name=self.name, category=self.category, reason=reason)

        except Exception:
            return None


# ======================================================================================
# 年线突破策略（收紧版）
# 逻辑：股价在年线下方运行一段时间 → 触及年线 → 放量上穿 → 连续2天站稳。
# 过滤掉"蹭一下年线就下来"和"早已远离年线"的情况。
# ======================================================================================

class AnnualLineBreakStrategy(BaseDailyStrategy):
    """
    年线突破：年线下方运行 → 放量突破 → 连续2天站稳 → 年线趋势向上。

    条件（全部满足才命中）：
    1. 近5日内最低价曾触及年线（真正的"回踩"或"突破"动作）
    2. 今日收盘 > SMA250 且 昨日收盘 > SMA250（连续2天站稳）
    3. SMA250趋势向上（年线在抬高，不是下降中继）
    4. 收盘不超年线5%（突破初期，还没跑远）
    5. 今日涨幅 1%~9.5%（温和放量突破，不追涨停）
    6. 成交量 > 20日均量 × 1.2（放量突破）
    7. 收盘 > SMA5（短均线支撑确认）
    8. 今日为阳线
    """

    name = "年线突破"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        fields = [
            "收盘", "开盘", "最低", "涨跌幅", "成交量",
            "SMA250", "昨日SMA250", "SMA250趋势",
            "昨日收盘", "SMA5",
            "近5日触及年线", "过去20日平均成交量",
        ]
        for c in fields:
            if c not in row.index or pd.isna(row[c]):
                return False

        close        = float(row["收盘"])
        open_        = float(row["开盘"])
        pct          = float(row["涨跌幅"])
        vol          = float(row["成交量"])
        sma250       = float(row["SMA250"])
        sma250_yest  = float(row["昨日SMA250"])
        sma250_trend = float(row["SMA250趋势"])
        close_yest   = float(row["昨日收盘"])
        ma5          = float(row["SMA5"])
        avg20        = float(row["过去20日平均成交量"])
        touched      = bool(row["近5日触及年线"])

        # ① 近5日内曾触及年线（真正的"碰线"动作）
        if not touched:
            return False

        # ② 连续2天收盘在年线上方
        if close <= sma250:
            return False
        if close_yest <= sma250_yest:
            return False

        # ③ 年线趋势向上（下降趋势中的突破多为假突破）
        if sma250_trend <= 0:
            return False

        # ④ 收盘不超年线5%（已经跑远的不是"刚突破"）
        if close > sma250 * 1.05:
            return False

        # ⑤ 温和放量突破：涨幅 1%~9.5%
        if pct < 1.0 or pct >= 9.5:
            return False

        # ⑥ 放量突破：成交量 > 20日均量 × 1.2
        if vol < avg20 * 1.2:
            return False

        # ⑦ 短均线确认：收盘 > SMA5
        if close <= ma5:
            return False

        # ⑧ 阳线
        if close <= open_:
            return False

        return True


# ======================================================================================
# 涨停回调一日游策略
#
# 核心逻辑：
#   近2~5天有放量涨停 → 缩量回调不破5日线 → 今天小实体企稳
#   → 尾盘买入，明天冲高卖出（超短线一日游）
#
# 适用场景：强势股首板后的N型反包，利用涨停后获利盘回吐的低吸机会
# ======================================================================================

class LimitUpPullbackDayTradeStrategy(BaseDailyStrategy):
    """
    涨停回调一日游：涨停→缩量回调→企稳支撑→尾盘买明天卖。

    条件（全部满足才命中）：
    1. 2~5天前出现过放量涨停（涨幅≥9.5%，量>20日均量×1.5）
    2. 从涨停收盘价回调 2%~8%（必须回调但不崩盘）
    3. 回调期间缩量至涨停日量的60%以下（抛压衰竭）
    4. 回调不破涨停日最低价（有序回调，没把涨幅全吐回去）
    5. 今天小实体企稳（振幅<6%）
    6. 今天不跳水——收盘高于最低价1.5%以上（有下影线）
    7. 今天温和——不是大涨也不是大跌（-4% < 涨幅 < 9.5%）
    """

    name = "涨停回调一日游"
    category = "主升"

    def match(self, row: pd.Series) -> bool:
        need_cols = [
            "近5日是否有涨停",
            "涨停距今天数",
            "涨停后缩量企稳",
            "涨跌幅",
        ]
        for col in need_cols:
            if col not in row.index or pd.isna(row[col]):
                return False

        return bool(
            row["近5日是否有涨停"]
            and 2 <= row["涨停距今天数"] <= 5
            and row["涨停后缩量企稳"]
            and -4.0 < row["涨跌幅"] < 9.5
        )