"""
详细回测：记录每笔交易的完整信息（股票代码、日期、价格、收益率）
覆盖当前全部28个策略 × 持股1-10天
"""
import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

MAX_HOLD = 10
MIN_SIGNALS = 5  # 至少5个信号才记录


def load_stock(fp):
    df = pd.read_csv(fp, dtype={"代码": str})
    if df.empty or len(df) < 80: return None
    for c in ["日期","开盘","最高","最低","收盘","成交量","成交额","涨跌幅"]:
        if c not in df.columns: return None
    df["日期"] = pd.to_datetime(df["日期"])
    for c in ["开盘","最高","最低","收盘","成交量","成交额","涨跌幅"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["开盘","最高","最低","收盘"])
    return df.sort_values("日期").reset_index(drop=True)


def enrich(df):
    """与 comprehensive_hold_sweep.py 完全一致的 enrich"""
    df = df.copy()
    df["昨收"] = df["收盘"].shift(1)
    df["昨开"] = df["开盘"].shift(1)
    df["昨低"] = df["最低"].shift(1)
    df["昨高"] = df["最高"].shift(1)
    df["昨量"] = df["成交量"].shift(1)
    df["昨涨跌"] = df["涨跌幅"].shift(1)
    df["前涨跌"] = df["涨跌幅"].shift(2)
    df["大前涨跌"] = df["涨跌幅"].shift(3)
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA5昨"] = df["SMA5"].shift(1)
    df["SMA10昨"] = df["SMA10"].shift(1)
    df["SMA20昨"] = df["SMA20"].shift(1)
    df["SMA20_5d"] = df["SMA20"].shift(5)
    df["10日高"] = df["最高"].shift(1).rolling(10).max()
    df["10日低"] = df["最低"].rolling(10).min()
    df["10日最高收"] = df["收盘"].shift(1).rolling(10).max()
    df["20日高"] = df["最高"].shift(1).rolling(20).max()
    df["20日低"] = df["最低"].rolling(20).min()
    df["5日高"] = df["最高"].shift(1).rolling(5).max()
    df["5日低"] = df["最低"].rolling(5).min()
    df["实体上沿"] = df[["开盘","收盘"]].max(axis=1)
    df["实体下沿"] = df[["开盘","收盘"]].min(axis=1)
    df["昨实体上沿"] = df["实体上沿"].shift(1)
    df["量比昨"] = df["成交量"] / df["昨量"].replace(0, np.nan)
    df["均量"] = df["过去20日平均成交量"]
    df["收阳"] = (df["收盘"] > df["开盘"]).fillna(0).astype(int)
    df["昨收阳"] = df["收阳"].shift(1).fillna(0).astype(int)
    df["前收阳"] = df["收阳"].shift(2).fillna(0).astype(int)
    df["缺口"] = (df["最低"] > df["昨高"]).fillna(0).astype(int)
    df["昨开缺口"] = ((df["昨开"] - df["收盘"].shift(2)) / df["收盘"].shift(2).replace(0, np.nan) * 100)
    return df


# ================================================================
# 策略定义 — 与 daily_strategies.py 参数完全一致的版本
# 每个策略返回 (策略名, 分类, 匹配函数)
# ================================================================

S = []

def reg(name, cat, func):
    S.append((name, cat, func))

# S1 箱体突破
reg("S1-箱体突破", "突破反转",
    lambda r,*_: r["收盘"]>r["过去60日最高价"] and r["成交量"]>r["均量"]*1.3 and r["过去20日实体振幅"]<=0.20)

# M1 主升箱体突破
reg("M1-主升箱体突破", "主升",
    lambda r,*_: r["收盘"]>r["过去60日最高收盘"] and r["成交量"]>r["均量"]*1.5)

# M2 主升底部反转
reg("M2-主升底部反转", "主升",
    lambda r,*_: r["收盘"]/r["过去60日最低收盘"]-1<0.30 and r["涨跌幅"]>5 and r["成交量"]>r["均量"]*2)

