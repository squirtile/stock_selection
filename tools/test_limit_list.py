#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 Tushare limit_step 接口（连板天梯）
文档: https://tushare.pro/document/2?doc_id=356

返回字段: ts_code, name, trade_date, nums（连板次数）
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import disable_proxy, get_tushare_pro

print("🔗 连接 Tushare...")
disable_proxy()
pro = get_tushare_pro()

# 测试 limit_step
print("\n📡 调用 limit_step(trade_date='20260710') ...")
try:
    df = pro.limit_step(trade_date="20260710")
except Exception as e:
    print(f"❌ 调用失败: {e}")
    df = None

if df is not None and not df.empty:
    print(f"✅ 成功！共 {len(df)} 条数据\n")
    print("--- 列名 ---")
    print(df.columns.tolist())
    print("\n--- 连板分布 ---")
    if "nums" in df.columns:
        df["nums"] = pd.to_numeric(df["nums"], errors="coerce")
        dist = df["nums"].value_counts().sort_index(ascending=False)
        for n, cnt in dist.items():
            print(f"  {int(n)}板: {cnt} 只")
    print("\n--- 前20行（按连板降序） ---")
    df_sorted = df.sort_values("nums", ascending=False)
    print(df_sorted.head(20).to_string())
else:
    print("⚠️ 数据为空，可能非交易日")
    # 换个日期试试
    print("\n📡 尝试 limit_step(trade_date='20260709') ...")
    try:
        df2 = pro.limit_step(trade_date="20260709")
        if df2 is not None and not df2.empty:
            print(f"✅ 7月9日有数据，共 {len(df2)} 条")
            print(df2.head(10).to_string())
        else:
            print("⚠️ 7月9日也为空")
    except Exception as e2:
        print(f"❌ {e2}")

print("\n✅ 测试完成")
