#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
连板天梯 工具

功能：展示当日涨停股票连板晋级情况，按连板数从高到低排列。

数据来源：Tushare Pro → limit_step（全市场，不依赖本地缓存）

使用方式：
  python tools/limit_up_ladder.py                  # 默认：今日连板天梯
  python tools/limit_up_ladder.py --date 20260710  # 指定日期
  python tools/limit_up_ladder.py --min-nums 3     # 只看3板及以上
  python tools/limit_up_ladder.py --csv            # 导出CSV
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import disable_proxy, get_tushare_pro

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
LADDER_JSON = "limit_up_ladder.json"


def fetch_ladder(pro, trade_date: str) -> pd.DataFrame:
    """调用 limit_step 获取连板数据（非交易日不重试）"""
    print(f"📡 获取连板数据（{trade_date}）...")

    try:
        df = pro.limit_step(trade_date=trade_date)
    except Exception as e:
        print(f"❌ 接口调用失败: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        print("⚠️ 当日无连板数据（可能非交易日或无连板股）")
        return pd.DataFrame()

    df["nums"] = pd.to_numeric(df["nums"], errors="coerce")
    df = df.sort_values("nums", ascending=False).reset_index(drop=True)
    print(f"   ✅ {len(df)} 只连板股")
    return df


def print_ladder(df: pd.DataFrame, min_nums: int = 2):
    """打印连板天梯"""
    if df.empty:
        return

    df = df[df["nums"] >= min_nums]
    if df.empty:
        print(f"⚠️ 无 ≥{min_nums}板 的股票")
        return

    max_nums = int(df["nums"].max())
    width = 65

    print(f"\n{'=' * width}")
    print(f"  🪜 连板天梯  ({max_nums}板 → 2板)")
    print(f"{'=' * width}")

    # 从高到低逐板展示
    for n in range(max_nums, 1, -1):
        group = df[df["nums"] == n]
        if group.empty:
            continue

        # 图标：高位连板用🔥
        if n >= 6:
            icon = "🔥"
            bar = "█" * min(n, 10)
        elif n >= 4:
            icon = "🟠"
            bar = "▆" * n
        elif n >= 3:
            icon = "🟡"
            bar = "▃" * n
        else:
            icon = "🟢"
            bar = "▁" * n

        stocks = "、".join(
            f"{row['name']}({str(row['ts_code'])[:6]})"
            for _, row in group.iterrows()
        )

        print(f"\n  {icon} {n}板 [{len(group)}只] {bar}")
        print(f"     {stocks}")

    print(f"\n{'=' * width}")
    print(f"  合计: {len(df)} 只连板股")
    print(f"{'=' * width}")


def _df_to_ladder(df: pd.DataFrame) -> dict:
    """将 DataFrame 转为单个日期的 ladder 数据"""
    if df.empty:
        return {"total": 0, "max_nums": 0, "ladder": []}

    max_nums = int(df["nums"].max())
    ladder_groups = []
    for n in range(max_nums, 1, -1):
        group = df[df["nums"] == n]
        if group.empty:
            continue
        ladder_groups.append({
            "nums": n,
            "count": len(group),
            "stocks": [
                {"ts_code": r["ts_code"], "name": r["name"], "nums": int(r["nums"])}
                for _, r in group.iterrows()
            ]
        })

    return {
        "total": len(df),
        "max_nums": max_nums,
        "ladder": ladder_groups,
    }


def export_json(data_by_date: dict):
    """导出多天连板天梯 JSON 到 output/limit_up_ladder.json"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, LADDER_JSON)

    dates = sorted(data_by_date.keys(), reverse=True)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dates": dates,
        "data": data_by_date,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"📁 JSON 已导出: {filepath}（{len(dates)}天）")
    return filepath


def get_trade_date(pro, target_date: str = None, prev: bool = False) -> str:
    """获取有效交易日。prev=True 时获取 target_date 的前一个交易日。"""
    if target_date and not prev:
        return target_date

    if target_date and prev:
        # 从 target_date 往前找
        base = datetime.strptime(target_date, "%Y%m%d")
    else:
        base = datetime.now()

    start_offset = 1 if prev else 0

    for i in range(start_offset, start_offset + 14):
        test_date = (base - timedelta(days=i)).strftime("%Y%m%d")
        test_dt = datetime.strptime(test_date, "%Y%m%d")
        if test_dt.weekday() >= 5:
            continue
        try:
            df_cal = pro.trade_cal(exchange="SSE", start_date=test_date, end_date=test_date)
            if df_cal is not None and not df_cal.empty:
                if df_cal.iloc[0].get("is_open", 0) == 1:
                    return test_date
        except Exception:
            pass
        return test_date

    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(
        description="连板天梯 — 基于 Tushare limit_step",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/limit_up_ladder.py                     # 今日连板天梯
  python tools/limit_up_ladder.py --min-nums 3        # 只看3板及以上
  python tools/limit_up_ladder.py --date 20260708     # 指定日期
  python tools/limit_up_ladder.py --json              # 导出近2天JSON供小程序使用
        """,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="交易日 YYYYMMDD，默认最近交易日")
    parser.add_argument("--min-nums", type=int, default=2,
                        help="最低连板数，默认2（即≥2板）")
    parser.add_argument("--json", action="store_true",
                        help="导出近2天JSON到output/limit_up_ladder.json")

    args = parser.parse_args()

    # 初始化
    print("🔗 连接 Tushare...")
    disable_proxy()
    pro = get_tushare_pro()

    # 确定目标日期
    if args.date:
        target_dates = [args.date]
    elif args.json:
        # JSON 模式：拉最近2个交易日
        t1 = get_trade_date(pro)           # 今天/最近
        t2 = get_trade_date(pro, t1, prev=True)  # 前一天
        target_dates = [d for d in [t1, t2] if d]
        print(f"📅 目标日期: {target_dates}")
    else:
        target_dates = [get_trade_date(pro)]
        print(f"📅 交易日: {target_dates[0]}")

    # 拉数据
    console_df = None  # 控制台展示用（第一个日期）
    data_by_date = {}

    for i, td in enumerate(target_dates):
        df = fetch_ladder(pro, td)
        if i == 0:
            console_df = df
        if not df.empty:
            data_by_date[td] = _df_to_ladder(df)
        else:
            data_by_date[td] = {"total": 0, "max_nums": 0, "ladder": []}

    # 控制台展示
    if console_df is not None:
        print_ladder(console_df, min_nums=args.min_nums)

    # 导出 JSON
    if args.json:
        export_json(data_by_date)

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