# M3 缩量回调
reg("M3-缩量回调", "主升",
    lambda r,*_: r["SMA5"]<r["SMA20"] and r["SMA60"]>r["SMA60_5日前"] and r["收盘"]>r["SMA5"] and r["成交量"]>r["均量"]*1.5)

# M4 均线多头
reg("M4-均线多头", "主升",
    lambda r,*_: r["SMA5"]>r["SMA10"] and r["SMA10"]>r["SMA20"] and r["SMA20"]>r["SMA60"] and r["涨跌幅"]>2 and r["成交量"]>r["均量"]*1.2)

# A 竞价追涨
def _a(row, df, idx, prev):
    if prev is None: return False
    if pd.isna(prev["涨跌幅"]) or prev["涨跌幅"]<9.9: return False
    yc,to=prev["收盘"],row["开盘"]
    if pd.isna(yc) or pd.isna(to) or yc<=0: return False
    gap=(to/yc-1)*100
    if gap<3 or gap>6: return False
    if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<7: return False
    av=row["均量"]
    return not(pd.isna(av) or av<=0) and row["成交量"]>=av*1.5
reg("A-竞价追涨", "主升", _a)

# B 龙头回调
def _b(row, df, idx, prev):
    if idx<20: return False
    tc=row["收盘"]
    if pd.isna(tc) or tc<=0: return False
    seg=df.iloc[max(0,idx-13):idx+1]
    cls=seg["收盘"].values
    if len(cls)<5: return False
    li,hi=int(np.argmin(cls)),int(np.argmax(cls))
    lp,hp=cls[li],cls[hi]
    if lp<=0 or hp<=0: return False
    if (hp/lp-1)*100<20: return False
    if hi<=li: return False
    if tc>=hp*0.99: return False
    pd_=len(seg)-1-hi
    if pd_<2 or pd_>8: return False
    if (hp-tc)/(hp-lp)*100>50: return False
    return True
reg("B-龙头回调", "突破反转", _b)

# C 追涨突破
def _c(row, df, idx, prev):
    if prev is None: return False
    yv,tv=prev["成交量"],row["成交量"]
    if pd.isna(yv) or pd.isna(tv) or yv<=0: return False
    if tv<yv*1.5: return False
    av=row["均量"]
    if pd.isna(av) or av<=0 or tv<av*3.0: return False
    if pd.isna(row["过去20日日均成交额"]) or row["过去20日日均成交额"]<50_000_000: return False
    if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<5: return False
    h=row.get("过去13日最高价")
    if h is None: h=row.get("10日高")
    return not(h is None or pd.isna(h) or h<=0) and row["收盘"]>h
reg("C-追涨突破", "主升", _c)

# N22 V型反转
reg("N22-V型反转", "突破反转",
    lambda r,*_: r["收盘"]/r["过去40日最低价"]-1<0.15 and r["涨跌幅"]>4 and r["昨涨跌"]<-1 and r["成交量"]>r["均量"]*1.8 and r["收阳"]==1)

# N1 双底放量反转
reg("N1-双底放量反转", "突破反转",
    lambda r,*_: r["收盘"]/r["过去40日最低价"]-1<0.15 and r["收盘"]/r["过去60日最低收盘"]-1<0.20 and r["涨跌幅"]>3 and r["成交量"]>r["均量"]*1.8 and r["收阳"]==1)

# N5 均线粘合突破
reg("N5-均线粘合突破", "突破反转",
    lambda r,*_: abs(r["SMA5"]/r["SMA10"]-1)<0.03 and abs(r["SMA10"]/r["SMA20"]-1)<0.05 and r["收盘"]>max(r["SMA5"],r["SMA10"],r["SMA20"]) and r["成交量"]>r["均量"]*1.5 and r["涨跌幅"]>3)

# N9 跳空不补
def _n9(row, df, idx, prev):
    if row["昨开"]<=row["收盘"].shift(2): return False
    if row["最低"]<=row["昨开"]: return False
    return row["昨收阳"]==1 and row["成交量"]>row["均量"]*1.3 and row["收阳"]==1
