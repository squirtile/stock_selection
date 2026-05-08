# realtime_strategy.py
# 盘中实时策略扫描：读取基础股票池 + 本地历史K线缓存 + Tushare老接口实时行情
#
# 使用方式：
#   python realtime_strategy.py --once
#   python realtime_strategy.py --loop --interval 60
#
# 说明：
# 1. 基础股票池来自 output/a_stock_selected.xlsx，由 main.py 使用 Tushare Pro 生成。
# 2. 历史K线优先读取 cache/hist/*_bs.csv，即 BaoStock 本地缓存。
# 3. 盘中实时行情使用 tushare.get_realtime_quotes()。
# 4. 本脚本不会修改 main.py，也不会替代盘后选股流程。

import argparse
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import tushare as ts
from wcwidth import wcswidth

from strategy import (
    HIST_CACHE_DIR,
    prepare_hist_data,
    check_strategy_1,
    check_strategy_2,
    check_strategy_1_main_promotion,
    check_strategy_2_main_promotion,
    check_strategy_3_main_promotion,
    check_strategy_4_main_promotion,
    check_secondary_filters,
)

from minute_strategy import scan_minute_buy_points


BASE_POOL_FILE = "output/a_stock_selected.xlsx"
OUTPUT_DIR = "output"
REALTIME_INCREMENTAL_DIR = "output/realtime_incremental"
DEFAULT_BATCH_SIZE = 50
DEFAULT_INTERVAL_SECONDS = 60


def align_text(text, width, align="left"):
    """
    按中文显示宽度对齐字符串。
    中文字符通常占2个宽度，英文数字占1个宽度。
    """

    text = "" if pd.isna(text) else str(text)
    text_width = wcswidth(text)
    padding = width - text_width

    if padding <= 0:
        return text

    if align == "right":
        return " " * padding + text

    if align == "center":
        left = padding // 2
        right = padding - left
        return " " * left + text + " " * right

    return text + " " * padding


def print_realtime_table(df: pd.DataFrame, max_rows: int = 50):
    """
    以和 daily 模式类似的纯文本表格展示实时命中结果。
    解决 pandas 默认输出导致中文列名、中文股票名错位的问题。
    """

    if df is None or df.empty:
        print("没有可展示的实时命中股票。")
        return

    show_cols = [
        "代码",
        "名称",
        "行情日期",
        "行情时间",
        "最新价",
        "涨跌幅",
        "行业",
        "量比",
    ]

    show_cols = [col for col in show_cols if col in df.columns]
    show_df = df[show_cols].copy().head(max_rows)

    if "代码" in show_df.columns:
        show_df["代码"] = show_df["代码"].astype(str).str.zfill(6)

    # 日期/时间格式化，避免 2026-05-08 00:00:00 太长。
    for col in ["K线日期", "行情日期"]:
        if col in show_df.columns:
            show_df[col] = pd.to_datetime(show_df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    numeric_2_cols = [
        "最新价",
        "涨跌幅",
        "量比",
    ]

    for col in numeric_2_cols:
        if col in show_df.columns:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else f"{x:.2f}"
            )

    for col in ["15日涨停", "命中策略数"]:
        if col in show_df.columns:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else str(int(x))
            )

    min_widths = {
        "代码": 8,
        "名称": 10,
        "行情日期": 12,
        "行情时间": 10,
        "最新价": 8,
        "涨跌幅": 8,
        "行业": 12,
        "量比": 8,
    }

    col_widths = {}

    for col in show_cols:
        max_width = wcswidth(col)
        for value in show_df[col].astype(str).tolist():
            max_width = max(max_width, wcswidth(value))
        col_widths[col] = max(max_width, min_widths.get(col, 8))

    right_align_cols = {
        "最新价",
        "涨跌幅",
        "总市值_亿元",
        "量比",
        "15日涨停",
        "命中策略数",
        "成交额_亿元",
        "流通市值_亿元",
    }

    header_parts = []
    for col in show_cols:
        align = "right" if col in right_align_cols else "left"
        header_parts.append(align_text(col, col_widths[col], align))

    print(" | ".join(header_parts))

    sep_parts = ["-" * col_widths[col] for col in show_cols]
    print("-+-".join(sep_parts))

    for _, row in show_df.iterrows():
        row_parts = []
        for col in show_cols:
            align = "right" if col in right_align_cols else "left"
            row_parts.append(align_text(row[col], col_widths[col], align))
        print(" | ".join(row_parts))


