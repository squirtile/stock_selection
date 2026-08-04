"""
简化版条件策略搜索 — 密度>1.92
===============================
三种高效策略, 不做嵌套循环
"""

import pandas as pd
import numpy as np
import os
from collections import Counter

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, '福彩3D历史开奖数据.csv')

df = pd.read_csv(DATA_FILE)
df['日期'] = pd.to_datetime(df['开奖日期'])
df['num'] = df['百位']*100 + df['十位']*10 + df['个位']
df = df.sort_values('日期').reset_index(drop=True)

n = len(df)
train_n = int(n * 0.7)
print(f"训练{train_n}期 | 测试{n-train_n}期")

# ═══════════════════════════════════════════
# 策略1: 极端遗漏狙击
# ═══════════════════════════════════════════
print("\n── 策略1: 极端遗漏单号狙击 ──")

best = {'dens': 0, 'info': ''}

for pos_name, pos_idx in [('百', 0), ('十', 1), ('个', 2)]:
    col = ['百位','十位','个位'][pos_idx]
    
    for miss_req in [60, 70, 80]:
        last_seen = {d: 9999 for d in range(10)}
        bets, wins = 0, 0
        
        for i in range(train_n):
            cur = df.iloc[i][col]
            for d in range(10):
                last_seen[d] += 1
            last_seen[cur] = 0
            
            # 找遗漏最久的数字
            most_missed = max(last_seen, key=last_seen.get)
            if last_seen[most_missed] >= miss_req:
                bets += 1
                # 买该数字在当前位置的10个号码 (0xx, 1xx, ... 9xx)
                if pos_name == '百':
                    candidates = {most_missed*100 + s*10 + g for s in range(10) for g in range(10)}
                elif pos_name == '十':
                    candidates = {b*100 + most_missed*10 + g for b in range(10) for g in range(10)}
                else:
                    candidates = {b*100 + s*10 + most_missed for b in range(10) for s in range(10)}
                
                if df.iloc[i]['num'] in candidates:
                    wins += 1
        
        if bets >= 5:
            hr = wins/bets
            dens = hr / (100/1000)
            if dens > best['dens']:
                best = {'dens': dens, 'info': f'{pos_name}位遗漏≥{miss_req}期 买100个号 出手{bets}次 命中{wins}次 命中率{hr*100:.1f}% 密度={dens:.2f}'}

for k, v in best.items():
    print(f"  {v}" if k == 'info' else f"  最佳密度: {v:.2f}")

# ═══════════════════════════════════════════
# 策略2: 形态过滤+热门
# ═══════════════════════════════════════════
print("\n── 策略2: 连续组三后买热门 ──")

best2 = {'dens': 0}

for lookback in [30, 50, 100]:
    for top_k in [5, 10, 20]:
        bets, wins = 0, 0
        
        for i in range(lookback, train_n):
            recent = df.iloc[i-lookback:i]
            # 条件: 最近期组三比例高
            g3_ratio = (recent['形态']=='组三').mean() if '形态' in df.columns else 0
            if g3_ratio >= 0.3:
                bets += 1
                hot = recent['num'].value_counts().head(top_k).index.tolist()
                if df.iloc[i]['num'] in hot:
                    wins += 1
        
        if bets >= 10:
            hr = wins/bets
            dens = hr / (top_k/1000)
            if dens > best2['dens']:
                best2 = {'dens': dens, 'lookback': lookback, 'top_k': top_k,
                         'bets': bets, 'wins': wins, 'hr': hr}

if best2['dens'] > 0:
    b2 = best2
    print(f"  窗口{b2['lookback']} Top{b2['top_k']} 出手{b2['bets']}次 命中{b2['wins']}次 "
          f"命中率{b2['hr']*100:.1f}% 密度={b2['dens']:.2f}")

# ═══════════════════════════════════════════
# 策略3: 冷热反差法
# ═══════════════════════════════════════════
print("\n── 策略3: 冷热反差法 ──")

best3 = {'dens': 0}
df['形态'] = '组六'
df.loc[(df['百位']==df['十位'])|(df['十位']==df['个位'])|(df['百位']==df['个位']), '形态'] = '组三'
df.loc[(df['百位']==df['十位'])&(df['十位']==df['个位']), '形态'] = '豹子'

for window in [100, 200, 300]:
    for top_k in [5, 10, 15]:
        bets, wins = 0, 0
        
        for i in range(window, train_n):
            recent = df.iloc[i-window:i]
            freq = recent['num'].value_counts().reindex(range(1000), fill_value=0)
            
            # 条件: 最近window期内, 最热与最冷差距极大
            hot_top = freq.nlargest(100).mean()
            cold_bottom = freq.nsmallest(100).mean()
            
            if hot_top - cold_bottom >= 3:  # 冷热分化明显
                bets += 1
                hottest = set(freq.nlargest(top_k).index)
                if df.iloc[i]['num'] in hottest:
                    wins += 1
        
        if bets >= 10:
            hr = wins/bets
            dens = hr / (top_k/1000)
            if dens > best3['dens']:
                best3 = {'dens': dens, 'window': window, 'top_k': top_k,
                         'bets': bets, 'wins': wins, 'hr': hr}

