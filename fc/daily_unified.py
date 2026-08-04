#!/usr/bin/env python3
"""
福彩每日统一推荐脚本
====================
每天早上 4:00 执行，同时预测福彩3D和双色球，合并发送一封邮件。

Crontab:
  0 4 * * * cd /home/ubuntu/code/stock/stock_selection && /usr/bin/python3 fc/daily_unified.py >> /var/log/fc_daily.log 2>&1
"""

import pandas as pd
import numpy as np
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from itertools import product, combinations
from datetime import datetime, timedelta
from collections import Counter

# ── 路径设置 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(BASE_DIR, "..")
sys.path.insert(0, PROJECT_ROOT)

try:
    from config import EMAIL_CONFIG
except ImportError:
    EMAIL_CONFIG = None
    print("⚠️ 未配置邮件, 仅打印结果")
    sys.exit(0)

# ── 随机种子：同一天多次运行结果相同 ──
today_str = datetime.now().strftime("%Y%m%d")

# ═══════════════════════════════════════════════════════════
#  Part 1: 福彩3D 预测
# ═══════════════════════════════════════════════════════════

def predict_fc3d():
    """返回: (top5_candidates, fc3d_html)"""
    np.random.seed(int(today_str) + 42)

    DATA_FC3D = os.path.join(BASE_DIR, "福彩3D历史开奖数据.csv")
    if not os.path.exists(DATA_FC3D):
        return None, "<p>福彩3D数据文件不存在</p>"

    df = pd.read_csv(DATA_FC3D)
    df["日期"] = pd.to_datetime(df["开奖日期"])
    df["num"] = df["百位"].astype(int)*100 + df["十位"].astype(int)*10 + df["个位"].astype(int)
    df = df.sort_values("日期").reset_index(drop=True)

    # 生成候选: 组六 + 和值[7,20] + 跨度[4,7] + 奇偶不全同
    candidates = []
    for b, s, g in product(range(10), repeat=3):
        num = b*100 + s*10 + g
        he = b + s + g
        sp = max(b, s, g) - min(b, s, g)
        od = b%2 + s%2 + g%2
        if b == s or s == g or b == g: continue
        if not (7 <= he <= 20): continue
        if not (4 <= sp <= 7): continue
        if od == 0 or od == 3: continue
        candidates.append(num)

    cand_set = set(candidates)
    hit_rate = df["num"].isin(cand_set).mean() * 100

    # 热度加权
    LOOKBACK = 200
    recent = df.tail(LOOKBACK)
    hot_counts = recent[recent["num"].isin(cand_set)]["num"].value_counts()
    weights = np.array([hot_counts.get(n, 0) + 1 for n in candidates])
    weights = weights / weights.sum()

    num_picks = 5
    picked_idx = np.random.choice(len(candidates), size=num_picks, replace=False, p=weights)
    picked = [candidates[i] for i in picked_idx]

    # 热度Top5
    hot5 = hot_counts.head(5)

    # 构建HTML
    rows = ""
    for rank, num in enumerate(picked, 1):
        cnt = hot_counts.get(num, 0)
        b, s, g = num//100, (num//10)%10, num%10
        he = b + s + g
        sp = max(b,s,g) - min(b,s,g)
        marker = " ⭐主推" if rank == 1 else ""
        rows += f"<tr><td>{rank}</td><td><b>{num:03d}</b></td><td>{b}{s}{g}</td><td>出现{cnt}次</td><td>和值{he}</td><td>跨度{sp}{marker}</td></tr>\n"

    html = f"""
    <h3 style="color:#E67E22;">🎲 福彩3D 推荐</h3>
    <p>策略: 组六 + 和值[7,20] + 跨度[4,7] + 奇偶不全同 → 近{LOOKBACK}期热度加权随机</p>
    <p>候选池: {len(candidates)}个 | 历史命中率: {hit_rate:.1f}%</p>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#E67E22;color:white;">
            <th>#</th><th>号码</th><th>直选</th><th>热度</th><th>和值</th><th>跨度</th>
        </tr>
        {rows}
    </table>
    <p>💡 <b>Top5一起买 (10元)</b>: {' '.join(f'{n:03d}' for n in picked)}</p>
    """
    return picked, html


