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


def check_strategy_resonance(codes: list[str], required_strategies: list[str] | None = None) -> dict[str, tuple[bool, str]]:
    """
    对给定股票列表，加载日线数据并跑全部日线策略。

    Args:
        codes: 股票代码列表
        required_strategies: 必须命中的策略名列表，None 表示任意策略命中即可
                             例：["二波形态"] 表示只有命中二波形态才算共振

    Returns:
        {code: (是否命中策略, 命中的策略名用逗号分隔)}
    """
    from strategy import prepare_hist_data
    from strategies.registry import evaluate_daily_strategies

    results: dict[str, tuple[bool, str]] = {}
    for code in codes:
        try:
            file_path = os.path.join(PROJECT_ROOT, "cache", "hist", f"{normalize_code(code)}_bs.csv")
            if not os.path.exists(file_path):
                results[code] = (False, "无缓存")
                continue
            df = pd.read_csv(file_path, dtype={"代码": str})
            if df.empty or "日期" not in df.columns:
                results[code] = (False, "数据为空")
                continue
            df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
            df = df.dropna(subset=["日期"]).sort_values("日期")

            df = prepare_hist_data(df)
            latest = df.iloc[-1]
            signals = evaluate_daily_strategies(latest)
            if signals:
                strategy_names = [s.strategy_name for s in signals]
                if required_strategies:
                    # 必须命中指定策略才算
                    hit = any(req in strategy_names for req in required_strategies)
                else:
                    hit = True
                results[code] = (hit, ", ".join(strategy_names))
            else:
                results[code] = (False, "无策略命中")
        except Exception as e:
            results[code] = (False, f"异常:{e}")
    return results

def load_stock_name_map(map_file: str = os.path.join("cache", "stock_name_map.csv")) -> dict[str, str]:
    """Load local code-name mapping from cache/stock_name_map.csv."""
    if not os.path.exists(map_file):
        print(f"提示：未找到股票名称映射表：{map_file}，结果将只显示代码。")
        print("可以先运行：python test/update_stock_name_map.py")
        return {}

    try:
        name_df = pd.read_csv(map_file, dtype={"代码": str})
    except Exception as e:
        print(f"提示：读取股票名称映射表失败：{e}，结果将只显示代码。")
        return {}

    if name_df.empty or "代码" not in name_df.columns or "名称" not in name_df.columns:
        print(f"提示：{map_file} 缺少 代码/名称 列，结果将只显示代码。")
        return {}

    name_df = name_df[["代码", "名称"]].copy()
    name_df["代码"] = name_df["代码"].apply(normalize_code)
    name_df["名称"] = name_df["名称"].astype(str).str.strip()
    name_df = name_df.dropna(subset=["代码", "名称"])
    name_df = name_df[name_df["代码"].astype(str).str.len() == 6]
    name_df = name_df.drop_duplicates(subset=["代码"], keep="first")

    return dict(zip(name_df["代码"], name_df["名称"]))


def add_stock_names(df: pd.DataFrame, name_map: dict[str, str]) -> pd.DataFrame:
    """Insert 名称 column after 代码 according to local name_map."""
    if df is None or df.empty or "代码" not in df.columns:
        return df

    result = df.copy()
    result["代码"] = result["代码"].apply(normalize_code)
    result["名称"] = result["代码"].map(name_map).fillna("")

    cols = list(result.columns)
    cols.remove("名称")
    code_idx = cols.index("代码")
    cols.insert(code_idx + 1, "名称")
    return result[cols]

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

    # ★ 必须有回调经历：近60日内，从任一个10日前的局部高点之后，至少有8%回撤
    #    目的：排除一路涨没回调的票（如百合花），二波形态必须"先涨→后跌→再涨"
    recent60 = data.tail(60)
    recent60_close = pd.to_numeric(recent60[close_col], errors="coerce")
    if len(recent60_close) >= 30:
        # 找过去20~40天之间的最高点（确保有足够时间回调）
        mid_high_idx = recent60_close.iloc[-40:-10].idxmax() if len(recent60_close) >= 40 else recent60_close.iloc[:-10].idxmax()
        if pd.notna(mid_high_idx):
            mid_high_val = recent60_close[mid_high_idx]
            after_mid = recent60_close.loc[mid_high_idx:]
            after_low = after_mid.min()
            if pd.notna(mid_high_val) and pd.notna(after_low) and mid_high_val > 0:
                pullback_from_mid = (after_low / mid_high_val - 1) * 100
                if pullback_from_mid > -8:
                    return False, f"无明显回调(中期高点后最大回撤仅{pullback_from_mid:.1f}%)"

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
    parser.add_argument("--strategy-resonance", action="store_true", help="ML信号 + 规则策略共振确认，只有规则策略也命中的才算有效信号")
    parser.add_argument("--name-map-file", default=os.path.join("cache", "stock_name_map.csv"), help="股票代码名称映射表，默认 cache/stock_name_map.csv")
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

    # 扫描完成后统一读取本地代码-名称映射表，并给所有结果补充“名称”列。
    # 注意：不要放在 scan_one_code() 里每只股票读取一次，否则会拖慢扫描速度。
    name_map = load_stock_name_map(args.name_map_file)
    df = add_stock_names(df, name_map)

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

    print("\n🟢 可观察候选，未涨停（TOP 10）：")
    if watch_df.empty:
        print("  暂无未涨停 ML 信号。")
    else:
        print(f"  共 {len(watch_df)} 只，展示前 10：")
        print_df(watch_df.head(10))

    if not limit_up_df.empty:
        print(f"\n🔴 涨停或接近涨停：{len(limit_up_df)} 只（已排除）")

    # ---- 策略共振确认（可选） ----
    resonance_df = pd.DataFrame()
    if args.strategy_resonance and not signal_df.empty:
        triggered_codes = signal_df["代码"].tolist()
        resonance_map = check_strategy_resonance(triggered_codes)

        signal_df["策略共振"] = signal_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[0])
        signal_df["命中策略"] = signal_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[1])

        if not watch_df.empty:
            watch_df["策略共振"] = watch_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[0])
            watch_df["命中策略"] = watch_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[1])
        if not limit_up_df.empty:
            limit_up_df["策略共振"] = limit_up_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[0])
            limit_up_df["命中策略"] = limit_up_df["代码"].map(lambda c: resonance_map.get(c, (False, ""))[1])

        resonance_df = signal_df[signal_df["策略共振"] == True].copy()
        hit_count = len(resonance_df)
        if hit_count > 0:
            print(f"\n🔗 策略共振：{hit_count}/{len(triggered_codes)} 只")
        else:
            print(f"\n🔗 策略共振：无（{len(triggered_codes)} 只均未通过规则验证）")
    # ---------------------------------

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
        if not resonance_df.empty:
            resonance_df.to_excel(writer, sheet_name="ML策略共振", index=False)

    print(f"\n扫描结果已保存：{args.output}")


if __name__ == "__main__":
    main()
