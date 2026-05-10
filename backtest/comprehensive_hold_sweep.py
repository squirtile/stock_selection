"""
Comprehensive backtest: Hold days 1-10, ALL strategies with parameter sweeps.
Optimized: single pass through data, compute all 10 holding periods simultaneously.
"""
import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

MAX_HOLD = 10  # test hold 1 through 10
MIN_SIGNALS = 15  # minimum signals for valid result


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
    """One-shot compute all extra indicators."""
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
    df["昨实体下沿"] = df["实体下沿"].shift(1)
    df["影线比"] = (df["实体下沿"] - df["最低"]) / df["收盘"].replace(0, np.nan)
    df["上影比"] = (df["最高"] - df["实体上沿"]) / df["收盘"].replace(0, np.nan)
    df["实体比"] = abs(df["收盘"] - df["开盘"]) / df["收盘"].replace(0, np.nan)
    df["量比昨"] = df["成交量"] / df["昨量"].replace(0, np.nan)
    df["均量"] = df["过去20日平均成交量"]
    df["昨均量比"] = df["昨量"] / df["均量"]
    df["收阳"] = (df["收盘"] > df["开盘"]).fillna(0).astype(int)
    df["昨收阳"] = df["收阳"].shift(1).fillna(0).astype(int)
    df["前收阳"] = df["收阳"].shift(2).fillna(0).astype(int)
    df["收阴"] = (df["收盘"] < df["开盘"]).fillna(0).astype(int)
    df["SMA5上穿SMA20"] = ((df["SMA5"] > df["SMA20"]) & (df["SMA5昨"] <= df["SMA20昨"])).fillna(0).astype(int)
    df["SMA5上穿SMA10"] = ((df["SMA5"] > df["SMA10"]) & (df["SMA5昨"] <= df["SMA10昨"])).fillna(0).astype(int)
    df["站上20MA"] = (df["收盘"] > df["SMA20"]).fillna(0).astype(int)
    df["站上20MA_count"] = df["站上20MA"].rolling(20).sum()
    df["缺口"] = (df["最低"] > df["昨高"]).fillna(0).astype(int)
    df["昨缺口"] = df["缺口"].shift(1).fillna(0).fillna(0).astype(int)
    df["昨开缺口"] = ((df["昨开"] - df["收盘"].shift(2)) / df["收盘"].shift(2).replace(0, np.nan) * 100)
    return df


# ============================================================================
# ALL STRATEGIES — expanded parameter ranges for per-hold-day tuning
# ============================================================================

S = []  # strategy list

def reg(name, cat, func):
    S.append((name, cat, func))


# --- S1 箱体突破 ---
for amp, vol in [(0.20,1.3),(0.20,1.5),(0.20,1.8),(0.15,1.5),(0.15,1.8)]:
    reg(f"S1_a{int(amp*100)}_v{vol}", "S1-箱体突破",
        lambda r,*_,a=amp,v=vol: r["收盘"]>r["过去60日最高价"] and r["成交量"]>r["均量"]*v and r["过去20日实体振幅"]<=a)

