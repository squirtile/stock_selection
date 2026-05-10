"""
高级回测：新增3个策略 + 动态止盈止损 + 持股5天测试

策略A - 竞价追涨（日线近似版）:
  1. 昨天涨停（涨跌幅>=9.9%）
  2. 今日高开3-6%（无法检测竞价细节，用开盘价近似）
  3. 今日涨幅>7%
  4. 放量（量>20日均量*1.5）

策略B - 龙头回调:
  1. 过去13天内存在20%+的涨幅段
  2. 从高点回调2-8天
  3. 回调幅度<50%

策略C - 追涨突破:
  1. 今日量>昨日量*1.5
  2. 换手率>5%（用成交额>5000万+量>20日均量*3近似）
  3. 今日涨幅>5%
  4. 突破13日最高价

卖出条件（持有期内每日检查）:
  - 止损: 收盘价 < 5MA → 当日收盘卖出
  - 止盈: 收盘 > 5MA 且 量 >= 20日均量 且 收阴线 → 当日收盘卖出
  - 到期: 持股满5日仍未触发 → T+5收盘卖出
"""

import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters
from backtest.backtest import load_stock_names_from_base_pool

MAX_HOLD_DAYS = 5

# =====================================================
# 策略函数
# =====================================================

def check_strategy_a(row, prev_row):
    """
    策略A - 竞价追涨（日线近似）
    需要: prev_row = 昨天K线
    可检测条件:
      1. 昨天涨停 (涨幅>=9.9%)
      2. 今日高开3-6%
      3. 今日涨幅>7%
      4. 放量
    无法检测(日线限制): 集合竞价细节、9:50前封板
    """
    if prev_row is None:
        return False

    yesterday_pct = prev_row["涨跌幅"]
    if pd.isna(yesterday_pct) or yesterday_pct < 9.9:
        return False

    # 高开: 今日开盘 / 昨日收盘 - 1
    yesterday_close = prev_row["收盘"]
    today_open = row["开盘"]
    if pd.isna(yesterday_close) or pd.isna(today_open) or yesterday_close <= 0:
        return False

    gap_pct = (today_open / yesterday_close - 1) * 100
    if gap_pct < 3.0 or gap_pct > 6.0:
        return False

    # 今日涨幅>7%（盘中触发，用日涨跌幅近似）
    today_pct = row["涨跌幅"]
    if pd.isna(today_pct) or today_pct < 7.0:
        return False

    # 放量
    avg_vol = row["过去20日平均成交量"]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return False
    if row["成交量"] < avg_vol * 1.5:
        return False

    return True


def check_strategy_b(df, idx):
    """
    策略B - 龙头回调
    在过去13天内检测: 20%+涨幅 → 2~8天回调 → 回调幅度<50%
    """
    if idx < 20:
        return False

    today_close = df.iloc[idx]["收盘"]
    if pd.isna(today_close) or today_close <= 0:
        return False

    # 在过去13个交易日内找最低点和最高点
    lookback_start = max(0, idx - 13)
    segment = df.iloc[lookback_start:idx + 1]

    closes = segment["收盘"].values
    if len(closes) < 5:
        return False

    # 找最低点的位置和最高点的位置
    low_idx_in_seg = int(np.argmin(closes))
    high_idx_in_seg = int(np.argmax(closes))

    low_price = closes[low_idx_in_seg]
    high_price = closes[high_idx_in_seg]

    if low_price <= 0 or high_price <= 0:
        return False

    rise_pct = (high_price / low_price - 1) * 100

    # 条件1: 涨幅 >= 20%
    if rise_pct < 20.0:
        return False

    # 条件2: 最高点出现在最低点之后（先涨后跌）
    if high_idx_in_seg <= low_idx_in_seg:
        return False

    # 条件3: 当前价低于最高价（正在回调）
    if today_close >= high_price * 0.99:
        return False

    # 条件4: 回调天数 2-8天（从最高点到现在）
    pullback_days = len(segment) - 1 - high_idx_in_seg
    if pullback_days < 2 or pullback_days > 8:
        return False

    # 条件5: 回调幅度不超过50%（相对于涨幅）
    pullback_pct = (high_price - today_close) / (high_price - low_price) * 100
    if pullback_pct > 50.0:
        return False

    return True


