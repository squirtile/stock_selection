#!/usr/bin/env python
"""Scan current ML signals using a trained model.

功能：
1. 加载训练好的 MLPatternModel pkl；
2. 扫描当前股票池最近一个 lookback 窗口；
3. 输出全部 ML 评分、触发 ML 信号股票；
4. 将触发信号拆分为“可观察候选_未涨停”和“涨停或接近涨停”；
5. 支持多线程、进度显示、自动排除训练模板股。
"""

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.ml_classifier import MLPatternModel
from ml_engine.pattern_extract import load_candidate_codes, normalize_code, extract_indicator_matrix


def print_df(df: pd.DataFrame):
    """Pretty print DataFrame in terminal."""
    if df is None or df.empty:
        print("空")
        return
    if tabulate:
        print(tabulate(df, headers="keys", tablefmt="pretty", showindex=False))
    else:
        print(df.to_string(index=False))


def classify_signal(row: pd.Series, limit_up_threshold: float = 9.85) -> str:
    """Classify ML signal for easier review."""
    pct = pd.to_numeric(row.get("涨跌幅"), errors="coerce")
    if pd.notna(pct) and pct >= limit_up_threshold:
        return "涨停或接近涨停"
    return "可观察候选_未涨停"


def check_trend_filter(df: pd.DataFrame, t: int | None = None):
    """
    趋势过滤：只在启用 --trend-filter 时使用。

    目的：剔除明显下跌趋势、破位走势、弱反抽股票。
    不启用时不影响原有 ML 扫描逻辑。

    返回：
    trend_ok: bool
    trend_reason: str
    """
    if df is None or df.empty:
        return False, "K线为空"

    if t is None:
        t = len(df) - 1

    # 至少需要 60 日均线 + 10 日趋势比较。
    if t < 70 or len(df.iloc[:t + 1]) < 71:
        return False, "K线不足71天"

    data = df.iloc[:t + 1].copy()

    if "收盘" in data.columns:
        close_col = "收盘"
    elif "close" in data.columns:
        close_col = "close"
    elif "收盘价" in data.columns:
        close_col = "收盘价"
    else:
        return False, "缺少收盘价字段"

    close_series = pd.to_numeric(data[close_col], errors="coerce")
    data["MA5"] = close_series.rolling(5).mean()
    data["MA10"] = close_series.rolling(10).mean()
    data["MA20"] = close_series.rolling(20).mean()
    data["MA60"] = close_series.rolling(60).mean()

    last = data.iloc[-1]
    prev5 = data.iloc[-6]
    prev10 = data.iloc[-11]

    close = pd.to_numeric(last[close_col], errors="coerce")
    ma5 = pd.to_numeric(last["MA5"], errors="coerce")
    ma10 = pd.to_numeric(last["MA10"], errors="coerce")
    ma20 = pd.to_numeric(last["MA20"], errors="coerce")
    ma60 = pd.to_numeric(last["MA60"], errors="coerce")

    if pd.isna(close) or pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20) or pd.isna(ma60):
        return False, "均线数据不足"

    if close < ma20:
        return False, "收盘价低于MA20"

    if close < ma60:
        return False, "收盘价低于MA60"

    # MA20 明显在 MA60 下方，通常不是主升结构。
    if ma20 < ma60 * 0.98:
        return False, "MA20明显低于MA60"

    # MA20 不能继续下行。
    if pd.notna(prev5["MA20"]) and ma20 < float(prev5["MA20"]):
        return False, "MA20向下"

    # MA60 允许轻微波动，但不能明显走弱。
    if pd.notna(prev10["MA60"]) and ma60 < float(prev10["MA60"]) * 0.995:
        return False, "MA60走弱"

    recent20 = data.tail(20)
    recent20_close = pd.to_numeric(recent20[close_col], errors="coerce")
    recent_high = recent20_close.max()
    if pd.notna(recent_high) and recent_high > 0:
        drawdown = (float(close) / float(recent_high) - 1) * 100
        if drawdown < -15:
            return False, f"近20日回撤过深{drawdown:.2f}%"

    recent5 = data.tail(5)
    recent5_close = pd.to_numeric(recent5[close_col], errors="coerce")
    weak_days = (recent5_close < recent5["MA5"]).sum()
    if weak_days >= 4:
        return False, "近5天多数低于MA5"

    return True, "趋势通过"


