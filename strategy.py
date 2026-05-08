# strategy.py

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import baostock as bs


HIST_CACHE_DIR = "cache/hist"
SIGNAL_OUTPUT_FILE = "output/a_stock_signal_selected.xlsx"
VERBOSE_KLINE_LOG = False

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


def get_hist_data_baostock(code: str, use_cache: bool = True) -> pd.DataFrame:
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

    old_df = pd.DataFrame()

    if use_cache and os.path.exists(cache_file):
        old_df = pd.read_csv(cache_file, dtype={"代码": str})

        if not old_df.empty and "日期" in old_df.columns:
            old_df["日期"] = pd.to_datetime(old_df["日期"])
            last_date = old_df["日期"].max()

            # 如果缓存已经更新到今天，直接使用
            if last_date.strftime("%Y-%m-%d") >= end_date:
                if VERBOSE_KLINE_LOG:
                    print(f"{code} 使用本地BaoStock缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")
                old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                return old_df

            # 从最后日期的下一天开始补数据
            start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            if VERBOSE_KLINE_LOG:
                print(f"{code} 本地BaoStock缓存最新K线日期：{last_date.strftime('%Y-%m-%d')}，开始增量更新...")
        else:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            if VERBOSE_KLINE_LOG:
                print(f"{code} 缓存文件异常，重新获取最近365天K线...")
    else:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if VERBOSE_KLINE_LOG:
            print(f"{code} 无本地BaoStock缓存，首次获取最近365天K线...")

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
            print(f"{code} BaoStock查询失败：{rs.error_msg}")

            # 如果新数据获取失败，但有旧缓存，就先用旧缓存
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
                "开盘",
                "最高",
                "最低",
                "收盘",
                "成交量",
                "成交额",
                "涨跌幅",
            ]

            for col in numeric_cols:
                new_df[col] = pd.to_numeric(new_df[col], errors="coerce")

            new_df["日期"] = pd.to_datetime(new_df["日期"])

            if not old_df.empty:
                df = pd.concat([old_df, new_df], ignore_index=True)
            else:
                df = new_df

            # 日期去重，保留最后一次
            df = df.drop_duplicates(subset=["日期"], keep="last")

            # 按日期排序
            df = df.sort_values("日期")

            # 只保留最近365个自然日附近的数据，避免文件无限变大
            cutoff_date = datetime.now() - timedelta(days=365)
            df = df[df["日期"] >= cutoff_date]

            latest_date = df["日期"].max().strftime("%Y-%m-%d")
            if VERBOSE_KLINE_LOG:
                print(f"{code} BaoStock K线已更新到：{latest_date}")

            # 保存时日期转成字符串
            df["日期"] = df["日期"].dt.strftime("%Y-%m-%d")
            df.to_csv(cache_file, index=False, encoding="utf-8-sig")

            return df

        else:
            # 没有新数据，说明可能今天还没更新，直接用旧缓存
            if not old_df.empty:
                last_date = old_df["日期"].max()
                if VERBOSE_KLINE_LOG:
                    print(f"{code} BaoStock暂无新数据，使用缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")

                old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
                return old_df

            print(f"{code} BaoStock没有返回K线数据。")
            return pd.DataFrame()

    except Exception as e:
        print(f"{code} BaoStock K线获取失败：{e}")

        if not old_df.empty:
            last_date = old_df["日期"].max()
            if VERBOSE_KLINE_LOG:
                print(f"{code} 使用旧缓存，最新K线日期：{last_date.strftime('%Y-%m-%d')}")

            old_df["日期"] = old_df["日期"].dt.strftime("%Y-%m-%d")
            return old_df

        return pd.DataFrame()


# 兼容旧函数名：如果其他地方还调用 get_hist_data_tushare，也转到 BaoStock。
def get_hist_data_tushare(code: str, use_cache: bool = True, pro=None) -> pd.DataFrame:
    return get_hist_data_baostock(code, use_cache=use_cache)


