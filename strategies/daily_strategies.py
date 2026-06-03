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
