# minute_strategy.py
# 分钟级买点确认模块：基于日线候选股，再使用 BaoStock 5分钟/30分钟K线做盘中B点确认。
#
# 当前版本定位：
# 1. 不替代 realtime_strategy.py 的日线实时预警；
# 2. 只对已经通过日线策略的股票做分钟级确认；
# 3. 先支持 5分钟 + 30分钟，预留后续扩展 1分钟数据源；
# 4. BaoStock 不提供1分钟K线，因此1分钟确认后续可接入其他数据源。

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import baostock as bs
from wcwidth import wcswidth

from strategy import get_bs_code


MINUTE_CACHE_DIR = "cache/minute"
MINUTE_OUTPUT_DIR = "output/minute_buy_points"

# BaoStock 支持的分钟级别：5、15、30、60。当前先用 5 和 30。
DEFAULT_MINUTE_DAYS = 30

# 后续如果接入 1分钟数据源，可以在这里增加开关和对应 loader。
ENABLE_1M_PLACEHOLDER = False


def align_text(text, width, align="left"):
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


def parse_baostock_time(date_value, time_value):
    """
    兼容 BaoStock 分钟线 time 字段。
    常见格式可能是：093500000、20260508093500000 等。
    """

    date_str = str(date_value)
    time_str = "" if pd.isna(time_value) else str(time_value)
    digits = "".join(ch for ch in time_str if ch.isdigit())

    if len(digits) >= 14:
        dt_str = digits[:14]
        return pd.to_datetime(dt_str, format="%Y%m%d%H%M%S", errors="coerce")

    if len(digits) >= 6:
        hm_str = digits[:6]
    elif len(digits) >= 4:
        hm_str = digits[:4] + "00"
    else:
        hm_str = "000000"

    return pd.to_datetime(date_str.replace("-", "") + hm_str, format="%Y%m%d%H%M%S", errors="coerce")


def normalize_minute_df(raw_df: pd.DataFrame, code: str, frequency: str) -> pd.DataFrame:
    """
    统一 BaoStock 分钟K线字段。
    """

    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()
    rename_map = {
        "date": "日期",
        "time": "时间",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
    }
    df = df.rename(columns=rename_map)

    needed_cols = ["日期", "时间", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]
    for col in needed_cols:
        if col not in df.columns:
            return pd.DataFrame()

    df["代码"] = str(code).zfill(6)
    df["周期"] = str(frequency)

    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["datetime"] = [
        parse_baostock_time(date_value, time_value)
        for date_value, time_value in zip(df["日期"], df["时间"])
    ]

    df = df.dropna(subset=["datetime", "开盘", "最高", "最低", "收盘"])
    df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")

    return df[
        ["datetime", "日期", "时间", "代码", "周期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"]
    ].copy()


def load_minute_cache(code: str, frequency: str) -> pd.DataFrame:
    code = str(code).zfill(6)
    cache_file = os.path.join(MINUTE_CACHE_DIR, f"{code}_{frequency}m_bs.csv")

    if not os.path.exists(cache_file):
        return pd.DataFrame()

    try:
        df = pd.read_csv(cache_file, dtype={"代码": str})
        if df.empty:
            return pd.DataFrame()
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"])
        return df.sort_values("datetime")
    except Exception:
        return pd.DataFrame()


def save_minute_cache(df: pd.DataFrame, code: str, frequency: str):
    if df is None or df.empty:
        return

    os.makedirs(MINUTE_CACHE_DIR, exist_ok=True)
    code = str(code).zfill(6)
    cache_file = os.path.join(MINUTE_CACHE_DIR, f"{code}_{frequency}m_bs.csv")
    df.to_csv(cache_file, index=False, encoding="utf-8-sig")


