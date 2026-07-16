# -*- coding: utf-8 -*-
"""
测试 Tushare 日K线数据拉取
==========================
验证 tushare 能否替代 BaoStock 的 query_history_k_data_plus。

BaoStock 当前返回字段: date, open, high, low, close, volume, amount, pctChg
Tushare 对应接口:   ts.pro_bar() 或 pro.daily()

Tushare pro_bar 字段:
  ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount

用法:
  python test_tushare_daily.py
  python test_tushare_daily.py --batch  # 批量测试 20 只
"""

import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import get_tushare_pro, call_with_retry

CACHE_DIR = "cache/hist"


def code_to_ts_code(code: str) -> str:
    """6位代码 → tushare ts_code"""
    code = str(code).zfill(6)
    if code.startswith(("600", "601", "603", "605")):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_daily_kline_ts(code: str, start_date: str = None, end_date: str = None, pro=None) -> pd.DataFrame:
    """
    使用 Tushare pro_bar 获取个股日K线（前复权）。

    返回 DataFrame 列（保持与现有缓存格式兼容）:
      日期, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 涨跌幅, 代码

    参数:
      code: 6位股票代码
      start_date: YYYYMMDD 或 YYYY-MM-DD
      end_date:   YYYYMMDD 或 YYYY-MM-DD
      pro: tushare pro 实例（可选，不传则自动初始化）
    """
    if pro is None:
        pro = get_tushare_pro()

    ts_code = code_to_ts_code(code)

    # 统一日期格式 YYYYMMDD
    def _fmt(d):
        if d is None:
            return None
        return str(d).replace("-", "")[:8]

    start = _fmt(start_date)
    end = _fmt(end_date)

    # 默认拉最近 365 天
    if end is None:
        end = datetime.now().strftime("%Y%m%d")
    if start is None:
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    try:
        # 方案1：pro.daily() 按 ts_code 获取个股历史日线（不复权）
        df = pro.daily(
            ts_code=ts_code,
            start_date=start,
            end_date=end,
        )

        # 方案2：如果 daily 不支持 ts_code 参数，尝试用 trade_date 逐日拉
        # （daily 接口设计是 trade_date 为必填，但有些版本支持 ts_code 过滤）
        if df is None or df.empty:
            # 回退：尝试不带 ts_code，按日期范围逐日拉（慢但稳）
            print(f"  {code} daily(ts_code=) 为空，尝试逐日获取...", end="")
            frames = []
            d = datetime.strptime(start, "%Y%m%d")
            d_end = datetime.strptime(end, "%Y%m%d")
            while d <= d_end:
                ds = d.strftime("%Y%m%d")
                try:
                    day_df = pro.daily(trade_date=ds)
                    if day_df is not None and not day_df.empty:
                        day_df = day_df[day_df["ts_code"] == ts_code]
                        if not day_df.empty:
                            frames.append(day_df)
                except Exception:
                    pass
                d += timedelta(days=1)
                if len(frames) > 0:
                    # 周末/节假日大概率空，减速
                    time.sleep(0.1)
            if frames:
                df = pd.concat(frames, ignore_index=True)
                print(f" 获取到 {len(df)} 条")
            else:
                print(" 无数据")
                return pd.DataFrame()

        if df is None or df.empty:
            print(f"  {code} Tushare 返回空数据")
            return pd.DataFrame()

        # 重命名列，兼容现有缓存格式
        col_map = {
            "trade_date": "日期",
            "open": "开盘",
            "high": "最高",
            "low": "最低",
            "close": "收盘",
            "vol": "成交量",
            "amount": "成交额",
            "pct_chg": "涨跌幅",
        }
        df = df.rename(columns=col_map)
        df["代码"] = code

        # 保留需要的列
        keep_cols = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅", "代码"]
        df = df[[c for c in keep_cols if c in df.columns]]

        # 类型转换
        for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["日期"] = pd.to_datetime(df["日期"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["日期"])
        df = df.sort_values("日期")
        df["日期"] = df["日期"].dt.strftime("%Y-%m-%d")

        return df

    except Exception as e:
        print(f"  {code} Tushare 请求异常：{e}")
        return pd.DataFrame()


def test_single():
    """测试单只股票"""
    print("=" * 60)
    print("🧪 测试 1：单只股票 — 平安银行 000001")
    print("=" * 60)

    pro = get_tushare_pro()
    t0 = time.time()
    df = fetch_daily_kline_ts("000001", pro=pro)
    elapsed = time.time() - t0

    if df.empty:
        print("❌ 获取失败！")
        return

    print(f"✅ 成功！{len(df)} 条记录，耗时 {elapsed:.1f}s")
    print(f"   日期范围：{df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
    print(f"   列：{list(df.columns)}")
    print(f"\n   最近 5 条：")
    print(df.tail(5).to_string(index=False))

    # 检查必要字段
    required = ["日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"\n⚠️ 缺少字段：{missing}")
    else:
        print(f"\n✅ 所有必要字段齐全")


def test_batch(n: int = 20):
    """批量测试 N 只，验证速度和稳定性"""
    print("=" * 60)
    print(f"🧪 测试 2：批量拉取 {n} 只股票")
    print("=" * 60)

    # 从缓存目录读已有股票列表（只用已有缓存文件的代码来测试）
    codes = []
    if os.path.isdir(CACHE_DIR):
        for f in sorted(os.listdir(CACHE_DIR)):
            if f.endswith("_bs.csv"):
                codes.append(f[:6])
    if not codes:
        # 没有缓存，用几个常见股票
        codes = ["000001", "600519", "300750", "002594", "601012",
                 "000858", "600036", "002415", "300059", "600276",
                 "002230", "601318", "000333", "600900", "002475",
                 "300124", "600809", "000651", "600030", "300015"]

    codes = codes[:n]
    print(f"  待测试：{len(codes)} 只")
    print(f"  代码：{', '.join(codes[:10])}...")

    pro = get_tushare_pro()
    success = 0
    fail = 0
    total_rows = 0
    t0 = time.time()

    for i, code in enumerate(codes):
        df = fetch_daily_kline_ts(code, pro=pro)
        if df.empty:
            fail += 1
            print(f"  [{i+1}/{n}] {code} ❌ 空数据")
        else:
            success += 1
            total_rows += len(df)
            if i < 5:
                print(f"  [{i+1}/{n}] {code} ✅ {len(df)} 条")

        # tushare 免费版限速：每分钟 200 次，保守 0.5s 间隔
        time.sleep(0.4)

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"📊 汇总：{success} 成功 / {fail} 失败")
    print(f"   总耗时：{elapsed:.1f}s，平均 {elapsed/len(codes):.2f}s/只")
    if success > 0:
        print(f"   总行数：{total_rows}，平均 {total_rows/success:.0f} 行/只")
    print(f"   估算 2736 只全量：{elapsed/len(codes)*2736/60:.1f} 分钟")


def test_compare():
    """对比 BaoStock 和 Tushare 同一只股票的数据一致性"""
    print("=" * 60)
    print("🧪 测试 3：BaoStock vs Tushare 数据对比")
    print("=" * 60)

    code = "000001"
    cache_file = os.path.join(CACHE_DIR, f"{code}_bs.csv")

    # 读 BaoStock 缓存
    bs_df = pd.DataFrame()
    if os.path.exists(cache_file):
        bs_df = pd.read_csv(cache_file, dtype={"代码": str})
        print(f"  BaoStock 缓存：{len(bs_df)} 条")

    # 拉 Tushare
    pro = get_tushare_pro()
    ts_df = fetch_daily_kline_ts(code, pro=pro)
    print(f"  Tushare 实时：{len(ts_df)} 条")

    if bs_df.empty or ts_df.empty:
        print("  ⚠️ 数据不足，跳过对比")
        return

    # 找共同日期
    bs_dates = set(bs_df["日期"].astype(str))
    ts_dates = set(ts_df["日期"].astype(str))
    common = sorted(bs_dates & ts_dates)
    only_bs = sorted(bs_dates - ts_dates)
    only_ts = sorted(ts_dates - bs_dates)

    print(f"  共同日期：{len(common)} 天")
    if only_bs:
        print(f"  仅 BaoStock 有：{only_bs[-5:]}")
    if only_ts:
        print(f"  仅 Tushare 有：{only_ts[-5:]}")

    # 在共同日期上对比收盘价（前复权）
    if len(common) >= 5:
        bs_c = bs_df.set_index("日期")
        ts_c = ts_df.set_index("日期")
        diff_count = 0
        max_diff = 0.0
        for d in common[-20:]:  # 最近 20 天
            bs_close = float(bs_c.loc[d, "收盘"]) if d in bs_c.index else None
            ts_close = float(ts_c.loc[d, "收盘"]) if d in ts_c.index else None
            if bs_close and ts_close and bs_close != 0:
                diff_pct = abs(ts_close - bs_close) / abs(bs_close) * 100
                if diff_pct > 0.1:
                    diff_count += 1
                    max_diff = max(max_diff, diff_pct)
                    if diff_pct > 1.0:
                        print(f"    {d} : BS={bs_close:.3f} TS={ts_close:.3f} 差异 {diff_pct:.2f}%")

        if diff_count == 0:
            print(f"  ✅ 最近 20 天收盘价完全一致（差异 < 0.1%）")
        else:
            print(f"  ⚠️ {diff_count}/20 天存在差异，最大 {max_diff:.2f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="测试 Tushare 日K拉取")
    parser.add_argument("--batch", action="store_true", help="批量测试")
    parser.add_argument("--compare", action="store_true", help="对比 BaoStock")
    parser.add_argument("--code", type=str, default="000001", help="指定股票代码")
    args = parser.parse_args()

    test_single()

    if args.compare:
        print()
        test_compare()

    if args.batch:
        print()
        test_batch(20)