# --- S2 底部放量反转 ---
for dist, pct, vol in [(0.20,5,2.0),(0.20,4,1.8),(0.20,5,2.5),(0.15,5,2.0),(0.25,5,1.8)]:
    reg(f"S2_d{int(dist*100)}_p{int(pct)}_v{vol}", "S2-底部反转",
        lambda r,*_,d=dist,p=pct,v=vol: r["收盘"]/r["过去40日最低价"]-1<d and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# --- M1 主升箱体突破 ---
for vol in [1.3, 1.5, 2.0, 3.0]:
    reg(f"M1_v{vol}", "M1-主升箱体突破",
        lambda r,*_,v=vol: r["收盘"]>r["过去60日最高收盘"] and r["成交量"]>r["均量"]*v)

# --- M2 主升底部反转 ---
for dist, pct, vol in [(0.30,5,2.0),(0.20,4,1.8),(0.25,5,1.8),(0.15,5,1.8),(0.20,6,2.0),(0.22,5,1.5)]:
    reg(f"M2_d{int(dist*100)}_p{int(pct)}_v{vol}", "M2-主升底部反转",
        lambda r,*_,d=dist,p=pct,v=vol: r["收盘"]/r["过去60日最低收盘"]-1<d and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# --- M3 缩量回调 ---
for vol in [1.2, 1.5, 2.0]:
    reg(f"M3_v{vol}", "M3-缩量回调",
        lambda r,*_,v=vol: r["SMA5"]<r["SMA20"] and r["SMA60"]>r["SMA60_5日前"] and r["收盘"]>r["SMA5"] and r["成交量"]>r["均量"]*v)

# --- M4 均线多头 ---
for pct, vol in [(2,1.2),(0,1.0),(1,1.2),(2,1.5),(3,1.5)]:
    reg(f"M4_p{int(pct)}_v{vol}", "M4-均线多头",
        lambda r,*_,p=pct,v=vol: r["SMA5"]>r["SMA10"] and r["SMA10"]>r["SMA20"] and r["SMA20"]>r["SMA60"] and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# --- A 竞价追涨 ---
for gmin, gmax, tp, vol in [(3,6,7,1.5),(3,7,5,1.5),(2,5,5,1.3)]:
    def _a(gmin,gmax,tp,vol):
        def f(row, df, idx, prev):
            if prev is None: return False
            if pd.isna(prev["涨跌幅"]) or prev["涨跌幅"]<9.9: return False
            yc,to=prev["收盘"],row["开盘"]
            if pd.isna(yc) or pd.isna(to) or yc<=0: return False
            gap=(to/yc-1)*100
            if gap<gmin or gap>gmax: return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<tp: return False
            av=row["均量"]
            return not(pd.isna(av) or av<=0) and row["成交量"]>=av*vol
        return f
    reg(f"A_g{gmin}-{gmax}_p{tp}_v{vol}", "A-竞价追涨", _a(gmin,gmax,tp,vol))

# --- B 龙头回调 ---
for rise, days, pb in [(20,8,50),(15,5,30),(20,5,40),(25,5,30)]:
    def _b(rise,days,pb):
        def f(row, df, idx, prev):
            if idx<20: return False
            tc=row["收盘"]
            if pd.isna(tc) or tc<=0: return False
            seg=df.iloc[max(0,idx-13):idx+1]
            cls=seg["收盘"].values
            if len(cls)<5: return False
            li,hi=int(np.argmin(cls)),int(np.argmax(cls))
            lp,hp=cls[li],cls[hi]
            if lp<=0 or hp<=0: return False
            if (hp/lp-1)*100<rise: return False
            if hi<=li: return False
            if tc>=hp*0.99: return False
            pd_=len(seg)-1-hi
            if pd_<2 or pd_>days: return False
            if (hp-tc)/(hp-lp)*100>pb: return False
            return True
        return f
    reg(f"B_r{rise}_d{days}_pb{pb}", "B-龙头回调", _b(rise,days,pb))

# --- C 追涨突破 ---
for vy, va, pct in [(1.5,3,5),(2,4,5),(1.5,2,5)]:
    def _c(vy,va,pct):
        def f(row, df, idx, prev):
            if prev is None: return False
            yv,tv=prev["成交量"],row["成交量"]
            if pd.isna(yv) or pd.isna(tv) or yv<=0: return False
            if tv<yv*vy: return False
            av=row["均量"]
            if pd.isna(av) or av<=0 or tv<av*va: return False
            if pd.isna(row["过去20日日均成交额"]) or row["过去20日日均成交额"]<50_000_000: return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<pct: return False
            h=row.get("过去13日最高价")
            if h is None: h=row.get("10日高")
            return not(h is None or pd.isna(h) or h<=0) and row["收盘"]>h
        return f
    reg(f"C_vy{vy}_va{va}_p{pct}", "C-追涨突破", _c(vy,va,pct))

# --- D 断板反包 ---
for lim, rev, brk in [(2,2,-8),(2,1,-8),(3,2,-5)]:
    def _d(lim,rev,brk):
        def f(row, df, idx, prev):
            if idx<10: return False
            t=df.iloc[idx]
            if pd.isna(t["收盘"]) or t["收盘"]<=0: return False
            b=df.iloc[idx-1]
            if pd.isna(b["涨跌幅"]) or b["涨跌幅"]>=9.95: return False
            clim=0
            for j in range(2,10):
                ci=idx-j
                if ci<0: break
                if df.iloc[ci]["涨跌幅"]>=9.95: clim+=1
                else: break
            if clim<lim: return False
            bh=max(b["开盘"],b["收盘"])
            if t["收盘"]<=bh: return False
            if pd.isna(t["涨跌幅"]) or t["涨跌幅"]<rev: return False
            if b["涨跌幅"]<brk: return False
            av=t.get("均量")
            return not(av is None or pd.isna(av) or av<=0) and t["成交量"]>=av*0.8
        return f
    reg(f"D_l{lim}_r{rev}_b{brk}", "D-断板反包", _d(lim,rev,brk))

# ==================== N1-N25 ====================

# N1 双底放量反转
for d40, d60, pct, vol in [
    (0.15,0.20,3.0,1.8),(0.12,0.18,2.0,2.0),(0.15,0.20,3.0,1.5),
    (0.10,0.15,2.0,1.5),(0.18,0.25,4.0,1.8),(0.15,0.25,3.0,1.8)]:
    reg(f"N1_d40_{int(d40*100)}_d60_{int(d60*100)}_p{int(pct)}_v{vol}", "N1-双底放量反转",
        lambda r,*_,d40=d40,d60=d60,p=pct,v=vol:
        r["收盘"]/r["过去40日最低价"]-1<d40 and r["收盘"]/r["过去60日最低收盘"]-1<d60
        and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N2 缩量回踩反击
for yv, tv, pct in [(0.6,1.5,2),(0.5,1.8,1),(0.7,1.5,1)]:
    reg(f"N2_y{yv}_t{tv}_p{int(pct)}", "N2-缩量回踩反击",
        lambda r,*_,yv=yv,tv=tv,p=pct:
        r["昨量"]<r["均量"]*yv and r["成交量"]>r["均量"]*tv
        and r["量比昨"]>1.3 and r["涨跌幅"]>p
        and r["收盘"]>r["SMA5"] and r["SMA20"]>r["SMA60"])

# N3 涨停回踩反弹
for tv, pct in [(1.5,2),(1.8,1),(1.5,1),(1.3,0)]:
    reg(f"N3_tv{tv}_p{int(pct)}", "N3-涨停回踩反弹",
        lambda r,*_,tv=tv,p=pct:
        r["近15日涨停次数"]>=1 and r["涨跌幅"]>p
        and r["成交量"]>r["均量"]*tv and r["收盘"]>r["SMA5"] and r["SMA5"]>r["SMA20"])

# N5 均线粘合突破
for vol, pct in [(1.5,3),(1.5,2),(1.8,1),(1.3,2)]:
    reg(f"N5_v{vol}_p{int(pct)}", "N5-均线粘合突破",
        lambda r,*_,v=vol,p=pct:
        abs(r["SMA5"]/r["SMA10"]-1)<0.03 and abs(r["SMA10"]/r["SMA20"]-1)<0.05
        and r["收盘"]>max(r["SMA5"],r["SMA10"],r["SMA20"])
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N6 放量长阳
for vol, pct, pos in [(2.5,5,0.8),(3,5,0.85),(2,5,0.85)]:
    reg(f"N6_v{vol}_p{int(pct)}_pos{int(pos*100)}", "N6-放量长阳",
        lambda r,*_,v=vol,p=pct,pos=pos:
        r["成交量"]>r["均量"]*v and r["涨跌幅"]>p
        and r["收盘位置"]>pos and r["收盘"]>r["SMA20"])

# N7 强势整理突破
for amp, vol, pct in [(0.15,1.5,2),(0.20,1.8,2),(0.10,1.5,2)]:
    reg(f"N7_a{int(amp*100)}_v{vol}_p{int(pct)}", "N7-整理突破",
        lambda r,*_,a=amp,v=vol,p=pct:
        r["收盘"]>r["10日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>p and r["过去20日实体振幅"]<=a and r["收盘"]>r["SMA20"])

# N9 跳空不补
for gap_pct, vol in [(2.0,1.3),(3.0,1.5),(1.5,1.2)]:
    reg(f"N9_g{int(gap_pct*10)}_v{vol}", "N9-跳空不补",
        lambda r,*_,g=gap_pct,v=vol:
        r["昨开缺口"]>g and r["昨收阳"]==1
        and r["最低"]>r["昨开"] and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N11 地量倍量
for dry, boom, pct in [(0.5,2.0,2),(0.4,2.5,1),(0.6,1.8,3)]:
    reg(f"N11_d{int(dry*10)}_b{int(boom*10)}_p{int(pct)}", "N11-地量倍量",
        lambda r,*_,dry=dry,boom=boom,p=pct:
        r["昨量"]<r["均量"]*dry and r["量比昨"]>boom
        and r["涨跌幅"]>p and r["收盘"]>r["SMA5"])

# N12 阳包阴
for vol, pct in [(1.3,2),(1.5,3),(1.2,1)]:
    reg(f"N12_v{vol}_p{int(pct)}", "N12-阳包阴",
        lambda r,*_,v=vol,p=pct:
        r["昨收阳"]==0 and r["收阳"]==1
        and r["收盘"]>r["昨开"] and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# N13 多方炮
for vol in [1.3, 1.5, 1.8]:
    reg(f"N13_v{vol}", "N13-多方炮",
        lambda r,*_,v=vol:
        r["前收阳"]==1 and r["昨收阳"]==0 and r["收阳"]==1
        and r["昨涨跌"]>-5 and r["收盘"]>r["昨高"] and r["成交量"]>r["均量"]*v)

# N15 均线金叉
for vol, pct in [(1.3,1),(1.5,2),(1.8,1)]:
    reg(f"N15_v{vol}_p{int(pct)}", "N15-均线金叉",
        lambda r,*_,v=vol,p=pct:
        r["SMA5上穿SMA20"]==1 and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N17 末端突破
for amp, vol, pct in [(0.10,1.5,2),(0.12,1.5,3),(0.08,1.8,2)]:
    reg(f"N17_a{int(amp*100)}_v{vol}_p{int(pct)}", "N17-末端突破",
        lambda r,*_,a=amp,v=vol,p=pct:
        r["10日高"]/r["10日低"]-1<a
        and r["收盘"]>r["10日高"] and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N20 加速上涨
for vol in [1.3, 1.5, 1.8]:
    reg(f"N20_v{vol}", "N20-加速上涨",
        lambda r,*_,v=vol:
        r["涨跌幅"]>r["昨涨跌"] and r["昨涨跌"]>r["前涨跌"]
        and r["涨跌幅"]>2 and r["前涨跌"]>0 and r["昨涨跌"]>0
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N22 V型反转 — WIDER sweep for per-hold-day tuning
for dist, pct, vol in [
    (0.08,3,1.2),(0.08,4,1.5),(0.10,3,1.2),(0.10,4,1.5),(0.10,4,1.8),
    (0.12,3,1.2),(0.12,4,1.2),(0.12,4,1.5),(0.12,5,1.5),(0.12,4,2.0),
    (0.15,3,1.2),(0.15,4,1.5),(0.15,4,1.8),(0.15,5,1.5),(0.15,5,1.8),
    (0.18,4,1.5),(0.18,5,1.8),(0.20,4,1.5),(0.20,5,1.8),(0.25,4,1.5)]:
    reg(f"N22_d{int(dist*100)}_p{int(pct)}_v{vol}", "N22-V型反转",
        lambda r,*_,d=dist,p=pct,v=vol:
        r["收盘"]/r["过去40日最低价"]-1<d
        and r["涨跌幅"]>p and r["昨涨跌"]<-1
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N23 倍量突破前高
for vm, lb in [(1.8,10),(2.0,20),(1.5,10)]:
    reg(f"N23_vm{vm}_lb{lb}", "N23-倍量突破前高",
        lambda r,*_,vm=vm,lb=lb:
        r["量比昨"]>vm and r["成交量"]>r["均量"]*1.5
        and r["收盘"]>(r["10日最高收"] if lb<=10 else r["过去60日最高收盘"])
        and r["涨跌幅"]>1.5 and r["收阳"]==1)

# N24 涨停缩量再放
reg("N24_d5", "N24-涨停缩量再放",
    lambda r: r["近15日涨停次数"]>=1 and r["昨量"]<r["均量"]*0.7 and r["量比昨"]>1.5
    and r["涨跌幅"]>2 and r["收盘"]>r["SMA10"] and r["SMA20"]>r["SMA60"])

# N25 假摔洗盘
for vol in [1.2, 1.5]:
    reg(f"N25_v{vol}", "N25-假摔洗盘",
        lambda r,*_,v=vol:
        r["前收阳"]==1 and r["昨收阳"]==0 and r["收阳"]==1
        and r["昨涨跌"]>-3 and r["收盘"]>r["昨高"] and r["成交量"]>r["均量"]*v)

# N26 强势突破连阳
for vol, pct in [(1.5,2),(1.8,2),(1.5,3)]:
    reg(f"N26_v{vol}_p{int(pct)}", "N26-强势突破连阳",
        lambda r,*_,v=vol,p=pct:
        r["收盘"]>r["5日高"] and r["昨收阳"]==1
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p and r["收阳"]==1)

# N27 涨停接力
for gmin, gmax, vol in [(1,4,1.8),(1,3,2.0),(0,5,1.5)]:
    def _n27(gmin,gmax,vol):
        def f(row, df, idx, prev):
            if prev is None: return False
            if pd.isna(prev["涨跌幅"]) or prev["涨跌幅"]<9.9: return False
            yc,to=prev["收盘"],row["开盘"]
            if pd.isna(yc) or pd.isna(to) or yc<=0: return False
            gap=(to/yc-1)*100
            if gap<gmin or gap>gmax: return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<2: return False
            av=row["均量"]
            return not(pd.isna(av) or av<=0) and row["成交量"]>=av*vol and row["收阳"]==1
        return f
    reg(f"N27_g{gmin}-{gmax}_v{vol}", "N27-涨停接力", _n27(gmin,gmax,vol))

# N28 缩量后突破
for yv, tv, pct in [(0.7,1.5,2),(0.6,1.8,1),(0.8,1.5,3)]:
    reg(f"N28_y{yv}_t{tv}_p{int(pct)}", "N28-缩量后突破",
        lambda r,*_,yv=yv,tv=tv,p=pct:
        r["昨量"]<r["均量"]*yv and r["成交量"]>r["均量"]*tv
        and r["收盘"]>r["昨高"] and r["涨跌幅"]>p and r["收阳"]==1)

# N29 3日窄幅突破
for amp, vol in [(0.03,1.5),(0.05,1.8),(0.03,2.0)]:
    reg(f"N29_a{int(amp*100)}_v{vol}", "N29-3日窄幅突破",
        lambda r,*_,a=amp,v=vol:
        r["5日高"]/r["5日低"]-1<a
        and r["收盘"]>r["5日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>1.5 and r["收阳"]==1)

# N30 连阳加速
for vol in [1.3, 1.5, 1.8]:
    reg(f"N30_v{vol}", "N30-连阳加速",
        lambda r,*_,v=vol:
        r["收阳"]==1 and r["昨收阳"]==1
        and r["涨跌幅"]>1 and r["昨涨跌"]>0
        and r["成交量"]>r["均量"]*v and r["昨量"]>r["均量"]*v
        and r["收盘"]>r["昨高"])

# N32 跳空高开
for gap_pct, vol in [(2.0,1.3),(3.0,1.5)]:
    reg(f"N32_g{int(gap_pct*10)}_v{vol}", "N32-跳空高开",
        lambda r,*_,g=gap_pct,v=vol:
        r["昨开缺口"]>g and r["昨收阳"]==1
        and r["最低"]>r["昨高"] and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N34 突破20日高
for vol in [2.0, 2.5, 3.0]:
    reg(f"N34_v{vol}", "N34-突破20日高",
        lambda r,*_,v=vol:
        r["收盘"]>r["20日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>1 and r["收阳"]==1 and r["SMA5"]>r["SMA10"])

# N35 急跌反弹
for drop, rise, vol in [(-3,2,1.5),(-5,3,1.8),(-4,3,1.5)]:
    reg(f"N35_d{abs(drop)}_r{int(rise)}_v{vol}", "N35-急跌反弹",
        lambda r,*_,d=drop,ri=rise,v=vol:
        r["昨涨跌"]<d and r["涨跌幅"]>ri
        and r["成交量"]>r["均量"]*v and r["收阳"]==1
        and r["收盘"]>r["昨实体上沿"])


# ============================================================================
# Main: single pass, compute all 10 holding periods
# ============================================================================

def run():
    n = len(S)
    print(f"全策略多持仓回测: {n}个策略变体 | 持股1-{MAX_HOLD}天 | 1136只股票")
    print("=" * 80)

    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total = len(files)

    # Accumulators: acc[hold_day][strategy_name] = {signals, wins, returns}
    acc = {}
    for hd in range(1, MAX_HOLD + 1):
        acc[hd] = {}
        for name, cat, _ in S:
            acc[hd][name] = {"signals": 0, "wins": 0, "returns": [], "category": cat}

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()
    total_signals = 0

    for fi, fname in enumerate(files, 1):
        raw = load_stock(os.path.join(HIST_CACHE_DIR, fname))
        if raw is None: continue

        df = prepare_hist_data(raw.copy())
        df = enrich(df)
        df = df.sort_values("日期").reset_index(drop=True)

        max_i = len(df) - MAX_HOLD - 1
        for i in range(65, max_i):
            row = df.iloc[i]
            if row[need_cols].isna().any(): continue
            if not check_secondary_filters(row): continue

            prev = df.iloc[i-1] if i >= 1 else None
            bp = df.iloc[i+1]["开盘"]  # T+1 open
            if pd.isna(bp) or bp <= 0: continue

            # Compute all 10 sell prices upfront
            sell_prices = []
            valid = True
            for hd in range(1, MAX_HOLD + 1):
                sp = df.iloc[i + hd]["收盘"]
                if pd.isna(sp):
                    valid = False
                    break
                sell_prices.append(sp)
            if not valid: continue

            # Compute all 10 returns
            returns = [(sp/bp - 1) * 100 for sp in sell_prices]
            wins = [r > 0 for r in returns]

            # Check each strategy once, record for all hold days
            for name, cat, func in S:
                try:
                    if func(row, df, i, prev):
                        for hd in range(1, MAX_HOLD + 1):
                            d = acc[hd][name]
                            d["signals"] += 1
                            d["returns"].append(returns[hd-1])
                            if wins[hd-1]:
                                d["wins"] += 1
                        total_signals += 1
                except Exception:
                    pass

        if fi % 200 == 0:
            e = time.time() - t0
            print(f"  {fi}/{total} | {e:.0f}s | 剩余{e/fi*(total-fi):.0f}s | 信号{total_signals}")

    elapsed = time.time() - t0
    print(f"\n完成: {elapsed:.0f}s | 总信号触发: {total_signals}")

    # ============================================================
    # Build results per hold day
    # ============================================================
    os.makedirs("output/backtest", exist_ok=True)

    all_hold_results = {}  # hold_day -> DataFrame

    for hd in range(1, MAX_HOLD + 1):
        results = []
        for name, d in acc[hd].items():
            cnt = d["signals"]
            if cnt < MIN_SIGNALS: continue
            rets = d["returns"]
            w = d["wins"]
            wr = w/cnt*100
            avg_r = sum(rets)/len(rets)
            med_r = sorted(rets)[len(rets)//2]
            avg_w = sum(r for r in rets if r>0)/max(1,sum(1 for r in rets if r>0))
            avg_l = sum(r for r in rets if r<=0)/max(1,sum(1 for r in rets if r<=0))
            pl = abs(avg_w/avg_l) if avg_l!=0 else 99
            results.append({
                "name": name, "cat": d["category"],
                "signals": cnt, "wins": w, "losses": cnt-w,
                "wr": wr, "avg": avg_r, "med": med_r,
                "max_g": max(rets), "max_l": min(rets),
                "avg_w": avg_w, "avg_l": avg_l, "pl": pl,
            })

        results.sort(key=lambda r: r["wr"], reverse=True)
        df_r = pd.DataFrame(results)
        all_hold_results[hd] = df_r

        # Save per hold day
        df_r.to_csv(f"output/backtest/all_hold{hd}d.csv", index=False, encoding="utf-8-sig")
        df_r.to_excel(f"output/backtest/all_hold{hd}d.xlsx", index=False)

    # ============================================================
    # Print summary report
    # ============================================================
    print("\n")
    print("=" * 120)
    print("  持股1-10天 各持仓最佳策略汇总")
    print("=" * 120)
    print(f"{'持仓':<6} {'最佳策略变体':<45} {'分类':<22} {'胜率%':>8} {'信号':>6} {'平均%':>8} {'盈亏比':>7}")
    print("-" * 110)

    best_per_hold = []

    for hd in range(1, MAX_HOLD + 1):
        df_r = all_hold_results[hd]
        if df_r.empty: continue
        best = df_r.iloc[0]
        best_per_hold.append((hd, best))
        print(f"{hd}天{'':>3} {best['name']:<45} {best['cat']:<22} {best['wr']:>8.2f} {best['signals']:>6} {best['avg']:>8.2f} {best['pl']:>7.2f}")

    # ============================================================
    # TOP 10 per hold day (detailed)
    # ============================================================
    for hd in range(1, MAX_HOLD + 1):
        df_r = all_hold_results[hd]
        if df_r.empty: continue
        print(f"\n{'='*100}")
        print(f"  持股{hd}天 — TOP 10 策略")
        print(f"{'='*100}")
        for rank, (_, r) in enumerate(df_r.head(10).iterrows(), 1):
            print(f"  {rank:>2}. {r['name']:<45} {r['cat']:<22} 胜率={r['wr']:.2f}%  信号={r['signals']}  平均={r['avg']:.2f}%  盈亏比={r['pl']:.2f}")

    # ============================================================
    # Champion of champions
    # ============================================================
    best_overall = max(best_per_hold, key=lambda x: x[1]["wr"])
    hd, best = best_overall
    print("\n")
    print("=" * 80)
    print(f"  ★ 全局冠军: 持股{hd}天 — {best['name']} ({best['cat']})")
    print(f"  ★ 胜率={best['wr']:.2f}%  信号={best['signals']}  平均收益={best['avg']:.2f}%  盈亏比={best['pl']:.2f}")
    print("=" * 80)

    # ============================================================
    # Best per category across all hold days
    # ============================================================
    print("\n" + "=" * 100)
    print("  各类别最佳（跨所有持仓天数）")
    print("=" * 100)

    all_results_combined = []
    for hd in range(1, MAX_HOLD + 1):
        df_r = all_hold_results[hd]
        for _, r in df_r.iterrows():
            all_results_combined.append({**r.to_dict(), "hold_days": hd})

    df_all = pd.DataFrame(all_results_combined)

    # Best per category (by win rate)
    categories = df_all["cat"].unique()
    best_cat = {}
    for cat in categories:
        cat_df = df_all[df_all["cat"] == cat]
        best_idx = cat_df["wr"].idxmax()
        best_cat[cat] = cat_df.loc[best_idx]

    sorted_cats = sorted(best_cat.items(), key=lambda x: x[1]["wr"], reverse=True)
    for cat, r in sorted_cats:
        hd = int(r["hold_days"])
        print(f"  {cat:<24} 持股{hd}天  {r['name']:<45} 胜率={r['wr']:.2f}%  信号={r['signals']}")

    # ============================================================
    # Win rate curve: how does each strategy type perform by hold days?
    # ============================================================
    print("\n" + "=" * 100)
    print("  策略类型胜率曲线（按持仓天数）")
    print("=" * 100)

    # Get top categories
    top_cats = [cat for cat, _ in sorted_cats[:15]]
    print(f"{'分类':<24}", end="")
    for hd in range(1, MAX_HOLD + 1):
        print(f"  {hd}天{'':>2}", end="")
    print()

    for cat in top_cats:
        print(f"{cat:<24}", end="")
        for hd in range(1, MAX_HOLD + 1):
            cat_hd = df_all[(df_all["cat"] == cat) & (df_all["hold_days"] == hd)]
            if cat_hd.empty:
                print(f"  {'--':>5}", end="")
            else:
                best_wr = cat_hd["wr"].max()
                print(f"  {best_wr:>5.1f}", end="")
        print()

    # Save master summary CSV
    df_all.to_csv("output/backtest/all_hold_days_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\n全部结果已保存: output/backtest/all_hold*d.csv|xlsx")
    print(f"汇总文件: output/backtest/all_hold_days_summary.csv")


if __name__ == "__main__":
    run()
