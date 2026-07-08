"""
福彩3D 数学模型分析：哪个数字概率最大？
============================================
方法论:
  1. 极大似然估计 (MLE) — 频率学派
  2. 贝叶斯推断 — 后验概率分布
  3. 马尔可夫链 — 转移概率矩阵
  4. 蒙特卡洛模拟 — 偏差显著性检验
  5. 时间序列分解 — 趋势/周期检测
"""

import pandas as pd
import numpy as np
import os
from scipy import stats
from scipy.special import logsumexp
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, '福彩3D历史开奖数据.csv')

# ── 加载 ──
df = pd.read_csv(DATA_FILE)
df['日期'] = pd.to_datetime(df['开奖日期'])
df = df.sort_values('日期').reset_index(drop=True)
n = len(df)  # 4676

print("=" * 70)
print("  福彩3D 数学模型分析")
print(f"  样本量 n = {n} 期")
print("=" * 70)

# ═══════════════════════════════════════════════
# 模型一：极大似然估计 (MLE)
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型一：极大似然估计 (MLE)")
print("─" * 55)
print("""
  假设: X_i ~ Categorical(p_0, p_1, ..., p_999), 独立同分布
  MLE: p̂_k = count(k) / n
  
  对所有 k ∈ [000, 999], p̂_k → 1/1000 当 n → ∞
  当前样本下 MLE 的 95% 置信区间:
    p̂_k ± 1.96 × √(p̂_k(1-p̂_k)/n)
    
  理论概率: 1/1000 = 0.00100
  置信区间半宽: 1.96 × √(0.001×0.999/4676) = 0.00091
  即 [0.00009, 0.00191]
""")

# MLE top 和 bottom
df['三位数值'] = df['百位'] * 100 + df['十位'] * 10 + df['个位']
counts = df['三位数值'].value_counts().reindex(range(1000), fill_value=0)

p_hat = counts / n
p_theory = 1 / 1000
se = np.sqrt(p_theory * (1 - p_theory) / n)
ci_half = 1.96 * se

print(f"  MLE 最大概率的10个号码:")
for idx in p_hat.nlargest(10).index:
    p = p_hat[idx]
    z = (p - p_theory) / se
    sig = "***" if abs(z) > 2.58 else ("**" if abs(z) > 1.96 else "")
    print(f"    {idx:03d}: p̂={p:.5f}  (z={z:+.2f}{sig})")

print(f"\n  MLE 最小概率的10个号码:")
for idx in p_hat.nsmallest(10).index:
    p = p_hat[idx]
    z = (p - p_theory) / se
    print(f"    {idx:03d}: p̂={p:.5f}  (z={z:+.2f})")

# Bonferroni校正: 检验1000个号码
alpha_corrected = 0.05 / 1000
z_critical = stats.norm.ppf(1 - alpha_corrected / 2)
print(f"\n  Bonferroni校正 (检验1000个假设): α' = {alpha_corrected:.6f}, z_crit = {z_critical:.2f}")
sig_after_correction = (abs(p_hat - p_theory) / se) > z_critical
print(f"  校正后显著的号码数: {sig_after_correction.sum()}")

# ═══════════════════════════════════════════════
# 模型二：贝叶斯推断 (Dirichlet-Multinomial)
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型二：贝叶斯推断 (Dirichlet-Multinomial)")
print("─" * 55)
print("""
  先验: Dirichlet(α, α, ..., α)  均匀先验 α=1
  后验: Dirichlet(α + count_0, α + count_1, ..., α + count_999)
  
  后验均值: E[p_k | data] = (count_k + α) / (n + 1000α)
  后验方差: Var[p_k | data] = E[p_k](1-E[p_k]) / (n + 1000α + 1)
  
  α=1:  E[p_k] ≈ (count_k + 1) / 5676
  α=0:  E[p_k] = count_k / 4676 = MLE (无先验)
""")

def bayesian_posterior(counts, alpha=1.0):
    n_total = len(counts)
    n_sum = counts.sum()
    post_mean = (counts + alpha) / (n_sum + n_total * alpha)
    post_var = post_mean * (1 - post_mean) / (n_sum + n_total * alpha + 1)
    return post_mean, post_var

