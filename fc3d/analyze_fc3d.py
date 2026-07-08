"""
福彩3D历史数据数学统计分析
从概率论与数理统计角度分析开奖号码
"""
import pandas as pd
import numpy as np
from scipy import stats
from collections import Counter
import os
import warnings
warnings.filterwarnings('ignore')

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, '福彩3D历史开奖数据.csv')

# ── 加载数据 ──
df = pd.read_csv(DATA_FILE)
df['开奖日期'] = pd.to_datetime(df['开奖日期'])
df = df.sort_values('开奖日期').reset_index(drop=True)

n = len(df)
digits = ['百位', '十位', '个位']

print("=" * 70)
print("  福彩3D 数学统计分析报告")
print("  数据范围:", df['开奖日期'].min().strftime('%Y-%m-%d'), "~", df['开奖日期'].max().strftime('%Y-%m-%d'))
print(f"  总期数: {n}")
print("=" * 70)

# ═══════════════════════════════════════════
# 1. 每位数字 0-9 均匀分布检验 (卡方检验)
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("1. 各位数字 0-9 分布均匀性 (卡方检验)")
print("─" * 50)

for col in digits:
    observed = df[col].value_counts().reindex(range(10), fill_value=0).sort_index()
    expected = np.full(10, n / 10)
    chi2, p_value = stats.chisquare(observed.values)
    
    print(f"\n  [{col}]")
    print(f"    分布: {dict(observed)}")
    print(f"    最多: {observed.idxmax()}({observed.max()}次)  最少: {observed.idxmin()}({observed.min()}次)")
    print(f"    卡方值: {chi2:.2f}  p值: {p_value:.4f}")
    if p_value > 0.05:
        print(f"    ✓ p > 0.05, 无法拒绝均匀分布假设 (符合随机)")
    else:
        print(f"    ✗ p <= 0.05, 显著偏离均匀分布!")

# ═══════════════════════════════════════════
# 2. 三位数值 (000-999) 分布分析
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("2. 三位数值 (000~999) 分布")
print("─" * 50)

df['三位数值'] = df['百位'] * 100 + df['十位'] * 10 + df['个位']

# 出现次数统计
value_counts = df['三位数值'].value_counts()
repeat_counts = value_counts.value_counts().sort_index()

print(f"  理论期望: 4676期, 1000个可能值, 每值期望 {n/1000:.1f} 次")
print(f"  实际出现过的不同值: {len(value_counts)} 个 / 1000")
print(f"  从未出现的值: {1000 - len(value_counts)} 个")
print(f"  出现次数分布:")
for k, v in repeat_counts.items():
    print(f"    出现{k}次的值: {v}个  (理论: 1000 * P(X={k}), λ={n/1000:.1f})")

# 泊松分布近似检验: 每个值出现次数是否服从 Poisson
max_repeat = df['三位数值'].value_counts().max()
print(f"  同一值最多出现: {max_repeat} 次")
# top重复
top_repeats = value_counts.head(10)
print(f"  重复最多的10个值:")
for val, cnt in top_repeats.items():
    print(f"    {val:03d} → {cnt} 次 (超出期望 {cnt - n/1000:+.1f})")

# ═══════════════════════════════════════════
# 3. 和值分布 (0-27, 理论均值=13.5, 标准差≈6.7)
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("3. 和值分布 (百+十+个)")
print("─" * 50)

df['和值'] = df['百位'] + df['十位'] + df['个位']
print(f"  理论均值: 13.5, 实测均值: {df['和值'].mean():.2f}")
print(f"  理论标准差: 6.71, 实测标准差: {df['和值'].std():.2f}")
print(f"  范围: {df['和值'].min()} ~ {df['和值'].max()}")

# 和值分布与理论对比
sum_dist = df['和值'].value_counts().sort_index()
# 理论: 每个和值的组合数 (三个骰子问题)
def sum_combinations(s):
    """0-27和值的三位数字组合数"""
    count = 0
    for a in range(10):
        for b in range(10):
            c = s - a - b
            if 0 <= c <= 9:
                count += 1
    return count

