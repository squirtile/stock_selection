"""
双色球 每日推荐脚本
====================
策略:
  红球: 热号加权 + 和值约束 + 奇偶/大小均衡 + 三区覆盖 + 排除纯连号
  蓝球: 热号 + 遗漏回补 + 奇偶交替
  投注: 每次推荐 1 注 (6红+1蓝) 为主推, 外加 4 注备选

运行时机: 开奖日 21:30 后运行 (fetch_ssq.py 先更新数据)
"""

import pandas as pd
import numpy as np
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from itertools import combinations
from datetime import datetime, timedelta
from collections import Counter

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(BASE_DIR, "..", "..")
sys.path.insert(0, PROJECT_ROOT)

try:
    from config import EMAIL_CONFIG
except ImportError:
    EMAIL_CONFIG = None

DATA_FILE = os.path.join(BASE_DIR, "双色球历史开奖数据.csv")
OUTPUT_FILE = os.path.join(BASE_DIR, "每日推荐.csv")

# ── 固定随机种子按日期 + 策略ID变化 ──
today_str = datetime.now().strftime("%Y%m%d")
np.random.seed(int(today_str) + 7)  # 与fc3d不同种子

# ═══════════════════════════════════════════
# 1. 加载历史数据
# ═══════════════════════════════════════════
if not os.path.exists(DATA_FILE):
    print(f"数据文件不存在: {DATA_FILE}")
    print("请先运行: python fc/ssq/fetch_ssq.py")
    sys.exit(1)

df = pd.read_csv(DATA_FILE, dtype={"期号": str})
if "开奖日期" in df.columns:
    df["开奖日期"] = pd.to_datetime(df["开奖日期"], errors="coerce")
df = df.sort_values("开奖日期").reset_index(drop=True)

total = len(df)
LOOKBACK = 200  # 近200期用于热度统计
recent = df.tail(LOOKBACK)

# ── 红球列 ──
RED_COLS = [f"红{i}" for i in range(1, 7)]

# ═══════════════════════════════════════════
# 2. 红球热度统计
# ═══════════════════════════════════════════
red_counter = Counter()
for col in RED_COLS:
    if col in recent.columns:
        red_counter.update(recent[col].dropna().astype(int))

# 蓝球热度
blue_counter = Counter(recent["蓝球"].dropna().astype(int)) if "蓝球" in recent.columns else Counter()

# ═══════════════════════════════════════════
# 3. 红球候选池筛选
# ═══════════════════════════════════════════
# 策略: 对1-33每个红球打分，选出Top候选

def score_red_ball(num: int, counter: Counter) -> float:
    """红球综合评分: 热度 + 近期偏好多因子"""
    hot_score = counter.get(num, 0) / max(counter.values(), default=1) * 50  # 50% 热度分

    # 奇偶均衡偏好: 根据近20期奇偶比调整
    last20 = df.tail(20)
    odd_cnt = 0
    for col in RED_COLS:
        if col in last20.columns:
            vals = last20[col].dropna().astype(int)
            odd_cnt += (vals % 2 == 1).sum()
    recent_odd_ratio = odd_cnt / 120  # 20期×6球
    if num % 2 == 1:
        parity_bonus = (0.5 - recent_odd_ratio) * 30  # 奇数偏多则减分, 偏少则加分
    else:
        parity_bonus = (recent_odd_ratio - 0.5) * 30

    # 大小均衡偏好
    big_cnt = sum(1 for col in RED_COLS if col in last20.columns
                  for v in last20[col].dropna().astype(int) if v >= 17)
    recent_big_ratio = big_cnt / 120
    if num >= 17:
        size_bonus = (0.5 - recent_big_ratio) * 20
    else:
        size_bonus = (recent_big_ratio - 0.5) * 20

    return hot_score + parity_bonus + size_bonus


all_red_scores = {n: score_red_ball(n, red_counter) for n in range(1, 34)}
sorted_reds = sorted(all_red_scores.items(), key=lambda x: x[1], reverse=True)

# Top 15 红球候选
TOP_RED_CANDIDATES = 15
red_candidates = [n for n, _ in sorted_reds[:TOP_RED_CANDIDATES]]
red_weights = np.array([all_red_scores[n] for n in red_candidates])
red_weights = np.exp(red_weights / 10)  # softmax增强差异
red_weights = red_weights / red_weights.sum()

# ═══════════════════════════════════════════
# 4. 生成红球组合 & 筛选
# ═══════════════════════════════════════════

