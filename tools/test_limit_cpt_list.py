#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 Tushare limit_cpt_list 接口（涨停最强板块统计）
文档: https://tushare.pro/document/2?doc_id=357

返回字段: ts_code, name, trade_date, days, up_stat, cons_nums, up_nums, pct_chg, rank
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import disable_proxy, get_tushare_pro

print("🔗 连接 Tushare...")
disable_proxy()
pro = get_tushare_pro()

# 测试 limit_cpt_list
print("\n📡 调用 limit_cpt_list(trade_date='20260710') ...")
try:
    df = pro.limit_cpt_list(trade_date="20260710")
except Exception as e:
    print(f"❌ 调用失败: {e}")
    df = None

if df is not None and not df.empty:
    print(f"✅ 成功！共 {len(df)} 个板块\n")
    print("--- 列名 ---")
    print(df.columns.tolist())
    print("\n--- 数据类型 ---")
    print(df.dtypes)
    print("\n--- 前20行（按排名） ---")
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.max_colwidth', 20)
    print(df.head(20).to_string())
    print(f"\n--- 统计 ---")
    print(f"  涨停家数范围: {df['up_nums'].min()} ~ {df['up_nums'].max()}")
    print(f"  涨跌幅范围:   {df['pct_chg'].min():.2f}% ~ {df['pct_chg'].max():.2f}%")
    print(f"  连板家数范围: {df['cons_nums'].min()} ~ {df['cons_nums'].max()}")
else:
    print("⚠️ 数据为空，换日期试试")
    for d in ["20260709", "20260708"]:
        print(f"\n📡 尝试 limit_cpt_list(trade_date='{d}') ...")
        try:
            df2 = pro.limit_cpt_list(trade_date=d)
            if df2 is not None and not df2.empty:
                print(f"✅ {d} 有数据，共 {len(df2)} 条")
                print(df2.head(10).to_string())
                break
            else:
                print(f"⚠️ {d} 为空")
        except Exception as e2:
            print(f"❌ {e2}")

print("\n✅ 测试完成")