def get_minute_data_baostock(
    code: str,
    frequency: str = "5",
    days: int = DEFAULT_MINUTE_DAYS,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    使用 BaoStock 获取分钟K线，支持本地缓存增量更新。

    当前支持 frequency: 5 / 15 / 30 / 60。

    增量逻辑：
    1. 有缓存时，先读取本地 cache/minute/*_bs.csv。
    2. 如果缓存最新日期已经是今天，直接返回缓存，避免实时 loop 中反复请求。
    3. 如果缓存不是今天，则从缓存最新日期开始重新拉取。
       注意这里从最新日期当天开始，而不是从下一天开始，目的是覆盖当日未完成的分钟K线。
    4. 新旧数据合并，按 datetime 去重，保留最后一次。
    5. 只保留最近 days 个自然日，避免缓存无限变大。
    6. 如果请求失败或无新数据，优先返回旧缓存。
    """

    frequency = str(frequency)
    code = str(code).zfill(6)

    if frequency not in {"5", "15", "30", "60"}:
        raise ValueError("BaoStock 分钟线 frequency 只支持 5、15、30、60。")

    today = datetime.now().date()
    end_date = datetime.now().strftime("%Y-%m-%d")
    bs_code = get_bs_code(code)

    old_df = pd.DataFrame()

    if use_cache:
        old_df = load_minute_cache(code, frequency)

    if not old_df.empty:
        old_df = old_df.copy()
        old_df["datetime"] = pd.to_datetime(old_df["datetime"], errors="coerce")
        old_df = old_df.dropna(subset=["datetime"]).sort_values("datetime")

        latest_dt = old_df["datetime"].max()
        latest_date = latest_dt.date()

        # loop 实时刷新时，如果已经有今天分钟K，先直接用缓存。
        # BaoStock 分钟数据通常不是逐分钟实时更新，反复请求意义不大。
        if latest_date >= today:
            return old_df

        # 增量按“日期”补，不按分钟补。
        # 从最新日期当天开始重新拉，避免当天半截K线或缺口。
        start_date = latest_date.strftime("%Y-%m-%d")
    else:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            fields="date,time,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag="2",
        )

        if rs.error_code != "0":
            return old_df

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            return old_df

        raw_df = pd.DataFrame(data_list, columns=rs.fields)
        new_df = normalize_minute_df(raw_df, code=code, frequency=frequency)

        if new_df.empty:
            return old_df

        if not old_df.empty:
            df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            df = new_df

        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df = df.dropna(subset=["datetime"])
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")

        # 控制缓存大小，避免无限增长。
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df["datetime"] >= cutoff].copy()

        save_minute_cache(df, code, frequency)
        return df

    except Exception:
        return old_df


def prepare_minute_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算分钟级买点所需指标。
    """

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])
    df = df.sort_values("datetime")

    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["MA5"] = df["收盘"].rolling(5).mean()
    df["MA10"] = df["收盘"].rolling(10).mean()
    df["MA20"] = df["收盘"].rolling(20).mean()
    df["VOL20"] = df["成交量"].shift(1).rolling(20).mean()

    df["前12根最高"] = df["最高"].shift(1).rolling(12).max()
    df["前12根最低"] = df["最低"].shift(1).rolling(12).min()
    df["前12根振幅"] = df["前12根最高"] / df["前12根最低"] - 1

    return df


def build_daily_group(row: pd.Series) -> str:
    """
    将日线策略标签映射为分钟级策略分组。
    """

    text = "、".join(
        [
            str(row.get("突破反转策略", "")),
            str(row.get("主升策略", "")),
            str(row.get("命中策略", "")),
        ]
    )

    groups = []

    if "主升-缩量回调启动" in text or "主升-均线多头排列" in text:
        groups.append("主升趋势类")

    if "箱体突破" in text:
        groups.append("突破类")

    if "底部放量反转" in text:
        groups.append("放量启动类")

    if not groups:
        groups.append("其他")

    return "、".join(dict.fromkeys(groups))


def check_30m_structure(df30: pd.DataFrame) -> tuple[bool, str]:
    """
    30分钟结构过滤：判断盘中是否具备基本趋势结构。
    """

    df = prepare_minute_data(df30)

    if len(df) < 25:
        return False, "30分钟K线不足"

    latest = df.iloc[-1]

    if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
        return False, "30分钟指标不足"

    cond_ma = latest["收盘"] > latest["MA5"] and latest["MA5"] >= latest["MA10"]
    cond_vol = latest["成交量"] >= latest["VOL20"] * 0.8 if latest["VOL20"] > 0 else False

    if cond_ma and cond_vol:
        return True, "30分钟趋势结构有效"

    return False, "30分钟结构未确认"


def check_5m_pullback_start(df5: pd.DataFrame) -> tuple[bool, str]:
    """
    5分钟B点1：回踩均线后重新启动。
    适合日线主升趋势类股票。
    """

    df = prepare_minute_data(df5)

    if len(df) < 30:
        return False, "5分钟K线不足"

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.isna(latest[["MA5", "MA10", "MA20", "VOL20"]]).any():
        return False, "5分钟指标不足"

    trend_ok = latest["MA5"] > latest["MA10"] > latest["MA20"]
    pullback_ok = (
        prev["最低"] <= prev["MA10"] * 1.01
        or prev["最低"] <= prev["MA20"] * 1.01
    )
    restart_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"]
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.10 if latest["VOL20"] > 0 else False

    if trend_ok and pullback_ok and restart_ok and volume_ok:
        return True, "5分钟回踩均线启动"

    return False, "5分钟回踩启动未确认"


def check_5m_platform_breakout(df5: pd.DataFrame) -> tuple[bool, str]:
    """
    5分钟B点2：平台突破确认。
    适合箱体突破、放量启动类股票。
    """

    df = prepare_minute_data(df5)

    if len(df) < 30:
        return False, "5分钟K线不足"

    latest = df.iloc[-1]

    if pd.isna(latest[["前12根最高", "前12根最低", "前12根振幅", "VOL20"]]).any():
        return False, "5分钟平台指标不足"

    range_ok = latest["前12根振幅"] <= 0.04
    breakout_ok = latest["收盘"] > latest["前12根最高"]
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.20 if latest["VOL20"] > 0 else False

    if range_ok and breakout_ok and volume_ok:
        return True, "5分钟平台突破确认"

    return False, "5分钟平台突破未确认"


def check_5m_volume_reversal(df5: pd.DataFrame) -> tuple[bool, str]:
    """
    5分钟B点3：放量反包确认。
    适合低位放量启动类股票。
    """

    df = prepare_minute_data(df5)

    if len(df) < 30:
        return False, "5分钟K线不足"

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.isna(latest[["MA5", "MA10", "VOL20"]]).any():
        return False, "5分钟反包指标不足"

    intrabar_pct = latest["收盘"] / latest["开盘"] - 1 if latest["开盘"] > 0 else 0
    reverse_ok = latest["收盘"] > latest["MA5"] and latest["收盘"] > prev["最高"] and intrabar_pct >= 0.005
    volume_ok = latest["成交量"] > latest["VOL20"] * 1.30 if latest["VOL20"] > 0 else False

    if reverse_ok and volume_ok:
        return True, "5分钟放量反包确认"

    return False, "5分钟放量反包未确认"


def evaluate_minute_buy_point(row: pd.Series, df5: pd.DataFrame, df30: pd.DataFrame):
    """
    根据日线策略分组，执行对应分钟级B点确认。
    """

    group = build_daily_group(row)

    structure_ok, structure_msg = check_30m_structure(df30)
    if not structure_ok:
        return False, [], group, structure_msg

    buy_points = []

    if "主升趋势类" in group:
        ok, msg = check_5m_pullback_start(df5)
        if ok:
            buy_points.append(msg)

    if "突破类" in group:
        ok, msg = check_5m_platform_breakout(df5)
        if ok:
            buy_points.append(msg)

    if "放量启动类" in group:
        ok, msg = check_5m_volume_reversal(df5)
        if ok:
            buy_points.append(msg)

    # 如果一个股票有日线信号但没有明确分组，也允许用平台突破作为保底确认。
    if group == "其他":
        ok, msg = check_5m_platform_breakout(df5)
        if ok:
            buy_points.append(msg)

    return bool(buy_points), buy_points, group, structure_msg


def print_minute_table(df: pd.DataFrame, max_rows: int = 50):
    if df is None or df.empty:
        print("没有可展示的分钟级B点。")
        return

    show_cols = [
        "代码",
        "名称",
        "触发时间",
        "最新价",
        "涨跌幅",
        "行业",
        "日线分组",
        "分钟B点",
    ]

    show_cols = [col for col in show_cols if col in df.columns]
    show_df = df[show_cols].copy().head(max_rows)

    if "代码" in show_df.columns:
        show_df["代码"] = show_df["代码"].astype(str).str.zfill(6)

    for col in ["最新价", "涨跌幅"]:
        if col in show_df.columns:
            show_df[col] = pd.to_numeric(show_df[col], errors="coerce").map(
                lambda x: "" if pd.isna(x) else f"{x:.2f}"
            )

    min_widths = {
        "代码": 8,
        "名称": 10,
        "触发时间": 20,
        "最新价": 8,
        "涨跌幅": 8,
        "行业": 12,
        "日线分组": 18,
        "分钟B点": 24,
    }

    right_align_cols = {"最新价", "涨跌幅"}
    col_widths = {}

    for col in show_cols:
        max_width = wcswidth(col)
        for value in show_df[col].astype(str).tolist():
            max_width = max(max_width, wcswidth(value))
        col_widths[col] = max(max_width, min_widths.get(col, 8))

    header = []
    for col in show_cols:
        align = "right" if col in right_align_cols else "left"
        header.append(align_text(col, col_widths[col], align))
    print(" | ".join(header))

    sep = ["-" * col_widths[col] for col in show_cols]
    print("-+-".join(sep))

    for _, row in show_df.iterrows():
        parts = []
        for col in show_cols:
            align = "right" if col in right_align_cols else "left"
            parts.append(align_text(row[col], col_widths[col], align))
        print(" | ".join(parts))


def save_minute_buy_points(df: pd.DataFrame):
    """
    保存当天分钟级B点结果。按 代码 + 分钟B点 + 触发时间 去重追加。
    """

    if df is None or df.empty:
        return ""

    os.makedirs(MINUTE_OUTPUT_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    output_file = os.path.join(MINUTE_OUTPUT_DIR, f"minute_buy_points_{today}.xlsx")

    save_df = df.copy()
    save_df["代码"] = save_df["代码"].astype(str).str.zfill(6)
    save_df["保存时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_df["分钟Key"] = (
        save_df["代码"].astype(str)
        + "|"
        + save_df["分钟B点"].fillna("").astype(str)
        + "|"
        + save_df["触发时间"].fillna("").astype(str)
    )

    if os.path.exists(output_file):
        try:
            old_df = pd.read_excel(output_file, dtype={"代码": str})
            if not old_df.empty and "分钟Key" in old_df.columns:
                old_keys = set(old_df["分钟Key"].dropna().astype(str).tolist())
                new_df = save_df[~save_df["分钟Key"].astype(str).isin(old_keys)].copy()
                if new_df.empty:
                    return output_file
                save_df = pd.concat([old_df, new_df], ignore_index=True)
        except Exception:
            pass

    save_df.to_excel(output_file, index=False)
    return output_file


def scan_minute_buy_points(
    daily_signal_df: pd.DataFrame,
    max_stocks: int = 0,
    minute_days: int = DEFAULT_MINUTE_DAYS,
) -> pd.DataFrame:
    """
    对日线候选股执行 5分钟 + 30分钟买点确认。
    """

    if daily_signal_df is None or daily_signal_df.empty:
        print("分钟级确认：没有日线候选股，跳过。")
        return pd.DataFrame()

    df = daily_signal_df.copy()
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    if max_stocks and max_stocks > 0:
        df = df.head(max_stocks).copy()

    print(f"\n开始分钟级B点确认：候选股票 {len(df)} 只，周期：30分钟结构 + 5分钟B点")

    lg = bs.login()
    if lg.error_code != "0":
        print(f"BaoStock 登录失败，分钟级确认跳过：{lg.error_msg}")
        return pd.DataFrame()

    result_list = []
    start_time = time.time()
    total = len(df)

    try:
        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            code = str(row["代码"]).zfill(6)
            name = row.get("名称", "")

            try:
                df5 = get_minute_data_baostock(code, frequency="5", days=minute_days)
                df30 = get_minute_data_baostock(code, frequency="30", days=minute_days)

                if df5.empty or df30.empty:
                    continue

                is_hit, buy_points, daily_group, structure_msg = evaluate_minute_buy_point(row, df5, df30)

                if is_hit:
                    df5_prepared = prepare_minute_data(df5)
                    latest5 = df5_prepared.iloc[-1]

                    result = {
                        "代码": code,
                        "名称": name,
                        "触发时间": latest5["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                        "最新价": row.get("最新价", row.get("收盘", latest5["收盘"])),
                        "涨跌幅": row.get("涨跌幅", pd.NA),
                        "行业": row.get("行业", ""),
                        "日线分组": daily_group,
                        "日线策略": "、".join(
                            [
                                str(row.get("突破反转策略", "")),
                                str(row.get("主升策略", "")),
                            ]
                        ).strip("、"),
                        "30分钟结构": structure_msg,
                        "分钟B点": "、".join(buy_points),
                        "5分钟收盘": latest5["收盘"],
                        "5分钟成交量": latest5["成交量"],
                        "5分钟量比": latest5["成交量"] / latest5["VOL20"] if latest5.get("VOL20", 0) else pd.NA,
                    }
                    result_list.append(result)

            except Exception as e:
                print(f"{code} {name} 分钟级确认失败：{e}")

            elapsed = time.time() - start_time
            avg = elapsed / idx
            remain = avg * (total - idx)

            if idx % 5 == 0 or idx == total:
                print(
                    f"分钟级确认进度：{idx}/{total} | "
                    f"B点数：{len(result_list)} | "
                    f"预计剩余：{remain:.1f} 秒",
                    end="\r",
                    flush=True,
                )

        print()

    finally:
        try:
            bs.logout()
        except Exception as e:
            print(f"\nBaoStock 退出异常，已忽略：{e}")

    if not result_list:
        print("分钟级确认完成：本轮没有发现5分钟/30分钟B点。")
        return pd.DataFrame()

    result_df = pd.DataFrame(result_list)

    if "5分钟量比" in result_df.columns:
        result_df["5分钟量比"] = pd.to_numeric(result_df["5分钟量比"], errors="coerce")
        result_df = result_df.sort_values(by="5分钟量比", ascending=False)

    output_file = save_minute_buy_points(result_df)

    print("分钟级确认完成。")
    print(f"分钟级B点数量：{len(result_df)}")
    if output_file:
        print(f"分钟级B点结果已保存：{output_file}")

    print("\n分钟级B点预览：")
    print_minute_table(result_df, max_rows=50)

    return result_df
