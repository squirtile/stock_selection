"""
条件触发策略 — 只在"高概率时刻"出手
=====================================
核心: 不是每期都买, 而是等待特定形态出现后才下注
密度 = 条件命中率 / (选号数/1000) → 可以 >> 1.92
"""

import pandas as pd
import numpy as np
from itertools import product, combinations
from collections import Counter

df = pd.read_csv(r'd:\Vscode\股票\stock_selection\fc3d\福彩3D历史开奖数据.csv')
df['日期'] = pd.to_datetime(df['开奖日期'])
df['num'] = df['百位']*100 + df['十位']*10 + df['个位']
df['形态'] = '组六'
df.loc[(df['百位']==df['十位'])|(df['十位']==df['个位'])|(df['百位']==df['个位']), '形态'] = '组三'
df.loc[(df['百位']==df['十位'])&(df['十位']==df['个位']), '形态'] = '豹子'
df = df.sort_values('日期').reset_index(drop=True)

n = len(df)
train_n = int(n * 0.7)

print("=" * 65)
print("  条件触发策略 — 不是每期都买")
print(f"  思路: 等待特定形态→精选号码→只在此时出手")
print("=" * 65)

# ═══════════════════════════════════════════
# 策略A: 形态追热法
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("策略A：形态追热")
print("  条件: 最近N期中某形态出现M次以上")
print("  然后: 只买该形态下近期最热的K个号")

best_a_density = 0
best_a_config = None
best_a_detail = None

for lookback in [20, 30, 50, 100]:
    for min_count in [2, 3, 4, 5]:
        for top_k in [2, 3, 5, 8, 10]:
            # 训练集
            bets = 0
            wins = 0
            for i in range(lookback, train_n):
                recent = df.iloc[i-lookback:i]
                # 检查各形态出现次数
                for form in ['组六', '组三']:
                    form_count = (recent['形态'] == form).sum()
                    if form_count >= min_count:
                        # 触发! 买该形态下最近最热的top_k
                        form_recent = recent[recent['形态'] == form]
                        hot_nums = form_recent['num'].value_counts().head(top_k).index.tolist()
                        if len(hot_nums) > 0:
                            bets += 1
                            if df.iloc[i]['num'] in hot_nums:
                                wins += 1
                        break  # 每期最多触发一次
            
            if bets >= 10:  # 至少要有一定样本
                hit_rate = wins / bets
                density = hit_rate / (top_k / 1000)
                if density > best_a_density:
                    best_a_density = density
                    best_a_config = (lookback, min_count, top_k)
                    best_a_detail = (bets, wins, hit_rate)

if best_a_config:
    lb, mc, tk = best_a_config
    bets_t, wins_t, hr_t = best_a_detail

    # 测试集
    bets_test = 0
    wins_test = 0
    for i in range(lb, len(df) - train_n):
        idx = train_n + i
        recent = df.iloc[idx-lb:idx]
        for form in ['组六', '组三']:
            form_count = (recent['形态'] == form).sum()
            if form_count >= mc:
                form_recent = recent[recent['形态'] == form]
                hot_nums = form_recent['num'].value_counts().head(tk).index.tolist()
                if len(hot_nums) > 0:
                    bets_test += 1
                    if df.iloc[idx]['num'] in hot_nums:
                        wins_test += 1
                break

    hr_test = wins_test / bets_test if bets_test > 0 else 0
    dens_test = hr_test / (tk / 1000) if bets_test > 0 else 0
    
    print(f"  训练: 窗口{lb}, 触发{min_count}次, Top{tk}")
    print(f"    出手{bets_t}次, 命中{wins_t}次, 命中率{hr_t*100:.1f}%")
    print(f"    密度 = {hr_t:.3f} / ({tk}/1000) = {best_a_density:.2f}")
    print(f"  测试: 出手{bets_test}次, 命中{wins_test}次")
    print(f"    密度 = {dens_test:.2f}")

# ═══════════════════════════════════════════
# 策略B: 遗漏回补 — 等某个数字很久没出
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("策略B：极端遗漏回补")
print("  条件: 某个数字在百/十/个位连续N期不出现")
print("  然后: 只买包含该数字的组六号")

best_b_density = 0
best_b_config = None

for miss_threshold in [30, 40, 50, 60, 70]:
    for pos_col in ['百位', '十位', '个位']:
        for top_k in [5, 10, 20, 36]:  # 包含某数字的组六号约36个
            
            bets = 0
            wins = 0
            last_seen = {d: -miss_threshold for d in range(10)}
            
            for i in range(train_n):
                cur_digit = df.iloc[i][pos_col]
                
                # 更新最近出现
                for d in range(10):
                    last_seen[d] += 1
                last_seen[cur_digit] = 0
                
                # 检查是否有数字遗漏超过阈值
                for d in range(10):
                    if last_seen[d] >= miss_threshold:
                        # 触发! 买包含d的组六号
                        candidates = set()
                        for a in range(10):
                            for c in range(10):
                                if a != c and a != d and c != d:
                                    # 数字d在三个位置之一
                                    candidates.add(d*100 + a*10 + c)
                                    candidates.add(a*100 + d*10 + c)
                                    candidates.add(a*100 + c*10 + d)
                        
                        # 取top_k
                        candidates = list(candidates)[:top_k]
                        bets += 1
                        if df.iloc[i]['num'] in candidates:
                            wins += 1
                        break
            
            if bets >= 5:
                hit_rate = wins / bets
                density = hit_rate / (top_k / 1000)
                if density > best_b_density:
                    best_b_density = density
                    best_b_config = (miss_threshold, pos_col, top_k, bets, wins, hit_rate)

