#!/usr/bin/env python3
"""
一次性转换分钟缓存：后复权 → 前复权。

原理：用日线前复权收盘价 / 分钟后复权收盘价 算出复权因子，
      将分钟 OHLC 全部乘以该因子。

用法：
  python3 convert_minute_adj.py          # 转换全部 30m + 60m
  python3 convert_minute_adj.py --dry-run # 只看不写
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np

STOCK_MINUTE_DIR = "cache/minute"
HIST_CACHE_DIR = "cache/hist"


def load_all_daily_closes() -> dict[str, float]:
    """批量加载所有日线缓存的最新收盘价（前复权），一次读完避免逐文件IO。"""
    price_map = {}
    if not os.path.exists(HIST_CACHE_DIR):
        return price_map

    files = [f for f in os.listdir(HIST_CACHE_DIR) if f.endswith("_bs.csv")]
    print(f"  📊 加载 {len(files)} 只股票日线收盘价...")

    for f in files:
        code = f.replace("_bs.csv", "")
        try:
            df = pd.read_csv(os.path.join(HIST_CACHE_DIR, f))
            if "收盘" in df.columns and len(df) > 0:
                price_map[code] = float(df["收盘"].iloc[-1])
        except Exception:
            continue

    print(f"  ✅ 加载完成: {len(price_map)} 只")
    return price_map


def convert_file(filepath: str, daily_prices: dict[str, float], dry_run: bool = False) -> str:
    """转换单个分钟文件，返回状态信息。"""
    try:
        df = pd.read_csv(filepath, dtype={"代码": str})
        if df.empty:
            return "空文件"

        last_close = float(df["收盘"].iloc[-1])
        if last_close <= 0:
            return "收盘价为0"

        basename = os.path.basename(filepath)
        code = basename.split("_")[0]

        daily_close = daily_prices.get(code)
        if daily_close is None or daily_close <= 0:
            return "无日线数据"

        factor = daily_close / last_close

        # 因子接近 1.0 说明已经是前复权
        if abs(factor - 1.0) < 0.002:
            return "已是前复权"

        if dry_run:
            return f"需转换: {last_close:.2f} → {daily_close:.2f} (×{factor:.4f})"

        for col in ["开盘", "最高", "最低", "收盘"]:
            if col in df.columns:
                df[col] = (pd.to_numeric(df[col], errors="coerce") * factor).round(2)

        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return f"已转换: {last_close:.2f} → {daily_close:.2f} (×{factor:.4f})"

    except Exception as e:
        return f"错误: {e}"


def main():
    parser = argparse.ArgumentParser(description="分钟数据后复权 → 前复权 批量转换")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际修改文件")
    args = parser.parse_args()

    if not os.path.exists(STOCK_MINUTE_DIR):
        print("❌ cache/minute/ 目录不存在")
        sys.exit(1)

    # 先批量加载日线收盘价
    daily_prices = load_all_daily_closes()
    if not daily_prices:
        print("❌ 没有找到日线数据")
        sys.exit(1)

    files = sorted([
        f for f in os.listdir(STOCK_MINUTE_DIR)
        if f.endswith(".csv") and any(f"_{freq}m" in f for freq in ["30", "60"])
    ])

    print(f"📁 分钟文件: {len(files)} 个")
    print("🔍 预览模式（--dry-run）" if args.dry_run else "✏️  转换模式")
    print("-" * 60)

    converted = 0
    skipped = 0
    errors = 0
    show_detail = True  # 前10个打印详情

    for i, f in enumerate(files):
        filepath = os.path.join(STOCK_MINUTE_DIR, f)
        status = convert_file(filepath, daily_prices, dry_run=args.dry_run)

        if "需转换" in status or "已转换" in status:
            converted += 1
            if show_detail and converted <= 10:
                print(f"  {f}: {status}")
        elif "已是前复权" in status:
            skipped += 1
        elif "错误" in status:
            errors += 1
            print(f"  ⚠️ {f}: {status}")
        else:
            skipped += 1

        if (i + 1) % 500 == 0:
            print(f"  ... 进度: {i+1}/{len(files)} | 转换: {converted} | 跳过: {skipped}")

    print("-" * 60)
    action = "需转换" if args.dry_run else "已转换"
    print(f"✅ {action}: {converted}  |  ⏭️ 跳过: {skipped}  |  ❌ 错误: {errors}")

    if args.dry_run and converted > 0:
        print("\n💡 确认无误后运行: python3 convert_minute_adj.py")
    elif not args.dry_run and converted > 0:
        print("\n🎉 转换完成！分钟数据现在是前复权了。")


if __name__ == "__main__":
    main()