# ═══════════════════════════════════════════════════════════
#  Part 2: 双色球 预测
# ═══════════════════════════════════════════════════════════

def predict_ssq():
    """返回: (picks_list, ssq_html)"""
    np.random.seed(int(today_str) + 7)

    DATA_SSQ = os.path.join(BASE_DIR, "ssq", "双色球历史开奖数据.csv")
    if not os.path.exists(DATA_SSQ):
        return None, "<p>双色球数据文件不存在</p>"

    df = pd.read_csv(DATA_SSQ, dtype={"期号": str})
    if "开奖日期" in df.columns:
        df["开奖日期"] = pd.to_datetime(df["开奖日期"], errors="coerce")
    df = df.sort_values("开奖日期").reset_index(drop=True)

    LOOKBACK = 200
    recent = df.tail(LOOKBACK)
    RED_COLS = [f"红{i}" for i in range(1, 7)]

    # 红球热度
    red_counter = Counter()
    for col in RED_COLS:
        if col in recent.columns:
            red_counter.update(recent[col].dropna().astype(int))

    # 蓝球热度
    blue_counter = Counter(recent["蓝球"].dropna().astype(int)) if "蓝球" in recent.columns else Counter()

    # 红球评分
    last20 = df.tail(20)
    odd_cnt = sum(1 for col in RED_COLS if col in last20.columns
                  for v in last20[col].dropna().astype(int) if v % 2 == 1)
    big_cnt = sum(1 for col in RED_COLS if col in last20.columns
                  for v in last20[col].dropna().astype(int) if v >= 17)
    recent_odd_ratio = odd_cnt / 120
    recent_big_ratio = big_cnt / 120

    def score_red(n):
        hot = red_counter.get(n, 0) / max(red_counter.values(), default=1) * 50
        parity = (0.5 - recent_odd_ratio) * 30 if n % 2 == 1 else (recent_odd_ratio - 0.5) * 30
        size = (0.5 - recent_big_ratio) * 20 if n >= 17 else (recent_big_ratio - 0.5) * 20
        return hot + parity + size

    all_scores = {n: score_red(n) for n in range(1, 34)}
    sorted_reds = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
    top_reds = [n for n, _ in sorted_reds[:15]]
    red_w = np.array([all_scores[n] for n in top_reds])
    red_w = np.exp(red_w / 10); red_w = red_w / red_w.sum()

    # 红球组合筛选
    def is_valid(reds):
        reds = sorted(reds)
        if not (70 <= sum(reds) <= 150): return False
        if max(reds) - min(reds) < 15: return False
        odd = sum(1 for r in reds if r % 2 == 1)
        if odd not in (2, 3, 4): return False
        zones = set()
        for r in reds:
            if r <= 11: zones.add(1)
            elif r <= 22: zones.add(2)
            else: zones.add(3)
        if len(zones) < 2: return False
        if reds[-1] - reds[0] == 5: return False
        return True

    all_combos = [c for c in combinations(sorted(top_reds), 6) if is_valid(c)]
    if not all_combos:
        top30 = [n for n, _ in sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:30]]
        all_combos = [c for c in combinations(sorted(top30), 6) if is_valid(c)]
    if not all_combos:
        return None, "<p>双色球：无有效组合</p>"

    combo_scores = np.array([sum(all_scores[r] for r in c) for c in all_combos])
    combo_prob = np.exp(combo_scores / 20); combo_prob = combo_prob / combo_prob.sum()
    red_picked = np.random.choice(len(all_combos), size=min(5, len(all_combos)), replace=False, p=combo_prob)

    # 蓝球推荐
    last_blue = int(df.iloc[-1]["蓝球"]) if pd.notna(df.iloc[-1].get("蓝球")) else None
    blue_scores = {}
    for num in range(1, 17):
        hot = blue_counter.get(num, 0) / max(blue_counter.values(), default=1) * 40
        miss = 0
        for i in range(len(df)-1, -1, -1):
            if int(df.iloc[i]["蓝球"]) == num: miss = len(df)-1-i; break
        miss_s = min(miss, 50) / 50 * 30
        alt = 30 if last_blue and num % 2 != last_blue % 2 else 0
        blue_scores[num] = hot + miss_s + alt

    sorted_blues = sorted(blue_scores.items(), key=lambda x: x[1], reverse=True)
    bw = np.array([s for _, s in sorted_blues]); bw = np.exp(bw / 15); bw = bw / bw.sum()
    bpicked = np.random.choice([n for n,_ in sorted_blues], size=5, replace=False, p=bw).tolist()

    # 构建HTML
    rows = ""
    picks = []
    for rank in range(5):
        reds = sorted(all_combos[red_picked[rank]])
        blue = bpicked[rank]
        he = sum(reds); sp = max(reds) - min(reds); odd = sum(1 for r in reds if r % 2 == 1)
        marker = " ⭐主推" if rank == 0 else ""
        red_str = " ".join(f"{r:02d}" for r in reds)
        rows += f"<tr><td>{rank+1}</td><td><b>{red_str}</b></td><td><b>{blue:02d}</b></td><td>{he}</td><td>{sp}</td><td>{odd}:{6-odd}{marker}</td></tr>\n"
        picks.append({"reds": reds, "blue": blue})

    html = f"""
    <h3 style="color:#C0392B;">🎱 双色球 推荐</h3>
    <p>策略: 红球Top15评分 + 和值70~150 + 跨度≥15 + 奇偶均衡 + 三区覆盖 | 蓝球热度+遗漏+交替</p>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#C0392B;color:white;">
            <th>#</th><th>红球 (6个)</th><th>蓝球</th><th>和值</th><th>跨度</th><th>奇偶</th>
        </tr>
        {rows}
    </table>
    <p>💡 <b>主推一注 (2元)</b>: 红[{' '.join(f'{r:02d}' for r in picks[0]['reds'])}] 蓝[{picks[0]['blue']:02d}]</p>
    """
    return picks, html