if best_b_config:
    mt, pc, tk, bets, wins, hr = best_b_config
    print(f"  训练: {pc}遗漏{mt}期, 买{tk}个号")
    print(f"    出手{bets}次, 命中{wins}次, 命中率{hr*100:.1f}%")
    print(f"    密度 = {best_b_density:.2f}")

# ═══════════════════════════════════════════
# 策略C: 和值反转 — 极端和值后反弹
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("策略C：极端和值反弹")
print("  条件: 上期和值极低(≤4)或极高(≥23)")
print("  然后: 买中等和值的组六号")

best_c_density = 0
best_c_config = None

for extreme_lo in [2, 3, 4]:
    for extreme_hi in [23, 24, 25]:
        for target_he_range in [(9,18), (10,17), (11,16)]:
            for top_k in [10, 20, 30, 50]:
                
                bets = 0
                wins = 0
                
                for i in range(1, train_n):
                    prev_he = df.iloc[i-1]['百位'] + df.iloc[i-1]['十位'] + df.iloc[i-1]['个位']
                    
                    if prev_he <= extreme_lo or prev_he >= extreme_hi:
                        # 生成和值在目标范围内的组六号码
                        candidates = []
                        for b in range(10):
                            for s in range(10):
                                for g in range(10):
                                    if b != s and s != g and b != g:
                                        he = b + s + g
                                        if target_he_range[0] <= he <= target_he_range[1]:
                                            candidates.append(b*100 + s*10 + g)
                        
                        candidates = list(set(candidates))[:top_k]
                        bets += 1
                        if df.iloc[i]['num'] in candidates:
                            wins += 1
                
                if bets >= 5:
                    hit_rate = wins / bets
                    density = hit_rate / (top_k / 1000)
                    if density > best_c_density:
                        best_c_density = density
                        best_c_config = (extreme_lo, extreme_hi, target_he_range, top_k, bets, wins, hit_rate)

if best_c_config:
    el, eh, thr, tk, bets, wins, hr = best_c_config
    print(f"  训练: 极端和值≤{el}或≥{eh}, 买和值{thr}的组六Top{tk}")
    print(f"    出手{bets}次, 命中{wins}次, 命中率{hr*100:.1f}%")
    print(f"    密度 = {best_c_density:.2f}")

# ═══════════════════════════════════════════
# 策略D: 精准狙击 — 特定序列模式
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("策略D：精准序列匹配")
print("  条件: 最近3期形态序列匹配特定模式")
print("  然后: 只买1个号")

best_d_density = 0
best_d_config = None

# 枚举所有3期形态序列
form_patterns = list(product(['组六', '组三', '豹子'], repeat=2))  # 2期历史

for pattern in form_patterns:
    for top_k in [1, 2, 3]:
        bets = 0
        wins = 0
        
        for i in range(2, train_n):
            prev_forms = (df.iloc[i-2]['形态'], df.iloc[i-1]['形态'])
            if prev_forms == pattern:
                # 训练中该模式后最常出现的号码
                pattern_hits = []
                for j in range(2, train_n):
                    if j >= i:  # 只用训练到i之前的数据
                        break
                    if (df.iloc[j-2]['形态'], df.iloc[j-1]['形态']) == pattern:
                        pattern_hits.append(df.iloc[j]['num'])
                
                if len(pattern_hits) >= 5:
                    hot = Counter(pattern_hits).most_common(top_k)
                    candidates = [h[0] for h in hot]
                    bets += 1
                    if df.iloc[i]['num'] in candidates:
                        wins += 1
        
        if bets >= 5:
            hit_rate = wins / bets
            density = hit_rate / (top_k / 1000)
            if density > best_d_density:
                best_d_density = density
                best_d_config = (pattern, top_k, bets, wins, hit_rate)

if best_d_config:
    pat, tk, bets, wins, hr = best_d_config
    print(f"  训练: 模式{pat}→买Top{tk}")
    print(f"    出手{bets}次, 命中{wins}次, 命中率{hr*100:.1f}%")
    print(f"    密度 = {best_d_density:.2f}")

# ═══════════════════════════════════════════
# 综合报告
# ═══════════════════════════════════════════
print("\n" + "=" * 65)
print("  四种策略汇总")
print("=" * 65)

strategies = [
    ('A 形态追热', best_a_density),
    ('B 极端遗漏', best_b_density),
    ('C 和值反弹', best_c_density),
    ('D 精准序列', best_d_density),
]

print(f"\n  {'策略':<15} {'训练密度':>10} {'>1.92?':>10}")
print(f"  {'─'*38}")
for name, dens in strategies:
    flag = '✅ 达标!' if dens > 1.92 else '❌'
    print(f"  {name:<15} {dens:>10.2f}  {flag:>10}")

print(f"""
  ═══════════════════════════════════════════
  ⚠️ 重要说明:
  
  密度>1.92的策略在训练集上一定能找到。
  但问题永远是:
  - 训练集上密度=3.0 → 测试集上密度=0.5
  - 因为任何条件触发策略都是过拟合
  
  这些策略的共同问题:
  1. 触发次数太少 (过拟合于少量样本)
  2. 测试集必然退化 (真实世界不会重复历史)
  3. 彩票期望为负的本质不变
  
  如果你真要用, 唯一建议:
  把每次想要下注的钱留起来,
  年终给自己买个礼物, 稳赚不赔。
  ═══════════════════════════════════════════
""")
