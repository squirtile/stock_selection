# strategy.py

import os
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


import pandas as pd
import numpy as np
import baostock as bs

from strategies import evaluate_daily_strategies


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

    # 昨日数据（供策略使用）
    df["昨收"] = df["收盘"].shift(1)
    df["昨开"] = df["开盘"].shift(1)
    df["昨高"] = df["最高"].shift(1)
    df["昨低"] = df["最低"].shift(1)
    df["昨量"] = df["成交量"].shift(1)
    df["昨涨跌"] = df["涨跌幅"].shift(1)

    # 前日涨跌（供N20加速上涨等策略使用）
    df["前涨跌"] = df["涨跌幅"].shift(2)

    # 前日收盘（供跳空缺口等策略使用）
    df["前收"] = df["收盘"].shift(2)

    # 收阳标记
    df["收阳"] = (df["收盘"] > df["开盘"]).fillna(0).astype(int)
    df["昨收阳"] = df["收阳"].shift(1).fillna(0).astype(int)
    df["前收阳"] = df["收阳"].shift(2).fillna(0).astype(int)
    df["收阴"] = (df["收盘"] < df["开盘"]).fillna(0).astype(int)

    # 均量别名（方便策略使用）
    df["均量"] = df["过去20日平均成交量"]

    # ---- 以下为策略所需的附加列（仅保留被多个策略使用的列）----

    # MA shifts（N15均线金叉内联计算用）
    df["SMA5昨"] = df["SMA5"].shift(1)
    df["SMA20昨"] = df["SMA20"].shift(1)
    df["SMA20_5d"] = df["SMA20"].shift(5)

    # 阶段高低点（N7/N17/N23/N26/N34等策略使用）
    df["10日高"] = df["最高"].shift(1).rolling(10).max()
    df["10日低"] = df["最低"].rolling(10).min()
    df["10日最高收"] = df["收盘"].shift(1).rolling(10).max()
    df["20日高"] = df["最高"].shift(1).rolling(20).max()
    df["5日高"] = df["最高"].shift(1).rolling(5).max()
    df["5日低"] = df["最低"].rolling(5).min()

    # 量比（N11/N23/N24等策略使用）
    df["量比昨"] = df["成交量"] / df["昨量"].replace(0, np.nan)

    # 过去13日高低点（B龙头回调、C追涨突破使用）
    df["过去13日最高价"] = df["最高"].shift(1).rolling(13).max()
    df["过去13日最高收"] = df["收盘"].shift(1).rolling(13).max()
    df["过去13日最低收"] = df["收盘"].shift(1).rolling(13).min()

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
        # 昨日/前日数据
        "昨收", "昨开", "昨高", "昨低", "昨量", "昨涨跌",
        "前涨跌", "前收",
        # K线形态
        "收阳", "昨收阳", "前收阳",
        # 量比
        "均量", "量比昨",
        # 阶段高低点
        "5日高", "5日低", "10日高", "10日低", "10日最高收", "20日高",
        # MA shifts
        "SMA5昨", "SMA20昨", "SMA20_5d",
        # 短期高低点
        "过去13日最高价", "过去13日最高收", "过去13日最低收",
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
    }


def evaluate_latest_signal(latest: pd.Series):
    """
    对已经计算好指标的最新K线执行全部已注册日线策略。

    返回：是否命中、命中策略文本、指标信息。
    这是日线扫描、盘中实时扫描、后续回测共用的核心入口。

    优化点：
    1. 先检查指标是否完整；
    2. 再执行统一二次过滤；
    3. 只有通过二次过滤的股票，才进入全部日线策略判断。

    这样不会改变最终选股结果，因为二次过滤本来就是所有策略命中后的统一必要条件，
    只是把它前置，减少无效股票反复执行几十个策略的耗时。
    """

    need_cols = get_required_strategy_columns()

    if latest[need_cols].isna().any():
        return False, "", None

    # 方案3：二次过滤前置。
    # 不满足流动性/涨停活跃度的股票，最终无论命中哪个策略都会被过滤掉，
    # 所以这里直接返回，避免继续跑全部日线策略。
    if not check_secondary_filters(latest):
        return False, "", None

    signals = evaluate_daily_strategies(latest)

    if not signals:
        return False, "", None

    breakthrough_strategies = [
        signal.name for signal in signals
        if signal.category == "突破反转"
    ]
    main_promotion_strategies = [
        signal.name for signal in signals
        if signal.category == "主升"
    ]
    hit_strategies = breakthrough_strategies + main_promotion_strategies

    info = build_signal_info(latest, breakthrough_strategies, main_promotion_strategies)

    return True, "、".join(hit_strategies), info


def check_main_rising_signal(code: str):
    """
    检查某只股票是否命中已注册日线策略。
    返回：是否命中、命中的策略、最新行情指标。
    """

    try:
        hist_df = get_hist_data_baostock(code)

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


