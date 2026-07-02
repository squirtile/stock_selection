"""
福彩3D 每日推荐脚本
====================
策略: 组六 + 和值[7,20] + 跨度[4,7] + 奇偶不全同
基础候选: 384个号码 (命中率 ~39%)
每日精选: 从候选中挑最近最热的1个 (2元一注)
"""

import pandas as pd
import numpy as np
from itertools import product
from datetime import datetime, timedelta

# ═══════════════════════════════════════════
# 1. 加载历史数据
# ═══════════════════════════════════════════
df = pd.read_csv(r'd:\Vscode\股票\stock_selection\fc3d\福彩3D历史开奖数据.csv')
df['日期'] = pd.to_datetime(df['开奖日期'])
df['num'] = df['百位'].astype(int)*100 + df['十位'].astype(int)*10 + df['个位'].astype(int)
df = df.sort_values('日期').reset_index(drop=True)

# ═══════════════════════════════════════════
# 2. 生成384个候选号码
# ═══════════════════════════════════════════
candidates = []
for b, s, g in product(range(10), repeat=3):
    num = b*100 + s*10 + g
    he = b + s + g
    sp = max(b, s, g) - min(b, s, g)
    od = b%2 + s%2 + g%2
    
    # 组六判断
    if b == s or s == g or b == g:
        continue  # 不是组六
    # 和值 [7, 20]
    if not (7 <= he <= 20):
        continue
    # 跨度 [4, 7]
    if not (4 <= sp <= 7):
        continue
    # 奇偶不全同 (不是 0或3)
    if od == 0 or od == 3:
        continue
    
    candidates.append(num)

cand_set = set(candidates)
print(f"基础候选: {len(candidates)} 个号码")
print(f"历史命中率: {df['num'].isin(cand_set).mean()*100:.1f}%")

# ═══════════════════════════════════════════
# 3. 从候选中选今日最热的1个
# ═══════════════════════════════════════════

# 最近N期内候选中各号码的出现频率
LOOKBACK = 200  # 看最近200期

recent = df.tail(LOOKBACK)
# 只统计候选中的号码
hot_in_candidates = recent[recent['num'].isin(cand_set)]['num'].value_counts()

print(f"\n最近{LOOKBACK}期内，384候选中最热的10个:")
for num, cnt in hot_in_candidates.head(10).items():
    b, s, g = num//100, (num//10)%10, num%10
    he = b + s + g
    sp = max(b,s,g) - min(b,s,g)
    od = b%2 + s%2 + g%2
    print(f"  {num:03d} ({b}{s}{g})  出现{cnt}次  和值{he} 跨度{sp} 奇偶{3-od}:{od}")

# 今日推荐: 最热的一个
today_pick = hot_in_candidates.index[0] if len(hot_in_candidates) > 0 else candidates[0]
b, s, g = today_pick//100, (today_pick//10)%10, today_pick%10

print(f"\n{'='*50}")
print(f"  🎯 今日推荐 (2元一注)")
print(f"  {'='*50}")
print(f"  号码: {today_pick:03d}")
print(f"  百位: {b}  十位: {s}  个位: {g}")
print(f"  和值: {b+s+g}  跨度: {max(b,s,g)-min(b,s,g)}")
print(f"  最近{LOOKBACK}期出现: {hot_in_candidates.iloc[0]} 次")
print(f"  {'='*50}")

# ═══════════════════════════════════════════
# 4. 如果想多买几注
# ═══════════════════════════════════════════
print(f"\n💡 如果想多买:")
print(f"  买Top5热门: {hot_in_candidates.head(5).index.tolist()} (10元)")
print(f"  买全部384个: 768元/期 (命中率 ~39%)")
print(f"\n⚠️ 提醒: 这只是统计游戏，彩票期望为负。理性购彩。")

# ═══════════════════════════════════════════
# 5. 保存推荐
# ═══════════════════════════════════════════
today_str = datetime.now().strftime('%Y-%m-%d')
output = {
    '日期': today_str,
    '推荐号码': f'{today_pick:03d}',
    '百位': b, '十位': s, '个位': g,
    '策略': '组六+和值7-20+跨度4-7+奇偶不全同→选最热',
    '候选总数': len(candidates),
    '命中率': f"{df['num'].isin(cand_set).mean()*100:.1f}%",
}
pd.DataFrame([output]).to_csv(
    r'd:\Vscode\股票\stock_selection\fc3d\每日推荐.csv',
    index=False, encoding='utf-8-sig', mode='a',
    header=not pd.io.common.file_exists(r'd:\Vscode\股票\stock_selection\fc3d\每日推荐.csv')
)
print(f"\n已追加到 fc3d/每日推荐.csv")