reg("N9-跳空不补", "突破反转", _n9)

# N2 缩量回踩反击
reg("N2-缩量回踩反击", "突破反转",
    lambda r,*_: r["昨量"]<r["均量"]*0.5 and r["成交量"]>r["均量"]*1.8 and r["量比昨"]>1.3 and r["涨跌幅"]>1 and r["收盘"]>r["SMA5"] and r["SMA20"]>r["SMA60"])

# N7 强势整理突破
reg("N7-强势整理突破", "突破反转",
    lambda r,*_: r["收盘"]>r["10日高"] and r["成交量"]>r["均量"]*1.5 and r["涨跌幅"]>2 and r["过去20日实体振幅"]<=0.20 and r["收盘"]>r["SMA20"])

# N11 地量倍量
reg("N11-地量倍量", "突破反转",
    lambda r,*_: r["昨量"]<r["均量"]*0.5 and r["量比昨"]>2.0 and r["涨跌幅"]>2 and r["收盘"]>r["SMA5"])

# N12 阳包阴
reg("N12-阳包阴", "突破反转",
    lambda r,*_: r["昨收阳"]==0 and r["收阳"]==1 and r["收盘"]>r["昨开"] and r["涨跌幅"]>2 and r["成交量"]>r["均量"]*1.3)

# N13 多方炮
reg("N13-多方炮", "突破反转",
    lambda r,*_: r["前收阳"]==1 and r["昨收阳"]==0 and r["收阳"]==1 and r["昨涨跌"]>-5 and r["收盘"]>r["昨高"] and r["成交量"]>r["均量"]*1.5)

# N17 末端突破
def _n17(row, df, idx, prev):
    if row["10日低"]<=0: return False
    amp=row["10日高"]/row["10日低"]-1
    return amp<0.10 and row["收盘"]>row["10日高"] and row["成交量"]>row["均量"]*1.5 and row["涨跌幅"]>2
reg("N17-末端突破", "突破反转", _n17)

# N23 倍量突破前高
reg("N23-倍量突破前高", "突破反转",
    lambda r,*_: r["量比昨"]>1.8 and r["成交量"]>r["均量"]*1.5 and r["收盘"]>r["10日最高收"] and r["涨跌幅"]>1.5 and r["收阳"]==1)

# N26 强势突破连阳
reg("N26-强势突破连阳", "突破反转",
    lambda r,*_: r["收盘"]>r["5日高"] and r["昨收阳"]==1 and r["成交量"]>r["均量"]*1.5 and r["涨跌幅"]>2 and r["收阳"]==1)

# N32 跳空高开
def _n32(row, df, idx, prev):
    if row["前收"]<=0: return False
    gap_pct=(row["昨开"]/row["前收"]-1)*100
    return gap_pct>2.0 and row["昨收阳"]==1 and row["最低"]>row["昨高"] and row["成交量"]>row["均量"]*1.3 and row["收阳"]==1
reg("N32-跳空高开", "突破反转", _n32)

# N34 突破20日高
reg("N34-突破20日高", "突破反转",
    lambda r,*_: r["收盘"]>r["20日高"] and r["成交量"]>r["均量"]*2.5 and r["涨跌幅"]>1 and r["收阳"]==1 and r["SMA5"]>r["SMA10"])

# N27 涨停接力
def _n27(row, df, idx, prev):
    if prev is None: return False
    if pd.isna(prev["涨跌幅"]) or prev["涨跌幅"]<9.9: return False
    yc,to=prev["收盘"],row["开盘"]
    if pd.isna(yc) or pd.isna(to) or yc<=0: return False
    gap=(to/yc-1)*100
    if gap<1 or gap>4: return False
    if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<2: return False
    av=row["均量"]
    return not(pd.isna(av) or av<=0) and row["成交量"]>=av*1.8 and row["收阳"]==1
reg("N27-涨停接力", "主升", _n27)

