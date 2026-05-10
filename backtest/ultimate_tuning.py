"""
终极策略PK v2: 30+策略 × 多参数变体 | 持股10天
"""

import os, sys, time
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from strategy import HIST_CACHE_DIR, prepare_hist_data, check_secondary_filters

HOLD_DAYS = 3


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
    # Shifts
    df["昨收"] = df["收盘"].shift(1)
    df["昨开"] = df["开盘"].shift(1)
    df["昨低"] = df["最低"].shift(1)
    df["昨高"] = df["最高"].shift(1)
    df["昨量"] = df["成交量"].shift(1)
    df["昨涨跌"] = df["涨跌幅"].shift(1)
    df["前涨跌"] = df["涨跌幅"].shift(2)
    df["大前涨跌"] = df["涨跌幅"].shift(3)
    # MA shifts
    df["SMA10"] = df["收盘"].rolling(10).mean()
    df["SMA20"] = df["收盘"].rolling(20).mean()
    df["SMA5昨"] = df["SMA5"].shift(1)
    df["SMA10昨"] = df["SMA10"].shift(1)
    df["SMA20昨"] = df["SMA20"].shift(1)
    df["SMA20_5d"] = df["SMA20"].shift(5)
    # Ranges
    df["10日高"] = df["最高"].shift(1).rolling(10).max()
    df["10日低"] = df["最低"].rolling(10).min()
    df["10日最高收"] = df["收盘"].shift(1).rolling(10).max()
    df["20日高"] = df["最高"].shift(1).rolling(20).max()
    df["20日低"] = df["最低"].rolling(20).min()
    df["5日高"] = df["最高"].shift(1).rolling(5).max()
    df["5日低"] = df["最低"].rolling(5).min()
    # Candlestick
    df["实体上沿"] = df[["开盘","收盘"]].max(axis=1)
    df["实体下沿"] = df[["开盘","收盘"]].min(axis=1)
    df["昨实体上沿"] = df["实体上沿"].shift(1)
    df["昨实体下沿"] = df["实体下沿"].shift(1)
    df["影线比"] = (df["实体下沿"] - df["最低"]) / df["收盘"].replace(0, np.nan)  # lower shadow
    df["上影比"] = (df["最高"] - df["实体上沿"]) / df["收盘"].replace(0, np.nan)
    df["实体比"] = abs(df["收盘"] - df["开盘"]) / df["收盘"].replace(0, np.nan)
    # Volume
    df["量比昨"] = df["成交量"] / df["昨量"].replace(0, np.nan)
    df["均量"] = df["过去20日平均成交量"]
    df["昨均量比"] = df["昨量"] / df["均量"]
    # Patterns
    df["收阳"] = (df["收盘"] > df["开盘"]).fillna(0).astype(int)
    df["昨收阳"] = df["收阳"].shift(1).fillna(0).astype(int)
    df["前收阳"] = df["收阳"].shift(2).fillna(0).astype(int)
    df["收阴"] = (df["收盘"] < df["开盘"]).fillna(0).astype(int)
    # MA cross
    df["SMA5上穿SMA20"] = ((df["SMA5"] > df["SMA20"]) & (df["SMA5昨"] <= df["SMA20昨"])).fillna(0).astype(int)
    df["SMA5上穿SMA10"] = ((df["SMA5"] > df["SMA10"]) & (df["SMA5昨"] <= df["SMA10昨"])).fillna(0).astype(int)
    # Above MA stats
    df["站上20MA"] = (df["收盘"] > df["SMA20"]).fillna(0).astype(int)
    df["站上20MA_count"] = df["站上20MA"].rolling(20).sum()
    # Gap
    df["缺口"] = (df["最低"] > df["昨高"]).fillna(0).astype(int)  # today's low > yesterday's high
    df["昨缺口"] = df["缺口"].shift(1).fillna(0).fillna(0).astype(int)
    df["昨开缺口"] = ((df["昨开"] - df["收盘"].shift(2)) / df["收盘"].shift(2).replace(0, np.nan) * 100)  # yesterday's gap %
    return df


# ============================================================================
# All strategies: (name, category, function)
# func takes (row, df, idx, prev_row) → bool
# - row: current day row
# - df: full dataframe
# - idx: current index
# - prev: previous day row (or None)
# ============================================================================

S = []  # strategy list

def reg(name, cat, func):
    S.append((name, cat, func))

# === ORIGINAL 10 categories (best variants) ===