def scan_one_code(model: MLPatternModel, code: str, threshold: float, trend_filter: bool = False):
    """
    扫描单只股票最近一个完整 lookback 窗口。

    为了加速，只读取尾部数据，不读完整历史。
    tail_rows=180 通常足够计算 SMA60、近20日涨幅、量能等指标。
    """
    code = normalize_code(code)

    try:
        df = extract_indicator_matrix(
            code,
            min_rows=model.lookback + 70,
            tail_rows=180,
        )

        if df.empty or len(df) < model.lookback:
            return None

        indicator_arr = df[model.feature_cols].values

        # 最近完整窗口
        t = len(df) - 1
        window = indicator_arr[t - model.lookback + 1:t + 1, :]

        if not np.all(np.isfinite(window)):
            # 如果最新一天有缺失，就退一日
            t = len(df) - 2
            if t < model.lookback - 1:
                return None
            window = indicator_arr[t - model.lookback + 1:t + 1, :]
            if not np.all(np.isfinite(window)):
                return None

        vec = window.flatten().astype(np.float64)
        score = float(model.predict_proba(vec))
        raw_ml_signal = bool(score >= threshold)

        trend_ok = True
        trend_reason = "未启用趋势过滤"
        if trend_filter:
            trend_ok, trend_reason = check_trend_filter(df, t)

        pct_change = pd.to_numeric(df.iloc[t].get("涨跌幅"), errors="coerce")
        close_price = pd.to_numeric(df.iloc[t].get("收盘"), errors="coerce")

        result = {
            "代码": code,
            "日期": str(df.iloc[t]["日期"])[:10],
            "ML分数": round(score, 4),
            "ML信号": bool(raw_ml_signal and trend_ok),
            "收盘价": round(float(close_price), 4) if pd.notna(close_price) else None,
            "涨跌幅": round(float(pct_change), 2) if pd.notna(pct_change) else None,
        }

        # 只有启用趋势过滤时才增加诊断字段，避免影响原有输出格式。
        if trend_filter:
            result["原始ML信号"] = raw_ml_signal
            result["趋势通过"] = bool(trend_ok)
            result["趋势原因"] = trend_reason

        return result

    except Exception:
        return None


