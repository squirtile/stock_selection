"""最终搜索：找出密度最大的单一策略"""
import pandas as pd, numpy as np
from itertools import product

df = pd.read_csv(r'd:\Vscode\股票\stock_selection\fc3d\福彩3D历史开奖数据.csv')
df['日期'] = pd.to_datetime(df['开奖日期'])
df['num'] = df['百位']*100 + df['十位']*10 + df['个位']
df = df.sort_values('日期').reset_index(drop=True)
n = len(df)
tn = int(n * 0.7)

# 预计算全部号码特征
all_nums = {}
for b, s, g in product(range(10), repeat=3):
    num = b*100 + s*10 + g
    he = b + s + g
    sp = max(b, s, g) - min(b, s, g)
    od = b%2 + s%2 + g%2
    bg = (b>=5) + (s>=5) + (g>=5)
    if b == s == g:
        f = 3
    elif b == s or s == g or b == g:
        f = 2
    else:
        f = 1
    all_nums[num] = (f, he, sp, od, bg)

tnums = df.iloc[:tn]['num']

# ===== 全天候过滤策略 =====
best_filter = {'d': 0, 't': 0, 'desc': ''}

for fm in [[1], [1, 2], [1, 2, 3]]:
    for hr in [(5, 22), (7, 20), (9, 18), (10, 17), (11, 16)]:
        for sr in [(1, 9), (2, 8), (3, 7), (4, 7)]:
            for odr in [(0, 3), (1, 2), (0, 2), (1, 3)]:
                for bgr in [(0, 3), (1, 2)]:
                    cand = set()
                    for num, (f, h, s, o, b) in all_nums.items():
                        if f in fm and hr[0] <= h <= hr[1]:
                            if sr[0] <= s <= sr[1]:
                                if odr[0] <= o <= odr[1]:
                                    if bgr[0] <= b <= bgr[1]:
                                        cand.add(num)
                    
                    k = len(cand)
                    if k < 5 or k > 600:
                        continue
                    
                    ht = tnums.isin(cand).sum()
                    hrt = ht / tn
                    dt = hrt / (k / 1000)
                    
                    hs = df.iloc[tn:]['num'].isin(cand).sum()
                    hrs = hs / (n - tn)
                    ds = hrs / (k / 1000)
                    
                    if dt > best_filter['d']:
                        best_filter = {
                            'd': dt, 't': ds,
                            'desc': f'形态={fm} 和值={hr} 跨度={sr} 奇偶={odr} 大小={bgr}',
                            'k': k, 'hr_train': hrt, 'hr_test': hrs
                        }

# ===== 条件触发策略 =====
best_cond = {'d': 0, 'desc': '', 'bets': 0, 'wins': 0}

# 1) 冷热分化触发
for w in [30, 50, 100, 200]:
    for tk in [5, 10, 20]:
        for threshold in [1, 2, 3]:
            B = W = 0
            for i in range(w, tn):
                fq = df.iloc[i-w:i]['num'].value_counts().reindex(range(1000), fill_value=0)
                if fq.nlargest(50).mean() - fq.nsmallest(50).mean() >= threshold:
                    B += 1
                    if df.iloc[i]['num'] in set(fq.nlargest(tk).index):
                        W += 1
            if B >= 10:
                d = (W / B) / (tk / 1000)
                if d > best_cond['d']:
                    best_cond = {'d': d, 'desc': f'冷热触发: 窗口{w} 分化≥{threshold} → 买Top{tk}热门',
                                 'bets': B, 'wins': W}

# 2) 极端和值后反转
for lo in [2, 3, 4]:
    for hi in [23, 24, 25]:
        for tk in [5, 10, 20]:
            B = W = 0
            for i in range(1, tn):
                prev_he = int(df.iloc[i-1]['百位']) + int(df.iloc[i-1]['十位']) + int(df.iloc[i-1]['个位'])
                if prev_he <= lo or prev_he >= hi:
                    B += 1
                    recent = df.iloc[max(0, i-100):i]
                    hot = set(recent['num'].value_counts().head(tk).index)
                    if df.iloc[i]['num'] in hot:
                        W += 1
            if B >= 10:
                d = (W / B) / (tk / 1000)
                if d > best_cond['d']:
                    best_cond = {'d': d, 'desc': f'和值反转: 上期≤{lo}或≥{hi} → 买Top{tk}热门',
                                 'bets': B, 'wins': W}

# 3) 连续组三后买组六热门
for consecutive in [2, 3]:
    for tk in [5, 10, 20]:
        B = W = 0
        for i in range(consecutive, tn):
            # 前N期全是组三
            prev_forms = []
            for j in range(1, consecutive+1):
                bv = int(df.iloc[i-j]['百位'])
                sv = int(df.iloc[i-j]['十位'])
                gv = int(df.iloc[i-j]['个位'])
                if bv==sv==gv:
                    prev_forms.append('豹子')
                elif bv==sv or sv==gv or bv==gv:
                    prev_forms.append('组三')
                else:
                    prev_forms.append('组六')
            
            if all(f in ['组三', '豹子'] for f in prev_forms):
                B += 1
                recent = df.iloc[max(0, i-100):i]
                # 买组六热门
                recent_g6 = recent
                hot = set(recent_g6['num'].value_counts().head(tk).index)
                if df.iloc[i]['num'] in hot:
                    W += 1
        if B >= 10:
            d = (W / B) / (tk / 1000)
            if d > best_cond['d']:
                best_cond = {'d': d, 'desc': f'连续{consecutive}期组三后 → 买Top{tk}热门',
                             'bets': B, 'wins': W}

# ===== 输出 =====
print("=" * 55)
print("  密度最大的策略")
print("=" * 55)

print(f"\n🏆 全天候过滤策略:")
print(f"   参数: {best_filter['desc']}")
print(f"   选号: {best_filter['k']} 个")
print(f"   训练: 命中率 {best_filter['hr_train']*100:.1f}%  密度 {best_filter['d']:.3f}")
print(f"   测试: 命中率 {best_filter['hr_test']*100:.1f}%  密度 {best_filter['t']:.3f}")

print(f"\n🏆 条件触发策略:")
print(f"   参数: {best_cond['desc']}")
print(f"   触发: {best_cond['bets']} 次  命中: {best_cond['wins']} 次")
print(f"   训练: 密度 {best_cond['d']:.3f}")

print(f"\n{'='*55}")
if best_cond['d'] > best_filter['d']:
    print(f"  冠军: 条件触发策略 (密度={best_cond['d']:.3f})")
    print(f"  但触发次数仅 {best_cond['bets']}/{tn} = {best_cond['bets']/tn*100:.1f}%")
    print(f"  大部分时间不出手")
else:
    print(f"  冠军: 全天候过滤 (密度={best_filter['d']:.3f})")
print(f"{'='*55}")
