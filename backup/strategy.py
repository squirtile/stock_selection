# strategy.py

import os
import time
from datetime import datetime, timedelta
from data_loader import disable_proxy

import akshare as ak
import pandas as pd


HIST_CACHE_DIR = "cache/hist"
SIGNAL_OUTPUT_FILE = "output/a_stock_signal_selected.xlsx"

# 二次过滤条件
MIN_AVG_AMOUNT_20D = 50_000_000      # 过去20天日均成交额 >= 5000万
LIMIT_UP_PCT = 9.95                  # 主板涨停判断：涨幅 >= 9.95%
LIMIT_UP_WINDOW = 15                 # 过去15个交易日

def check_secondary_filters(row) -> bool:
    """
    策略命中后的统一二次过滤：

    1. 过去20天日均成交额 >= 5000万
    2. 过去15个交易日，含今日，至少出现1次涨停
    """

    return (
        row["过去20日日均成交额"] >= MIN_AVG_AMOUNT_20D
        and row["近15日涨停次数"] >= 1
    )

# def get_hist_data(code: str, use_cache: bool = True) -> pd.DataFrame:
#     """
#     获取个股日 K 线数据。
#     优先读取本地缓存，避免每次重复请求。
#     """
#      # 这里一定要加
#     disable_proxy()

#     os.makedirs(HIST_CACHE_DIR, exist_ok=True)

#     code = str(code).zfill(6)
#     cache_file = os.path.join(HIST_CACHE_DIR, f"{code}.csv")

#     if use_cache and os.path.exists(cache_file):
#         df = pd.read_csv(cache_file)
#     else:
#         end_date = datetime.now().strftime("%Y%m%d")
#         start_date = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")

#         df = ak.stock_zh_a_hist(
#             symbol=code,
#             period="daily",
#             start_date=start_date,
#             end_date=end_date,
#             adjust="qfq"
#         )

#         if df is not None and not df.empty:
#             df.to_csv(cache_file, index=False, encoding="utf-8-sig")

#         # 防止请求太快被限制
#         time.sleep(0.2)

#     return df

def get_hist_data(code: str, use_cache: bool = True) -> pd.DataFrame:
    """
    获取个股日 K 线数据。
    优先读取本地缓存，避免每次重复请求。
    东方财富接口不稳定，所以必须限速 + 重试。
    """

    disable_proxy()

    os.makedirs(HIST_CACHE_DIR, exist_ok=True)

    code = str(code).zfill(6)
    cache_file = os.path.join(HIST_CACHE_DIR, f"{code}.csv")

    # 有缓存就直接读，千万不要重复请求
    if use_cache and os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=300)).strftime("%Y%m%d")

    max_retry = 5
    sleep_seconds = 8
    last_error = None

    for i in range(max_retry):
        try:
            print(f"{code} 正在获取K线，第 {i + 1}/{max_retry} 次尝试...")

            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"
            )

            if df is not None and not df.empty:
                df.to_csv(cache_file, index=False, encoding="utf-8-sig")
                return df

        except Exception as e:
            last_error = e
            print(f"{code} K线获取失败，第 {i + 1}/{max_retry} 次：{e}")
            time.sleep(sleep_seconds)

    print(f"{code} K线多次获取失败，跳过。最后错误：{last_error}")

    return pd.DataFrame()


