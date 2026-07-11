#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
资金流向 工具

功能：获取三类资金流向数据：
  1. 大盘资金流向（moneyflow_mkt_dc）
  2. 概念板块资金流向（moneyflow_cnt_ths）
  3. 行业资金流向（moneyflow_ind_ths）

使用方式：
  python tools/money_flow.py                      # 控制台展示
  python tools/money_flow.py --date 20260710      # 指定日期
  python tools/money_flow.py --json               # 导出JSON供小程序使用
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
MONEYFLOW_JSON = "money_flow.json"


def fetch_mkt(pro, trade_date: str) -> dict:
    """大盘资金流向 → dict"""
    try:
        df = pro.moneyflow_mkt_dc(trade_date=trade_date)
    except Exception as e:
        print(f"  ❌ 大盘: {e}")
        return None
    if df is None or df.empty:
        return None
    r = df.iloc[0].to_dict()
    # 金额转为亿元
    for k in ["net_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount"]:
        if k in r and pd.notna(r[k]):
            r[k] = round(r[k] / 1e8, 2)
    return r


def _df_to_list(df: pd.DataFrame, name_col: str = "name") -> list:
    """DataFrame → list of dict，金额转亿"""
    if df is None or df.empty:
        return []
    result = []
    amount_cols = ["net_amount", "net_buy_amount", "net_sell_amount"]
    for _, row in df.iterrows():
        item = {}
        for col in df.columns:
            val = row[col]
            if col in amount_cols and pd.notna(val):
                val = round(float(val), 2)
            elif pd.isna(val):
                val = None
            elif isinstance(val, (float,)):
                val = round(val, 4)
            else:
                val = str(val) if not isinstance(val, (int, float)) else val
            item[col] = val
        result.append(item)
    return result


def print_mkt(mkt: dict):
    """打印大盘资金流向"""
    if not mkt:
        print("⚠️ 无大盘数据")
        return
    net = mkt.get("net_amount", 0)
    d = "流入" if net > 0 else "流出"
    print(f"\n📊 大盘资金流向")
    print(f"  上证 {mkt.get('close_sh')}  {mkt.get('pct_change_sh'):+.2f}%")
    print(f"  深证 {mkt.get('close_sz')}  {mkt.get('pct_change_sz'):+.2f}%")
    print(f"  主力净{d}: {abs(net):.1f}亿  (占比 {mkt.get('net_amount_rate', 0):.2f}%)")
    print(f"  超大单: {mkt.get('buy_elg_amount', 0):+.1f}亿  大单: {mkt.get('buy_lg_amount', 0):+.1f}亿")
    print(f"  中单:   {mkt.get('buy_md_amount', 0):+.1f}亿  小单: {mkt.get('buy_sm_amount', 0):+.1f}亿")


def print_list(df: pd.DataFrame, title: str, name_col: str = "name", top_n: int = 10):
    """打印板块排名"""
    if df is None or df.empty:
        print(f"⚠️ 无{title}数据")
        return
    s = df.sort_values("net_amount", ascending=False)
    print(f"\n📈 {title} 净流入 Top{top_n}")
    for _, r in s.head(top_n).iterrows():
        print(f"  🟢 {r[name_col]:<14} 净{r['net_amount']:+.1f}亿  涨{r.get('pct_change', 0):+.2f}%  领涨:{r.get('lead_stock', '')}")
    print(f"\n📉 {title} 净流出 Top{top_n}")
    for _, r in s.tail(top_n).iloc[::-1].iterrows():
        print(f"  🔴 {r[name_col]:<14} 净{r['net_amount']:+.1f}亿  涨{r.get('pct_change', 0):+.2f}%  领涨:{r.get('lead_stock', '')}")


def export_json(mkt: dict, cnt: list, ind: list, trade_date: str):
    """导出到 output/money_flow.json"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, MONEYFLOW_JSON)

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": trade_date,
        "mkt": mkt,
        "cnt": cnt,
        "ind": ind,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 JSON 已导出: {filepath}（大盘+{len(cnt)}概念+{len(ind)}行业）")


def get_trade_date(pro, target_date: str = None) -> str:
    """获取有效交易日"""
    if target_date:
        return target_date
    today = datetime.now()
    for i in range(10):
        test_date = (today - timedelta(days=i)).strftime("%Y%m%d")
        test_dt = datetime.strptime(test_date, "%Y%m%d")
        if test_dt.weekday() >= 5:
            continue
        try:
            df_cal = pro.trade_cal(exchange="SSE", start_date=test_date, end_date=test_date)
            if df_cal is not None and not df_cal.empty and df_cal.iloc[0].get("is_open", 0) == 1:
                return test_date
        except Exception:
            pass
        return test_date
    return (today - timedelta(days=1)).strftime("%Y%m%d")


def main():
    parser = argparse.ArgumentParser(description="资金流向 — 大盘/概念/行业")
    parser.add_argument("--date", type=str, default=None, help="交易日 YYYYMMDD")
    parser.add_argument("--json", action="store_true", help="导出JSON")
    args = parser.parse_args()

    print("🔗 连接 Tushare...")
    disable_proxy()
    pro = get_tushare_pro()

    td = get_trade_date(pro, args.date)
    print(f"📅 交易日: {td}")

    # 拉数据
    print("\n📡 大盘资金流向...")
    mkt = fetch_mkt(pro, td)
    print_mkt(mkt)

    print("\n📡 概念板块资金流向...")
    try:
        df_cnt = pro.moneyflow_cnt_ths(trade_date=td)
        print(f"   ✅ {len(df_cnt) if df_cnt is not None else 0} 条")
        print_list(df_cnt, "概念板块")
    except Exception as e:
        print(f"   ❌ {e}")
        df_cnt = None

    print("\n📡 行业资金流向...")
    try:
        df_ind = pro.moneyflow_ind_ths(trade_date=td)
        print(f"   ✅ {len(df_ind) if df_ind is not None else 0} 条")
        print_list(df_ind, "行业板块", "industry")
    except Exception as e:
        print(f"   ❌ {e}")
        df_ind = None

    if args.json:
        export_json(
            mkt,
            _df_to_list(df_cnt) if df_cnt is not None else [],
            _df_to_list(df_ind) if df_ind is not None else [],
            td,
        )

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