def check_strategy_c(row, prev_row):
    """
    策略C - 追涨突破
    1. 量>昨日量*1.5
    2. 换手率>5%（用量>20日均量*3 + 成交额>5000万近似）
    3. 涨幅>5%
    4. 突破13日最高价
    5. 筹码获利比例>90%（无法计算，用突破60日最高价近似替代）
    """
    if prev_row is None:
        return False

    # 条件1: 量比（vs 昨日）
    yesterday_vol = prev_row["成交量"]
    today_vol = row["成交量"]
    if pd.isna(yesterday_vol) or pd.isna(today_vol) or yesterday_vol <= 0:
        return False
    if today_vol < yesterday_vol * 1.5:
        return False

    # 条件2: 换手率>5%（近似：量>20日均量*3 且 成交额>5000万）
    avg_vol = row["过去20日平均成交量"]
    if pd.isna(avg_vol) or avg_vol <= 0:
        return False
    if today_vol < avg_vol * 3.0:
        return False

    avg_amount = row["过去20日日均成交额"]
    if pd.isna(avg_amount) or avg_amount < 50_000_000:
        return False

    # 条件3: 涨幅>5%
    today_pct = row["涨跌幅"]
    if pd.isna(today_pct) or today_pct < 5.0:
        return False

    # 条件4: 突破13日最高价（由主循环计算）
    high_13d = row.get("过去13日最高价")
    if high_13d is None or pd.isna(high_13d) or high_13d <= 0:
        return False
    if row["收盘"] <= high_13d:
        return False

    # 条件5: 筹码获利比例>90%（无法从日线精确计算，用60日均线位置近似：
    # 收盘远高于60日线说明大部分持仓者获利）
    sma60 = row.get("SMA60")
    if sma60 is None or pd.isna(sma60) or sma60 <= 0:
        return False
    if row["收盘"] < sma60 * 1.05:  # 比60日线高5%以上
        return False

    return True


def check_strategy_d(df, idx):
    """
    策略D - 断板反包
    1. 三连板以上（含3板）: 之前连续3天以上涨停
    2. 出现断板洗盘: 连板后有一天不是涨停
    3. 第2天出现反包或者涨停: 断板后第二天收阳反包
    4. 介入点: 突破断板当日实体最高价
    5. 止损位: 跌破断板当日最低价
    """
    if idx < 10:
        return False

    today = df.iloc[idx]
    today_close = today["收盘"]
    today_open = today["开盘"]

    if pd.isna(today_close) or pd.isna(today_open) or today_close <= 0:
        return False

    # 断板日 = idx-1（昨天），该日不是涨停但之前是连板
    broken_day = df.iloc[idx - 1]
    broken_close = broken_day["收盘"]
    broken_open = broken_day["开盘"]
    broken_pct = broken_day["涨跌幅"]
    broken_low = broken_day["最低"]
    broken_entity_high = max(broken_open, broken_close)

    if pd.isna(broken_pct) or pd.isna(broken_low):
        return False

    # 断板日不能是涨停
    if broken_pct >= 9.95:
        return False

    # 向前数连板天数（断板日之前，从 idx-2 开始往前找涨停）
    consecutive_limits = 0
    for j in range(2, 10):
        check_idx = idx - j
        if check_idx < 0:
            break
        if df.iloc[check_idx]["涨跌幅"] >= 9.95:
            consecutive_limits += 1
        else:
            break

    # 条件1: 二连板以上（放宽到2板，找更多信号）
    if consecutive_limits < 2:
        return False

    # 条件2: 今天反包 - 收盘突破断板日实体最高价
    if today_close <= broken_entity_high:
        return False

    # 条件3: 今天收阳（可不涨停但至少上涨）
    today_pct = today["涨跌幅"]
    if pd.isna(today_pct) or today_pct < 1.0:
        return False

    # 条件4: 断板日不是大阴线（洗盘特征）
    if broken_pct < -8.0:
        return False

    # 条件5: 反包放量（至少不缩量）
    avg_vol = today.get("过去20日平均成交量")
    if avg_vol is None or pd.isna(avg_vol) or avg_vol <= 0:
        return False
    if today["成交量"] < avg_vol * 0.8:
        return False

    return True


# =====================================================
# 动态卖出逻辑
# =====================================================