def prepare_hist_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    整理 K 线数据，计算策略所需指标。
    """

    df = df.copy()

    # 按日期排序
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")

    # 转成数值
    # numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "涨跌幅"]
    numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 均线
    df["SMA5"] = df["收盘"].rolling(5).mean()
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA60"] = df["收盘"].rolling(60).mean()

    # 过去 60 天最高价，不含今日
    df["过去60日最高收盘"] = df["收盘"].shift(1).rolling(60).max()

    # 过去 60 天最低价，不含今日
    df["过去60日最低收盘"] = df["收盘"].shift(1).rolling(60).min()

    # 过去 20 天平均成交量，不含今日
    df["过去20日平均成交量"] = df["成交量"].shift(1).rolling(20).mean()

    # 过去20天日均成交额，含今日
    df["过去20日日均成交额"] = df["成交额"].rolling(20).mean()

    # 过去15个交易日内涨停次数，含今日
    df["近15日涨停次数"] = (df["涨跌幅"] >= LIMIT_UP_PCT).rolling(LIMIT_UP_WINDOW).sum()

    # 5 天前的 60 日均线
    df["SMA60_5日前"] = df["SMA60"].shift(5)

    return df


def check_strategy_1(row) -> bool:
    """
    策略1：
    股价创60天新高，伴随放量
    今日收盘价 > max(过去60天，不含今日)
    今日成交量 > avg(过去20天 volume) * 1.5
    """

    return (
        row["收盘"] > row["过去60日最高收盘"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_2(row) -> bool:
    """
    策略2：
    长期低位 + 突然放量大涨
    当前价格距60天最低点 < 30%
    今日涨幅 > 5%
    今日成交量 > avg(过去20天 volume) * 2
    """

    distance_from_low = row["收盘"] / row["过去60日最低收盘"] - 1

    return (
        distance_from_low < 0.30
        and row["涨跌幅"] > 5
        and row["成交量"] > row["过去20日平均成交量"] * 2
    )


def check_strategy_3(row) -> bool:
    """
    策略3：
    短期回调结束，重新启动

    SMA(5) < SMA(20)
    SMA(60) > SMA(60, 5天前)
    今日收盘 > SMA(5)
    今日成交量 > avg(过去20天 volume) * 1.5
    """

    return (
        row["SMA5"] < row["SMA20"]
        and row["SMA60"] > row["SMA60_5日前"]
        and row["收盘"] > row["SMA5"]
        and row["成交量"] > row["过去20日平均成交量"] * 1.5
    )


def check_strategy_4(row) -> bool:
    """
    策略4：
    均线多头排列

    SMA(5) > SMA(10) > SMA(20) > SMA(60)
    今日涨幅 > 2%
    今日成交量 > avg(过去20天 volume) * 1.2
    """

    return (
        row["SMA5"] > row["SMA10"]
        and row["SMA10"] > row["SMA20"]
        and row["SMA20"] > row["SMA60"]
        and row["涨跌幅"] > 2
        and row["成交量"] > row["过去20日平均成交量"] * 1.2
    )


def check_main_rising_signal(code: str):
    """
    检查某只股票是否命中主升策略。
    返回：
    是否命中、命中的策略、最新行情指标
    """

    try:
        hist_df = get_hist_data(code)

        if hist_df is None or hist_df.empty:
            return False, "", None

        hist_df = prepare_hist_data(hist_df)

        # 数据不足 65 天，无法计算完整策略
        if len(hist_df) < 65:
            return False, "", None

        latest = hist_df.iloc[-1]

        # 如果关键指标为空，跳过
        need_cols = [
            "SMA5",
            "SMA10",
            "SMA20",
            "SMA60",
            "过去60日最高收盘",
            "过去60日最低收盘",
            "过去20日平均成交量",
            "过去20日日均成交额",
            "近15日涨停次数",
            "SMA60_5日前",
        ]

        if latest[need_cols].isna().any():
            return False, "", None

        hit_strategies = []

        if check_strategy_1(latest):
            hit_strategies.append("箱体突破")

        if check_strategy_2(latest):
            hit_strategies.append("底部放量反转")

        if check_strategy_3(latest):
            hit_strategies.append("缩量回调启动")

        if check_strategy_4(latest):
            hit_strategies.append("均线多头排列")

        # 四个主升策略一个都没命中，直接排除
        if len(hit_strategies) == 0:
            return False, "", None

        # 命中策略后，再进行统一二次过滤
        if not check_secondary_filters(latest):
            return False, "", None

        info = {
            "K线日期": latest["日期"],
            "收盘价": latest["收盘"],
            "今日涨跌幅": latest["涨跌幅"],
            "今日成交量": latest["成交量"],
            "过去20日平均成交量": latest["过去20日平均成交量"],
            "量比": latest["成交量"] / latest["过去20日平均成交量"],

            "过去20日日均成交额": latest["过去20日日均成交额"],
            "过去20日日均成交额_万元": latest["过去20日日均成交额"] / 10000,
            "15日涨停": int(latest["近15日涨停次数"]),

            "过去60日最高收盘": latest["过去60日最高收盘"],
            "过去60日最低收盘": latest["过去60日最低收盘"],
            "距60日低点涨幅": latest["收盘"] / latest["过去60日最低收盘"] - 1,
            "SMA5": latest["SMA5"],
            "SMA10": latest["SMA10"],
            "SMA20": latest["SMA20"],
            "SMA60": latest["SMA60"],
        }

        return True, "、".join(hit_strategies), info

    except Exception as e:
        print(f"{code} 策略计算失败：{e}")
        return False, "", None


def scan_main_rising_stocks(stock_pool_df: pd.DataFrame) -> pd.DataFrame:
    """
    对基础股票池进行主升信号扫描。
    """

    result_list = []

    total = len(stock_pool_df)

    for index, row in stock_pool_df.iterrows():
        code = str(row["代码"]).zfill(6)
        name = row["名称"]

        print(f"正在扫描 {index + 1}/{total}：{code} {name}")

        is_hit, hit_strategy, info = check_main_rising_signal(code)

        if is_hit:
            result = row.to_dict()
            result["命中策略"] = hit_strategy

            if info:
                result.update(info)

            result_list.append(result)

        # 很重要：控制请求频率，避免东方财富断连
        time.sleep(1.2)

    if not result_list:
        print("没有股票命中主升信号。")
        return pd.DataFrame()

    result_df = pd.DataFrame(result_list)

    # 排序：优先按量比从高到低
    if "量比" in result_df.columns:
        result_df = result_df.sort_values(by="量比", ascending=False)

    return result_df