def load_base_pool(base_pool_file: str = BASE_POOL_FILE) -> pd.DataFrame:
    """
    读取基础股票池。
    基础股票池由 main.py 生成，数据源是 Tushare Pro。
    """

    if not os.path.exists(base_pool_file):
        raise FileNotFoundError(
            f"没有找到基础股票池文件：{base_pool_file}\n"
            "请先运行 python main.py 生成 output/a_stock_selected.xlsx"
        )

    df = pd.read_excel(base_pool_file, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    print(f"基础股票池数量：{len(df)}")
    return df


def fetch_one_realtime_batch(batch_codes, batch_no, total_batch):
    """
    获取一批实时行情。
    子线程里不打印，避免并发输出错乱。
    """

    try:
        df = ts.get_realtime_quotes(batch_codes)

        if df is not None and not df.empty:
            return {
                "batch_no": batch_no,
                "success": True,
                "count": len(df),
                "df": df,
                "error": "",
            }

        return {
            "batch_no": batch_no,
            "success": False,
            "count": 0,
            "df": pd.DataFrame(),
            "error": "返回空",
        }

    except Exception as e:
        return {
            "batch_no": batch_no,
            "success": False,
            "count": 0,
            "df": pd.DataFrame(),
            "error": str(e),
        }


def get_realtime_quotes_batch(
    codes,
    batch_size=100,
    sleep_seconds=0.1,
    max_workers=4
):
    """
    并发分批获取实时行情。

    原来是串行请求：
    12批 × 每批约5秒 = 60秒+

    现在并发请求：
    12批 / 4线程 ≈ 3轮请求
    理论上可明显加速。
    """

    all_list = []
    total = len(codes)

    batches = []

    for start in range(0, total, batch_size):
        batch_codes = codes[start:start + batch_size]
        batches.append(batch_codes)

    total_batch = len(batches)

    start_time = time.time()

    print(
        f"开始并发获取实时行情：股票数 {total}，"
        f"批次数 {total_batch}，每批 {batch_size}，并发数 {max_workers}"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}

        for idx, batch_codes in enumerate(batches):
            batch_no = idx + 1

            future = executor.submit(
                fetch_one_realtime_batch,
                batch_codes,
                batch_no,
                total_batch
            )

            future_map[future] = batch_no

            # 轻微错峰，避免瞬间打爆接口
            time.sleep(sleep_seconds)

        finished_batches = 0
        success_stocks = 0
        failed_batches = 0

        for future in as_completed(future_map):
            result = future.result()

            finished_batches += 1

            if result["success"] and result["df"] is not None and not result["df"].empty:
                all_list.append(result["df"])
                success_stocks += result["count"]
            else:
                failed_batches += 1

            print(
                f"实时行情获取进度：{finished_batches}/{total_batch} 批 | "
                f"已获取股票：{success_stocks}/{total} | "
                f"失败批次：{failed_batches}",
                end="\r",
                flush=True,
            )

        print()

    elapsed = time.time() - start_time

    if not all_list:
        print("没有获取到任何实时行情。")
        return pd.DataFrame()

    result = pd.concat(all_list, ignore_index=True)

    result = result.drop_duplicates(subset=["code"], keep="last")

    print(f"实时行情获取完成，数量：{len(result)}，耗时：{elapsed:.2f} 秒")

    return result

def format_realtime_df(rt_df: pd.DataFrame) -> pd.DataFrame:
    """
    整理实时行情字段，转换为后续策略需要的动态日K字段。
    """

    if rt_df is None or rt_df.empty:
        return pd.DataFrame()

    df = rt_df.copy()

    df["代码"] = df["code"].astype(str).str.zfill(6)
    df["名称"] = df["name"].astype(str)

    numeric_cols = [
        "open",
        "pre_close",
        "price",
        "high",
        "low",
        "volume",
        "amount",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 停牌或异常行情常见 price/open 为 0，这里先剔除。
    df = df[(df["price"] > 0) & (df["open"] > 0)].copy()

    if df.empty:
        return pd.DataFrame()

    df["实时涨跌幅"] = (df["price"] / df["pre_close"] - 1) * 100
    # 过滤已经涨停的股票
    # 主板普通股票涨停一般约为 10%，这里用 9.8 作为近似阈值
    # 因为实时行情里涨停可能显示为 9.96、9.98、10.00、10.03 等
    before_count = len(df)

    df = df[df["实时涨跌幅"] < 9.8].copy()

    print(f"过滤已涨停股票：{before_count} -> {len(df)}")

    result = pd.DataFrame()
    result["代码"] = df["代码"]
    result["名称"] = df["名称"]
    result["行情日期"] = df["date"]
    result["行情时间"] = df["time"]
    result["开盘"] = df["open"]
    result["最高"] = df["high"]
    result["最低"] = df["low"]
    result["收盘"] = df["price"]       # 用实时最新价作为动态日K收盘价
    result["昨收"] = df["pre_close"]
    result["涨跌幅"] = df["实时涨跌幅"]
    result["成交量"] = df["volume"]
    result["成交额"] = df["amount"]

    return result


def load_hist_cache(code: str) -> pd.DataFrame:
    """
    读取本地历史K线缓存。
    优先读取 BaoStock 缓存 *_bs.csv。
    如果没有，则兼容读取之前 Tushare 测试时留下的 *_ts.csv。
    """

    code = str(code).zfill(6)

    bs_cache = os.path.join(HIST_CACHE_DIR, f"{code}_bs.csv")
    ts_cache = os.path.join(HIST_CACHE_DIR, f"{code}_ts.csv")

    cache_file = None

    if os.path.exists(bs_cache):
        cache_file = bs_cache
    elif os.path.exists(ts_cache):
        cache_file = ts_cache

    if cache_file is None:
        return pd.DataFrame()

    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
    except Exception as e:
        print(f"{code} 历史缓存读取失败：{e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    df["代码"] = code

    needed_cols = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅", "代码"]
    for col in needed_cols:
        if col not in df.columns:
            print(f"{code} 历史缓存缺少字段：{col}")
            return pd.DataFrame()

    return df[needed_cols].copy()


def append_realtime_bar(hist_df: pd.DataFrame, rt_row: pd.Series) -> pd.DataFrame:
    """
    把实时行情拼成今日动态日K，并追加到历史K线末尾。
    如果历史缓存里已经有同一天K线，则用实时K线覆盖当天这一行。
    """

    hist_df = hist_df.copy()
    hist_df["日期"] = pd.to_datetime(hist_df["日期"])

    rt_date = pd.to_datetime(rt_row["行情日期"])
    code = str(rt_row["代码"]).zfill(6)

    # 删除历史中同日期数据，避免重复。
    hist_df = hist_df[hist_df["日期"] != rt_date].copy()

    today_bar = {
        "日期": rt_date,
        "开盘": rt_row["开盘"],
        "最高": rt_row["最高"],
        "最低": rt_row["最低"],
        "收盘": rt_row["收盘"],
        "成交量": rt_row["成交量"],
        "成交额": rt_row["成交额"],
        "涨跌幅": rt_row["涨跌幅"],
        "代码": code,
    }

    combined = pd.concat([hist_df, pd.DataFrame([today_bar])], ignore_index=True)
    combined = combined.drop_duplicates(subset=["日期"], keep="last")
    combined = combined.sort_values("日期")

    return combined


def evaluate_strategy_from_hist(hist_df: pd.DataFrame):
    """
    对追加了实时动态日K后的历史数据执行原有策略判断。
    返回：是否命中、命中策略文本、指标信息。
    """

    if hist_df is None or hist_df.empty:
        return False, "", None

    prepared = prepare_hist_data(hist_df)

    if len(prepared) < 65:
        return False, "", None

    latest = prepared.iloc[-1]

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

    if check_strategy_1(latest):
        breakthrough_strategies.append("箱体突破")

    if check_strategy_2(latest):
        breakthrough_strategies.append("底部放量反转")

    if check_strategy_1_main_promotion(latest):
        main_promotion_strategies.append("主升-箱体突破")

    if check_strategy_2_main_promotion(latest):
        main_promotion_strategies.append("主升-底部放量反转")

    if check_strategy_3_main_promotion(latest):
        main_promotion_strategies.append("主升-缩量回调启动")

    if check_strategy_4_main_promotion(latest):
        main_promotion_strategies.append("主升-均线多头排列")

    hit_strategies = breakthrough_strategies + main_promotion_strategies

    if not hit_strategies:
        return False, "", None

    # 沿用原主程序的统一二次过滤。
    if not check_secondary_filters(latest):
        return False, "", None

    signal_types = []
    if breakthrough_strategies:
        signal_types.append("突破反转")
    if main_promotion_strategies:
        signal_types.append("主升")

    info = {
        "信号类型": "、".join(signal_types),
        "突破反转策略": "、".join(breakthrough_strategies),
        "主升策略": "、".join(main_promotion_strategies),
        "突破反转策略数": len(breakthrough_strategies),
        "主升策略数": len(main_promotion_strategies),
        "命中策略数": len(hit_strategies),
        "K线日期": latest["日期"],
        "最新价": latest["收盘"],
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

    return True, "、".join(hit_strategies), info


def split_realtime_sections(signal_df: pd.DataFrame):
    """
    按原 main.py 逻辑拆分突破反转和纯主升。
    """

    if signal_df is None or signal_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    breakthrough_df = signal_df[
        signal_df["信号类型"].astype(str).str.contains("突破反转", na=False)
    ].copy()

    main_promotion_df = signal_df[
        signal_df["信号类型"].astype(str).str.contains("主升", na=False)
        & ~signal_df["信号类型"].astype(str).str.contains("突破反转", na=False)
    ].copy()

    return breakthrough_df, main_promotion_df

def build_incremental_key(df: pd.DataFrame) -> pd.Series:
    """
    构造增量去重键。
    同一股票 + 同一策略组合，当天只保存一次。
    如果同一股票后续策略发生变化，则会作为新记录追加。
    """

    df = df.copy()

    for col in ["代码", "信号类型", "突破反转策略", "主升策略"]:
        if col not in df.columns:
            df[col] = ""

    return (
        df["代码"].fillna("").astype(str).str.zfill(6)
        + "|"
        + df["信号类型"].fillna("").astype(str)
        + "|"
        + df["突破反转策略"].fillna("").astype(str)
        + "|"
        + df["主升策略"].fillna("").astype(str)
    )


def save_daily_incremental_result(export_df: pd.DataFrame):
    """
    保存到当日增量文件。

    逻辑：
    1. 每轮扫描仍然是全量扫描。
    2. 终端仍然展示本轮全部命中。
    3. Excel 只追加当天没有保存过的“新增命中/策略变化”。
    """

    if export_df is None or export_df.empty:
        return pd.DataFrame(), ""

    os.makedirs(REALTIME_INCREMENTAL_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    incremental_file = os.path.join(
        REALTIME_INCREMENTAL_DIR,
        f"realtime_incremental_{today}.xlsx"
    )

    current_df = export_df.copy()
    current_df["代码"] = current_df["代码"].astype(str).str.zfill(6)
    current_df["记录时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_df["增量Key"] = build_incremental_key(current_df)

    if os.path.exists(incremental_file):
        try:
            old_df = pd.read_excel(incremental_file, dtype={"代码": str})
            old_df["代码"] = old_df["代码"].astype(str).str.zfill(6)

            if "增量Key" not in old_df.columns:
                old_df["增量Key"] = build_incremental_key(old_df)

            old_keys = set(old_df["增量Key"].dropna().astype(str).tolist())

        except Exception as e:
            print(f"读取当日增量文件失败，将重新创建。错误：{e}")
            old_df = pd.DataFrame()
            old_keys = set()
    else:
        old_df = pd.DataFrame()
        old_keys = set()

    new_df = current_df[
        ~current_df["增量Key"].astype(str).isin(old_keys)
    ].copy()

    if new_df.empty:
        return pd.DataFrame(), incremental_file

    if old_df is not None and not old_df.empty:
        save_df = pd.concat([old_df, new_df], ignore_index=True)
    else:
        save_df = new_df

    # 排序：记录时间升序，同一时间内命中策略数和量比高的靠前
    sort_cols = []
    ascending = []

    if "记录时间" in save_df.columns:
        sort_cols.append("记录时间")
        ascending.append(True)

    if "命中策略数" in save_df.columns:
        sort_cols.append("命中策略数")
        ascending.append(False)

    if "量比" in save_df.columns:
        sort_cols.append("量比")
        ascending.append(False)

    if sort_cols:
        save_df = save_df.sort_values(by=sort_cols, ascending=ascending)

    save_df.to_excel(incremental_file, index=False)

    return new_df, incremental_file

def scan_realtime_once(
    base_pool_file: str = BASE_POOL_FILE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    quote_sleep: float = 0.5,
    max_stocks: int = 0,
    max_workers: int = 4,
    enable_minute: bool = True,
    minute_max_stocks: int = 0,
) -> pd.DataFrame:
    """
    执行一轮实时扫描。
    """

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pool_df = load_base_pool(base_pool_file)

    if max_stocks and max_stocks > 0:
        pool_df = pool_df.head(max_stocks).copy()
        print(f"测试模式：只扫描前 {len(pool_df)} 只股票。")

    codes = pool_df["代码"].astype(str).str.zfill(6).tolist()

    rt_raw_df = get_realtime_quotes_batch(
        codes,
        batch_size=batch_size,
        sleep_seconds=quote_sleep,
        max_workers=max_workers,
    )

    rt_df = format_realtime_df(rt_raw_df)

    if rt_df.empty:
        print("实时行情为空，本轮扫描结束。")
        return pd.DataFrame()

    # 合并基础股票池信息，方便导出行业、市值等字段。
    # 注意：基础池里也有“涨跌幅/成交额”等列，如果直接合并，pandas 会生成
    # “涨跌幅_x/涨跌幅_y”，导致后面找不到实时行情的“涨跌幅”。
    # 所以这里排除会和实时行情动态日K冲突的字段，只保留行业、市值等辅助字段。
    realtime_cols = {
        "名称",
        "行情日期",
        "行情时间",
        "开盘",
        "最高",
        "最低",
        "收盘",
        "昨收",
        "最新价",
        "涨跌幅",
        "成交量",
        "成交额",
    }
    pool_cols = [
        col for col in pool_df.columns
        if col == "代码" or col not in realtime_cols
    ]
    merged_rt_df = rt_df.merge(pool_df[pool_cols], on="代码", how="left")

    result_list = []
    total = len(merged_rt_df)
    scan_start_time = time.time()

    for scan_no, (_, row) in enumerate(merged_rt_df.iterrows(), start=1):
        code = str(row["代码"]).zfill(6)
        name = row.get("名称", "")

        hist_df = load_hist_cache(code)

        if hist_df.empty:
            # 没有缓存就跳过，不单独刷屏
            continue

        # 防止合并字段冲突或异常行情导致关键列缺失。
        required_realtime_cols = ["行情日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]
        missing_cols = [col for col in required_realtime_cols if col not in row.index]
        if missing_cols:
            continue

        combined_df = append_realtime_bar(hist_df, row)
        is_hit, hit_strategy, info = evaluate_strategy_from_hist(combined_df)

        if is_hit:
            result = row.to_dict()
            result["命中策略"] = hit_strategy
            result.update(info)
            result_list.append(result)

            # 命中时单独打印，方便你马上看到
            # print(" " * 120, end="\r")
            # print(f"✅ 实时命中：{code} {name} | {hit_strategy}")

        elapsed_seconds = time.time() - scan_start_time
        avg_seconds = elapsed_seconds / scan_no
        remaining_seconds = avg_seconds * (total - scan_no)

        # 每 20 只刷新一次进度，最后一只也刷新
        if scan_no % 20 == 0 or scan_no == total:
            print(
                f"实时扫描进度：{scan_no}/{total} | "
                f"命中数：{len(result_list)} | "
                f"预计剩余：{remaining_seconds:.1f} 秒",
                end="\r",
                flush=True,
            )

    print()

    if not result_list:
        print("\n本轮没有实时命中股票。")
        return pd.DataFrame()

    signal_df = pd.DataFrame(result_list)
    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    sort_cols = []
    ascending = []

    if "命中策略数" in signal_df.columns:
        sort_cols.append("命中策略数")
        ascending.append(False)

    if "量比" in signal_df.columns:
        sort_cols.append("量比")
        ascending.append(False)

    if sort_cols:
        signal_df = signal_df.sort_values(by=sort_cols, ascending=ascending)

    # 整理导出字段。
    export_cols = [
        "代码",
        "名称",
        "行情日期",
        "行情时间",
        "K线日期",
        "信号类型",
        "突破反转策略",
        "主升策略",
        "最新价",
        "涨跌幅",
        "行业",
        "命中策略数",
        "总市值_亿元",
        "量比",
        "15日涨停",
        "成交额_亿元",
        "流通市值_亿元",
    ]

    export_cols = [col for col in export_cols if col in signal_df.columns]
    export_df = signal_df[export_cols].copy()

    number_cols = export_df.select_dtypes(include=["number"]).columns
    export_df[number_cols] = export_df[number_cols].round(2)

    breakthrough_df, main_promotion_df = split_realtime_sections(export_df)

    # 保存到当日增量文件。
    # 注意：终端仍然展示本轮全部命中，但文件只追加新增命中或策略变化。
    incremental_df, incremental_file = save_daily_incremental_result(export_df)

    minute_df = pd.DataFrame()
    if enable_minute:
        minute_df = scan_minute_buy_points(
            export_df,
            max_stocks=minute_max_stocks,
        )

    print("\n实时扫描完成。")
    print(f"本轮实时命中股票数量：{len(export_df)}")
    print(f"突破反转股票数量：{len(breakthrough_df)}")
    print(f"主升信号股票数量：{len(main_promotion_df)}")
    if enable_minute:
        print(f"分钟级B点数量：{0 if minute_df is None else len(minute_df)}")

    if incremental_file:
        if incremental_df is not None and not incremental_df.empty:
            print(f"本轮新增保存数量：{len(incremental_df)}")
            print(f"当日增量文件：{incremental_file}")
        else:
            print("本轮没有新增命中或策略变化，未追加保存。")
            print(f"当日增量文件：{incremental_file}")

    print("\n实时命中预览：")
    print_realtime_table(export_df, max_rows=50)

    return export_df


def main():
    parser = argparse.ArgumentParser(description="盘中实时策略扫描")

    parser.add_argument(
        "--once",
        action="store_true",
        help="只执行一轮实时扫描。默认就是执行一轮。",
    )

    parser.add_argument(
        "--loop",
        action="store_true",
        help="循环执行实时扫描。",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="循环模式下每轮扫描间隔秒数，默认60秒。",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="实时行情每批请求股票数量，默认50。",
    )

    parser.add_argument(
        "--quote-sleep",
        type=float,
        default=0.5,
        help="每批实时行情请求之间的间隔秒数，默认0.5秒。",
    )

    parser.add_argument(
        "--max-stocks",
        type=int,
        default=0,
        help="测试用：只扫描前N只股票。默认0表示扫描全部。",
    )

    parser.add_argument(
        "--disable-minute",
        action="store_true",
        help="关闭分钟级B点确认。默认开启。",
    )

    parser.add_argument(
        "--minute-max-stocks",
        type=int,
        default=0,
        help="测试用：分钟级确认只处理前N只日线命中股票。默认0表示全部。",
    )

    args = parser.parse_args()

    if args.loop:
        while True:
            loop_start_time = time.time()

            print("\n" + "=" * 100)
            print(f"开始新一轮实时扫描：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 100)

            try:
                scan_realtime_once(
                    batch_size=args.batch_size,
                    quote_sleep=args.quote_sleep,
                    max_stocks=args.max_stocks,
                    enable_minute=not args.disable_minute,
                    minute_max_stocks=args.minute_max_stocks,
                )
            except KeyboardInterrupt:
                print("用户中断，实时扫描结束。")
                break
            except Exception as e:
                print(f"本轮实时扫描异常：{e}")

            elapsed = time.time() - loop_start_time
            sleep_seconds = max(0, args.interval - elapsed)

            print(
                f"本轮耗时：{elapsed:.2f} 秒，"
                f"目标间隔：{args.interval} 秒，"
                f"等待：{sleep_seconds:.2f} 秒后开始下一轮..."
            )

            try:
                time.sleep(sleep_seconds)
            except KeyboardInterrupt:
                print("用户中断，实时扫描结束。")
                break
    else:
        scan_realtime_once(
            batch_size=args.batch_size,
            quote_sleep=args.quote_sleep,
            max_stocks=args.max_stocks,
            enable_minute=not args.disable_minute,
            minute_max_stocks=args.minute_max_stocks,
        )


if __name__ == "__main__":
    main()