print(f"\n  和值分布 (实测 vs 理论):")
print(f"  {'和值':>4} {'组合数':>5} {'理论占比':>7} {'实测次数':>7} {'实测占比':>7} {'偏差':>6}")
for s in range(0, 28):
    combos = sum_combinations(s)
    theory_pct = combos / 1000 * 100
    actual = sum_dist.get(s, 0)
    actual_pct = actual / n * 100
    bias = actual_pct - theory_pct
    marker = " ***" if abs(bias) > 1.0 else ""
    if abs(bias) > 0.5 or s <= 2 or s >= 25:
        print(f"  {s:4d} {combos:5d} {theory_pct:6.2f}% {actual:7d} {actual_pct:7.2f}% {bias:+6.2f}%{marker}")

# 卡方检验和值分布
observed_sum = [sum_dist.get(i, 0) for i in range(28)]
expected_sum = [n * sum_combinations(i) / 1000 for i in range(28)]
# 合并小期望值
obs_merged, exp_merged = [], []
for o, e in zip(observed_sum, expected_sum):
    if len(obs_merged) > 0 and exp_merged[-1] < 5:
        obs_merged[-1] += o
        exp_merged[-1] += e
    else:
        obs_merged.append(o)
        exp_merged.append(e)
chi2_sum, p_sum = stats.chisquare(obs_merged, exp_merged)
print(f"\n  和值分布卡方检验: χ² = {chi2_sum:.2f}, p = {p_sum:.4f}")
print(f"  {'✓ 符合理论分布' if p_sum > 0.05 else '✗ 显著偏离理论分布!'}")

# ═══════════════════════════════════════════
# 4. 奇偶/大小形态
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("4. 奇偶与大小形态")
print("─" * 50)

df['奇偶型'] = ((df['百位']%2).astype(str) + (df['十位']%2).astype(str) + (df['个位']%2).astype(str))
df['大小型'] = ((df['百位']>=5).astype(int).astype(str) + (df['十位']>=5).astype(int).astype(str) + (df['个位']>=5).astype(int).astype(str))

# 奇偶: 8种形态, 每种理论概率=1/8=12.5%
print("  奇偶形态 (0=偶,1=奇):")
oe_dist = df['奇偶型'].value_counts()
for pat in sorted(oe_dist.index):
    cnt = oe_dist[pat]
    pct = cnt / n * 100
    bias = pct - 12.5
    print(f"    {pat}: {cnt:5d} ({pct:5.1f}%) 偏差 {bias:+5.1f}%")

# 大小: 8种形态
print("  大小形态 (0=小0-4,1=大5-9):")
bs_dist = df['大小型'].value_counts()
for pat in sorted(bs_dist.index):
    cnt = bs_dist[pat]
    pct = cnt / n * 100
    bias = pct - 12.5
    print(f"    {pat}: {cnt:5d} ({pct:5.1f}%) 偏差 {bias:+5.1f}%")

# ═══════════════════════════════════════════
# 5. 组三/组六/豹子
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("5. 组三/组六/豹子形态")
print("─" * 50)

df['形态'] = '组六'
df.loc[(df['百位']==df['十位']) | (df['十位']==df['个位']) | (df['百位']==df['个位']), '形态'] = '组三'
df.loc[(df['百位']==df['十位']) & (df['十位']==df['个位']), '形态'] = '豹子'

# 理论概率
# 豹子: 10/1000 = 1%
# 组三(不含豹子): 3个位置选2个相同 * 10种数字 * 9种不同 = C(3,2)*10*9 = 270 / 1000 = 27%
# 组六: 10*9*8 = 720 / 1000 = 72%
print(f"  {'形态':>4} {'理论概率':>8} {'实测次数':>7} {'实测概率':>7}")
theory = {'豹子': 1.0, '组三': 27.0, '组六': 72.0}
for form in ['豹子', '组三', '组六']:
    cnt = (df['形态'] == form).sum()
    pct = cnt / n * 100
    theory_pct = theory[form]
    print(f"  {form:>4} {theory_pct:7.1f}% {cnt:7d} {pct:7.1f}% 偏差 {pct-theory_pct:+.1f}%")

# ═══════════════════════════════════════════
# 6. 跨度分析 (max-min)
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("6. 跨度分析 (最大值-最小值)")
print("─" * 50)

df['跨度'] = df[digits].max(axis=1) - df[digits].min(axis=1)
span_dist = df['跨度'].value_counts().sort_index()
print(f"  平均跨度: {df['跨度'].mean():.2f} (理论≈4.5)")
for span in range(10):
    cnt = span_dist.get(span, 0)
    pct = cnt / n * 100
    print(f"    跨度{span}: {cnt}次 ({pct:.1f}%)")