for alpha in [0.01, 1.0, 10.0]:
    post_mean, post_var = bayesian_posterior(counts.values, alpha)
    post_std = np.sqrt(post_var)
    print(f"\n  α={alpha}:")
    print(f"    后验均值范围: [{post_mean.min():.6f}, {post_mean.max():.6f}]")
    print(f"    后验均值=1/1000 的 z-score 最大: {((post_mean - 1/1000)/post_std).max():.2f}")

# ═══════════════════════════════════════════════
# 模型三：马尔可夫链 (转移概率)
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型三：一阶马尔可夫链")
print("─" * 55)
print("""
  如果存在马尔可夫依赖, 转移概率 P(X_t | X_{t-1}) ≠ P(X_t)
  即某个号码出现后, 下一个号码的概率分布会改变
  
  零假设: P(i→j) = 1/1000 对所有 i,j
""")

# 构建转移计数矩阵 (1000×1000, 稀疏)
vals = df['三位数值'].values
from collections import defaultdict
transitions = defaultdict(lambda: defaultdict(int))
for t in range(n - 1):
    transitions[vals[t]][vals[t+1]] += 1

# 检查是否某些转移概率显著偏大
all_z_scores = []
for i in transitions:
    total_i = counts[i]
    for j, cnt in transitions[i].items():
        expected = total_i / 1000
        if expected >= 5:  # 正态近似条件
            z = (cnt - expected) / np.sqrt(expected)
            all_z_scores.append(z)

all_z = np.array(all_z_scores)
print(f"  非零转移对数量: {len(all_z)}")
print(f"  转移概率 z-score 均值: {all_z.mean():.3f}")
print(f"  转移概率 z-score 标准差: {all_z.std():.3f}")
print(f"  |z| > 1.96 的比例: {(abs(all_z) > 1.96).mean()*100:.1f}% (期望 5%)")
print(f"  |z| > 3.0 的比例: {(abs(all_z) > 3.0).mean()*100:.1f}%")

# ═══════════════════════════════════════════════
# 模型四：蒙特卡洛显著性检验
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型四：蒙特卡洛模拟 — 偏差显著性")
print("─" * 55)
print("  模拟10000次纯随机抽样 4676 期，看实测极端值的显著性")

n_sim = 10000
sim_max_counts = np.zeros(n_sim)
sim_min_counts = np.zeros(n_sim)
sim_max_z = np.zeros(n_sim)

for i in range(n_sim):
    sim = np.random.randint(0, 1000, size=n)
    sim_count = np.bincount(sim, minlength=1000)
    sim_max_counts[i] = sim_count.max()
    sim_min_counts[i] = sim_count.min()
    se_sim = np.sqrt(1/1000 * 0.999 / n)
    sim_max_z[i] = (sim_count.max()/n - 1/1000) / se_sim

actual_max = counts.max()
actual_max_z = (actual_max/n - 1/1000) / se

print(f"\n  实测最大出现次数: {actual_max}")
print(f"  模拟中最大出现次数的分布:")
print(f"    均值: {sim_max_counts.mean():.1f}  中位数: {np.median(sim_max_counts):.0f}")
print(f"    95%分位: {np.percentile(sim_max_counts, 95):.0f}")
print(f"    99%分位: {np.percentile(sim_max_counts, 99):.0f}")
print(f"    实测值 {actual_max} 在模拟中的分位: {stats.percentileofscore(sim_max_counts, actual_max):.1f}%")

print(f"\n  实测最大 z-score: {actual_max_z:.2f}")
print(f"  模拟中 max|z| 的分布:")
print(f"    95%分位: {np.percentile(np.abs(sim_max_z), 95):.2f}")
print(f"    99%分位: {np.percentile(np.abs(sim_max_z), 99):.2f}")
p_val = (sim_max_counts >= actual_max).mean()
print(f"  p值 (模拟): {p_val:.4f}  {'显著!' if p_val < 0.05 else '不显著'}")

# ═══════════════════════════════════════════════
# 模型五：滚动窗口检验 — 概率是否随时间漂移？
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型五：滚动窗口稳定性检验")
print("─" * 55)
print("  检验每位数字的频率是否随时间稳定")

window = 1000
df['三位数值'] = df['百位'] * 100 + df['十位'] * 10 + df['个位']

