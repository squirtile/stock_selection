#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 Tushare 资金流向三个接口：
  1. moneyflow_mkt_dc   - 大盘资金流向
  2. moneyflow_cnt_ths  - 同花顺概念板块资金流向
  3. moneyflow_ind_ths  - 同花顺行业资金流向
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import disable_proxy, get_tushare_pro

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 16)

print("🔗 连接 Tushare...")
disable_proxy()
pro = get_tushare_pro()

TD = "20260710"

# ---- 1. 大盘资金流向 ----
print(f"\n{'='*60}")
print(f"  1. moneyflow_mkt_dc (大盘资金流向)")
print(f"{'='*60}")
try:
    df1 = pro.moneyflow_mkt_dc(trade_date=TD)
    if df1 is not None and not df1.empty:
        print(f"✅ {len(df1)} 条")
        print("列名:", df1.columns.tolist())
        print(df1.to_string())
    else:
        print("⚠️ 空")
except Exception as e:
    print(f"❌ {e}")

# ---- 2. 概念板块资金流向 ----
print(f"\n{'='*60}")
print(f"  2. moneyflow_cnt_ths (概念板块资金流向)")
print(f"{'='*60}")
try:
    df2 = pro.moneyflow_cnt_ths(trade_date=TD)
    if df2 is not None and not df2.empty:
        print(f"✅ {len(df2)} 条")
        print("列名:", df2.columns.tolist())
        # 按净额排序 Top5
        if "net_amount" in df2.columns:
            top = df2.sort_values("net_amount", ascending=False).head(5)
            print("\n净流入 Top5:")
            print(top[["name", "pct_change", "net_amount", "lead_stock"]].to_string())
            bot = df2.sort_values("net_amount", ascending=True).head(5)
            print("\n净流出 Top5:")
            print(bot[["name", "pct_change", "net_amount", "lead_stock"]].to_string())
    else:
        print("⚠️ 空")
except Exception as e:
    print(f"❌ {e}")

# ---- 3. 行业资金流向 ----
print(f"\n{'='*60}")
print(f"  3. moneyflow_ind_ths (行业资金流向)")
print(f"{'='*60}")
try:
    df3 = pro.moneyflow_ind_ths(trade_date=TD)
    if df3 is not None and not df3.empty:
        print(f"✅ {len(df3)} 条")
        print("列名:", df3.columns.tolist())
        if "net_amount" in df3.columns:
            top = df3.sort_values("net_amount", ascending=False).head(5)
            print("\n净流入 Top5:")
            print(top[["industry", "pct_change", "net_amount", "lead_stock"]].to_string())
            bot = df3.sort_values("net_amount", ascending=True).head(5)
            print("\n净流出 Top5:")
            print(bot[["industry", "pct_change", "net_amount", "lead_stock"]].to_string())
    else:
        print("⚠️ 空")
except Exception as e:
    print(f"❌ {e}")

print(f"\n✅ 测试完成")