def prepare_hist_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    整理 K 线数据，计算策略所需指标。
    """

    df = df.copy()

    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期")

    numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 均线
    df["SMA5"] = df["收盘"].rolling(5).mean()
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA60"] = df["收盘"].rolling(60).mean()

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


def check_main_rising_signal(code: str):
    """
    检查某只股票是否命中主升策略。
    返回：是否命中、命中的策略、最新行情指标。
    """

    try:
        hist_df = get_hist_data_baostock(code)

        if hist_df is None or hist_df.empty:
            return False, "", None

        hist_df = prepare_hist_data(hist_df)

        # 数据不足65天，无法计算完整策略
        if len(hist_df) < 65:
            return False, "", None

        latest = hist_df.iloc[-1]

        need_cols = [
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

        if latest[need_cols].isna().any():
            return False, "", None

        breakthrough_strategies = []
        main_promotion_strategies = []

        # 突破 / 反转类
        if check_strategy_1(latest):
            breakthrough_strategies.append("箱体突破")

        if check_strategy_2(latest):
            breakthrough_strategies.append("底部放量反转")

        # 主升类
        if check_strategy_1_main_promotion(latest):
            main_promotion_strategies.append("主升-箱体突破")

        if check_strategy_2_main_promotion(latest):
            main_promotion_strategies.append("主升-底部放量反转")

        if check_strategy_3_main_promotion(latest):
            main_promotion_strategies.append("主升-缩量回调启动")

        if check_strategy_4_main_promotion(latest):
            main_promotion_strategies.append("主升-均线多头排列")

        hit_strategies = breakthrough_strategies + main_promotion_strategies

        if len(hit_strategies) == 0:
            return False, "", None

        signal_types = []

        if len(breakthrough_strategies) > 0:
            signal_types.append("突破反转")

        if len(main_promotion_strategies) > 0:
            signal_types.append("主升")

        # 命中策略后，再执行统一二次过滤
        if not check_secondary_filters(latest):
            return False, "", None

        info = {
            "信号类型": "、".join(signal_types),
            "突破反转策略": "、".join(breakthrough_strategies),
            "主升策略": "、".join(main_promotion_strategies),
            "突破反转策略数": len(breakthrough_strategies),
            "主升策略数": len(main_promotion_strategies),
            "命中策略数": len(hit_strategies),

            "K线日期": latest["日期"],
            "收盘价": latest["收盘"],
            "今日涨跌幅": latest["涨跌幅"],
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
        }

        return True, "、".join(hit_strategies), info

    except Exception as e:
        print(f"{code} 策略计算失败：{e}")
        return False, "", None


def scan_main_rising_stocks(stock_pool_df: pd.DataFrame) -> pd.DataFrame:
    """
    对基础股票池进行主升信号扫描。

    BaoStock 版本：
    1. 统一登录一次 BaoStock
    2. 历史K线优先读取本地 cache/hist/*_bs.csv
    3. 终端只单行刷新扫描进度，不逐只刷屏
    """

    result_list = []
    total = len(stock_pool_df)

    print("正在登录 BaoStock，用于第二步 K 线扫描...")
    lg = bs.login()

    if lg.error_code != "0":
        print(f"BaoStock 登录失败：{lg.error_msg}")
        return pd.DataFrame()

    scan_start_time = time.time()

    try:
        for scan_no, (_, row) in enumerate(stock_pool_df.iterrows(), start=1):
            code = str(row["代码"]).zfill(6)
            name = row["名称"]

            is_hit, hit_strategy, info = check_main_rising_signal(code)

            if is_hit:
                result = row.to_dict()
                result["命中策略"] = hit_strategy

                if info:
                    result.update(info)

                result_list.append(result)

            elapsed_seconds = time.time() - scan_start_time
            avg_seconds = elapsed_seconds / scan_no
            remaining_count = total - scan_no
            estimated_remaining_seconds = avg_seconds * remaining_count

            print(
                f"日线扫描进度：{scan_no}/{total} | "
                f"当前：{code} {name} | "
                f"命中数：{len(result_list)} | "
                f"预计剩余：{estimated_remaining_seconds / 60:.2f} 分钟",
                end="\r",
                flush=True,
            )

            # BaoStock相对稳定，轻微限速即可
            time.sleep(0.05)

        print()

    finally:
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