# S1 箱体突破
for nm, amp, vol in [("S1_amp20_vol1.3_原版",0.20,1.3),("S1_amp20_vol1.5",0.20,1.5),("S1_amp20_vol1.8",0.20,1.8)]:
    reg(nm, "S1-箱体突破", lambda r,*_,a=amp,v=vol: r["收盘"]>r["过去60日最高价"] and r["成交量"]>r["均量"]*v and r["过去20日实体振幅"]<=a)

# S2 底部放量反转
for nm, dist, pct, vol in [("S2_dist20_pct5_vol2.0_原版",0.20,5,2.0),("S2_dist20_pct4_vol1.8",0.20,4,1.8),("S2_dist20_pct5_vol2.5",0.20,5,2.5)]:
    reg(nm, "S2-底部反转", lambda r,*_,d=dist,p=pct,v=vol: r["收盘"]/r["过去40日最低价"]-1<d and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# M1 主升箱体突破
for nm, vol in [("M1_vol1.5_原版",1.5),("M1_vol2.0",2.0),("M1_vol3.0",3.0)]:
    reg(nm, "M1-主升箱体突破", lambda r,*_,v=vol: r["收盘"]>r["过去60日最高收盘"] and r["成交量"]>r["均量"]*v)

# M2 主升底部反转 (best!)
for nm, dist, pct, vol in [("M2_dist30_pct5_vol2.0_原版",0.30,5,2.0),("M2_dist20_pct4_vol1.8",0.20,4,1.8)]:
    reg(nm, "M2-主升底部反转", lambda r,*_,d=dist,p=pct,v=vol: r["收盘"]/r["过去60日最低收盘"]-1<d and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# M3 主升缩量回调
for nm, vol in [("M3_vol1.5_原版",1.5),("M3_vol1.2",1.2)]:
    reg(nm, "M3-缩量回调", lambda r,*_,v=vol: r["SMA5"]<r["SMA20"] and r["SMA60"]>r["SMA60_5日前"] and r["收盘"]>r["SMA5"] and r["成交量"]>r["均量"]*v)

# M4 主升均线多头
for nm, pct, vol in [("M4_pct2_vol1.2_原版",2,1.2),("M4_pct0_vol1.0",0,1.0),("M4_pct1_vol1.2",1,1.2)]:
    reg(nm, "M4-均线多头", lambda r,*_,p=pct,v=vol: r["SMA5"]>r["SMA10"] and r["SMA10"]>r["SMA20"] and r["SMA20"]>r["SMA60"] and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# A 竞价追涨
for nm, gmin, gmax, tp, vol in [("A_gap3-6_pct7_vol1.5_原版",3,6,7,1.5),("A_gap3-7_pct5_vol1.5",3,7,5,1.5)]:
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
    reg(nm, "A-竞价追涨", _a(gmin,gmax,tp,vol))

# B 龙头回调
for nm, rise, days, pb in [("B_rise20_d8_pb50_原版",20,8,50),("B_rise15_d5_pb30",15,5,30),("B_rise20_d5_pb40",20,5,40)]:
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
    reg(nm, "B-龙头回调", _b(rise,days,pb))

# C 追涨突破
for nm, vy, va, pct, lb in [("C_vy1.5_va3_pct5_lb13_原版",1.5,3,5,13),("C_vy2_va4_pct5_lb13",2,4,5,13)]:
    def _c(vy,va,pct,lb):
        def f(row, df, idx, prev):
            if prev is None: return False
            yv,tv=prev["成交量"],row["成交量"]
            if pd.isna(yv) or pd.isna(tv) or yv<=0: return False
            if tv<yv*vy: return False
            av=row["均量"]
            if pd.isna(av) or av<=0 or tv<av*va: return False
            if pd.isna(row["过去20日日均成交额"]) or row["过去20日日均成交额"]<50_000_000: return False
            if pd.isna(row["涨跌幅"]) or row["涨跌幅"]<pct: return False
            hcol="过去13日最高价" if lb>=13 else "10日高"
            h=row.get(hcol)
            return not(h is None or pd.isna(h) or h<=0) and row["收盘"]>h
        return f
    reg(nm, "C-追涨突破", _c(vy,va,pct,lb))

# D 断板反包
for nm, lim, rev, brk in [("D_lim2_rev2_brk-8_原版",2,2,-8),("D_lim2_rev1_brk-8",2,1,-8)]:
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
    reg(nm, "D-断板反包", _d(lim,rev,brk))


# ============================================================================
# ==== NEW STRATEGIES (N1-N22) ==============================================
# ============================================================================

# N1 双底放量反转 (from previous test, top performer)
for nm, d40, d60, pct, vol in [
    ("N1_双底_dist15_pct3_vol1.8", 0.15, 0.20, 3.0, 1.8),
    ("N1_双底_dist12_pct2_vol2.0", 0.12, 0.18, 2.0, 2.0),
    ("N1_双底_dist15_pct3_vol1.5", 0.15, 0.20, 3.0, 1.5),
]:
    reg(nm, "N1-双底放量反转",
        lambda r,*_,d40=d40,d60=d60,p=pct,v=vol:
        r["收盘"]/r["过去40日最低价"]-1<d40
        and r["收盘"]/r["过去60日最低收盘"]-1<d60
        and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N2 缩量回踩反击 (shrink pullback then counter)
for nm, yv, tv, pct in [("N2_缩量反击_v6_t1.5_p2",0.6,1.5,2),("N2_缩量反击_v5_t1.8_p1",0.5,1.8,1)]:
    reg(nm, "N2-缩量回踩反击",
        lambda r,*_,yv=yv,tv=tv,p=pct:
        r["昨量"]<r["均量"]*yv and r["成交量"]>r["均量"]*tv
        and r["量比昨"]>1.3 and r["涨跌幅"]>p
        and r["收盘"]>r["SMA5"] and r["SMA20"]>r["SMA60"])

# N3 涨停回踩反弹 (limit-up gene + pullback rebound)
for nm, tv, pct in [("N3_涨停回踩_tv1.5_p2",1.5,2),("N3_涨停回踩_tv1.8_p1",1.8,1),("N3_涨停回踩_tv1.5_p1",1.5,1)]:
    reg(nm, "N3-涨停回踩反弹",
        lambda r,*_,tv=tv,p=pct:
        r["近15日涨停次数"]>=1 and r["涨跌幅"]>p
        and r["成交量"]>r["均量"]*tv
        and r["收盘"]>r["SMA5"] and r["SMA5"]>r["SMA20"])

# N4 底部三连阳 (bottom 3 white soldiers)
for nm, tv, pct in [("N4_三连阳_tv1.3_p0",1.3,0),("N4_三连阳_tv1.5_p0",1.5,0)]:
    reg(nm, "N4-底部三连阳",
        lambda r,*_,tv=tv,p=pct:
        r["涨跌幅"]>p and r["昨涨跌"]>-0.5
        and r["收盘"]/r["过去40日最低价"]-1<0.25
        and r["成交量"]>r["均量"]*tv and r["收阳"]==1)

# N5 均线粘合突破 (MA pinch breakout)
for nm, vol, pct in [("N5_均线粘合_v1.5_p3",1.5,3),("N5_均线粘合_v1.5_p2",1.5,2),("N5_均线粘合_v1.8_p1",1.8,1)]:
    reg(nm, "N5-均线粘合突破",
        lambda r,*_,v=vol,p=pct:
        abs(r["SMA5"]/r["SMA10"]-1)<0.03 and abs(r["SMA10"]/r["SMA20"]-1)<0.05
        and r["收盘"]>max(r["SMA5"],r["SMA10"],r["SMA20"])
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N6 放量长阳扫货 (volume surge strong close)
for nm, vol, pct, pos in [("N6_长阳_v2.5_p5_pos80",2.5,5,0.8),("N6_长阳_v3_p5_pos85",3,5,0.85),("N6_长阳_v2_p5_pos85",2,5,0.85)]:
    reg(nm, "N6-放量长阳",
        lambda r,*_,v=vol,p=pct,pos=pos:
        r["成交量"]>r["均量"]*v and r["涨跌幅"]>p
        and r["收盘位置"]>pos and r["收盘"]>r["SMA20"])

# N7 强势整理突破 (consolidation then breakout)
for nm, amp, vol, pct in [("N7_整理突破_a15_v1.5_p2",0.15,1.5,2),("N7_整理突破_a20_v1.8_p2",0.20,1.8,2)]:
    reg(nm, "N7-整理突破",
        lambda r,*_,a=amp,v=vol,p=pct:
        r["收盘"]>r["10日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>p and r["过去20日实体振幅"]<=a and r["收盘"]>r["SMA20"])

# N8 60MA支撑反弹 (60MA support bounce)
for nm, d, vol, pct in [("N8_60MA_d3_v1.5_p1",0.03,1.5,1),("N8_60MA_d5_v1.5_p2",0.05,1.5,2)]:
    reg(nm, "N8-60MA支撑",
        lambda r,*_,d=d,v=vol,p=pct:
        abs(r["收盘"]/r["SMA60"]-1)<d and r["SMA60"]>r["SMA60_5日前"]
        and r["SMA20"]>r["SMA60"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>p and r["收阳"]==1)

# ---- BRAND NEW STRATEGIES (N9-N22) ----

# N9 跳空缺口不回补 (Gap Not Filled)
for nm, gap_pct, vol in [("N9_跳空不补_g2_v1.3",2.0,1.3),("N9_跳空不补_g3_v1.5",3.0,1.5),("N9_跳空不补_g1.5_v1.2",1.5,1.2)]:
    reg(nm, "N9-跳空不补",
        lambda r,*_,g=gap_pct,v=vol:
        r["昨开缺口"]>g and r["昨收阳"]==1  # yesterday gapped up and closed yang
        and r["最低"]>r["昨开"]  # today's low > yesterday's open (gap holds)
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N10 长下影线探底回升 (Long Lower Shadow Bottom Reversal)
for nm, shadow, dist, vol in [("N10_下影_s3_d15_v1.3",0.03,0.15,1.3),("N10_下影_s4_d20_v1.5",0.04,0.20,1.5),("N10_下影_s3_d12_v1.2",0.03,0.12,1.2)]:
    reg(nm, "N10-长下影探底",
        lambda r,*_,s=shadow,d=dist,v=vol:
        r["影线比"]>s  # long lower shadow
        and r["收盘"]/r["过去40日最低价"]-1<d  # near bottom
        and r["收阳"]==1 and r["成交量"]>r["均量"]*v)

# N11 地量后倍量启动 (Volume Dry-up → Explosion)
for nm, dry, boom, pct in [("N11_地量倍量_d0.5_b2_p2",0.5,2.0,2),("N11_地量倍量_d0.4_b2.5_p1",0.4,2.5,1),("N11_地量倍量_d0.6_b1.8_p3",0.6,1.8,3)]:
    reg(nm, "N11-地量倍量",
        lambda r,*_,dry=dry,boom=boom,p=pct:
        r["昨量"]<r["均量"]*dry and r["量比昨"]>boom
        and r["涨跌幅"]>p and r["收盘"]>r["SMA5"])

# N12 阳包阴反转 (Bullish Engulfing Reversal)
for nm, vol, pct in [("N12_阳包阴_v1.3_p2",1.3,2),("N12_阳包阴_v1.5_p3",1.5,3),("N12_阳包阴_v1.2_p1",1.2,1)]:
    reg(nm, "N12-阳包阴",
        lambda r,*_,v=vol,p=pct:
        r["昨收阳"]==0  # yesterday was bearish
        and r["收阳"]==1  # today bullish
        and r["收盘"]>r["昨开"]  # engulfs yesterday's open
        and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# N13 多方炮 (Two Yangs Sandwich One Yin)
for nm, vol in [("N13_多方炮_v1.3",1.3),("N13_多方炮_v1.5",1.5),("N13_多方炮_v1.8",1.8)]:
    reg(nm, "N13-多方炮",
        lambda r,*_,v=vol:
        r["前收阳"]==1 and r["昨收阳"]==0 and r["收阳"]==1
        and r["昨涨跌"]>-5  # yin not too bearish
        and r["收盘"]>r["昨高"]  # today breaks yesterday's high
        and r["成交量"]>r["均量"]*v)

# N14 强势股首次回踩10MA (Strong Stock First 10MA Dip)
for nm, dist_ma in [("N14_首踩10MA_d2",0.02),("N14_首踩10MA_d3",0.03)]:
    reg(nm, "N14-首踩10MA",
        lambda r,*_,d=dist_ma:
        r["近15日涨停次数"]>=1
        and abs(r["收盘"]/r["SMA10"]-1)<d
        and r["昨量"]<r["均量"]*0.8  # shrink
        and r["SMA10"]>r["SMA20"] and r["收阳"]==1)

# N15 均线金叉放量 (MA Golden Cross + Volume)
for nm, vol, pct in [("N15_金叉_v1.3_p1",1.3,1),("N15_金叉_v1.5_p2",1.5,2),("N15_金叉_v1.8_p1",1.8,1)]:
    reg(nm, "N15-均线金叉",
        lambda r,*_,v=vol,p=pct:
        r["SMA5上穿SMA20"]==1  # golden cross today
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N16 连续放量上攻 (Consecutive Volume & Price Rise)
for nm, vol, pct in [("N16_连攻_v1.2_p1",1.2,1),("N16_连攻_v1.3_p2",1.3,2)]:
    reg(nm, "N16-连续放量上攻",
        lambda r,*_,v=vol,p=pct:
        r["成交量"]>r["均量"]*v and r["昨量"]>r["均量"]*v  # 2-day volume > avg
        and r["涨跌幅"]>p and r["昨涨跌"]>0 and r["收阳"]==1)

# N17 窄幅整理末端突破 (Tight Range End Breakout)
for nm, amp, vol, pct in [("N17_末端突破_a10_v1.5_p2",0.10,1.5,2),("N17_末端突破_a12_v1.5_p3",0.12,1.5,3),("N17_末端突破_a8_v1.8_p2",0.08,1.8,2)]:
    reg(nm, "N17-末端突破",
        lambda r,*_,a=amp,v=vol,p=pct:
        r["10日高"]/r["10日低"]-1<a  # 10-day range very tight
        and r["收盘"]>r["10日高"]  # breakout
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p)

# N18 回踩20MA不破反弹 (Dip to 20MA Hold & Bounce)
for nm, vol, pct in [("N18_20MA撑_v1.2_p1",1.2,1),("N18_20MA撑_v1.3_p2",1.3,2)]:
    reg(nm, "N18-20MA支撑",
        lambda r,*_,v=vol,p=pct:
        r["收盘"]/r["SMA20"]-1<0.03 and r["收盘"]>r["SMA20"]  # near 20MA but above
        and r["昨收"]<r["SMA20"]  # yesterday was below 20MA
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p and r["SMA20"]>r["SMA20_5d"])

# N19 强势股高位整理不破 (Strong Stock High-Level Hold)
for nm, days, vol in [("N19_高位整理_d10_v1.3",10,1.3),("N19_高位整理_d15_v1.2",15,1.2)]:
    reg(nm, "N19-高位整理",
        lambda r,*_,d=days,v=vol:
        r["近15日涨停次数"]>=1  # had limit-up recently
        and r["过去20日实体振幅"]<=0.25  # consolidation
        and r["收盘"]/r["SMA20"]>0.95  # not broken down
        and r["收盘"]>r["5日高"]  # breaking short-term high
        and r["成交量"]>r["均量"]*v)

# N20 加速上涨 (Price Acceleration)
for nm, vol in [("N20_加速_v1.3",1.3),("N20_加速_v1.5",1.5),("N20_加速_v1.8",1.8)]:
    reg(nm, "N20-加速上涨",
        lambda r,*_,v=vol:
        r["涨跌幅"]>r["昨涨跌"] and r["昨涨跌"]>r["前涨跌"]  # accelerating
        and r["涨跌幅"]>2 and r["前涨跌"]>0 and r["昨涨跌"]>0
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N21 涨停后强势整理 (Post-Limit-Up Consolidation)
for nm, hold_pct in [("N21_涨停整理_h3",0.03),("N21_涨停整理_h5",0.05)]:
    reg(nm, "N21-涨停后整理",
        lambda r,*_,h=hold_pct:
        r["近15日涨停次数"]>=1
        and r["收盘"]/r["20日高"]>1-h  # near 20-day high
        and r["过去20日实体振幅"]<=0.20
        and r["收盘"]>r["SMA10"] and r["成交量"]>r["均量"]*1.2)

# N22 V型急跌急涨 (V-Shape Sharp Recovery)
for nm, dist, pct, vol in [("N22_V型_d10_p3_v1.5",0.10,3,1.5),("N22_V型_d15_p4_v1.8",0.15,4,1.8)]:
    reg(nm, "N22-V型反转",
        lambda r,*_,d=dist,p=pct,v=vol:
        r["收盘"]/r["过去40日最低价"]-1<d
        and r["涨跌幅"]>p and r["昨涨跌"]<-1  # yesterday dropped
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N23 倍量突破前高 (Double Volume Break Prev High)
for nm, vol_mult, lookback in [("N23_倍量突破_lb10",1.8,10),("N23_倍量突破_lb20",2.0,20)]:
    reg(nm, "N23-倍量突破前高",
        lambda r,*_,vm=vol_mult,lb=lookback:
        r["量比昨"]>vm and r["成交量"]>r["均量"]*1.5
        and r["收盘"]>(r["10日最高收"] if lb<=10 else r["过去60日最高收盘"])
        and r["涨跌幅"]>1.5 and r["收阳"]==1)

# N24 涨停+缩量回踩+再放量 (LimitUp→Shrink→ReExpand)
for nm, gap_days in [("N24_涨停缩量再放_d5",5),("N24_涨停缩量再放_d8",8)]:
    reg(nm, "N24-涨停缩量再放",
        lambda r,*_,gd=gap_days:
        r["近15日涨停次数"]>=1
        and r["昨量"]<r["均量"]*0.7 and r["量比昨"]>1.5  # yesterday shrink, today expand
        and r["涨跌幅"]>2 and r["收盘"]>r["SMA10"] and r["SMA20"]>r["SMA60"])

# N25 连续阳线后首阴反转失败再阳 (Post-Streak Yin Reversal Fail → Yang)
for nm, vol in [("N25_假摔_v1.2",1.2),("N25_假摔_v1.5",1.5)]:
    reg(nm, "N25-假摔洗盘",
        lambda r,*_,v=vol:
        r["前收阳"]==1 and r["昨收阳"]==0 and r["收阳"]==1  # yang→yin→yang
        and r["昨涨跌"]>-3  # yesterday wasn't a crash
        and r["收盘"]>r["昨高"]  # today recovered above yesterday's high
        and r["成交量"]>r["均量"]*v)

# ============================================================================
# ==== 3-DAY OPTIMIZED STRATEGIES (N26-N35) ==================================
# ============================================================================

# N26 强势突破连阳: break 5-day high + yesterday yang + volume surge
for nm, vol, pct in [("N26_突破连阳_v1.5_p2",1.5,2),("N26_突破连阳_v1.8_p2",1.8,2),("N26_突破连阳_v1.5_p3",1.5,3)]:
    reg(nm, "N26-强势突破连阳",
        lambda r,*_,v=vol,p=pct:
        r["收盘"]>r["5日高"] and r["昨收阳"]==1
        and r["成交量"]>r["均量"]*v and r["涨跌幅"]>p and r["收阳"]==1)

# N27 涨停次日接力: yesterday limit-up + small gap up + volume confirmation
for nm, gmin, gmax, vol in [("N27_涨停接力_g1-4_v1.8",1,4,1.8),("N27_涨停接力_g1-3_v2.0",1,3,2.0),("N27_涨停接力_g0-5_v1.5",0,5,1.5)]:
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
    reg(nm, "N27-涨停接力", _n27(gmin,gmax,vol))

# N28 缩量回踩后放量突破: yesterday shrink + today break yesterday's high + volume
for nm, yv, tv, pct in [("N28_缩量突破_y0.7_t1.5_p2",0.7,1.5,2),("N28_缩量突破_y0.6_t1.8_p1",0.6,1.8,1),("N28_缩量突破_y0.8_t1.5_p3",0.8,1.5,3)]:
    reg(nm, "N28-缩量后突破",
        lambda r,*_,yv=yv,tv=tv,p=pct:
        r["昨量"]<r["均量"]*yv and r["成交量"]>r["均量"]*tv
        and r["收盘"]>r["昨高"] and r["涨跌幅"]>p and r["收阳"]==1)

# N29 3日窄幅突破: 3-day tight range + breakout + volume
for nm, amp, vol in [("N29_3日突破_a3_v1.5",0.03,1.5),("N29_3日突破_a5_v1.8",0.05,1.8),("N29_3日突破_a3_v2.0",0.03,2.0)]:
    reg(nm, "N29-3日窄幅突破",
        lambda r,*_,a=amp,v=vol:
        r["5日高"]/r["5日低"]-1<a
        and r["收盘"]>r["5日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>1.5 and r["收阳"]==1)

# N30 连阳加速突破: 2+ consecutive yang + accelerating + volume
for nm, vol in [("N30_连阳加速_v1.3",1.3),("N30_连阳加速_v1.5",1.5),("N30_连阳加速_v1.8",1.8)]:
    reg(nm, "N30-连阳加速",
        lambda r,*_,v=vol:
        r["收阳"]==1 and r["昨收阳"]==1
        and r["涨跌幅"]>1 and r["昨涨跌"]>0
        and r["成交量"]>r["均量"]*v and r["昨量"]>r["均量"]*v
        and r["收盘"]>r["昨高"])  # breaks yesterday's high

# N31 强势股回踩5日线: strong stock + pullback to 5MA + volume shrink + bounce
for nm, dist_ma in [("N31_回踩5MA_d1.5",0.015),("N31_回踩5MA_d2",0.02)]:
    reg(nm, "N31-回踩5MA",
        lambda r,*_,d=dist_ma:
        r["近15日涨停次数"]>=1
        and abs(r["收盘"]/r["SMA5"]-1)<d and r["收盘"]>r["SMA5"]
        and r["昨量"]<r["均量"]*0.8 and r["成交量"]>r["均量"]*1.2
        and r["SMA5"]>r["SMA10"] and r["收阳"]==1)

# N32 跳空高开不回补: gap up + holds above yesterday's high all day
for nm, gap_pct, vol in [("N32_跳空高开_g2_v1.3",2.0,1.3),("N32_跳空高开_g3_v1.5",3.0,1.5)]:
    reg(nm, "N32-跳空高开",
        lambda r,*_,g=gap_pct,v=vol:
        r["昨开缺口"]>g and r["昨收阳"]==1
        and r["最低"]>r["昨高"]  # gap completely unfilled
        and r["成交量"]>r["均量"]*v and r["收阳"]==1)

# N33 放量反包阴线: yesterday yin + today yang engulfing + volume explosion
for nm, vol, pct in [("N33_放量反包_v1.5_p2",1.5,2),("N33_放量反包_v2.0_p3",2.0,3)]:
    reg(nm, "N33-放量反包",
        lambda r,*_,v=vol,p=pct:
        r["昨收阳"]==0 and r["收阳"]==1
        and r["收盘"]>r["昨开"] and r["开盘"]<r["昨收"]  # true engulfing
        and r["涨跌幅"]>p and r["成交量"]>r["均量"]*v)

# N34 突破20日高点放量: break 20-day high + volume > 2x avg
for nm, vol in [("N34_突破20日高_v2.0",2.0),("N34_突破20日高_v2.5",2.5),("N34_突破20日高_v3.0",3.0)]:
    reg(nm, "N34-突破20日高",
        lambda r,*_,v=vol:
        r["收盘"]>r["20日高"] and r["成交量"]>r["均量"]*v
        and r["涨跌幅"]>1 and r["收阳"]==1 and r["SMA5"]>r["SMA10"])

# N35 急跌后企稳反弹: sharp drop + stabilization + volume
for nm, drop, rise, vol in [("N35_急跌反弹_d3_r2_v1.5",-3,2,1.5),("N35_急跌反弹_d5_r3_v1.8",-5,3,1.8)]:
    reg(nm, "N35-急跌反弹",
        lambda r,*_,d=drop,ri=rise,v=vol:
        r["昨涨跌"]<d and r["涨跌幅"]>ri
        and r["成交量"]>r["均量"]*v and r["收阳"]==1
        and r["收盘"]>r["昨实体上沿"])  # close above yesterday's entity high

# ============================================================================
# Main
# ============================================================================

def run():
    n = len(S)
    print(f"终极PK: {n}个策略变体 | 持股{HOLD_DAYS}天 | 1136只股票")
    print("=" * 80)

    files = sorted([f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")])
    total = len(files)

    acc = {}
    for name, cat, _ in S:
        acc[name] = {"signals": 0, "wins": 0, "returns": [], "category": cat}

    need_cols = [
        "SMA5", "SMA10", "SMA20", "SMA60",
        "过去60日最高价", "过去60日最高收盘", "过去60日最低收盘",
        "过去40日最低价", "过去20日实体振幅", "过去20日平均成交量",
        "过去20日日均成交额", "近15日涨停次数", "SMA60_5日前",
    ]

    t0 = time.time()

    for fi, fname in enumerate(files, 1):
        raw = load_stock(os.path.join(HIST_CACHE_DIR, fname))
        if raw is None: continue

        df = prepare_hist_data(raw.copy())
        df = enrich(df)
        df = df.sort_values("日期").reset_index(drop=True)

        for i in range(65, len(df) - HOLD_DAYS - 1):
            row = df.iloc[i]
            if row[need_cols].isna().any(): continue
            if not check_secondary_filters(row): continue

            prev = df.iloc[i-1] if i >= 1 else None
            bp = df.iloc[i+1]["开盘"]
            sp = df.iloc[i+HOLD_DAYS]["收盘"]
            if pd.isna(bp) or pd.isna(sp) or bp <= 0: continue

            ret = (sp/bp - 1) * 100
            iw = ret > 0

            for name, cat, func in S:
                try:
                    if func(row, df, i, prev):
                        acc[name]["signals"] += 1
                        acc[name]["returns"].append(ret)
                        if iw: acc[name]["wins"] += 1
                except Exception:
                    pass

        if fi % 200 == 0:
            e = time.time() - t0
            sc = sum(d["signals"] for d in acc.values())
            print(f"  {fi}/{total} | {e:.0f}s | 剩余{e/fi*(total-fi):.0f}s | 信号{sc}")

    print(f"\n完成: {time.time()-t0:.0f}s")

    # Results
    results = []
    for name, d in acc.items():
        cnt = d["signals"]
        if cnt < 15: continue
        rets = d["returns"]
        w = d["wins"]
        wr = w/cnt*100
        avg_w = sum(r for r in rets if r>0)/max(1,sum(1 for r in rets if r>0))
        avg_l = sum(r for r in rets if r<=0)/max(1,sum(1 for r in rets if r<=0))
        results.append({
            "name": name, "cat": d["category"], "signals": cnt,
            "wins": w, "losses": cnt-w, "wr": wr,
            "avg": sum(rets)/len(rets), "med": sorted(rets)[len(rets)//2],
            "max_g": max(rets), "max_l": min(rets),
            "avg_w": avg_w, "avg_l": avg_l,
            "pl": abs(avg_w/avg_l) if avg_l!=0 else 99,
        })

    results.sort(key=lambda r: r["wr"], reverse=True)

    # Print ALL sorted by win rate
    print("\n" + "=" * 120)
    print(f"  全部策略胜率排名 - 持股{HOLD_DAYS}天 (从高到低)")
    print("=" * 120)
    hdr = f"{'排名':<4} {'策略变体':<42} {'分类':<22} {'信号':>6} {'胜率%':>8} {'平均%':>8} {'中位%':>8} {'盈亏比':>7}"
    print(hdr)
    print("-" * 118)
    for rank, r in enumerate(results, 1):
        tag = " [原版]" if "原版" in r["name"] else ""
        print(f"{rank:<4} {r['name']:<42} {r['cat']:<22} {r['signals']:>6} {r['wr']:>8.2f} {r['avg']:>8.2f} {r['med']:>8.2f} {r['pl']:>7.2f}{tag}")

    # TOP 25
    print("\n" + "=" * 80)
    print(f"  TOP 25 最高胜率 (持股{HOLD_DAYS}天)")
    print("=" * 80)
    for rank, r in enumerate(results[:25], 1):
        tag = ""
        if "原版" in r["name"]: tag = "[原版]"
        elif r["cat"].startswith("N"): tag = "[NEW!]"
        print(f"  {rank:>2}. {r['name']:<44} {r['cat']:<24} 胜率={r['wr']:.2f}%  信号={r['signals']}  平均={r['avg']:.2f}%{tag}")

    # Best per category
    print("\n" + "=" * 80)
    print("  各类别最佳")
    print("=" * 80)
    best_cat = {}
    for r in results:
        c = r["cat"]
        if c not in best_cat or r["wr"] > best_cat[c]["wr"]:
            best_cat[c] = r
    # Sort categories by their best win rate
    sorted_cats = sorted(best_cat.items(), key=lambda x: x[1]["wr"], reverse=True)
    for c, r in sorted_cats:
        print(f"  {c:<24} {r['name']:<44} 胜率={r['wr']:.2f}%  信号={r['signals']}")

    # Champion
    best = results[0]
    print("\n" + "=" * 80)
    print(f"  CHAMPION: {best['name']} ({best['cat']})")
    print(f"  胜率={best['wr']:.2f}%  信号={best['signals']}  平均收益={best['avg']:.2f}%  盈亏比={best['pl']:.2f}")
    print(f"  最大盈利={best['max_g']:.2f}%  最大亏损={best['max_l']:.2f}%")
    print("=" * 80)

    # Save
    os.makedirs("output/backtest", exist_ok=True)
    pd.DataFrame(results).to_excel(f"output/backtest/ultimate_hold{HOLD_DAYS}d.xlsx", index=False)
    print(f"\n结果已保存: output/backtest/ultimate_hold{HOLD_DAYS}d.xlsx")

    # Also save as CSV for easy reading
    pd.DataFrame(results).to_csv(f"output/backtest/ultimate_hold{HOLD_DAYS}d.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    run()