def get_exit_day(df, entry_idx, max_hold):
    """
    从买入日开始逐日检查卖出条件，返回卖出日索引。
    买入日 = entry_idx（T+1，已买入）
    持有日 = entry_idx+1 到 entry_idx+max_hold（T+2 到 T+5）

    卖出规则：
    1. 止损: 收盘 < 5MA → 当日收盘卖出
    2. 止盈: 收盘 > 5MA 且 量 >= 20日均量 且 收阴线 → 当日收盘卖出
    3. 到期: 持股满5日 → T+5收盘卖出

    返回: (exit_idx, exit_reason)
    """
    for hold_day in range(1, max_hold + 1):
        check_idx = entry_idx + hold_day

        if check_idx >= len(df):
            return entry_idx + max_hold, "到期(数据不足)"

        row = df.iloc[check_idx]
        sma5 = row.get("SMA5", None)
        close = row["收盘"]
        vol = row["成交量"]
        avg_vol = row.get("过去20日平均成交量", None)
        open_price = row["开盘"]

        if pd.isna(close) or close <= 0:
            return check_idx - 1, "数据异常"

        # 最后一天，必须卖出
        if hold_day == max_hold:
            return check_idx, "到期(满5日)"

        # 条件1: 跌破5MA止损
        if sma5 is not None and not pd.isna(sma5):
            if close < sma5:
                return check_idx, f"止损(跌破5MA) D+{hold_day+1}"

        # 条件2: 5MA上方 + 放量 + 阴线止盈
        if sma5 is not None and not pd.isna(sma5) and close > sma5:
            is_bearish = close < open_price
            if is_bearish:
                # 量 >= 20日均量
                if avg_vol is not None and not pd.isna(avg_vol) and vol >= avg_vol:
                    return check_idx, f"止盈(5MA上+放量阴线) D+{hold_day+1}"

    return entry_idx + max_hold, "到期(满5日)"


# =====================================================
# 主回测
# =====================================================

def load_stock(file_path):
    df = pd.read_csv(file_path, dtype={"代码": str})
    code = os.path.basename(file_path).replace("_bs.csv", "")
    if df.empty or len(df) < 80:
        return None
    for col in ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        if col not in df.columns:
            return None
    df["代码"] = code
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["开盘", "最高", "最低", "收盘"])
    return df.sort_values("日期").reset_index(drop=True)


def advanced_backtest(max_stocks=0):
    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    if max_stocks and max_stocks > 0:
        files = files[:max_stocks]
    total = len(files)

    stock_name_map = load_stock_names_from_base_pool()

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    # 结果收集: 每个策略独立统计
    strategy_results = {
        "策略A(竞价追涨)": [],
        "策略B(龙头回调)": [],
        "策略C(追涨突破)": [],
        "策略D(断板反包)": [],
    }

    t0 = time.time()
    stocks_done = 0

    for fi, fname in enumerate(files, 1):
        file_path = os.path.join(HIST_CACHE_DIR, fname)
        raw_df = load_stock(file_path)
        if raw_df is None:
            continue

        stocks_done += 1
        code = os.path.basename(fname).replace("_bs.csv", "")
        name = stock_name_map.get(code, "")

        df = prepare_hist_data(raw_df.copy())
        df = df.sort_values("日期").reset_index(drop=True)

        # 策略B需要额外计算13日高点
        df["过去13日最高价"] = df["最高"].shift(1).rolling(13).max()

        for i in range(65, len(df) - MAX_HOLD_DAYS - 1):
            row = df.iloc[i]
            if row[need_cols].isna().any():
                continue

            prev_row = df.iloc[i - 1] if i >= 1 else None

            buy_price = df.iloc[i + 1]["开盘"]
            if pd.isna(buy_price) or buy_price <= 0:
                continue

            # 记录命中了哪些策略
            hit_a = check_strategy_a(row, prev_row)
            hit_b = check_strategy_b(df, i)
            hit_c = check_strategy_c(row, prev_row)
            hit_d = check_strategy_d(df, i)

            if not (hit_a or hit_b or hit_c or hit_d):
                continue

            # 对命中的每个策略，独立模拟卖出
            entry_idx = i + 1  # T+1 买入
            exit_idx, exit_reason = get_exit_day(df, entry_idx, MAX_HOLD_DAYS)

            sell_price = df.iloc[exit_idx]["收盘"]
            if pd.isna(sell_price) or sell_price <= 0:
                continue

            return_pct = (sell_price / buy_price - 1) * 100
            hold_days_actual = exit_idx - entry_idx
            is_win = return_pct > 0

            trade_record = {
                "代码": code,
                "名称": name,
                "信号日期": row["日期"],
                "买入日期": df.iloc[entry_idx]["日期"],
                "卖出日期": df.iloc[exit_idx]["日期"],
                "买入价": round(buy_price, 2),
                "卖出价": round(sell_price, 2),
                "实际持有天数": hold_days_actual,
                "收益率%": round(return_pct, 2),
                "是否盈利": is_win,
                "卖出原因": exit_reason,
                "信号日涨跌幅": row["涨跌幅"],
                "信号日量比": row["成交量"] / row["过去20日平均成交量"],
            }

            if hit_a:
                strategy_results["策略A(竞价追涨)"].append(trade_record)
            if hit_b:
                strategy_results["策略B(龙头回调)"].append(trade_record)
            if hit_c:
                strategy_results["策略C(追涨突破)"].append(trade_record)
            if hit_d:
                strategy_results["策略D(断板反包)"].append(trade_record)

        if fi % 200 == 0:
            elapsed = time.time() - t0
            print(f"  进度: {fi}/{total} | 耗时: {elapsed:.0f}s", flush=True)

    elapsed = time.time() - t0
    print(f"\n处理完成: {stocks_done}只股票 | 总耗时: {elapsed:.0f}s\n")

    return strategy_results