def scan_one_daily_candidate(row: pd.Series) -> dict:
    """
    单只股票日线扫描任务。
    给线程池调用，子线程只返回结果，不打印进度，避免并发输出错乱。
    """

    code = str(row.get("代码", "")).zfill(6)
    name = row.get("名称", "")

    try:
        is_hit, hit_strategy, info = check_main_rising_signal(code)

        if not is_hit:
            return {
                "success": True,
                "hit": False,
                "code": code,
                "name": name,
                "result": None,
                "error": "",
            }

        result = row.to_dict()
        result["代码"] = code
        result["命中策略"] = hit_strategy

        if info:
            result.update(info)

        return {
            "success": True,
            "hit": True,
            "code": code,
            "name": name,
            "result": result,
            "error": "",
        }

    except Exception as e:
        return {
            "success": False,
            "hit": False,
            "code": code,
            "name": name,
            "result": None,
            "error": str(e),
        }


def scan_main_rising_stocks(stock_pool_df: pd.DataFrame, max_workers: int = 4) -> pd.DataFrame:
    """
    对基础股票池进行主升信号扫描。

    BaoStock 版本：
    1. 统一登录一次 BaoStock；
    2. 历史K线优先读取本地 cache/hist/*_bs.csv；
    3. 使用线程池并发扫描股票，加快日线级别扫描；
    4. 终端只单行刷新扫描进度，不逐只刷屏。

    max_workers 建议：
    - 4：相对稳妥，适合本地缓存较多但仍可能补数据的情况；
    - 6：缓存基本齐全时可尝试；
    - 不建议过高，避免 BaoStock 或磁盘读写压力过大。
    """

    if stock_pool_df is None or stock_pool_df.empty:
        print("基础股票池为空，跳过日线扫描。")
        return pd.DataFrame()

    df = stock_pool_df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    total = len(df)
    max_workers = max(1, int(max_workers or 1))
    max_workers = min(max_workers, total)

    result_list = []
    failed_count = 0

    print("正在登录 BaoStock，用于第二步 K 线扫描...")
    lg = bs.login()

    if lg.error_code != "0":
        print(f"BaoStock 登录失败：{lg.error_msg}")
        return pd.DataFrame()

    print(
        f"开始并发日线扫描：股票数 {total}，"
        f"并发数 {max_workers}，"
        f"优化：二次过滤前置 + 线程池扫描"
    )

    scan_start_time = time.time()

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}

            for _, row in df.iterrows():
                code = str(row["代码"]).zfill(6)
                future = executor.submit(scan_one_daily_candidate, row.copy())
                future_map[future] = code

            finished = 0

            for future in as_completed(future_map):
                finished += 1
                code = future_map.get(future, "")

                try:
                    item = future.result()
                except Exception as e:
                    failed_count += 1
                    item = {
                        "success": False,
                        "hit": False,
                        "code": code,
                        "name": "",
                        "result": None,
                        "error": str(e),
                    }

                if item.get("success") is False:
                    failed_count += 1

                if item.get("hit") and item.get("result"):
                    result_list.append(item["result"])

                elapsed_seconds = time.time() - scan_start_time
                avg_seconds = elapsed_seconds / finished if finished else 0
                remaining_count = total - finished
                estimated_remaining_seconds = avg_seconds * remaining_count

                # 每 10 只刷新一次进度，最后一只也刷新。
                if finished % 10 == 0 or finished == total:
                    print(
                        f"日线扫描进度：{finished}/{total} | "
                        f"当前：{item.get('code', code)} {item.get('name', '')} | "
                        f"命中数：{len(result_list)} | "
                        f"失败数：{failed_count} | "
                        f"预计剩余：{estimated_remaining_seconds / 60:.2f} 分钟",
                        end="\r",
                        flush=True,
                    )

        print()

    finally:
        bs.logout()
        print("BaoStock 已退出。")

    total_seconds = time.time() - scan_start_time

    print("\n第二步信号扫描完成。")
    print(f"扫描股票总数：{total}")
    print(f"命中股票数量：{len(result_list)}")
    print(f"失败数量：{failed_count}")
    print(f"并发数：{max_workers}")
    print(f"总耗时：{total_seconds / 60:.2f} 分钟")
    if total > 0:
        print(f"平均耗时：{total_seconds / total:.2f} 秒/只")

    if not result_list:
        print("没有股票命中主升信号。")
        return pd.DataFrame()

    result_df = pd.DataFrame(result_list)

    if "代码" in result_df.columns:
        result_df["代码"] = result_df["代码"].astype(str).str.zfill(6)

    if "量比" in result_df.columns:
        result_df = result_df.sort_values(by="量比", ascending=False)

    return result_df