def scan_ml_signals_fast(
    model: MLPatternModel,
    codes: list[str],
    threshold: float = 0.65,
    workers: int = 1,
    progress_every: int = 20,
    trend_filter: bool = False,
) -> pd.DataFrame:
    """Scan stocks with optional multithreading and progress display."""
    results = []
    total = len(codes)
    done = 0
    valid = 0
    signal_count = 0
    start_ts = time.time()
    workers = max(1, int(workers or 1))

    def print_progress(current_code: str, force: bool = False):
        if not force and not (done == 1 or done % progress_every == 0 or done == total):
            return

        elapsed = max(time.time() - start_ts, 0.001)
        speed = done / elapsed if done else 0
        remain = (total - done) / speed if speed > 0 else 0

        print(
            f"\r  ML扫描进度: {done}/{total} | 当前: {current_code} | 有效: {valid} | "
            f"触发: {signal_count} | 并发: {workers} | 预计剩余: {remain/60:.1f} 分钟",
            end="",
            flush=True,
        )

    if workers <= 1:
        for code in codes:
            done += 1
            result = scan_one_code(model, code, threshold, trend_filter=trend_filter)
            if result is not None:
                valid += 1
                if result["ML信号"]:
                    signal_count += 1
                results.append(result)
            print_progress(code)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(scan_one_code, model, code, threshold, trend_filter): code
                for code in codes
            }

            for future in as_completed(future_map):
                done += 1
                code = future_map[future]

                try:
                    result = future.result()
                except Exception:
                    result = None

                if result is not None:
                    valid += 1
                    if result["ML信号"]:
                        signal_count += 1
                    results.append(result)

                print_progress(code)

    print_progress(codes[-1] if codes else "", force=True)
    print()

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values("ML分数", ascending=False).reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="扫描当前机器学习形态信号")
    parser.add_argument("--model", required=True, help="模型 pkl 文件路径")
    parser.add_argument("--threshold", type=float, default=0.65, help="ML 信号阈值")
    parser.add_argument("--candidate-file", default="", help="候选股票文件，支持 xlsx/csv")
    parser.add_argument("--use-selected-file", action="store_true", help="使用 output/a_stock_selected.xlsx 作为候选池")
    parser.add_argument("--max-stocks", type=int, default=0, help="最多扫描多少只，0表示全部")
    parser.add_argument("--output", default="", help="输出 Excel 文件路径")
    parser.add_argument("--include-train-templates", action="store_true", help="扫描时不排除训练模板股")
    parser.add_argument("--workers", type=int, default=1, help="并发线程数，Windows建议4或8")
    parser.add_argument("--progress-every", type=int, default=20, help="每多少只刷新一次进度")
    parser.add_argument("--limit-up-threshold", type=float, default=9.85, help="涨停或接近涨停阈值，默认9.85")
    parser.add_argument("--trend-filter", action="store_true", help="启用趋势过滤，剔除下跌趋势、破位票、弱反抽票")
    args = parser.parse_args()

    model = MLPatternModel.load(args.model)

    codes = load_candidate_codes(
        args.candidate_file or None,
        default_selected=args.use_selected_file,
    )

    train_templates = [
        normalize_code(c)
        for c in getattr(model, "template_codes", []) or []
    ]

    if train_templates and not args.include_train_templates:
        before = len(codes)
        exclude_set = set(train_templates)
        codes = [normalize_code(c) for c in codes]
        codes = [c for c in codes if c not in exclude_set]
        print(f"已自动排除训练模板股：{','.join(train_templates)}")
        print(f"扫描股票池：{before} -> {len(codes)}")
    elif train_templates and args.include_train_templates:
        print(f"本次不排除训练模板股：{','.join(train_templates)}")
    else:
        print("当前模型未记录训练模板股，无法自动排除。")

    if args.max_stocks:
        codes = codes[:args.max_stocks]

    print(f"开始扫描 ML 信号：股票数 {len(codes)}，阈值 {args.threshold}，并发 {args.workers}")
    if args.trend_filter:
        print("已启用趋势过滤：会剔除下跌趋势、破位票、弱反抽票")

    df = scan_ml_signals_fast(
        model=model,
        codes=codes,
        threshold=args.threshold,
        workers=args.workers,
        progress_every=args.progress_every,
        trend_filter=args.trend_filter,
    )

    if df.empty:
        print("无有效 ML 扫描结果。")
        return

    signal_df = df[df["ML信号"] == True].copy()

    if not signal_df.empty:
        signal_df["信号分类"] = signal_df.apply(
            lambda row: classify_signal(row, args.limit_up_threshold),
            axis=1,
        )
        limit_up_df = signal_df[signal_df["信号分类"] == "涨停或接近涨停"].copy()
        watch_df = signal_df[signal_df["信号分类"] == "可观察候选_未涨停"].copy()
    else:
        limit_up_df = pd.DataFrame(columns=list(df.columns) + ["信号分类"])
        watch_df = pd.DataFrame(columns=list(df.columns) + ["信号分类"])

    print("\nML分数最高的前20只：")
    print_df(df.head(20))

    print("\n可观察候选，未涨停：")
    if watch_df.empty:
        print("暂无未涨停 ML 信号。")
    else:
        print_df(watch_df)

    print("\n涨停或接近涨停，单独观察：")
    if limit_up_df.empty:
        print("暂无涨停或接近涨停 ML 信号。")
    else:
        print_df(limit_up_df)

    print("\n触发ML信号的股票，全部：")
    if signal_df.empty:
        print("暂无股票达到阈值。可以降低 --threshold，比如 0.60。")
    else:
        print_df(signal_df)

    if not args.output:
        args.output = os.path.join(
            "output",
            "ml_similarity",
            f"ml_scan_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="全部ML评分", index=False)
        watch_df.to_excel(writer, sheet_name="可观察候选_未涨停", index=False)
        limit_up_df.to_excel(writer, sheet_name="涨停或接近涨停", index=False)
        signal_df.to_excel(writer, sheet_name="触发ML信号_全部", index=False)

    print(f"\n扫描结果已保存：{args.output}")


if __name__ == "__main__":
    main()