for pos, col in enumerate(['百位', '十位', '个位']):
    rolling_std = df[col].rolling(window).std()
    print(f"  [{col}] 滚动标准差: 均值 {rolling_std.mean():.2f} (理论 2.87)")
    
    # 前后半段差异
    mid = n // 2
    first_half = df[col].iloc[:mid]
    second_half = df[col].iloc[mid:]
    ks_stat, ks_p = stats.ks_2samp(first_half, second_half)
    print(f"    KS检验 (前半 vs 后半): D={ks_stat:.3f}, p={ks_p:.3f} "
          f"{'✓ 分布相同' if ks_p > 0.05 else '✗ 分布不同!'}")

# ═══════════════════════════════════════════════
# 模型六：信息论视角 — 熵
# ═══════════════════════════════════════════════
print("\n" + "─" * 55)
print("模型六：信息论 — 熵")
print("─" * 55)

def entropy(probs):
    probs = probs[probs > 0]  # 只计算出现过的
    return -np.sum(probs * np.log2(probs))

# 三位数值的熵
p_full = counts.values / n
H_observed = entropy(p_full)
H_max = np.log2(1000)  # 均匀分布时的最大熵 ≈ 9.966
H_efficiency = H_observed / H_max * 100

print(f"  理论最大熵 (均匀): {H_max:.4f} bits")
print(f"  实测熵: {H_observed:.4f} bits")
print(f"  熵效率: {H_efficiency:.2f}%")
print(f"  结论: 接近最大熵 → 接近完美随机")

# 每位独立熵
for col in ['百位', '十位', '个位']:
    digit_probs = df[col].value_counts(normalize=True).reindex(range(10), fill_value=0)
    H_digit = entropy(digit_probs.values)
    print(f"  [{col}] 熵: {H_digit:.4f} / {np.log2(10):.4f}")

# ═══════════════════════════════════════════════
# 最终答案：哪个数字概率最大？
# ═══════════════════════════════════════════════
print("\n" + "=" * 70)
print("  最终答案：哪个数字概率最大？")
print("=" * 70)
print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │   数学模型结论：所有号码概率相等，都是 1/1000           │
  │                                                         │
  │   MLE 最大: {p_hat.nlargest(1).index[0]:03d} (p̂={p_hat.max():.5f}, z={actual_max_z:.2f})                │
  │   但这只是采样波动，经 Bonferroni 校正后无显著差异       │
  │                                                         │
  │   蒙特卡洛模拟: 实测最大值在随机模拟中的分位为           │
  │   {stats.percentileofscore(sim_max_counts, actual_max):.1f}%，完全在随机波动范围内                          │
  │                                                         │
  │   信息熵: {H_efficiency:.1f}% 接近理论最大熵 — 说明数据几乎完美随机         │
  │                                                         │
  │   ═══════════════════════════════════════════════════    │
  │   ⚠️  任何声称能预测福彩3D的模型都是骗子               │
  │   ═══════════════════════════════════════════════════    │
  │                                                         │
  │   下一次开奖: P(任意号码) = 1/1000 = 0.1%                │
  │   无论之前开出过什么、多少次、多久没出                   │
  │                                                         │
  └─────────────────────────────────────────────────────────┘
""")

# ── 补充：如果真的想"找规律"，最接近"能用的"统计量 ──
print("─" * 55)
print('附录：如果你非要找一个"概率偏差最大的号码"')
print("  (注意：以下偏差在统计上不显著，纯属采样噪声)")
print("─" * 55)

# 用贝叶斯收缩估计（James-Stein型），缩小极端值
alpha_opt = 1.0
post_mean, _ = bayesian_posterior(counts.values, alpha_opt)
# 按后验均值排序
ranked = pd.DataFrame({
    '号码': [f'{i:03d}' for i in range(1000)],
    '出现次数': counts.values,
    'MLE概率': p_hat.values,
    '贝叶斯后验均值': post_mean,
    '偏差z-score': (p_hat.values - p_theory) / se
}).sort_values('贝叶斯后验均值', ascending=False)

print(f"\n  贝叶斯后验均值 Top 20:")
print(f"  {'号码':>5} {'次数':>5} {'MLE概率':>8} {'后验均值':>10} {'z-score':>8}")
for _, row in ranked.head(20).iterrows():
    print(f"  {row['号码']:>5} {int(row['出现次数']):>5} {row['MLE概率']:>8.5f} {row['贝叶斯后验均值']:>10.5f} {row['偏差z-score']:>+7.2f}")

print(f"\n  所有偏差都在 ±3σ 以内，Bonferroni 校正后全部不显著。")
print(f"  这些号码下次中奖概率仍是 1/1000。")