# ═══════════════════════════════════════════
# 7. 位置间相关性
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("7. 位间相关性")
print("─" * 50)

for i, (c1, c2) in enumerate([('百位','十位'), ('十位','个位'), ('百位','个位')]):
    corr = df[c1].corr(df[c2])
    print(f"  {c1} vs {c2}: r = {corr:.4f} {'(几乎无相关性 ✓)' if abs(corr) < 0.05 else '(存在相关性!?)'}")

# ═══════════════════════════════════════════
# 8. 序列自相关 (滞后1-5期)
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("8. 自相关分析 (序列独立性)")
print("─" * 50)

for col in digits:
    print(f"  [{col}] 滞后自相关:")
    for lag in [1, 2, 3, 5]:
        autocorr = df[col].autocorr(lag=lag)
        flag = " ✓" if abs(autocorr) < 0.05 else ""
        print(f"    lag={lag}: r={autocorr:+.4f}{flag}")

# ═══════════════════════════════════════════
# 9. 连号与重复分析
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("9. 连号与重复模式")
print("─" * 50)

# 相邻期重复 (同一号码连续出现)
for col in digits:
    same = (df[col].diff() == 0).sum()
    print(f"  [{col}] 与上期相同: {same}次 ({same/n*100:.1f}%) 理论10%")

# 三位完全相同连续
same_all = (df['三位数值'].diff() == 0).sum()
print(f"  三位完全相同(连续): {same_all}次  (理论: {n*0.001:.1f}次)")

# 最长连续不重复天数
def max_consecutive_no_repeat(series):
    max_run = cur = 0
    for v in series:
        if v == 0:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    return max_run

# 对于每个数字，最长连续不出现
print(f"\n  每个数字最长连续遗漏(百位):")
for d in range(10):
    missing = (df['百位'] != d).astype(int)
    runs = missing.groupby((missing == 0).cumsum()).cumsum()
    max_miss = runs.max()
    print(f"    数字{d}: 最长连续 {max_miss} 期未出现")

# ═══════════════════════════════════════════
# 10. 游程检验 (Wald-Wolfowitz Runs Test)
# ═══════════════════════════════════════════
print("\n" + "─" * 50)
print("10. 游程检验 (Runs Test) — 检验序列随机性")
print("─" * 50)

def runs_test(series):
    """Wald-Wolfowitz runs test"""
    median = series.median()
    above = (series > median).astype(int)
    runs = 1 + (above.diff() != 0).sum()
    n1 = above.sum()
    n2 = len(above) - n1
    if n1 == 0 or n2 == 0:
        return 0, 1.0
    mean_runs = 2 * n1 * n2 / (n1 + n2) + 1
    std_runs = np.sqrt(2 * n1 * n2 * (2 * n1 * n2 - n1 - n2) / ((n1 + n2)**2 * (n1 + n2 - 1)))
    z = (runs - mean_runs) / std_runs
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return runs, p

for col in ['和值'] + digits:
    r, p = runs_test(df[col])
    print(f"  [{col}] 游程数: {r}, p值: {p:.4f} {'✓ 随机' if p > 0.05 else '✗ 非随机!'}")

# ═══════════════════════════════════════════
# 11. 综合结论
# ═══════════════════════════════════════════
print("\n" + "=" * 70)
print("  综合结论")
print("=" * 70)
print("""
  福彩3D本质上就是 000~999 的均匀随机抽样。从数学角度看:

  1. 每一位 (百/十/个) 0-9 的分布基本均匀，卡方检验大多通过
  2. 和值分布接近理论 (均值13.5, 峰在14附近)
  3. 组三/组六/豹子比例接近理论 27%/72%/1%
  4. 位间相关性极低 (近乎独立)
  5. 序列自相关不显著 (每期独立)
  6. 奇偶/大小形态分布均匀

  ⚠️ 重要认知:
  - 每次开奖是独立事件，历史数据不能预测未来
  - 所谓"冷号/热号"在统计上没有预测能力 (赌徒谬误)
  - 长期来看各数字频率趋近10%，但短期波动正常
  - 没有任何"规律"能击败随机性，期望收益始终为负
""")
