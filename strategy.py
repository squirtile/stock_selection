# strategy.py

import os
import time
import warnings
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import baostock as bs

from strategies import evaluate_daily_strategies


HIST_CACHE_DIR = "cache/hist"
SIGNAL_OUTPUT_FILE = "output/a_stock_signal_selected.xlsx"
VERBOSE_KLINE_LOG = False

# 二次过滤条件
MIN_AVG_AMOUNT_20D = 50_000_000      # 过去20天日均成交额 >= 5000万
LIMIT_UP_PCT = 9.95                  # 主板涨停判断：涨幅 >= 9.95%
LIMIT_UP_WINDOW = 15                 # 过去15个交易日

# BaoStock 日线数据一般在盘后较晚才稳定更新。
# 盘前/盘中扫描时，如果本地缓存最新日期是上一交易日，属于正常情况。
DAILY_AUTO_UPDATE_AFTER_TIME = "17:30"


def is_after_daily_auto_update_time(now=None, after_time: str = DAILY_AUTO_UPDATE_AFTER_TIME) -> bool:
    """
    是否已经到达允许自动更新 BaoStock 日线缓存的时间。

    默认 17:30 之后才允许自动请求 BaoStock 补当天日K；
    17:30 之前优先使用本地 cache/hist，避免盘前扫描被逐只请求拖慢。
    """

    now = now or datetime.now()

    try:
        target_time = datetime.strptime(str(after_time), "%H:%M").time()
    except Exception:
        target_time = datetime.strptime(DAILY_AUTO_UPDATE_AFTER_TIME, "%H:%M").time()

    return now.time() >= target_time


def should_update_daily_cache(
    *,
    cache_only: bool = False,
    force_update: bool = False,
    after_time: str = DAILY_AUTO_UPDATE_AFTER_TIME,
) -> bool:
    """
    日线缓存更新决策：
    1. cache_only=True：永远不请求 BaoStock；
    2. force_update=True：强制请求 BaoStock；
    3. 默认：17:30 之后才允许自动请求 BaoStock。
    """

    if cache_only:
        return False

    if force_update:
        return True

    return is_after_daily_auto_update_time(after_time=after_time)


def check_secondary_filters(row) -> bool:
    """
    策略命中后的统一二次过滤：

    1. 过去20天日均成交额 >= 5000万（保证流动性）
    """

    return row["过去20日日均成交额"] >= MIN_AVG_AMOUNT_20D


def get_bs_code(code: str) -> str:
    """
    转换成 BaoStock 代码格式。

    上海：sh.600xxx / sh.601xxx / sh.603xxx / sh.605xxx
    深圳：sz.000xxx / sz.001xxx / sz.002xxx / sz.003xxx
    """

    code = str(code).zfill(6)

    if code.startswith(("600", "601", "603", "605")):
        return f"sh.{code}"

    return f"sz.{code}"


def get_hist_data_baostock(
    code: str,
    use_cache: bool = True,
    cache_only: bool = False,
    force_update: bool = False,
    auto_update_after_time: str = DAILY_AUTO_UPDATE_AFTER_TIME,
) -> pd.DataFrame:
    """
    使用 BaoStock 获取个股日 K 线数据。

    增量缓存逻辑：
    1. 如果没有缓存，首次获取最近150个自然日数据
    2. 如果已有缓存，只从缓存最后日期之后开始更新
    3. 合并新旧数据，按日期去重
    4. 打印当前使用的最新K线日期
    """

    os.makedirs(HIST_CACHE_DIR, exist_ok=True)

    code = str(code).zfill(6)
    cache_file = os.path.join(HIST_CACHE_DIR, f"{code}_bs.csv")

    end_date = datetime.now().strftime("%Y-%m-%d")
    bs_code = get_bs_code(code)
    allow_update = should_update_daily_cache(
        cache_only=cache_only,
        force_update=force_update,
        after_time=auto_update_after_time,
    )

    old_df = pd.DataFrame()

    if use_cache and os.path.exists(cache_file):
        old_df = pd.read_csv(cache_file, dtype={"代码": str})

        if not old_df.empty and "日期" in old_df.columns:
            old_df["日期"] = pd.to_datetime(old_df["日期"], errors="coerce")
            old_df = old_df.dropna(subset=["日期"])
            old_df = old_df.drop_duplicates(subset=["日期"], keep="last")
            old_df = old_df.sort_values("日期")

            if not old_df.empty:
                last_date = old_df["日期"].max()

                # 缓存已到今天，直接使用。
                if last_date.strftime("%Y-%m-%d") >= end_date:
                    if VERBOSE_KLINE_LOG:
                        print(f"{code} 使用本地BaoStock缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")
                    old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                    return old_df

                # 17:30 前，或者 cache_only 模式，允许昨天缓存直接参与盘前扫描。
                if not allow_update:
                    if VERBOSE_KLINE_LOG:
                        print(
                            f"{code} 使用本地BaoStock缓存分析，"
                            f"最新K线日期：{last_date.strftime('%Y-%m-%d')}；"
                            f"未到 {auto_update_after_time} 或已指定只用缓存，不请求 BaoStock。"
                        )
                    old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                    return old_df

                # 17:30 后，或者强制更新时，才从最后日期的下一天开始补数据。
                start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
                if VERBOSE_KLINE_LOG:
                    print(f"{code} 本地BaoStock缓存最新K线日期：{last_date.strftime('%Y-%m-%d')}，开始增量更新...")
            else:
                start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                if not allow_update:
                    return pd.DataFrame()
                if VERBOSE_KLINE_LOG:
                    print(f"{code} 缓存文件异常，重新获取最近365天K线...")
        else:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            if not allow_update:
                return pd.DataFrame()
            if VERBOSE_KLINE_LOG:
                print(f"{code} 缓存文件异常，重新获取最近365天K线...")
    else:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if not allow_update:
            if VERBOSE_KLINE_LOG:
                print(f"{code} 无本地BaoStock缓存，且未到 {auto_update_after_time}，跳过 BaoStock 请求。")
            return pd.DataFrame()
        if VERBOSE_KLINE_LOG:
            print(f"{code} 无本地BaoStock缓存，首次获取最近365天K线...")

    MAX_RETRIES = 3
    last_error = None
    for retry in range(MAX_RETRIES):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields="date,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"
            )

            if rs.error_code != "0":
                err_msg = rs.error_msg or ""
                # 网络类错误 → 抛异常触发重试；业务错误 → 直接回退缓存
                NETWORK_ERROR_KEYWORDS = ["网络接收", "网络", "超时", "连接", "timeout", "reset", "broken", "pipe"]
                if any(kw in str(err_msg).lower() for kw in NETWORK_ERROR_KEYWORDS):
                    raise ConnectionError(f"{code} BaoStock网络错误：{err_msg}")

                print(f"{code} BaoStock查询失败：{err_msg}")
                if not old_df.empty:
                    last_date = old_df["日期"].max()
                    if VERBOSE_KLINE_LOG:
                        print(f"{code} 使用旧缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")
                    old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                    return old_df
                return pd.DataFrame()

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if data_list:
                new_df = pd.DataFrame(data_list, columns=rs.fields)
                new_df = new_df.rename(
                    columns={
                        "date": "日期",
                        "open": "开盘",
                        "high": "最高",
                        "low": "最低",
                        "close": "收盘",
                        "volume": "成交量",
                        "amount": "成交额",
                        "pctChg": "涨跌幅",
                    }
                )
                new_df["代码"] = code

                numeric_cols = [
                    "开盘", "最高", "最低", "收盘",
                    "成交量", "成交额", "涨跌幅",
                ]
                for col in numeric_cols:
                    new_df[col] = pd.to_numeric(new_df[col], errors="coerce")

                new_df["日期"] = pd.to_datetime(new_df["日期"])

                if not old_df.empty:
                    df = pd.concat([old_df, new_df], ignore_index=True)
                else:
                    df = new_df

                df = df.drop_duplicates(subset=["日期"], keep="last")
                df = df.sort_values("日期")

                cutoff_date = datetime.now() - timedelta(days=365)
                df = df[df["日期"] >= cutoff_date]

                latest_date = df["日期"].max().strftime("%Y-%m-%d")
                if VERBOSE_KLINE_LOG:
                    print(f"{code} BaoStock K线已更新到：{latest_date}")

                df["日期"] = df["日期"].dt.strftime("%Y-%m-%d")
                df.to_csv(cache_file, index=False, encoding="utf-8-sig")
                return df

            else:
                # 没有新数据，用旧缓存
                if not old_df.empty:
                    last_date = old_df["日期"].max()
                    if VERBOSE_KLINE_LOG:
                        print(f"{code} BaoStock暂无新数据，使用缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")
                    old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                    return old_df
                print(f"{code} BaoStock没有返回K线数据。")
                return pd.DataFrame()

        except Exception as e:
            last_error = e
            if retry < MAX_RETRIES - 1:
                time.sleep(2 * (retry + 1))
            # 3次都失败，抛出让外层处理（重登+重试）

    # 重试耗尽，抛出最后一个异常给外层
    raise last_error


