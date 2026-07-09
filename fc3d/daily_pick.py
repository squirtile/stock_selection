"""
福彩3D 每日推荐脚本
====================
策略: 组六 + 和值[7,20] + 跨度[4,7] + 奇偶不全同
基础候选: 348个号码 (命中率 ~35%)
每日精选: 从候选中按热度加权随机抽取 (每次运行结果不同)
"""

import pandas as pd
import numpy as np
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from itertools import product
from datetime import datetime, timedelta

# ── 路径 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(BASE_DIR, '..')
sys.path.insert(0, PROJECT_ROOT)
from config import EMAIL_CONFIG

DATA_FILE = os.path.join(BASE_DIR, '福彩3D历史开奖数据.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, '每日推荐.csv')

# ── 固定随机种子按日期变化: 同一天多次运行结果相同, 不同天结果不同 ──
today_str = datetime.now().strftime('%Y%m%d')
np.random.seed(int(today_str) + 42)

# ═══════════════════════════════════════════
# 1. 加载历史数据
# ═══════════════════════════════════════════
df = pd.read_csv(DATA_FILE)
df['日期'] = pd.to_datetime(df['开奖日期'])
df['num'] = df['百位'].astype(int)*100 + df['十位'].astype(int)*10 + df['个位'].astype(int)
df = df.sort_values('日期').reset_index(drop=True)

# ═══════════════════════════════════════════
# 2. 生成候选号码
# ═══════════════════════════════════════════
candidates = []
for b, s, g in product(range(10), repeat=3):
    num = b*100 + s*10 + g
    he = b + s + g
    sp = max(b, s, g) - min(b, s, g)
    od = b%2 + s%2 + g%2
    
    if b == s or s == g or b == g:
        continue
    if not (7 <= he <= 20):
        continue
    if not (4 <= sp <= 7):
        continue
    if od == 0 or od == 3:
        continue
    
    candidates.append(num)

cand_set = set(candidates)
print(f"基础候选: {len(candidates)} 个号码")
print(f"历史命中率: {df['num'].isin(cand_set).mean()*100:.1f}%")

# ═══════════════════════════════════════════
# 3. 热度加权随机抽取
# ═══════════════════════════════════════════

LOOKBACK = 200

recent = df.tail(LOOKBACK)
hot_counts = recent[recent['num'].isin(cand_set)]['num'].value_counts()

# 构建加权池: 每个候选号的权重 = 出现次数 + 1 (没出现过的也有机会)
weights = np.zeros(len(candidates))
for i, num in enumerate(candidates):
    weights[i] = hot_counts.get(num, 0) + 1  # +1 确保冷号也有概率

# 归一化
weights = weights / weights.sum()

# 加权随机抽取
num_picks = 5
picked_indices = np.random.choice(len(candidates), size=num_picks, replace=False, p=weights)
picked_nums = [candidates[i] for i in picked_indices]

# 显示热度排名 (供参考)
print(f"\n最近{LOOKBACK}期内，候选中最热的10个 (仅供参考):")
for num, cnt in hot_counts.head(10).items():
    b, s, g = num//100, (num//10)%10, num%10
    he = b + s + g
    sp = max(b,s,g) - min(b,s,g)
    od = b%2 + s%2 + g%2
    weight_pct = weights[candidates.index(num)] * 100
    print(f"  {num:03d} ({b}{s}{g})  出现{cnt}次  权重{weight_pct:.1f}%  和值{he} 跨度{sp} 奇偶{3-od}:{od}")

# ═══════════════════════════════════════════
# 4. 今日推荐 (加权随机)
# ═══════════════════════════════════════════
print(f"\n{'='*55}")
print(f"  🎲 随机加权抽选 (每天结果不同)")
print(f"  {'='*55}")

for rank, num in enumerate(picked_nums, 1):
    cnt = hot_counts.get(num, 0)
    b, s, g = num//100, (num//10)%10, num%10
    he = b + s + g
    sp = max(b,s,g) - min(b,s,g)
    marker = " ⭐主推" if rank == 1 else ""
    print(f"  {rank}. {num:03d} ({b}{s}{g})  出现{cnt}次  和值{he} 跨度{sp}{marker}")

today_pick = picked_nums[0]
b, s, g = today_pick//100, (today_pick//10)%10, today_pick%10

print(f"\n  💡 Top5 一起买 (10元): {[f'{n:03d}' for n in picked_nums]}")
print(f"  💡 买全部{len(candidates)}个: {len(candidates)*2}元/期 (命中率 ~35%)")
print(f"\n  ⚠️ 提醒: 随机≠策略优势，彩票期望为负。理性购彩。")

# ═══════════════════════════════════════════
# 5. 保存推荐
# ═══════════════════════════════════════════
output_date = datetime.now().strftime('%Y-%m-%d')
output = {
    '日期': output_date,
    '推荐号码': f'{today_pick:03d}',
    '百位': b, '十位': s, '个位': g,
    'Top5': ','.join([f'{n:03d}' for n in picked_nums]),
    '策略': '组六+和值7-20+跨度4-7+奇偶不全同→热度加权随机',
    '候选总数': len(candidates),
    '命中率': f"{df['num'].isin(cand_set).mean()*100:.1f}%",
}
pd.DataFrame([output]).to_csv(
    OUTPUT_FILE,
    index=False, encoding='utf-8-sig', mode='a',
    header=not os.path.exists(OUTPUT_FILE)
)
print(f"\n已追加到 fc3d/每日推荐.csv")

# ═══════════════════════════════════════════
# 6. 发送邮件
# ═══════════════════════════════════════════

def send_pick_email():
    """将今日推荐通过邮件发送"""
    cfg = EMAIL_CONFIG
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 构建 Top5 列表
    top5_rows = ""
    for rank, num in enumerate(picked_nums, 1):
        cnt = hot_counts.get(num, 0)
        b2, s2, g2 = num//100, (num//10)%10, num%10
        he2 = b2 + s2 + g2
        sp2 = max(b2,s2,g2) - min(b2,s2,g2)
        marker = " ⭐主推" if rank == 1 else ""
        top5_rows += f"<tr><td>{rank}</td><td><b>{num:03d}</b></td><td>{b2}{s2}{g2}</td><td>出现{cnt}次</td><td>和值{he2}</td><td>跨度{sp2}{marker}</td></tr>\n"
    
    body = f"""
    <h2>🎲 福彩3D 每日推荐 - {today}</h2>
    <hr>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background:#4472C4;color:white;">
            <th>排名</th><th>号码</th><th>直选</th><th>热度</th><th>和值</th><th>跨度</th>
        </tr>
        {top5_rows}
    </table>
    <br>
    <p>💡 <b>Top5 一起买 (10元)</b>：{[f'{n:03d}' for n in picked_nums]}</p>
    <p>💡 买全部 {len(candidates)} 个：{len(candidates)*2} 元/期（命中率 ~35%）</p>
    <hr>
    <p style="color:#888;font-size:12px;">
    策略：组六 + 和值[7,20] + 跨度[4,7] + 奇偶不全同 → 热度加权随机<br>
    历史命中率：{df['num'].isin(cand_set).mean()*100:.1f}% | 候选总数：{len(candidates)} 个<br>
    ⚠️ 随机≠策略优势，彩票期望为负，理性购彩。
    </p>
    """
    
    msg = MIMEText(body, "html", "utf-8")
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]
    msg["Subject"] = Header(f"福彩3D每日推荐 {today} - {' '.join([f'{n:03d}' for n in picked_nums])}", "utf-8")
    
    try:
        server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receiver"], msg.as_string())
        server.quit()
        print(f"📧 邮件已发送至 {cfg['receiver']}")
    except Exception as e:
        print(f"📧 邮件发送失败: {e}")

send_pick_email()