# ═══════════════════════════════════════════════════════════
#  Part 3: 合并发送邮件
# ═══════════════════════════════════════════════════════════

def send_unified_email(fc3d_html: str, ssq_html: str):
    """合并福彩3D和双色球推荐，发送一封邮件"""
    cfg = EMAIL_CONFIG
    today = datetime.now().strftime("%Y-%m-%d")

    body = f"""
    <html>
    <body style="font-family: 'Microsoft YaHei', Arial, sans-serif;">
    <h2>🎲 福彩每日统一推荐 - {today}</h2>
    <hr>
    {fc3d_html}
    <hr>
    {ssq_html}
    <hr>
    <p style="color:#888;font-size:12px;">
    ⚠️ 以上推荐由算法随机生成，不构成购彩建议。彩票期望为负，请理性购彩，量力而行。<br>
    脚本路径: fc/daily_unified.py | Crontab: 0 4 * * *
    </p>
    </body>
    </html>
    """

    msg = MIMEText(body, "html", "utf-8")
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]
    msg["Subject"] = Header(f"福彩每日推荐 {today} | 3D + 双色球", "utf-8")

    try:
        server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receiver"], msg.as_string())
        server.quit()
        print(f"✅ 合并邮件已发送至 {cfg['receiver']}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  福彩每日统一推荐 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 1. 福彩3D
    print("【1/2】生成福彩3D推荐...")
    fc3d_picks, fc3d_html = predict_fc3d()
    if fc3d_picks:
        for rank, num in enumerate(fc3d_picks, 1):
            print(f"  {rank}. {num:03d}" + (" ⭐主推" if rank == 1 else ""))
    else:
        print("  ❌ 福彩3D预测失败")
        fc3d_html = "<p>福彩3D数据不可用</p>"

    # 2. 双色球
    print("\n【2/2】生成双色球推荐...")
    ssq_picks, ssq_html = predict_ssq()
    if ssq_picks:
        for rank, p in enumerate(ssq_picks, 1):
            red_str = " ".join(f"{r:02d}" for r in p["reds"])
            print(f"  {rank}. 红[{red_str}] 蓝[{p['blue']:02d}]" + (" ⭐主推" if rank == 1 else ""))
    else:
        print("  ❌ 双色球预测失败")
        ssq_html = "<p>双色球数据不可用</p>"

    # 3. 发送合并邮件
    print()
    send_unified_email(fc3d_html, ssq_html)
    print("完成。")