# N20 加速上涨
reg("N20-加速上涨", "主升",
    lambda r,*_: r["涨跌幅"]>r["昨涨跌"] and r["昨涨跌"]>r["前涨跌"] and r["涨跌幅"]>2 and r["前涨跌"]>0 and r["昨涨跌"]>0 and r["成交量"]>r["均量"]*1.5 and r["收阳"]==1)

# N3 涨停回踩反弹
reg("N3-涨停回踩反弹", "主升",
    lambda r,*_: r["近15日涨停次数"]>=1 and r["涨跌幅"]>1 and r["成交量"]>r["均量"]*1.5 and r["收盘"]>r["SMA5"] and r["SMA5"]>r["SMA20"])

# N15 均线金叉
def _n15(row, df, idx, prev):
    cross = row["SMA5"]>row["SMA20"] and row["SMA5昨"]<=row["SMA20昨"]
    return cross and row["成交量"]>row["均量"]*1.3 and row["涨跌幅"]>1
reg("N15-均线金叉", "主升", _n15)

# N24 涨停缩量再放
reg("N24-涨停缩量再放", "主升",
    lambda r,*_: r["近15日涨停次数"]>=1 and r["昨量"]<r["均量"]*0.7 and r["量比昨"]>1.5 and r["涨跌幅"]>2 and r["收盘"]>r["SMA10"] and r["SMA20"]>r["SMA60"])

# N30 连阳加速
reg("N30-连阳加速", "主升",
    lambda r,*_: r["收阳"]==1 and r["昨收阳"]==1 and r["涨跌幅"]>1 and r["昨涨跌"]>0 and r["成交量"]>r["均量"]*1.5 and r["昨量"]>r["均量"]*1.5 and r["收盘"]>r["昨高"])


