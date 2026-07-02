"""快速搜索密度最大策略"""
import pandas as pd, numpy as np
from itertools import product
import time

t0 = time.time()

df = pd.read_csv(r'd:\Vscode\股票\stock_selection\fc3d\福彩3D历史开奖数据.csv')
df['num'] = df['百位'].astype(int)*100 + df['十位'].astype(int)*10 + df['个位'].astype(int)
df = df.sort_values('开奖日期').reset_index(drop=True)
n = len(df)
tn = int(n * 0.7)

# 预计算
feat = {}
for b, s, g in product(range(10), repeat=3):
    num = b*100 + s*10 + g
    he = b + s + g
    sp = max(b, s, g) - min(b, s, g)
    od = b%2 + s%2 + g%2
    bg = (b>=5) + (s>=5) + (g>=5)
    if b == s == g: f = 3
    elif b == s or s == g or b == g: f = 2
    else: f = 1
    feat[num] = (f, he, sp, od, bg)

# 转为numpy加速
nums_arr = np.array([feat[i] for i in range(1000)])  # shape (1000, 5)
train_nums = df['num'].iloc[:tn].values

# 网格搜索
best = {'d': 0, 't': 0, 'desc': '', 'k': 0}
params = list(product(
    [[1], [1,2], [1,2,3]],
    [(5,22), (7,20), (9,18), (10,17), (11,16)],
    [(1,9), (2,8), (3,7), (4,7)],
    [(0,3), (1,2), (0,2), (1,3)],
    [(0,3), (1,2)]
))

for fm, hr, sr, odr, bgr in params:
    # 向量化筛选
    mask = np.isin(nums_arr[:, 0], fm)
    mask &= (nums_arr[:, 1] >= hr[0]) & (nums_arr[:, 1] <= hr[1])
    mask &= (nums_arr[:, 2] >= sr[0]) & (nums_arr[:, 2] <= sr[1])
    mask &= (nums_arr[:, 3] >= odr[0]) & (nums_arr[:, 3] <= odr[1])
    mask &= (nums_arr[:, 4] >= bgr[0]) & (nums_arr[:, 4] <= bgr[1])
    
    cand = set(np.where(mask)[0])
    k = len(cand)
    if k < 5 or k > 600:
        continue
    
    ht = np.isin(train_nums, list(cand)).sum()
    hrt = ht / tn
    dt = hrt / (k / 1000)
    
    hs = np.isin(df['num'].iloc[tn:].values, list(cand)).sum()
    hrs = hs / (n - tn)
    ds = hrs / (k / 1000)
    
    if dt > best['d']:
        best = {'d': dt, 't': ds, 'desc': f'形态={fm} 和值={hr} 跨度={sr} 奇偶={odr} 大小={bgr}', 'k': k,
                'hr_train': hrt, 'hr_test': hrs}

# 条件触发：冷热反差
bc = {'d': 0, 'desc': '', 'bets': 0, 'wins': 0}
for w in [30, 50, 100, 200]:
    for tk in [5, 10, 20]:
        B = W = 0
        for i in range(w, tn):
            fq = np.bincount(df['num'].iloc[i-w:i].values, minlength=1000)
            hot50 = np.sort(fq)[-50:].mean()
            cold50 = np.sort(fq)[:50].mean()
            if hot50 - cold50 >= 2:
                B += 1
                topk = set(np.argsort(fq)[-tk:])
                if df['num'].iloc[i] in topk:
                    W += 1
        if B >= 10:
            d = (W / B) / (tk / 1000)
            if d > bc['d']:
                bc = {'d': d, 'desc': f'冷热分化触发 | 窗口{w} Top{tk} | 出手{B}次 命中{W}次',
                      'bets': B, 'wins': W}

# 输出
print(f'(耗时 {time.time()-t0:.1f}s)')
print()
print(f'🏆 全天候过滤: 密度 {best["d"]:.3f}(训练) / {best["t"]:.3f}(测试)')
print(f'   参数: {best["desc"]}  |  {best["k"]}个号')
print(f'   命中率: {best["hr_train"]*100:.1f}%(训练) / {best["hr_test"]*100:.1f}%(测试)')
print()
print(f'🏆 条件触发:   密度 {bc["d"]:.3f}(训练)')
print(f'   策略: {bc["desc"]}')
print(f'   命中率: {bc["wins"]/bc["bets"]*100:.1f}%' if bc['bets'] > 0 else '   未触发')
print()
winner = '条件触发' if bc['d'] > best['d'] else '全天候过滤'
w_dens = max(bc['d'], best['d'])
print(f'👑 冠军: {winner} (密度={w_dens:.3f})')
