import pandas as pd
import os

base = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(os.path.dirname(base), "output", "backtest")

# Find latest hold_2d file
for f in sorted(os.listdir(output_dir), reverse=True):
    if "hold_2d" in f and f.endswith(".xlsx"):
        path = os.path.join(output_dir, f)
        print(f"读取: {f}")

        df1 = pd.read_excel(path, sheet_name="总体统计")
        print("\n=== 总体统计 ===")
        print(df1.to_string(index=False))

        df2 = pd.read_excel(path, sheet_name="按策略统计")
        if not df2.empty:
            df2 = df2.sort_values("胜率", ascending=False)
            print("\n=== 按策略统计（各策略独立胜率排名） ===")
            print(df2.to_string(index=False))

        # 也看一下交易明细中策略名称的分布
        df3 = pd.read_excel(path, sheet_name="交易明细")
        print(f"\n=== 交易明细 ===")
        print(f"总交易数: {len(df3)}")
        if "信号类型" in df3.columns:
            print("\n信号类型分布:")
            print(df3["信号类型"].value_counts().to_string())
        if "突破反转策略" in df3.columns:
            print("\n突破反转策略分布:")
            print(df3["突破反转策略"].value_counts().to_string())
        if "主升策略" in df3.columns:
            print("\n主升策略分布:")
            print(df3["主升策略"].value_counts().to_string())
        break