# 兼容旧函数名：如果其他地方还调用 get_hist_data_tushare，也转到 BaoStock。
def get_hist_data_tushare(
    code: str,
    use_cache: bool = True,
    pro=None,
    cache_only: bool = False,
    force_update: bool = False,
) -> pd.DataFrame:
    return get_hist_data_baostock(
        code,
        use_cache=use_cache,
        cache_only=cache_only,
        force_update=force_update,
    )


def prepare_hist_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    整理 K 线数据，计算策略所需指标。
    """

    # 抑制批量添加列时 pandas 的 PerformanceWarning（逐列赋值是正常的）
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

    df = df.copy()

    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").reset_index(drop=True)

    numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 均线
    df["SMA5"] = df["收盘"].rolling(5).mean()
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA60"] = df["收盘"].rolling(60).mean()
    df["SMA250"] = df["收盘"].rolling(250, min_periods=120).mean()

    # ---- 年线突破策略辅助字段 ----
    df["昨日收盘"] = df["收盘"].shift(1)
    df["前日收盘"] = df["收盘"].shift(2)
    df["昨日SMA250"] = df["SMA250"].shift(1)
    df["前日SMA250"] = df["SMA250"].shift(2)
    # SMA250趋势：>0 表示年线向上
    df["SMA250_5日前"] = df["SMA250"].shift(5)
    df["SMA250趋势"] = df["SMA250"] - df["SMA250_5日前"]
    # 近5日内是否曾触及年线（最低价曾 <= SMA250）
    df["近5日最低价"] = df["最低"].rolling(5).min()
    df["近5日触及年线"] = (
        df["最低"].shift(1).rolling(5).min() <= df["SMA250"].shift(1).rolling(5).max()
    )

    # 过去60个交易日最高价，不含今日
    df["过去60日最高价"] = df["最高"].shift(1).rolling(60).max()

    # 过去60个交易日最高收盘，不含今日，保留备用
    df["过去60日最高收盘"] = df["收盘"].shift(1).rolling(60).max()

    # 过去40个交易日最低价，含今日，用于判断当前是否还在底部附近
    df["过去40日最低价"] = df["最低"].rolling(40).min()

    # 过去60个交易日最低收盘，不含今日，保留备用
    df["过去60日最低收盘"] = df["收盘"].shift(1).rolling(60).min()

    # K线实体上下沿，避免影线插针误判
    df["实体上沿"] = df[["开盘", "收盘"]].max(axis=1)
    df["实体下沿"] = df[["开盘", "收盘"]].min(axis=1)

    # 过去20个交易日实体最高和实体最低，不含今日
    df["过去20日实体最高"] = df["实体上沿"].shift(1).rolling(20).max()
    df["过去20日实体最低"] = df["实体下沿"].shift(1).rolling(20).min()

    # 过去20个交易日K线实体振幅，不含今日
    df["过去20日实体振幅"] = (
        df["过去20日实体最高"] / df["过去20日实体最低"] - 1
    )

    # 过去20日平均成交量，不含今日
    df["过去20日平均成交量"] = df["成交量"].shift(1).rolling(20).mean()

    # 过去20日日均成交额，含今日
    df["过去20日日均成交额"] = df["成交额"].rolling(20).mean()

    # 过去15个交易日内涨停次数，含今日
    df["近15日涨停次数"] = (
        df["涨跌幅"] >= LIMIT_UP_PCT
    ).rolling(LIMIT_UP_WINDOW).sum()

    # 5天前的60日均线
    df["SMA60_5日前"] = df["SMA60"].shift(5)

    # =========================
    # 长庄建仓洗盘突破策略辅助字段
    # =========================
    # 建仓区间：最近 60-120 个交易日之间，避开最近20天的突破阶段。
    # 等价于取 [-120:-20] 这一段作为建仓平台。
    df["建仓区间最高价"] = df["最高"].shift(20).rolling(100).max()
    df["建仓区间最低价"] = df["最低"].shift(20).rolling(100).min()
    df["建仓区间中位价"] = (df["建仓区间最高价"] + df["建仓区间最低价"]) / 2
    df["建仓平台振幅"] = (
        df["建仓区间最高价"] - df["建仓区间最低价"]
    ) / df["建仓区间中位价"]

    # 洗盘区间：最近 180 个交易日，避开最近10天。
    # 用来判断是否经历了较长时间横盘洗盘。
    df["洗盘区间最高价"] = df["最高"].shift(10).rolling(170).max()
    df["洗盘区间最低价"] = df["最低"].shift(10).rolling(170).min()
    df["洗盘区间中位价"] = (df["洗盘区间最高价"] + df["洗盘区间最低价"]) / 2
    df["洗盘区间振幅"] = (
        df["洗盘区间最高价"] - df["洗盘区间最低价"]
    ) / df["洗盘区间中位价"]

    # 近期人气：近15日涨停次数，或者5%以上大阳次数。
    df["近15日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(15).sum()

    # 近期是否突破建仓平台上沿。
    df["是否突破建仓平台"] = df["收盘"] > df["建仓区间最高价"] * 1.02
    df["近5日是否突破建仓平台"] = (
        df["是否突破建仓平台"].rolling(5).sum() >= 1
    )

    # 近期量能是否放大。
    df["近5日平均成交量"] = df["成交量"].rolling(5).mean()
    df["建仓后基准成交量"] = df["成交量"].shift(10).rolling(50).mean()

    # =========================
    # 长庄建仓洗盘突破策略：防止火箭式加速过滤字段
    # =========================
    df["近10日涨幅"] = df["收盘"] / df["收盘"].shift(10) - 1
    df["近20日涨幅"] = df["收盘"] / df["收盘"].shift(20) - 1
    df["近60日涨幅"] = df["收盘"] / df["收盘"].shift(60) - 1

    df["近10日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(10).sum()

    df["近20日5点大阳次数"] = (
        df["涨跌幅"] >= 5.0
    ).rolling(20).sum()

    df["距离20日线乖离"] = df["收盘"] / df["SMA20"] - 1
    df["距离60日线乖离"] = df["收盘"] / df["SMA60"] - 1

    df["SMA20_10日前"] = df["SMA20"].shift(10)
    df["SMA60_20日前"] = df["SMA60"].shift(20)

    df["SMA20近10日涨幅"] = df["SMA20"] / df["SMA20_10日前"] - 1
    df["SMA60近20日涨幅"] = df["SMA60"] / df["SMA60_20日前"] - 1

    df["单日振幅"] = df["最高"] / df["最低"] - 1

    df["近20日高位巨震次数"] = (
        (df["单日振幅"] >= 0.12)
        | (df["涨跌幅"] <= -6.0)
    ).rolling(20).sum()

    df["近20日最高价"] = df["最高"].rolling(20).max()
    df["近20日最低价"] = df["最低"].rolling(20).min()
    df["近20日最大区间涨幅"] = df["近20日最高价"] / df["近20日最低价"] - 1

    df["近60日最高价"] = df["最高"].rolling(60).max()
    df["近60日最低价"] = df["最低"].rolling(60).min()
    df["近60日最大区间涨幅"] = df["近60日最高价"] / df["近60日最低价"] - 1

    df["是否阶梯趋势"] = (
        (df["收盘"] > df["SMA20"])
        & (df["SMA20"] > df["SMA60"])
        & (df["SMA20近10日涨幅"] > 0)
        & (df["SMA60近20日涨幅"] > 0)
        & (df["距离20日线乖离"] <= 0.28)
        & (df["距离60日线乖离"] <= 0.75)
    )

    # =========================
    # 主升策略5：大阳启动后3-5个交易日缩量回踩不破5/10日线
    # =========================
    # 这个策略用于识别：第一次涨幅 >= 8% 的放量大阳启动后，
    # 第3-5个交易日仍处于强势缩量回踩区间，且不有效跌破短均线的形态。
    df["是否8点大阳启动"] = (
        (df["涨跌幅"] >= 8.0)
        & (df["成交量"] >= df["过去20日平均成交量"] * 1.5)
        & (df["收盘"] > df["SMA5"])
        & (df["收盘"] > df["SMA10"])
    )

    # 以下字段按“最近一次启动大阳线”逐行计算。
    # 不把这些字段放进 get_required_strategy_columns，避免影响其他原有策略。
    df["近5日是否有8点大阳启动"] = False
    df["启动大阳距今天数"] = pd.NA
    df["近5日启动大阳收盘"] = pd.NA
    df["近5日启动大阳成交量"] = pd.NA
    df["启动后回撤不深"] = False
    df["回踩不破5日或10日线"] = False
    df["近5日不破10日线"] = False
    df["回调缩量"] = False
    df["当前不破10日线"] = False

    big_yang_positions = df.index[df["是否8点大阳启动"].fillna(False)].tolist()

    for pos in range(len(df)):
        # 只在当前K线之前找启动大阳，避免当天大阳线直接把自己也判成“回踩”。
        # 短线版只看启动后的第3-5个交易日。
        candidate_positions = [p for p in big_yang_positions if 3 <= pos - p <= 5]
        if not candidate_positions:
            continue

        start_pos = candidate_positions[-1]
        days_since_start = pos - start_pos

        start_row = df.iloc[start_pos]
        latest_row = df.iloc[pos]
        pullback_df = df.iloc[start_pos + 1: pos + 1].copy()

        if pullback_df.empty:
            continue

        start_close = start_row["收盘"]
        start_volume = start_row["成交量"]

        if pd.isna(start_close) or pd.isna(start_volume) or start_close <= 0 or start_volume <= 0:
            continue

        # 回踩不有效跌破10日线，允许2%误差；
        # 同时保留“5日或10日线”的字段，后续你想调成更强条件也方便。
        valid_ma10 = pullback_df["SMA10"].notna()
        no_break_ma10 = bool(
            valid_ma10.any()
            and (pullback_df.loc[valid_ma10, "最低"] >= pullback_df.loc[valid_ma10, "SMA10"] * 0.98).all()
        )

        valid_ma5_or_ma10 = pullback_df["SMA5"].notna() & pullback_df["SMA10"].notna()
        no_break_ma5_or_ma10 = bool(
            valid_ma5_or_ma10.any()
            and (
                (pullback_df.loc[valid_ma5_or_ma10, "最低"] >= pullback_df.loc[valid_ma5_or_ma10, "SMA5"] * 0.98)
                | (pullback_df.loc[valid_ma5_or_ma10, "最低"] >= pullback_df.loc[valid_ma5_or_ma10, "SMA10"] * 0.98)
            ).all()
        )

        # 回调阶段缩量：启动后到当前的平均量，不超过启动大阳量的70%。
        pullback_avg_volume = pd.to_numeric(pullback_df["成交量"], errors="coerce").mean()
        volume_shrink = bool(pd.notna(pullback_avg_volume) and pullback_avg_volume <= start_volume * 0.70)

        # 启动后不能回撤太深，防止大阳后直接走坏。
        drawdown_ok = bool(pd.notna(latest_row["收盘"]) and latest_row["收盘"] >= start_close * 0.88)

        # 当前仍在10日线附近上方，允许2%误差。
        current_no_break_ma10 = bool(
            pd.notna(latest_row["SMA10"])
            and pd.notna(latest_row["收盘"])
            and latest_row["收盘"] >= latest_row["SMA10"] * 0.98
        )

        df.iat[pos, df.columns.get_loc("近5日是否有8点大阳启动")] = True
        df.iat[pos, df.columns.get_loc("启动大阳距今天数")] = days_since_start
        df.iat[pos, df.columns.get_loc("近5日启动大阳收盘")] = start_close
        df.iat[pos, df.columns.get_loc("近5日启动大阳成交量")] = start_volume
        df.iat[pos, df.columns.get_loc("启动后回撤不深")] = drawdown_ok
        df.iat[pos, df.columns.get_loc("回踩不破5日或10日线")] = no_break_ma5_or_ma10
        df.iat[pos, df.columns.get_loc("近5日不破10日线")] = no_break_ma10
        df.iat[pos, df.columns.get_loc("回调缩量")] = volume_shrink
        df.iat[pos, df.columns.get_loc("当前不破10日线")] = current_no_break_ma10

    # =====================================================================
    # 涨停回调一日游策略辅助字段
    #
    # 核心逻辑：近2~5天有涨停 → 缩量回调 → 今天企稳在支撑位
    # → 尾盘买入，明天卖出（超短线一日游）
    # =====================================================================
    df["近5日是否有涨停"] = False
    df["涨停距今天数"] = pd.NA
    df["涨停日收盘"] = pd.NA
    df["涨停日成交量"] = pd.NA
    df["涨停日最低价"] = pd.NA
    df["涨停后缩量企稳"] = False

    limit_up_positions_all = df.index[(df["涨跌幅"] >= 9.5).fillna(False)].tolist()

    for pos in range(len(df)):
        # 只在 2~5 天前找涨停
        candidate_positions = [p for p in limit_up_positions_all if 2 <= pos - p <= 5]
        if not candidate_positions:
            continue

        # 取最近一次涨停
        limit_pos = candidate_positions[-1]
        days_since = pos - limit_pos

        limit_row = df.iloc[limit_pos]
        current_row = df.iloc[pos]

        limit_close = limit_row["收盘"]
        limit_vol = limit_row["成交量"]
        limit_low = limit_row["最低"]
        current_close = current_row["收盘"]
        current_open = current_row["开盘"]
        current_high = current_row["最高"]
        current_low = current_row["最低"]
        current_pct = current_row["涨跌幅"]

        if pd.isna(limit_close) or limit_close <= 0:
            continue

        # ---- 条件1：涨停日必须是放量的（真涨停，不是尾盘偷袭）----
        avg_vol20_limit = limit_row["过去20日平均成交量"]
        if pd.isna(avg_vol20_limit) or avg_vol20_limit <= 0:
            continue
        if limit_vol < avg_vol20_limit * 1.5:
            continue

        # ---- 条件2：回调幅度 2%~8%（必须回调，不能太浅也不能崩盘）----
        pullback_pct = current_close / limit_close - 1
        if pullback_pct > -0.02 or pullback_pct < -0.08:
            continue

        # ---- 条件3：缩量——近2日均量 < 涨停日量的60% ----
        pullback_slice_data = df.iloc[limit_pos + 1:pos + 1]
        if len(pullback_slice_data) < 2:
            continue
        recent_2_vol = pullback_slice_data["成交量"].tail(2).mean()
        if pd.isna(recent_2_vol) or recent_2_vol <= 0:
            continue
        if recent_2_vol >= limit_vol * 0.60:
            continue

        # ---- 条件4：回调有序——不破涨停日最低价（没把涨停全吐回去）----
        pullback_low = pullback_slice_data["最低"].min()
        if pd.isna(pullback_low) or pd.isna(limit_low):
            continue
        if pullback_low < limit_low * 0.98:
            continue

        # ---- 条件5：今天企稳——小实体，振幅 < 6% ----
        if pd.isna(current_open) or current_open <= 0:
            continue
        body_range = (current_high - current_low) / current_open
        if abs(body_range) >= 0.06:
            continue

        # ---- 条件6：今天不跳水——收盘不在最低价，有下影线企稳 ----
        if pd.isna(current_low) or current_low <= 0:
            continue
        if current_close < current_low * 1.015:
            continue

        # ---- 条件7：今天温和——不是大涨也不是大跌（-4% < 涨幅 < 9.5%）----
        if pd.isna(current_pct):
            continue
        if current_pct <= -4.0 or current_pct >= 9.5:
            continue

        # ---- 汇总 ----
        df.iat[pos, df.columns.get_loc("近5日是否有涨停")] = True
        df.iat[pos, df.columns.get_loc("涨停距今天数")] = days_since
        df.iat[pos, df.columns.get_loc("涨停日收盘")] = limit_close
        df.iat[pos, df.columns.get_loc("涨停日成交量")] = limit_vol
        df.iat[pos, df.columns.get_loc("涨停日最低价")] = limit_low
        df.iat[pos, df.columns.get_loc("涨停后缩量企稳")] = True

    # =====================================================================
    # 二波形态策略辅助字段（改进版）
    #
    # 脉冲过滤开关：过滤掉单日暴拉的假峰值（如一日涨停后次日崩回）
    # 设为 False 可关闭，恢复原始峰值检测
    # =====================================================================
    ENABLE_PULSE_FILTER = True      # 是否过滤脉冲假峰
    PULSE_MAX_RATIO   = 1.08        # 峰值超过前后3天均价8%以上视为脉冲
    ENABLE_COMPLETED_WAVE_FILTER = True  # 是否过滤"二波已走完"的票
    COMPLETED_WAVE_RECOVERY = 0.60       # 峰后反弹超过跌幅60%视为可能已完成
    COMPLETED_WAVE_DROPOFF  = 0.12       # 且当前价低于反弹高点12%以上 → 确认已走完

    # 二波启动检测需要的辅助字段
    df["昨日最高"] = df["最高"].shift(1)
    df["昨日涨跌幅"] = df["涨跌幅"].shift(1)
    df["近5日最高收盘"] = df["收盘"].shift(1).rolling(5).max()

    close_arr = df["收盘"].values
    high_arr  = df["最高"].values
    low_arr   = df["最低"].values
    ma5_arr   = df["SMA5"].values
    ma20_arr  = df["SMA20"].values
    vol_arr   = df["成交量"].values
    pct_arr   = df["涨跌幅"].values

    n = len(df)
    wave_peak_prices    = np.full(n, np.nan)
    wave_peak_positions = np.full(n, -1, dtype=int)   # 距离当前的天数
    wave_base_prices    = np.full(n, np.nan)
    wave_gains          = np.full(n, np.nan)            # 第一波真实涨幅
    pullback_ratios     = np.full(n, np.nan)            # 从峰值回调幅度(负值)
    room_to_peak        = np.full(n, np.nan)            # 距峰值空间(正值)
    stair_counts        = np.full(n, 0, dtype=int)      # 回调期反弹阳线次数
    wave_vol_avgs       = np.full(n, np.nan)            # 第一波期间均量
    pullback_vol_ratios = np.full(n, np.nan)            # 当前均量/第一波均量
    pullback_dec_ratios = np.full(n, np.nan)            # 回调期量逐日递减占比
    recovery_from_lows  = np.full(n, np.nan)            # 从低点反弹幅度

    for i in range(n):
        if i < 60 or pd.isna(close_arr[i]):
            continue

        # ---- 第一步：在 [3, 35] 天前区间找第一波峰值（用最高价）----
        peak_start = max(0, i - 35)
        peak_end   = max(0, i - 3)
        if peak_end <= peak_start + 3:
            continue

        peak_idx_in_range = peak_start + np.argmax(high_arr[peak_start:peak_end])
        peak_price = high_arr[peak_idx_in_range]  # 用最高价作为峰值

        if pd.isna(peak_price) or peak_price <= 0:
            continue

        # ---- 脉冲过滤：排除单日暴拉的假峰，找下一个真正的峰 ----
        if ENABLE_PULSE_FILTER:
            # 取窗口内所有候选峰值（从高到低），找到第一个非脉冲的
            window_highs = high_arr[peak_start:peak_end]
            candidate_indices = np.argsort(window_highs)[::-1]  # 从高到低排序
            found_real_peak = False
            for cand_offset in candidate_indices:
                cand_idx = peak_start + cand_offset
                cand_price = high_arr[cand_idx]
                if pd.isna(cand_price):
                    continue
                # 比较候选峰和前后3天的均价
                neighbors = []
                for offset in [-3, -2, -1, 1, 2, 3]:
                    ni = cand_idx + offset
                    if 0 <= ni < n and not pd.isna(high_arr[ni]):
                        neighbors.append(high_arr[ni])
                if len(neighbors) >= 3:
                    neighbor_avg = np.mean(neighbors)
                    if cand_price <= neighbor_avg * PULSE_MAX_RATIO:
                        # 不是脉冲峰，采纳
                        peak_idx_in_range = cand_idx
                        peak_price = cand_price
                        found_real_peak = True
                        break
                else:
                    # 邻居不够，放宽条件直接采纳
                    peak_idx_in_range = cand_idx
                    peak_price = cand_price
                    found_real_peak = True
                    break
            if not found_real_peak:
                continue  # 整个窗口都是脉冲，跳过这只票

        # ---- 第二步：峰值之前找一波起涨点（用最低价）----
        base_start = max(0, peak_idx_in_range - 30)
        base_end   = max(0, peak_idx_in_range - 5)
        if base_end <= base_start + 3:
            continue

        base_idx = base_start + np.argmin(low_arr[base_start:base_end])
        base_price = low_arr[base_idx]  # 用最低价作为起涨点

        if pd.isna(base_price) or base_price <= 0:
            continue

        wave_gain = peak_price / base_price - 1
        if wave_gain < 0.35:  # 第一波至少涨35%
            continue

        # ---- 第三步：验证第一波期间 MA5 > MA20 的天数占比 ----
        wave_slice = slice(base_idx, peak_idx_in_range + 1)
        wave_len = peak_idx_in_range - base_idx + 1
        if wave_len < 5:  # 一浪至少5天（模板最低7天）
            continue

        ma5_seg = ma5_arr[wave_slice]
        ma20_seg = ma20_arr[wave_slice]
        valid_mask = ~(pd.isna(ma5_seg) | pd.isna(ma20_seg))
        if valid_mask.sum() < max(5, wave_len * 0.5):
            continue

        uptrend_ratio = (ma5_seg[valid_mask] > ma20_seg[valid_mask]).sum() / valid_mask.sum()
        if uptrend_ratio < 0.50:  # 第一波期间需50%以上天数 MA5 > MA20
            continue

        # ---- 第四步：从峰值到当前的回调特征 ----
        pullback_len = i - peak_idx_in_range
        if pullback_len < 3:   # 回调至少3天
            continue
        if pullback_len > 20:  # 回调最长20天
            continue

        # ---- 第五步：过滤已走完二波的票 ----
        # 条件：反弹超过阈值 + 当前价已从反弹高点回落 → 二波已结束
        if ENABLE_COMPLETED_WAVE_FILTER:
            post_highs = high_arr[peak_idx_in_range + 1:i + 1] if i > peak_idx_in_range else np.array([peak_price])
            post_lows_raw = low_arr[peak_idx_in_range + 1:i + 1] if i > peak_idx_in_range else np.array([peak_price])
            if len(post_lows_raw) > 0 and len(post_highs) > 0:
                trough_val = np.min(post_lows_raw)
                t_idx = np.argmin(post_lows_raw)
                after_trough = post_highs[t_idx:]
                recovery_high = np.max(after_trough) if len(after_trough) > 0 else trough_val
                if peak_price > trough_val:
                    ratio = (recovery_high - trough_val) / (peak_price - trough_val)
                    current_close = close_arr[i]
                    dropped = current_close < recovery_high * (1 - COMPLETED_WAVE_DROPOFF)
                    if ratio >= COMPLETED_WAVE_RECOVERY and dropped:
                        continue  # 二波已走完

        # 峰值以来收盘价的反弹阳线次数（阶梯特征）
        pullback_slice = slice(peak_idx_in_range + 1, i + 1)
        pullback_pct = pct_arr[pullback_slice]
        stair_count = int(((pullback_pct > 2.0) & ~np.isnan(pullback_pct)).sum())

        # 第一波期间的平均成交量
        wave_vol = vol_arr[wave_slice]
        wave_vol_valid = wave_vol[~np.isnan(wave_vol)]
        wave_vol_avg = float(np.mean(wave_vol_valid)) if len(wave_vol_valid) > 0 else np.nan

        # 近10日均量 / 第一波均量（越小越缩量）
        pullback_vol_slice = vol_arr[max(0, i - 9):i + 1]
        pullback_vol_valid = pullback_vol_slice[~np.isnan(pullback_vol_slice)]
        pullback_vol_avg = float(np.mean(pullback_vol_valid)) if len(pullback_vol_valid) > 0 else np.nan
        pullback_vol_ratio = pullback_vol_avg / wave_vol_avg if (wave_vol_avg > 0 and not np.isnan(wave_vol_avg)) else np.nan

        # ---- 存储结果 ----
        wave_peak_prices[i]    = peak_price
        wave_peak_positions[i] = i - peak_idx_in_range
        wave_base_prices[i]    = base_price
        wave_gains[i]          = wave_gain
        # 真实回撤：峰值后最低价 / 峰值最高价 - 1（用高低价，反映最大回撤）
        post_peak_lows = low_arr[peak_idx_in_range + 1:i + 1] if i > peak_idx_in_range else np.array([peak_price])
        lowest_after_peak = np.min(post_peak_lows) if len(post_peak_lows) > 0 else peak_price
        pullback_ratios[i]     = lowest_after_peak / peak_price - 1   # 负值=已回调
        room_to_peak[i]        = 1 - close_arr[i] / peak_price        # 正值=还有空间
        stair_counts[i]        = stair_count
        wave_vol_avgs[i]       = wave_vol_avg
        pullback_vol_ratios[i] = pullback_vol_ratio

        # 从低点反弹幅度：当前价/回调最低点 - 1（>8% 说明已经弹起来了）
        if lowest_after_peak > 0:
            recovery_from_lows[i] = close_arr[i] / lowest_after_peak - 1

        # 回调期量逐日递减占比：峰值后每天量 < 前一天量的天数 / 可比较天数
        pb_vols = vol_arr[peak_idx_in_range + 1:i + 1]  # 峰值后到今天的量
        if len(pb_vols) >= 2:
            valid_mask = ~np.isnan(pb_vols[1:]) & ~np.isnan(pb_vols[:-1])
            if valid_mask.sum() > 0:
                dec_count = int(((pb_vols[1:] < pb_vols[:-1]) & valid_mask).sum())
                pullback_dec_ratios[i] = dec_count / (len(pb_vols) - 1)

    df["第一波峰值"]      = wave_peak_prices
    df["第一波峰值距今天数"] = wave_peak_positions
    df["第一波起涨价"]    = wave_base_prices
    df["第一波涨幅"]      = wave_gains          # 第一波真实涨幅（峰值/起涨价-1）
    df["从高点回调幅度"]  = pullback_ratios      # 负值=已回调
    df["距前高空间"]      = room_to_peak         # 正值=还有空间

    # ---- 阶梯式回调：峰值以来至少出现过2次涨幅>2%的反弹阳线 ----
    df["阶梯式回调"]      = stair_counts >= 2

    # ---- 回调缩量递减占比：峰值后量逐日减少的天数比例 ----
    df["回调缩量递减占比"] = pullback_dec_ratios  # >=0.6 说明量在持续萎缩
    # 从低点反弹幅度：当前价/回调最低点 - 1
    df["距低点反弹幅度"]   = recovery_from_lows    # >0.08 说明已经弹起来了
    # 兼容旧字段（保留供其他策略使用）
    df["回调缩量比"]      = pullback_vol_ratios
    df["缩量比5日"]       = pullback_vol_ratios
    df["缩量比10日"]      = pullback_vol_ratios

    # ---- 均线趋势 ----
    df["MA5_3日前"] = df["SMA5"].shift(3)
    df["MA5趋势"] = df["SMA5"] - df["MA5_3日前"]  # >0 = 上翘
    df["MA10_5日前"] = df["SMA10"].shift(5)
    df["MA10趋势"] = df["SMA10"] - df["MA10_5日前"]

    # ---- MACD（底背离判断）----
    df["EMA12"] = df["收盘"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["收盘"].ewm(span=26, adjust=False).mean()
    df["DIF"] = df["EMA12"] - df["EMA26"]
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD柱"] = 2 * (df["DIF"] - df["DEA"])

    df["DIF_昨日"] = df["DIF"].shift(1)
    df["DEA_昨日"] = df["DEA"].shift(1)
    df["DIF金叉"] = (df["DIF_昨日"] <= df["DEA_昨日"]) & (df["DIF"] > df["DEA"])

    # 底背离：近20日价格新低但DIF拒绝新低
    df["近20日最低收盘"] = df["收盘"].rolling(20, min_periods=15).min()
    df["近20日最低DIF"] = df["DIF"].rolling(20, min_periods=15).min()
    df["前20日最低收盘"] = df["近20日最低收盘"].shift(20)
    df["前20日最低DIF"] = df["近20日最低DIF"].shift(20)
    df["MACD底背离"] = (
        (df["近20日最低收盘"] <= df["前20日最低收盘"] * 1.02)
        & (df["近20日最低DIF"] > df["前20日最低DIF"])
    )

    # ---- 前期平台支撑：40~60天前的20日均价作为平台参考 ----
    df["远期均价"] = df["收盘"].shift(40).rolling(20).mean()
    df["接近前期平台"] = (
        df["远期均价"] > 0
        & (df["收盘"] >= df["远期均价"] * 0.92)
        & (df["收盘"] <= df["远期均价"] * 1.08)
    )

    # ---- 近60日涨停次数（判断"曾经热过"）----
    df["近60日涨停次数"] = (
        df["涨跌幅"] >= 9.95
    ).rolling(60, min_periods=30).sum()

    # 合并碎片化的 DataFrame，消除 PerformanceWarning
    df = df.copy()

    return df


def check_strategy_1(row) -> bool:
    """
    策略1：箱体突破
    前期横盘 + 放量创新高
    """

    return (
        row["收盘"] > row["过去60日最高价"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.3
        and row["过去20日实体振幅"] <= 0.20
    )


def check_strategy_2(row) -> bool:
    """
    策略2：底部放量反转
    V型启动
    """

    distance_from_40d_low = row["收盘"] / row["过去40日最低价"] - 1

    return (
        distance_from_40d_low < 0.20
        and row["涨跌幅"] > 5
        and row["成交量"] > row["过去20日平均成交量"] * 2
    )


def check_strategy_1_main_promotion(row) -> bool:
    """
    主升策略1：股价创60天新高，伴随放量。
    """

    return (
        row["收盘"] > row["过去60日最高收盘"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_2_main_promotion(row) -> bool:
    """
    主升策略2：长期低位 + 突然放量大涨。
    """

    distance_from_low = row["收盘"] / row["过去60日最低收盘"] - 1

    return (
        distance_from_low < 0.30
        and row["涨跌幅"] > 5
        and row["成交量"] > row["过去20日平均成交量"] * 2
    )


def check_strategy_3_main_promotion(row) -> bool:
    """
    主升策略3：缩量回调启动。
    """

    return (
        row["SMA5"] < row["SMA20"]
        and row["SMA60"] > row["SMA60_5日前"]
        and row["收盘"] > row["SMA5"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_4_main_promotion(row) -> bool:
    """
    主升策略4：均线多头排列。
    """

    return (
        row["SMA5"] > row["SMA10"]
        and row["SMA10"] > row["SMA20"]
        and row["SMA20"] > row["SMA60"]
        and row["涨跌幅"] > 2
        and row["成交量"] > row["过去20日平均成交量"] * 1.2
    )


def get_required_strategy_columns() -> list[str]:
    """策略计算前必须存在且不能为 NaN 的指标列。"""

    return [
        "SMA5",
        "SMA10",
        "SMA20",
        "SMA60",
        "过去60日最高价",
        "过去60日最高收盘",
        "过去60日最低收盘",
        "过去40日最低价",
        "过去20日实体振幅",
        "过去20日平均成交量",
        "过去20日日均成交额",
        "近15日涨停次数",
        "SMA60_5日前",
    ]


def build_signal_info(latest: pd.Series, breakthrough_strategies: list[str], main_promotion_strategies: list[str]) -> dict:
    """把策略命中结果整理成主程序、实时扫描、回测都能复用的字段。"""

    hit_strategies = breakthrough_strategies + main_promotion_strategies

    signal_types = []
    if breakthrough_strategies:
        signal_types.append("突破反转")
    if main_promotion_strategies:
        signal_types.append("主升")

    return {
        "信号类型": "、".join(signal_types),
        "突破反转策略": "、".join(breakthrough_strategies),
        "主升策略": "、".join(main_promotion_strategies),
        "突破反转策略数": len(breakthrough_strategies),
        "主升策略数": len(main_promotion_strategies),
        "命中策略数": len(hit_strategies),

        "K线日期": latest["日期"],
        "收盘价": latest["收盘"],
        "最新价": latest["收盘"],
        "今日涨跌幅": latest["涨跌幅"],
        "涨跌幅": latest["涨跌幅"],
        "今日成交量": latest["成交量"],
        "过去20日平均成交量": latest["过去20日平均成交量"],
        "量比": latest["成交量"] / latest["过去20日平均成交量"],

        "过去20日日均成交额": latest["过去20日日均成交额"],
        "过去20日日均成交额_万元": latest["过去20日日均成交额"] / 10000,
        "15日涨停": int(latest["近15日涨停次数"]),

        "过去60日最高价": latest["过去60日最高价"],
        "过去60日最高收盘": latest["过去60日最高收盘"],
        "过去60日最低收盘": latest["过去60日最低收盘"],
        "过去40日最低价": latest["过去40日最低价"],
        "距40日低点涨幅": latest["收盘"] / latest["过去40日最低价"] - 1,
        "过去20日实体振幅": latest["过去20日实体振幅"],
        "距60日低点涨幅": latest["收盘"] / latest["过去60日最低收盘"] - 1,
        "SMA5": latest["SMA5"],
        "SMA10": latest["SMA10"],
        "SMA20": latest["SMA20"],
        "SMA60": latest["SMA60"],

        # 主升-大阳缩量回踩辅助字段，方便导出后复盘。
        "启动大阳距今天数": latest.get("启动大阳距今天数", pd.NA),
        "启动大阳收盘": latest.get("近5日启动大阳收盘", pd.NA),
        "启动大阳成交量": latest.get("近5日启动大阳成交量", pd.NA),
        "回踩不破5日或10日线": latest.get("回踩不破5日或10日线", pd.NA),
        "回调缩量": latest.get("回调缩量", pd.NA),
    }


def evaluate_latest_signal(latest: pd.Series):
    """
    对已经计算好指标的最新K线执行全部已注册日线策略。

    返回：是否命中、命中策略文本、指标信息。
    这是日线扫描、盘中实时扫描、后续回测共用的核心入口。
    """

    need_cols = get_required_strategy_columns()

    if latest[need_cols].isna().any():
        return False, "", None

    signals = evaluate_daily_strategies(latest)

    if not signals:
        return False, "", None

    # 命中策略后，再执行统一二次过滤。
    if not check_secondary_filters(latest):
        return False, "", None

    breakthrough_strategies = [signal.name for signal in signals if signal.category == "突破反转"]
    main_promotion_strategies = [signal.name for signal in signals if signal.category == "主升"]
    hit_strategies = breakthrough_strategies + main_promotion_strategies

    info = build_signal_info(latest, breakthrough_strategies, main_promotion_strategies)

    return True, "、".join(hit_strategies), info


def check_main_rising_signal(
    code: str,
    cache_only: bool = False,
    force_update: bool = False,
):
    """
    检查某只股票是否命中已注册日线策略。
    返回：是否命中、命中的策略、最新行情指标。
    """

    try:
        hist_df = get_hist_data_baostock(
            code,
            use_cache=True,
            cache_only=cache_only,
            force_update=force_update,
        )

        if hist_df is None or hist_df.empty:
            return False, "", None

        hist_df = prepare_hist_data(hist_df)

        # 数据不足65天，无法计算完整策略。
        if len(hist_df) < 65:
            return False, "", None

        latest = hist_df.iloc[-1]
        return evaluate_latest_signal(latest)

    except Exception as e:
        print(f"{code} 策略计算失败：{e}")
        return False, "", None


def scan_main_rising_stocks(
    stock_pool_df: pd.DataFrame,
    cache_only: bool = False,
    force_update: bool = False,
    workers: int = 1,
) -> pd.DataFrame:
    """
    对基础股票池进行主升信号扫描。

    两阶段策略（解决 BaoStock 不支持多线程的问题）：
    阶段1：单线程更新所有缓存（如需联网）
    阶段2：多线程从缓存扫描（workers 默认 1，纯缓存推荐 8）
    """

    result_list = []
    total = len(stock_pool_df)
    allow_update = should_update_daily_cache(
        cache_only=cache_only,
        force_update=force_update,
    )
    login_failed = False

    # ---------- 登录 ----------
    if allow_update:
        if force_update:
            print("日线扫描模式：强制更新 BaoStock 日K缓存。")
        else:
            print(f"日线扫描模式：已到 {DAILY_AUTO_UPDATE_AFTER_TIME} 后，允许 BaoStock 增量更新。")

        print("正在登录 BaoStock...")
        lg = None
        for attempt in range(3):
            try:
                lg = bs.login()
                if getattr(lg, "error_code", None) == "0":
                    break
                print(f"BaoStock 第 {attempt + 1} 次登录失败：{getattr(lg, 'error_msg', '未知错误')}")
            except Exception as exc:
                print(f"BaoStock 第 {attempt + 1} 次登录异常：{exc}")
            if attempt < 2:
                time.sleep(2)

        if getattr(lg, "error_code", None) != "0":
            login_failed = True
            print("BaoStock 登录失败，切换为仅使用本地缓存继续扫描。")
    else:
        lg = None
        if cache_only:
            print(f"日线扫描模式：只使用本地 cache/hist（{workers}线程），不请求 BaoStock。")
        else:
            print(f"日线扫描模式：未到 {DAILY_AUTO_UPDATE_AFTER_TIME}，使用本地 cache/hist（{workers}线程）。")

    do_update = force_update and not login_failed
    scan_start_time = time.time()

    try:
        # ================================================================
        # 阶段1：单线程更新缓存（BaoStock 不支持并发）
        # ================================================================
        if allow_update and not login_failed:
            print(f"\n阶段1：单线程更新日K缓存（共 {total} 只）...")
            phase1_start = time.time()
            failed_stocks = []  # 记录重登后仍然失败的股票，最后统一再抢救一次
            for i, (_, row) in enumerate(stock_pool_df.iterrows(), start=1):
                code = str(row["代码"]).zfill(6)
                name = row["名称"]
                try:
                    get_hist_data_baostock(code, cache_only=False, force_update=do_update)
                except Exception as e:
                    # 内部3次重试都失败 → 重登 → 再试一次
                    print(f"\n  {code} {name} 失败({e})，重登后重试...")
                    try:
                        bs.logout()
                    except Exception:
                        pass
                    time.sleep(2)
                    try:
                        lg = bs.login()
                        if getattr(lg, "error_code", None) == "0":
                            try:
                                get_hist_data_baostock(code, cache_only=False, force_update=do_update)
                            except Exception:
                                failed_stocks.append((code, name))  # 重登后仍失败，记录待抢救
                        else:
                            print(f"  重登失败: {getattr(lg, 'error_msg', '未知')}，切换为仅缓存模式。")
                            break
                    except Exception as login_err:
                        print(f"  重登异常: {login_err}，切换为仅缓存模式。")
                        break

                elapsed = time.time() - phase1_start
                remaining = (total - i) * elapsed / i if i > 0 else 0
                print(
                    f"  缓存更新：{i}/{total} | {code} {name} | "
                    f"预计剩余：{remaining / 60:.1f} 分钟",
                    end="\r",
                    flush=True,
                )
                time.sleep(0.03)
            print()
            print(f"  缓存更新完成，耗时 {time.time()-phase1_start:.1f} 秒")

            # 最后统一抢救一轮失败的股票
            if failed_stocks:
                print(f"\n  最后尝试抢救 {len(failed_stocks)} 只失败的股票...")
                try:
                    bs.logout()
                except Exception:
                    pass
                time.sleep(2)
                try:
                    lg = bs.login()
                    if getattr(lg, "error_code", None) == "0":
                        rescued = 0
                        for fcode, fname in failed_stocks:
                            try:
                                get_hist_data_baostock(fcode, cache_only=False, force_update=do_update)
                                rescued += 1
                                print(f"    {fcode} {fname} ✅")
                            except Exception:
                                print(f"    {fcode} {fname} ❌")
                        print(f"  抢救结果：{rescued}/{len(failed_stocks)} 成功")
                    else:
                        print(f"  抢救前重登失败，跳过。")
                except Exception:
                    print(f"  抢救前重登异常，跳过。")

        # ================================================================
        # 阶段2：多线程从缓存扫描
        # ================================================================
        use_multithread = workers > 1
        scan_cache_only = True  # 阶段2永远只读缓存

        if use_multithread:
            print(f"\n阶段2：{workers}线程从缓存扫描...")
            tasks = [
                (str(row["代码"]).zfill(6), row.to_dict())
                for _, row in stock_pool_df.iterrows()
            ]

            completed = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {}
                for code, meta in tasks:
                    futures[
                        executor.submit(check_main_rising_signal, code, True, False)
                    ] = (code, meta)

                for future in as_completed(futures):
                    code, meta = futures[future]
                    completed += 1
                    try:
                        is_hit, hit_strategy, info = future.result()
                    except Exception:
                        is_hit, hit_strategy, info = False, "", None

                    if is_hit:
                        result = dict(meta)
                        result["命中策略"] = hit_strategy
                        if info:
                            result.update(info)
                        result_list.append(result)

                    if completed % 100 == 0 or completed == total:
                        elapsed = time.time() - scan_start_time
                        avg_s = elapsed / completed
                        remaining = (total - completed) * avg_s
                        print(
                            f"  扫描进度：{completed}/{total} | "
                            f"命中数：{len(result_list)} | "
                            f"预计剩余：{remaining / 60:.1f} 分钟",
                            flush=True,
                        )
        else:
            # ---- 单线程模式 ----
            print()
            for scan_no, (_, row) in enumerate(stock_pool_df.iterrows(), start=1):
                code = str(row["代码"]).zfill(6)
                name = row["名称"]

                is_hit, hit_strategy, info = check_main_rising_signal(
                    code, cache_only=scan_cache_only, force_update=False,
                )

                if is_hit:
                    result = row.to_dict()
                    result["命中策略"] = hit_strategy
                    if info:
                        result.update(info)
                    result_list.append(result)

                elapsed = time.time() - scan_start_time
                remaining = (total - scan_no) * elapsed / scan_no
                print(
                    f"日线扫描进度：{scan_no}/{total} | "
                    f"当前：{code} {name} | "
                    f"命中数：{len(result_list)} | "
                    f"预计剩余：{remaining / 60:.2f} 分钟",
                    end="\r",
                    flush=True,
                )
            print()

    finally:
        if allow_update:
            bs.logout()
            print("BaoStock 已退出。")

    total_seconds = time.time() - scan_start_time

    print("\n第二步信号扫描完成。")
    print(f"扫描股票总数：{total}")
    print(f"命中股票数量：{len(result_list)}")
    print(f"总耗时：{total_seconds / 60:.2f} 分钟")
    if total > 0:
        print(f"平均耗时：{total_seconds / total:.2f} 秒/只")

    if not result_list:
        print("没有股票命中主升信号。")
        return pd.DataFrame()

    result_df = pd.DataFrame(result_list)

    if "量比" in result_df.columns:
        result_df = result_df.sort_values(by="量比", ascending=False)

    return result_df