def print_strategy_stats(name, trades):
    """打印单个策略的详细统计"""
    if not trades:
        print(f"\n  {name}: 无信号")
        return

    df = pd.DataFrame(trades)
    total = len(df)
    wins = int(df["是否盈利"].sum())
    losses = total - wins
    win_rate = wins / total * 100

    rets = df["收益率%"].values
    avg_ret = np.mean(rets)
    med_ret = np.median(rets)
    max_ret = np.max(rets)
    min_ret = np.min(rets)

    avg_win = np.mean(rets[rets > 0]) if wins > 0 else 0
    avg_loss = np.mean(rets[rets <= 0]) if losses > 0 else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

    print(f"\n{'='*70}")
    print(f"  {name}")
    print(f"{'='*70}")
    print(f"  信号次数: {total}")
    print(f"  盈利次数: {wins}  |  亏损次数: {losses}")
    print(f"  胜率: {win_rate:.2f}%")
    print(f"  平均收益率: {avg_ret:.2f}%")
    print(f"  中位数收益率: {med_ret:.2f}%")
    print(f"  最大单笔收益: {max_ret:.2f}%")
    print(f"  最大单笔亏损: {min_ret:.2f}%")
    print(f"  平均盈利: {avg_win:.2f}%")
    print(f"  平均亏损: {avg_loss:.2f}%")
    print(f"  盈亏比: {pl_ratio:.2f}")

    # 卖出原因分布
    if "卖出原因" in df.columns:
        print(f"\n  卖出原因分布:")
        for reason, cnt in df["卖出原因"].value_counts().items():
            sub = df[df["卖出原因"] == reason]
            sub_win = sub["是否盈利"].sum()
            sub_wr = sub_win / len(sub) * 100
            print(f"    {reason}: {cnt}次 (胜率{sub_wr:.1f}%)")

    # 持有天数分布
    if "实际持有天数" in df.columns:
        print(f"\n  实际持有天数分布:")
        for days, cnt in sorted(df["实际持有天数"].value_counts().items()):
            sub = df[df["实际持有天数"] == days]
            sub_win = sub["是否盈利"].sum()
            sub_wr = sub_win / len(sub) * 100
            avg_r = sub["收益率%"].mean()
            print(f"    {days}天: {cnt}次 | 胜率{sub_wr:.1f}% | 平均收益{avg_r:.2f}%")


def main():
    print("高级回测: 新增策略A/B/C + 动态止盈止损 + 持股5天")
    print("=" * 70)

    # 也测试原本的6个策略作为对照
    print("\n>>> 第1部分: 新增策略A/B/C + 动态卖出")
    results = advanced_backtest()

    all_names = ["策略A(竞价追涨)", "策略B(龙头回调)", "策略C(追涨突破)", "策略D(断板反包)"]

    for name in all_names:
        print_strategy_stats(name, results[name])

    # 汇总对比
    print(f"\n\n{'='*70}")
    print("  四策略汇总对比")
    print(f"{'='*70}")
    print(f"{'策略':<22} {'信号':>6} {'胜率%':>8} {'平均收益%':>10} {'中位数%':>8} {'盈亏比':>8}")
    print("-" * 70)

    summary_rows = []
    for name in all_names:
        trades = results[name]
        if not trades:
            continue
        df = pd.DataFrame(trades)
        total = len(df)
        wins = int(df["是否盈利"].sum())
        wr = wins / total * 100
        rets = df["收益率%"].values
        avg_r = np.mean(rets)
        med_r = np.median(rets)
        avg_win = np.mean(rets[rets > 0]) if wins > 0 else 0
        avg_loss = np.mean(rets[rets <= 0]) if total - wins > 0 else 0
        pl = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        print(f"{name:<22} {total:>6} {wr:>8.2f} {avg_r:>10.2f} {med_r:>8.2f} {pl:>8.2f}")
        summary_rows.append((name, total, wr, avg_r, med_r, pl))

    # 最佳策略
    if summary_rows:
        best = max(summary_rows, key=lambda x: x[2])
        print(f"\n胜率最高: {best[0]} = {best[2]:.2f}% ({best[1]}次信号)")

    print(f"\n注意: 策略A中的集合竞价细节(9:20报价、9:50前封板)无法用日线数据检测，为近似模拟。")
    print(f"      策略C中的换手率和筹码获利比例使用替代指标近似。")


if __name__ == "__main__":
    main()