if best3['dens'] > 0:
    b3 = best3
    print(f"  窗口{b3['window']} Top{b3['top_k']} 出手{b3['bets']}次 命中{b3['wins']}次 "
          f"命中率{b3['hr']*100:.1f}% 密度={b3['dens']:.2f}")

# ═══════════════════════════════════════════
# 策略4: 暴力穷举 — 直接找最优单号
# ═══════════════════════════════════════════
print("\n── 策略4: 暴力穷举 — 在所有条件中找单期最优 ──")

best4 = {'dens': 0}

# 枚举所有可能的过滤条件组合
for form_allow in [[1], [2], [1,2]]:  # 1=组六,2=组三
    for he_lo, he_hi in [(7,20), (9,18), (10,17), (11,16)]:
        for span_lo, span_hi in [(2,8), (3,7), (4,7)]:
            for odd_cnt in [[1,2], [0,1,2,3]]:
                # 生成符合条件的号码集合
                candidates = set()
                for b in range(10):
                    for s in range(10):
                        for g in range(10):
                            num = b*100 + s*10 + g
                            he = b+s+g
                            sp = max(b,s,g)-min(b,s,g)
                            od = (b%2 + s%2 + g%2)
                            
                            # 形态判断
                            if b==s==g:
                                f = 3  # 豹子
                            elif b==s or s==g or b==g:
                                f = 2  # 组三
                            else:
                                f = 1  # 组六
                            
                            if f not in form_allow:
                                continue
                            if not (he_lo <= he <= he_hi):
                                continue
                            if not (span_lo <= sp <= span_hi):
                                continue
                            if od not in odd_cnt:
                                continue
                            
                            candidates.add(num)
                
                if len(candidates) < 10 or len(candidates) > 500:
                    continue
                
                # 在训练集上统计命中
                hits = df.iloc[:train_n]['num'].isin(candidates).sum()
                hr = hits / train_n
                dens = hr / (len(candidates)/1000)
                
                if dens > best4['dens'] and len(candidates) <= 200:
                    best4 = {'dens': dens, 'n_sel': len(candidates),
                             'form': form_allow, 'he': (he_lo, he_hi),
                             'span': (span_lo, span_hi), 'odd': odd_cnt,
                             'hr': hr}

if best4['dens'] > 0:
    b4 = best4
    form_map = {1:'组六', 2:'组三', 3:'豹子'}
    forms = [form_map[f] for f in b4['form']]
    print(f"  形态:{forms} 和值:{b4['he']} 跨度:{b4['span']} 奇偶:{b4['odd']}")
    print(f"  选号{b4['n_sel']}个 训练命中率{b4['hr']*100:.1f}% 密度={b4['dens']:.2f}")
    
    # 测试集
    candidates = set()
    for b in range(10):
        for s in range(10):
            for g in range(10):
                num = b*100+s*10+g
                he = b+s+g
                sp = max(b,s,g)-min(b,s,g)
                od = (b%2 + s%2 + g%2)
                if b==s==g: f=3
                elif b==s or s==g or b==g: f=2
                else: f=1
                if f in b4['form'] and b4['he'][0]<=he<=b4['he'][1] and \
                   b4['span'][0]<=sp<=b4['span'][1] and od in b4['odd']:
                    candidates.add(num)
    
    hits_test = df.iloc[train_n:]['num'].isin(candidates).sum()
    hr_test = hits_test / (n-train_n)
    dens_test = hr_test / (len(candidates)/1000)
    print(f"  测试集: 命中率{hr_test*100:.1f}% 密度={dens_test:.2f}")

# ═══════════════════════════════════════════
print("\n" + "=" * 50)
print("  总结")
print("=" * 50)

results = [
    ('极端遗漏', best.get('dens', 0)),
    ('组三追热', best2.get('dens', 0)),
    ('冷热反差', best3.get('dens', 0)),
    ('暴力穷举', best4.get('dens', 0)),
]
for name, dens in results:
    flag = '✅ >1.92' if dens > 1.92 else f'{dens:.2f}'
    print(f"  {name}: {flag}")

print(f"""
  ⚠️ 以上策略在训练集上找的最优参数。
  但如果放到测试集(后30%数据), 密度必然大幅退化。
  这就是过拟合的本质: 历史规律≠未来规律。
""")
