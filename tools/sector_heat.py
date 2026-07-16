#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
板块热度/涨跌排名 工具

功能：基于 Tushare limit_cpt_list 接口，获取涨停最强板块统计数据。
      --json 模式拉取近一周数据，并汇总统计强势板块。

数据来源：Tushare Pro → limit_cpt_list（涨停最强板块统计）

使用方式：
  python tools/sector_heat.py                      # 今日板块热度排名
  python tools/sector_heat.py --date 20260710      # 指定日期
  python tools/sector_heat.py --json               # 导出近一周JSON + 汇总统计
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_loader import disable_proxy, get_tushare_pro, get_latest_trade_date

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
SECTOR_JSON = "sector_heat.json"
WEEK_DAYS = 5


def fetch_sectors(pro, trade_date: str) -> pd.DataFrame:
    """调用 limit_cpt_list 获取板块热度数据"""
    try:
        df = pro.limit_cpt_list(trade_date=trade_date)
    except Exception as e:
        print(f"  ❌ {trade_date} 接口失败: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        print(f"  ⚠️ {trade_date} 无数据")
        return pd.DataFrame()

    for col in ["up_nums", "cons_nums", "pct_chg", "rank", "days"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _sector_list(df: pd.DataFrame) -> list:
    """DataFrame 转为板块列表"""
    if df.empty:
        return []
    sectors = []
    for _, r in df.iterrows():
        sectors.append({
            "ts_code": r.get("ts_code", ""),
            "name": r.get("name", ""),
            "up_nums": int(r.get("up_nums", 0) or 0),
            "pct_chg": round(float(r.get("pct_chg", 0) or 0), 2),
            "cons_nums": int(r.get("cons_nums", 0) or 0),
            "up_stat": str(r.get("up_stat", "")),
            "days": int(r.get("days", 0) or 0),
            "rank": int(r.get("rank", 0) or 0),
        })
    return sectors


def build_summary(data_by_date: dict) -> list:
    """汇总一周：按板块名聚合，计算出现次数、平均排名、平均涨停家数、平均涨跌幅"""
    stats = defaultdict(lambda: {"count": 0, "ranks": [], "up_nums": [], "pct_chg": []})

    for day_data in data_by_date.values():
        for s in day_data.get("sectors", []):
            name = s["name"]
            stats[name]["count"] += 1
            stats[name]["ranks"].append(s["rank"])
            stats[name]["up_nums"].append(s["up_nums"])
            stats[name]["pct_chg"].append(s["pct_chg"])

    summary = []
    for name, st in stats.items():
        avg_rank = round(sum(st["ranks"]) / len(st["ranks"]), 1)
        avg_up = round(sum(st["up_nums"]) / len(st["up_nums"]), 1)
        avg_pct = round(sum(st["pct_chg"]) / len(st["pct_chg"]), 2)
        heat_score = st["count"] * 10 - avg_rank
        summary.append({
            "name": name,
            "count": st["count"],
            "avg_rank": avg_rank,
            "avg_up_nums": avg_up,
            "avg_pct_chg": avg_pct,
            "heat_score": round(heat_score, 1),
        })

    summary.sort(key=lambda x: x["heat_score"], reverse=True)
    return summary


def print_table(df: pd.DataFrame, top_n: int = 20):
    """控制台打印板块热度排名"""
    if df.empty:
        print("⚠️ 无数据")
        return

    print(f"\n{'=' * 70}")
    print(f"  📊 涨停最强板块  Top{min(top_n, len(df))}")
    print(f"{'=' * 70}")
    print(f"{'排名':<5} {'板块':<14} {'涨停家数':<10} {'涨跌幅%':<10} {'连板高度':<12}")
    print("-" * 70)

    for _, row in df.head(top_n).iterrows():
        up = int(row.get("up_nums", 0) or 0)
        pct = row.get("pct_chg", 0)
        pct_str = f"{pct:+.2f}%" if pd.notna(pct) else "N/A"
        flag = "🔥" if up >= 20 else ("🟠" if up >= 15 else "🟢")
        print(
            f"{flag} {int(row.get('rank', 0)):<3} "
            f"{str(row.get('name', '')):<14} "
            f"{up:<10} "
            f"{pct_str:<10} "
            f"{str(row.get('up_stat', '')):<12}"
        )
    print("=" * 70)


def export_json(data_by_date: dict, summary: list):
    """导出到 output/sector_heat.json"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, SECTOR_JSON)

    dates = sorted(data_by_date.keys(), reverse=True)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dates": dates,
        "data": data_by_date,
        "summary": summary,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n📁 JSON 已导出: {filepath}（{len(dates)}天，{len(summary)}板块汇总）")


def get_trade_dates(pro, target_date: str = None, count: int = WEEK_DAYS) -> list:
    """获取最近 N 个交易日，从早到晚。当天（工作日）不依赖 trade_cal 确认。"""
    if target_date:
        base = datetime.strptime(target_date, "%Y%m%d")
        return [(base - timedelta(days=i)).strftime("%Y%m%d") for i in range(count - 1, -1, -1)]

    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
    dates = []
    i = 0
    while len(dates) < count and i < 21:
        test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
        test_dt = datetime.strptime(test_date, "%Y%m%d")
        i += 1
        if test_dt.weekday() >= 5:
            continue
        # 今天（工作日）直接接受，不依赖 trade_cal
        if test_date == today_str:
            dates.insert(0, test_date)
            continue
        try:
            df_cal = pro.trade_cal(exchange="SSE", start_date=test_date, end_date=test_date)
            if df_cal is not None and not df_cal.empty:
                if df_cal.iloc[0].get("is_open", 0) == 1:
                    dates.insert(0, test_date)
                    continue
        except Exception:
            pass
        dates.insert(0, test_date)

    return dates


def main():
    parser = argparse.ArgumentParser(
        description="板块热度/涨跌排名 — 基于 Tushare limit_cpt_list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/sector_heat.py                     # 今日板块热度
  python tools/sector_heat.py --date 20260708     # 指定日期
  python tools/sector_heat.py --json              # 导出近一周JSON + 汇总
        """,
    )
    parser.add_argument("--date", type=str, default=None,
                        help="交易日 YYYYMMDD，默认最近交易日")
    parser.add_argument("--json", action="store_true",
                        help="导出近一周JSON到output/sector_heat.json")

    args = parser.parse_args()

    print("🔗 连接 Tushare...")
    disable_proxy()
    pro = get_tushare_pro()

    # 确定目标日期
    if args.json:
        target_dates = get_trade_dates(pro, args.date)
        print(f"📅 拉取 {len(target_dates)} 天: {target_dates[0]} ~ {target_dates[-1]}")
    elif args.date:
        target_dates = [args.date]
    else:
        target_dates = [get_trade_dates(pro, count=1)[0]]
        print(f"📅 交易日: {target_dates[0]}")

    # 拉数据
    data_by_date = {}
    console_df = None

    for td in target_dates:
        print(f"\n📡 {td} ...")
        df = fetch_sectors(pro, td)
        if not df.empty:
            console_df = df  # 取最新日期用于展示
        data_by_date[td] = {
            "total": len(df),
            "sectors": _sector_list(df),
        }

    # 控制台展示
    if console_df is not None:
        print_table(console_df)

    # 汇总 + 导出
    if args.json:
        summary = build_summary(data_by_date)
        print(f"\n📊 一周强势板块汇总 Top10:")
        print(f"{'板块':<14} {'出现天数':<10} {'平均排名':<10} {'平均涨停':<10} {'平均涨跌':<10}")
        print("-" * 60)
        for s in summary[:10]:
            pct_str = f"{s['avg_pct_chg']:+.2f}%"
            print(f"{s['name']:<14} {s['count']:<10} {s['avg_rank']:<10} {s['avg_up_nums']:<10} {pct_str:<10}")

        export_json(data_by_date, summary)

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