def is_valid_combo(reds: tuple) -> bool:
    """验证红球组合有效性"""
    reds = sorted(reds)
    # 和值约束: 70~150 (覆盖~90%历史区间)
    if not (70 <= sum(reds) <= 150):
        return False
    # 跨度: 至少15
    if max(reds) - min(reds) < 15:
        return False
    # 奇偶比: 不全奇不全偶 (2:4, 3:3, 4:2)
    odd = sum(1 for r in reds if r % 2 == 1)
    if odd not in (2, 3, 4):
        return False
    # 三区至少覆盖2个区 (1-11, 12-22, 23-33)
    zones = set()
    for r in reds:
        if r <= 11: zones.add(1)
        elif r <= 22: zones.add(2)
        else: zones.add(3)
    if len(zones) < 2:
        return False
    # 排除纯连号 (6个连续)
    if reds[-1] - reds[0] == 5:
        return False
    return True


def generate_red_combos(n_candidates: int, n_picks: int) -> list:
    """从候选池中加权随机生成红球组合"""
    combos = []
    attempts = 0
    max_attempts = n_picks * 50

    # 预生成所有有效组合 (15选6 = 5005, 完全可枚举)
    all_combos = [c for c in combinations(sorted(red_candidates), 6) if is_valid_combo(c)]

    if not all_combos:
        # 候选池太小, 放宽条件
        print("  候选池无有效组合, 从全量33选6中随机生成...")
        full_candidates = sorted(all_red_scores.items(), key=lambda x: x[1], reverse=True)
        top30 = [n for n, _ in full_candidates[:30]]
        all_combos = [c for c in combinations(sorted(top30), 6) if is_valid_combo(c)]

    if not all_combos:
        return []

    # 给每个组合打分 (红球权重之和)
    combo_scores = np.array([sum(all_red_scores[r] for r in c) for c in all_combos])
    combo_probs = np.exp(combo_scores / 20)
    combo_probs = combo_probs / combo_probs.sum()

    picked_indices = np.random.choice(len(all_combos), size=min(n_picks, len(all_combos)),
                                      replace=False, p=combo_probs)
    return [all_combos[i] for i in picked_indices]


# ═══════════════════════════════════════════
# 5. 蓝球推荐
# ═══════════════════════════════════════════

def pick_blue_balls(n_picks: int) -> list:
    """蓝球推荐: 热度 + 遗漏回补 + 奇偶交替"""
    # 最近一期蓝球
    last_blue = int(df.iloc[-1]["蓝球"]) if "蓝球" in df.columns and pd.notna(df.iloc[-1].get("蓝球")) else None

    scores = {}
    for num in range(1, 17):
        hot = blue_counter.get(num, 0) / max(blue_counter.values(), default=1) * 40

        # 遗漏回补: 从最后往前找该号码
        miss = 0
        for i in range(len(df) - 1, -1, -1):
            if int(df.iloc[i]["蓝球"]) == num:
                miss = len(df) - 1 - i
                break
        miss_score = min(miss, 50) / 50 * 30

        # 奇偶交替: 如果最近是奇数, 偶数加分
        alt_score = 0
        if last_blue is not None:
            if num % 2 != last_blue % 2:
                alt_score = 30

        scores[num] = hot + miss_score + alt_score

    sorted_blues = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    blue_weights = np.array([s for _, s in sorted_blues])
    blue_weights = np.exp(blue_weights / 15)
    blue_weights = blue_weights / blue_weights.sum()

    picked = np.random.choice([n for n, _ in sorted_blues], size=n_picks,
                              replace=False, p=blue_weights)
    return picked.tolist()


# ═══════════════════════════════════════════
# 6. 生成推荐
# ═══════════════════════════════════════════
NUM_PICKS = 5
red_combos = generate_red_combos(TOP_RED_CANDIDATES, NUM_PICKS)
blue_picks = pick_blue_balls(NUM_PICKS)

# ── 红球候选热度 ──
print(f"\n红球 Top {TOP_RED_CANDIDATES} 候选 (从33个中评分):")
for i, (num, score) in enumerate(sorted_reds[:TOP_RED_CANDIDATES], 1):
    cnt = red_counter.get(num, 0)
    print(f"  {i:2d}. {num:02d}  (近{LOOKBACK}期出现{cnt}次, 评分{score:.1f})")

# ── 蓝球候选 ──
print(f"\n蓝球推荐池:")
for num in blue_picks:
    cnt = blue_counter.get(num, 0)
    miss = 0
    for i in range(len(df) - 1, -1, -1):
        if int(df.iloc[i]["蓝球"]) == num:
            miss = len(df) - 1 - i
            break
    print(f"  {num:02d}  近{LOOKBACK}期出现{cnt}次, 遗漏{miss}期")

# ── 今日推荐 ──
print(f"\n{'=' * 60}")
print(f"  🎱 双色球 每日推荐 - {datetime.now().strftime('%Y-%m-%d')}")
print(f"  {'=' * 60}")