def run():
    n = len(S)
    MAX_HOLD = 10
    print(f"详细回测: {n}个策略 | 持股1-{MAX_HOLD}天 | 1136只股票")
    print("=" * 80)

    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total = len(files)

    # 存储所有交易记录
    all_trades = []  # list of dicts

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()
    total_trades = 0

    for fi, fname in enumerate(files, 1):
        raw = load_stock(os.path.join(HIST_CACHE_DIR, fname))
        if raw is None: continue

        code = fname.replace("_bs.csv", "")

        df = prepare_hist_data(raw.copy())
        df = enrich(df)
        df = df.sort_values("日期").reset_index(drop=True)

        max_i = len(df) - MAX_HOLD - 1
        for i in range(65, max_i):
            row = df.iloc[i]
            if row[need_cols].isna().any(): continue
            if not check_secondary_filters(row): continue

            prev = df.iloc[i-1] if i >= 1 else None
            signal_date = row["日期"]

            # 买入价
            bp = df.iloc[i+1]["开盘"]
            if pd.isna(bp) or bp <= 0: continue

            # 10个持仓天数的卖出价
            sell_prices = []
            valid = True
            for hd in range(1, MAX_HOLD + 1):
                sp = df.iloc[i + hd]["收盘"]
                if pd.isna(sp):
                    valid = False
                    break
                sell_prices.append(sp)
            if not valid: continue

            # 检查每个策略
            for name, cat, func in S:
                try:
                    if func(row, df, i, prev):
                        # 对所有10个持仓天数分别记录
                        for hd in range(1, MAX_HOLD + 1):
                            sp = sell_prices[hd-1]
                            ret = (sp/bp - 1) * 100
                            all_trades.append({
                                "策略": name,
                                "分类": cat,
                                "持仓天数": hd,
                                "代码": code,
                                "信号日期": signal_date,
                                "买入日期": df.iloc[i+1]["日期"],
                                "卖出日期": df.iloc[i+hd]["日期"],
                                "买入价": round(bp, 2),
                                "卖出价": round(sp, 2),
                                "收益率%": round(ret, 2),
                                "盈利": ret > 0,
                            })
                            total_trades += 1
                except Exception:
                    pass

        if fi % 200 == 0:
            e = time.time() - t0
            print(f"  {fi}/{total} | {e:.0f}s | 剩余{e/fi*(total-fi):.0f}s | 交易记录{total_trades}")

    elapsed = time.time() - t0
    print(f"\n完成: {elapsed:.0f}s | 总交易记录: {total_trades}")

    # 转DataFrame
    df_trades = pd.DataFrame(all_trades)
    if df_trades.empty:
        print("没有交易记录！")
        return

    # 按策略+持仓天数分组保存
    os.makedirs("output/backtest/detail", exist_ok=True)

    # 1) 主文件：全部交易明细
    master_file = "output/backtest/detail/all_trades_detail.csv"
    df_trades.to_csv(master_file, index=False, encoding="utf-8-sig")
    print(f"\n全部交易明细: {master_file} ({len(df_trades)}条)")

    # 2) 按策略分sheet的Excel
    excel_file = "output/backtest/detail/all_trades_by_strategy.xlsx"
    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        for sname in df_trades["策略"].unique():
            sub = df_trades[df_trades["策略"] == sname]
            # 只保留足够信号的
            if len(sub) < MIN_SIGNALS * MAX_HOLD:
                continue
            sub.to_excel(writer, sheet_name=sname[:31], index=False)  # sheet name max 31 chars
    print(f"策略分表Excel: {excel_file}")

    # 3) 汇总统计
    print("\n" + "=" * 120)
    print("  各策略各持仓天数汇总")
    print("=" * 120)
    print(f"  {'策略':<24} {'持仓':>5} {'交易数':>7} {'胜率%':>8} {'平均%':>8} {'盈亏比':>7}")

    summary_rows = []
    for sname in df_trades["策略"].unique():
        sub = df_trades[df_trades["策略"] == sname]
        for hd in range(1, MAX_HOLD + 1):
            sh = sub[sub["持仓天数"] == hd]
            cnt = len(sh)
            if cnt < MIN_SIGNALS: continue
            wins = sh["盈利"].sum()
            wr = wins / cnt * 100
            avg_r = sh["收益率%"].mean()
            w_rets = sh[sh["盈利"]]["收益率%"]
            l_rets = sh[~sh["盈利"]]["收益率%"]
            avg_w = w_rets.mean() if len(w_rets) > 0 else 0
            avg_l = l_rets.mean() if len(l_rets) > 0 else 0
            pl = abs(avg_w / avg_l) if avg_l != 0 else 99
            summary_rows.append({
                "策略": sname, "持仓天数": hd, "交易数": cnt,
                "胜率%": round(wr, 2), "平均收益%": round(avg_r, 2),
                "盈亏比": round(pl, 2),
            })

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values("胜率%", ascending=False)

    for _, r in summary_df.iterrows():
        print(f"  {r['策略']:<24} {int(r['持仓天数']):>5}天 {int(r['交易数']):>7} {r['胜率%']:>8.2f} {r['平均收益%']:>8.2f} {r['盈亏比']:>7.2f}")

    summary_df.to_csv("output/backtest/detail/summary_by_strategy_hold.csv", index=False, encoding="utf-8-sig")
    print(f"\n汇总保存: output/backtest/detail/summary_by_strategy_hold.csv")

    # 4) 每个策略的TOP持仓天数
    print("\n" + "=" * 80)
    print("  各策略最佳持仓天数")
    print("=" * 80)
    best_per_strat = summary_df.loc[summary_df.groupby("策略")["胜率%"].idxmax()]
    best_per_strat = best_per_strat.sort_values("胜率%", ascending=False)
    for _, r in best_per_strat.iterrows():
        print(f"  {r['策略']:<24} {int(r['持仓天数'])}天  胜率={r['胜率%']:.2f}%  交易数={int(r['交易数'])}  平均={r['平均收益%']:.2f}%")

    print("\n文件列表:")
    print(f"  {master_file}")
    print(f"  {excel_file}")
    print(f"  output/backtest/detail/summary_by_strategy_hold.csv")


if __name__ == "__main__":
    run()
