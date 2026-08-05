#!/usr/bin/env python3
# test_chanlun_divergence.py
"""
单独测试缠论选股 + 指数/个股背离扫描（30m + 60m）。
不依赖 daily_report 其他步骤，直接跑。

用法：
  python test_chanlun_divergence.py                     # 全部股票池
  python test_chanlun_divergence.py --max 100            # 只扫前100只
  python test_chanlun_divergence.py --codes 000001,600519 # 指定股票
  python test_chanlun_divergence.py --no-chanlun          # 只跑背离
  python test_chanlun_divergence.py --no-divergence       # 只跑缠论
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUTPUT_DIR = "output"
POOL_FILE = os.path.join(OUTPUT_DIR, "a_stock_selected.xlsx")
OUTPUT_JSON = os.path.join(OUTPUT_DIR, "mini_program_stocks.json")


def main():
    parser = argparse.ArgumentParser(description="缠论+背离扫描测试")
    parser.add_argument("--max", type=int, default=0, help="最多扫N只, 0=全部")
    parser.add_argument("--codes", type=str, help="指定股票, 逗号分隔")
    parser.add_argument("--no-chanlun", action="store_true", help="跳过缠论选股")
    parser.add_argument("--no-divergence", action="store_true", help="跳过背离扫描")
    parser.add_argument("--no-index", action="store_true", help="跳过指数背离")
    args = parser.parse_args()

    # ── 加载股票池 ──
    if args.codes:
        codes_list = [c.strip() for c in args.codes.split(",")]
        pool_df = pd.DataFrame({"代码": [str(c).zfill(6) for c in codes_list]})
    elif os.path.exists(POOL_FILE):
        pool_df = pd.read_excel(POOL_FILE, dtype={"代码": str})
        pool_df["代码"] = pool_df["代码"].astype(str).str.zfill(6)
        if args.max > 0:
            pool_df = pool_df.head(args.max)
    else:
        print(f"❌ 股票池不存在: {POOL_FILE}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"🧪 缠论选股 + 背离扫描 测试")
    print(f"{'='*60}")
    print(f"  股票数: {len(pool_df)} 只")
    print(f"  缠论: {'✅' if not args.no_chanlun else '❌ 跳过'}")
    print(f"  背离: {'✅' if not args.no_divergence else '❌ 跳过'}")
    print(f"  指数背离: {'✅' if not args.no_index else '❌ 跳过'}")
    print()

    name_map = {}
    if "名称" in pool_df.columns:
        for _, row in pool_df.iterrows():
            name_map[str(row["代码"]).zfill(6)] = str(row["名称"])

    result = {
        "index_divergence": {},
        "chanlun_stocks": [],
        "divergence_stocks": [],
    }

    total_start = time.time()

    # ── 1. 指数背离 ──
    if not args.no_index:
        print("📊 指数背离扫描（30m + 60m）...")
        try:
            from strategies.index_divergence import check_single_index_divergence, market_bottom_signal, INDEX_MAP
            idx_all = {}
            for freq in ["30", "60"]:
                freq_label = f"{freq}分钟"
                print(f"  ⏳ {freq_label} ...")
                freq_results = {}
                for idx_key in INDEX_MAP:
                    freq_results[idx_key] = check_single_index_divergence(idx_key)
                has_signal, desc = market_bottom_signal(freq_results)
                idx_all[freq_label] = {
                    "has_signal": has_signal,
                    "description": desc,
                    "indices": {k: {
                        "name": v["index_name"],
                        "price": v.get("latest_price", 0),
                        "bottom_divergence": v.get("bottom_divergence", False),
                        "golden_cross_divergence": v.get("golden_cross_divergence", False),
                        "trend": v.get("trend", "neutral"),
                    } for k, v in freq_results.items()},
                }
                print(f"    → {desc}")
            result["index_divergence"] = idx_all
        except Exception as e:
            print(f"  ⚠️ 指数背离失败: {e}")

    # ── 2. 个股缠论 + 背离 ──
    total = len(pool_df)
    for freq in ["30", "60"]:
        freq_label = f"{freq}分钟"
        chanlun_count = 0
        divergence_count = 0
        no_data_count = 0
        t0 = time.time()

        for idx, (_, row) in enumerate(pool_df.iterrows()):
            code = str(row["代码"]).zfill(6)
            name = name_map.get(code, "")

            minute_file = os.path.join("cache", "minute", f"{code}_{freq}m.csv")
            if not os.path.exists(minute_file):
                no_data_count += 1
                continue

            try:
                df = pd.read_csv(minute_file, dtype={"代码": str})
                if df.empty or len(df) < 60:
                    no_data_count += 1
                    continue

                # 缠论买点
                if not args.no_chanlun:
                    from strategies.chanlun import analyze, detect_all_buy_points
                    ctx = analyze(df)
                    if ctx is not None and ctx.strokes and len(ctx.strokes) >= 3:
                        _, buy_points = detect_all_buy_points(df)
                        for bp in buy_points:
                            result["chanlun_stocks"].append({
                                "code": code, "name": name,
                                "buy_type": bp.type,
                                "price": round(bp.price, 2),
                                "confidence": round(bp.confidence, 2),
                                "frequency": freq_label,
                            })
                            chanlun_count += 1

                # 个股背离
                if not args.no_divergence:
                    from strategies.minute_divergence import check_stock_minute_divergence
                    div_result = check_stock_minute_divergence(code, frequency=freq)
                    if div_result.get("dif_divergence"):
                        result["divergence_stocks"].append({
                            "code": code, "name": name,
                            "div_type": "DIF底背离",
                            "price": div_result.get("latest_price", 0),
                            "frequency": freq_label,
                        })
                        divergence_count += 1
                    if div_result.get("golden_cross_divergence"):
                        result["divergence_stocks"].append({
                            "code": code, "name": name,
                            "div_type": "MACD金叉背离",
                            "price": div_result.get("latest_price", 0),
                            "frequency": freq_label,
                        })
                        divergence_count += 1

            except Exception:
                continue

            if (idx + 1) % 100 == 0:
                print(f"  [{freq_label}] 进度: {idx+1}/{total} | 缠论: {chanlun_count} | 背离: {divergence_count}")

        elapsed = time.time() - t0
        print(f"  [{freq_label}] 完成: 缠论 {chanlun_count}, 背离 {divergence_count}, "
              f"无数据 {no_data_count}, 耗时 {elapsed:.1f}s")

    total_elapsed = time.time() - total_start

    # ── 汇总 ──
    print(f"\n{'='*60}")
    print(f"📊 扫描结果汇总")
    print(f"{'='*60}")

    # 指数背离
    if result["index_divergence"]:
        print(f"\n【指数背离】")
        for freq_label, idx_info in result["index_divergence"].items():
            print(f"  {freq_label}: {idx_info['description']}")
            for k, v in idx_info["indices"].items():
                flags = []
                if v["bottom_divergence"]:
                    flags.append("🔴底背离")
                if v["golden_cross_divergence"]:
                    flags.append("🟡金叉背离")
                if not flags:
                    flags.append("✅无")
                print(f"    {v['name']} | {v['price']:.2f} | {' '.join(flags)}")

    # 缠论
    chanlun = result["chanlun_stocks"]
    if chanlun:
        print(f"\n【缠论买点】共 {len(chanlun)} 个:")
        for freq_label in ["30分钟", "60分钟"]:
            freq_stocks = [s for s in chanlun if s.get("frequency") == freq_label]
            if freq_stocks:
                print(f"  [{freq_label}]")
                for bt in ["一买", "二买", "三买"]:
                    bt_stocks = [s for s in freq_stocks if s["buy_type"] == bt]
                    if bt_stocks:
                        print(f"    {bt} ({len(bt_stocks)}只):")
                        for s in sorted(bt_stocks, key=lambda x: -x["confidence"])[:10]:
                            print(f"      {s['code']} {s['name']} | ¥{s['price']} | 置信度{s['confidence']:.2f}")

    # 背离
    divs = result["divergence_stocks"]
    if divs:
        print(f"\n【个股背离】共 {len(divs)} 个:")
        for freq_label in ["30分钟", "60分钟"]:
            freq_stocks = [s for s in divs if s.get("frequency") == freq_label]
            if freq_stocks:
                print(f"  [{freq_label}]")
                for dt in ["DIF底背离", "MACD金叉背离"]:
                    dt_stocks = [s for s in freq_stocks if s["div_type"] == dt]
                    if dt_stocks:
                        print(f"    {dt} ({len(dt_stocks)}只, 前10):")
                        for s in dt_stocks[:10]:
                            print(f"      {s['code']} {s['name']} | ¥{s['price']}")

    print(f"\n⏱️ 总耗时: {total_elapsed:.1f}s")

    # 保存 JSON（处理 numpy bool）
    def _to_native(obj):
        if isinstance(obj, (bool,)):
            return bool(obj)
        return obj

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "test_chanlun_divergence",
        "index_divergence": result["index_divergence"],
        "chanlun_stocks": result["chanlun_stocks"],
        "divergence_stocks": result["divergence_stocks"],
        "total_chanlun": len(chanlun),
        "total_divergence": len(divs),
    }
    json_path = os.path.join(OUTPUT_DIR, "chanlun_divergence_test.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 详细结果: {json_path}")


if __name__ == "__main__":
    main()