picks = []
for rank in range(NUM_PICKS):
    reds = sorted(red_combos[rank]) if rank < len(red_combos) else []
    blue = blue_picks[rank] if rank < len(blue_picks) else None
    if not reds or blue is None:
        continue

    red_str = " ".join(f"{r:02d}" for r in reds)
    he = sum(reds)
    sp = max(reds) - min(reds)
    odd = sum(1 for r in reds if r % 2 == 1)

    marker = " ⭐主推" if rank == 0 else ""
    print(f"  {rank + 1}. 红球: [{red_str}]  蓝球: [{blue:02d}]{marker}")
    print(f"     和值{he} 跨度{sp} 奇偶{odd}:{6 - odd}")
    picks.append({"reds": reds, "blue": blue, "rank": rank + 1})

print(f"\n  💡 主推一注 (2元): 红[{picks[0]['reds']}] 蓝[{picks[0]['blue']:02d}]")
print(f"  💡 备选四注 (8元): 按上表2~5行")
print(f"\n  ⚠️ 提醒: 彩票期望为负，理性购彩。")

# ═══════════════════════════════════════════
# 7. 保存
# ═══════════════════════════════════════════
if picks:
    main = picks[0]
    output_date = datetime.now().strftime("%Y-%m-%d")
    output = {
        "日期": output_date,
        "红球": " ".join(f"{r:02d}" for r in main["reds"]),
        "蓝球": f"{main['blue']:02d}",
        "和值": sum(main["reds"]),
        "跨度": max(main["reds"]) - min(main["reds"]),
        "备选红球": " | ".join(" ".join(f"{r:02d}" for r in p["reds"]) for p in picks[1:5]),
        "备选蓝球": " ".join(f"{p['blue']:02d}" for p in picks[1:5]),
        "策略": f"红球Top{TOP_RED_CANDIDATES}评分+组合筛选+蓝球热度遗漏",
    }
    pd.DataFrame([output]).to_csv(
        OUTPUT_FILE, index=False, encoding="utf-8-sig", mode="a",
        header=not os.path.exists(OUTPUT_FILE),
    )
    print(f"\n已追加到 ssq/每日推荐.csv")


# ═══════════════════════════════════════════
# 8. 邮件发送
# ═══════════════════════════════════════════

def send_pick_email():
    """将今日推荐通过邮件发送"""
    if EMAIL_CONFIG is None:
        print("未配置邮件，跳过发送。")
        return

    cfg = EMAIL_CONFIG
    today = datetime.now().strftime("%Y-%m-%d")

    rows_html = ""
    for p in picks:
        reds_str = " ".join(f"{r:02d}" for r in p["reds"])
        blue_str = f"{p['blue']:02d}"
        he = sum(p["reds"])
        sp = max(p["reds"]) - min(p["reds"])
        odd = sum(1 for r in p["reds"] if r % 2 == 1)
        marker = " ⭐主推" if p["rank"] == 1 else ""
        rows_html += (
            f"<tr>"
            f"<td>{p['rank']}</td>"
            f"<td><b>{reds_str}</b></td>"
            f"<td><b>{blue_str}</b></td>"
            f"<td>{he}</td><td>{sp}</td><td>{odd}:{6 - odd}</td>"
            f"<td>{marker}</td>"
            f"</tr>\n"
        )

    body = f"""
    <h2>🎱 双色球 每日推荐 - {today}</h2>
    <hr>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#C0392B;color:white;">
            <th>#</th><th>红球 (6个)</th><th>蓝球</th><th>和值</th><th>跨度</th><th>奇偶</th><th></th>
        </tr>
        {rows_html}
    </table>
    <br>
    <p>💡 <b>主推一注 (2元)</b>: 红[{picks[0]['reds']}] 蓝[{picks[0]['blue']:02d}]</p>
    <hr>
    <p style="color:#888;font-size:12px;">
    红球策略: Top{TOP_RED_CANDIDATES}评分 + 和值70~150 + 跨度≥15 + 奇偶2:4/3:3/4:2 + 三区≥2<br>
    蓝球策略: 热度 + 遗漏回补 + 奇偶交替<br>
    ⚠️ 随机≠策略优势，彩票期望为负，理性购彩。
    </p>
    """

    msg = MIMEText(body, "html", "utf-8")
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]
    main_str = " ".join(f"{r:02d}" for r in picks[0]["reds"])
    msg["Subject"] = Header(f"双色球每日推荐 {today} - 红[{main_str}] 蓝[{picks[0]['blue']:02d}]", "utf-8")

    try:
        server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receiver"], msg.as_string())
        server.quit()
        print(f"📧 邮件已发送至 {cfg['receiver']}")
    except Exception as e:
        print(f"📧 邮件发送失败: {e}")


send_pick_email()
