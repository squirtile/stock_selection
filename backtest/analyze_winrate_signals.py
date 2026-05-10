"""
综合评分分析：胜率 × 信号量 双重维度排序
从 all_hold_days_summary.csv 加载数据，按多种维度重排
"""
import pandas as pd
import numpy as np
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

df = pd.read_csv("output/backtest/all_hold_days_summary.csv")

# ============================================================
# 评分函数
# ============================================================

def wilson_lower(wr_pct, n, z=1.96):
    """Wilson score interval lower bound - 统计置信下界"""
    if n <= 0: return 0
    p = wr_pct / 100.0
    denom = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    margin = z * np.sqrt(p*(1-p)/n + z**2/(4*n*n)) / denom
    return (center - margin) * 100

def composite_score(wr, signals, alpha=0.3):
    """
    综合评分：胜率权重(1-alpha) + 信号归一化权重(alpha)
    alpha=0.3 表示信号量占30%权重
    """
    # 信号量取对数归一化（避免极端值）
    log_sig = np.log1p(signals)
    log_sig_norm = (log_sig - np.log1p(15)) / (np.log1p(10000) - np.log1p(15))
    log_sig_norm = np.clip(log_sig_norm, 0, 1)
    # 胜率也归一化到0-1
    wr_norm = wr / 100.0
    return (wr_norm * (1 - alpha) + log_sig_norm * alpha) * 100

# Add scores to dataframe
df["wilson_lower"] = df.apply(lambda r: wilson_lower(r["wr"], r["signals"]), axis=1)
df["composite"] = df.apply(lambda r: composite_score(r["wr"], r["signals"]), axis=1)
df["hold_days"] = df["hold_days"].astype(int)

# ============================================================
# 视图1: 全部排名 — 按胜率从高到低（显示信号数）
# ============================================================
print("=" * 120)
print("  全部策略排名 — 按胜率从高到低（全部列出）")
print("=" * 120)
all_by_wr = df.sort_values("wr", ascending=False).reset_index(drop=True)
for rank, (_, r) in enumerate(all_by_wr.iterrows(), 1):
    print(f"  {rank:>4}. 持仓{r['hold_days']:.0f}天 {r['name']:<50} {r['cat']:<24} "
          f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  平均={r['avg']:.2f}%  "
          f"Wilson下界={r['wilson_lower']:.2f}%  综合={r['composite']:.1f}")

# ============================================================
# 视图2: 按Wilson置信下界排名（统计上最可靠的策略）
# ============================================================
print("\n" + "=" * 120)
print("  按Wilson置信下界排名 — 胜率高 + 信号足的策略（TOP 50）")
print("=" * 120)
by_wilson = df.sort_values("wilson_lower", ascending=False).head(50).reset_index(drop=True)
for rank, (_, r) in enumerate(by_wilson.iterrows(), 1):
    print(f"  {rank:>3}. 持仓{r['hold_days']:.0f}天 {r['name']:<50} {r['cat']:<24} "
          f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  Wilson下界={r['wilson_lower']:.2f}%")

# ============================================================
# 视图3: 按综合评分排名
# ============================================================
print("\n" + "=" * 120)
print("  按综合评分排名（胜率70%权重 + 信号量30%权重）— TOP 50")
print("=" * 120)
by_comp = df.sort_values("composite", ascending=False).head(50).reset_index(drop=True)
for rank, (_, r) in enumerate(by_comp.iterrows(), 1):
    print(f"  {rank:>3}. 持仓{r['hold_days']:.0f}天 {r['name']:<50} {r['cat']:<24} "
          f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  综合={r['composite']:.1f}")

# ============================================================
# 视图4: 按信号量分层 — 每层按胜率排序
# ============================================================
for min_sig, label in [(50, ">=50信号"), (100, ">=100信号"), (200, ">=200信号"), (500, ">=500信号")]:
    tier = df[df["signals"] >= min_sig].sort_values("wr", ascending=False)
    print(f"\n{'='*120}")
    print(f"  {label} — 按胜率排序 (共{len(tier)}个)")
    print(f"{'='*120}")
    for rank, (_, r) in enumerate(tier.iterrows(), 1):
        print(f"  {rank:>3}. 持仓{r['hold_days']:.0f}天 {r['name']:<50} {r['cat']:<24} "
              f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  平均={r['avg']:.2f}%")

# ============================================================
# 视图5: 每个持仓天数的TOP 10（按综合评分）
# ============================================================
for hd in range(1, 11):
    hd_df = df[df["hold_days"] == hd].sort_values("composite", ascending=False).head(10)
    print(f"\n{'='*100}")
    print(f"  持仓{hd}天 TOP 10（按综合评分）")
    print(f"{'='*100}")
    for rank, (_, r) in enumerate(hd_df.iterrows(), 1):
        print(f"  {rank:>2}. {r['name']:<50} {r['cat']:<24} "
              f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  综合={r['composite']:.1f}")

# ============================================================
# 视图6: 胜率>50% 且 信号>100 的最佳策略
# ============================================================
print(f"\n{'='*120}")
print(f"  胜率≥50% 且 信号≥100 — 按胜率排序")
print(f"{'='*120}")
good = df[(df["wr"] >= 50) & (df["signals"] >= 100)].sort_values("wr", ascending=False)
for rank, (_, r) in enumerate(good.iterrows(), 1):
    print(f"  {rank:>3}. 持仓{r['hold_days']:.0f}天 {r['name']:<50} {r['cat']:<24} "
          f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  平均={r['avg']:.2f}%  盈亏比={r['pl']:.2f}")

# ============================================================
# 最优推荐：高胜率+高信号 的帕累托前沿
# ============================================================
print(f"\n{'='*120}")
print(f"  帕累托最优前沿（没人能在胜率和信号上都超过你）")
print(f"{'='*120}")

# Find Pareto frontier: a point dominates if both WR and signals are higher
pareto = []
all_points = [(r["wr"], r["signals"], r) for _, r in df.iterrows()]
all_points.sort(key=lambda x: (-x[0], -x[1]))  # sort by WR desc

current_max_signals = -1
for wr, sig, r in all_points:
    if sig > current_max_signals:
        pareto.append(r)
        current_max_signals = sig

for rank, r in enumerate(pareto, 1):
    print(f"  {rank:>2}. 持仓{int(r['hold_days'])}天 {r['name']:<50} {r['cat']:<24} "
          f"胜率={r['wr']:.2f}%  信号={int(r['signals'])}  平均={r['avg']:.2f}%")

# ============================================================
# 保存结果
# ============================================================
df.to_csv("output/backtest/all_hold_days_scored.csv", index=False, encoding="utf-8-sig")
print(f"\n评分结果已保存: output/backtest/all_hold_days_scored.csv")
