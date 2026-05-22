"""Backtest evaluation and Excel report generation."""

from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import extract_indicator_matrix, ML_INDICATOR_COLUMNS, DEFAULT_LOOKBACK
from ml_engine.ml_classifier import MLPatternModel
from ml_engine.similarity import _compute_cosine_similarity_batched


def _can_buy_next_day(df: pd.DataFrame, buy_idx: int, skip_limit_up: bool = True) -> bool:
    if not skip_limit_up or buy_idx <= 0 or buy_idx >= len(df):
        return True
    pct = pd.to_numeric(df.iloc[buy_idx].get("涨跌幅", np.nan), errors="coerce")
    # 主板大致涨停约 10%；这里用 9.85 粗略过滤一字/大幅高开不可买情形。
    return not (pd.notna(pct) and pct >= 9.85)


def _calc_return(buy_price: float, sell_price: float, fee_bps: float = 0.0, slippage_bps: float = 0.0) -> float:
    buy = buy_price * (1 + slippage_bps / 10000)
    sell = sell_price * (1 - slippage_bps / 10000)
    ret = (sell / buy - 1) * 100
    ret -= fee_bps / 100  # round-trip fee in bps converted to percent
    return ret


def compute_ml_backtest(
    model: MLPatternModel,
    codes: list[str],
    hold_days_list: list[int] | None = None,
    threshold: float = 0.65,
    min_stock_rows: int = 80,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    skip_limit_up_next_open: bool = True,
) -> pd.DataFrame:
    if hold_days_list is None:
        hold_days_list = [1, 3, 5, 10]
    trades = []
    for code in codes:
        df = extract_indicator_matrix(code, min_rows=min_stock_rows)
        if df.empty:
            continue
        indicator_arr = df[model.feature_cols].values
        closes = df["收盘"].values
        opens = df["开盘"].values
        dates = df["日期"].values
        vol_avg_20 = df.get("过去20日平均成交量", pd.Series(np.nan, index=df.index)).values
        volumes = df["成交量"].values
        amounts = df["成交额"].values
        pct_changes = df["涨跌幅"].values
        n = len(df)
        for t in range(model.lookback - 1, n - 1):
            window = indicator_arr[t - model.lookback + 1:t + 1, :]
            if not np.all(np.isfinite(window)):
                continue
            try:
                score = float(model.predict_proba(window.flatten().astype(np.float64)))
            except Exception:
                continue
            if score < threshold:
                continue
            for hold_days in hold_days_list:
                buy_idx = t + 1
                sell_idx = t + hold_days
                if buy_idx >= n or sell_idx >= n:
                    continue
                if not _can_buy_next_day(df, buy_idx, skip_limit_up_next_open):
                    continue
                buy_price, sell_price = opens[buy_idx], closes[sell_idx]
                if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0 or sell_price <= 0:
                    continue
                return_pct = _calc_return(float(buy_price), float(sell_price), fee_bps, slippage_bps)
                vol_ratio = volumes[t] / vol_avg_20[t] if pd.notna(vol_avg_20[t]) and vol_avg_20[t] > 0 else None
                trades.append({
                    "代码": code,
                    "信号日期": str(dates[t])[:10],
                    "买入日期": str(dates[buy_idx])[:10],
                    "卖出日期": str(dates[sell_idx])[:10],
                    "买入价": round(float(buy_price), 4),
                    "卖出价": round(float(sell_price), 4),
                    "持有天数": hold_days,
                    "收益率%": round(float(return_pct), 2),
                    "是否盈利": return_pct > 0,
                    "ML分数": round(score, 4),
                    "信号日收盘价": round(float(closes[t]), 4),
                    "信号日涨跌幅": round(float(pct_changes[t]), 2) if pd.notna(pct_changes[t]) else None,
                    "信号日量比": round(float(vol_ratio), 2) if vol_ratio is not None else None,
                    "信号日成交额": float(amounts[t]) if pd.notna(amounts[t]) else None,
                })
    return pd.DataFrame(trades)


def _prepare_similarity_scaler(template_vectors: list[np.ndarray], stock_vectors: list[np.ndarray]):
    from sklearn.preprocessing import StandardScaler
    s = StandardScaler()
    s.fit(np.vstack([np.array(template_vectors, dtype=np.float64), np.array(stock_vectors, dtype=np.float64)]))
    return s


def compute_similarity_backtest(
    template_vectors: list[np.ndarray],
    codes: list[str],
    hold_days_list: list[int] | None = None,
    similarity_threshold: float = 0.60,
    scaler=None,
    min_stock_rows: int = 80,
    lookback: int = DEFAULT_LOOKBACK,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    skip_limit_up_next_open: bool = True,
    show_progress: bool = True,
    progress_every: int = 10,
) -> pd.DataFrame:
    """
    Similarity backtest. Scans every historical window of every code.
    A signal is generated when max similarity >= threshold.
    """
    if hold_days_list is None:
        hold_days_list = [1, 3, 5, 10]
    tpl_matrix_raw = np.array([np.asarray(v, dtype=np.float64) for v in template_vectors], dtype=np.float64)
    trades = []
    total = len(codes)
    start_ts = time.time()
    valid_stocks = 0
    signal_stocks = 0
    for i, code in enumerate(codes, start=1):
        df = extract_indicator_matrix(code, min_rows=min_stock_rows)
        if df.empty or len(df) < lookback + max(hold_days_list):
            if show_progress and (i == 1 or i % progress_every == 0 or i == total):
                elapsed = max(time.time() - start_ts, 0.001)
                speed = i / elapsed
                remain = (total - i) / speed if speed > 0 else 0
                print(f"\r  回测进度: {i}/{total} | 当前: {code} | 有效: {valid_stocks} | 有信号: {signal_stocks} | 交易: {len(trades)} | 预计剩余: {remain/60:.1f} 分钟", end="", flush=True)
            continue
        valid_stocks += 1
        indicator_arr = df[ML_INDICATOR_COLUMNS].values
        closes = df["收盘"].values
        opens = df["开盘"].values
        dates = df["日期"].values
        vol_avg_20 = df.get("过去20日平均成交量", pd.Series(np.nan, index=df.index)).values
        volumes = df["成交量"].values
        amounts = df["成交额"].values
        pct_changes = df["涨跌幅"].values
        n = len(df)

        stock_records = []
        stock_vectors = []
        for t in range(lookback - 1, n - 1):
            window = indicator_arr[t - lookback + 1:t + 1, :]
            if np.all(np.isfinite(window)):
                stock_records.append(t)
                stock_vectors.append(window.flatten().astype(np.float64))
        if not stock_vectors:
            continue

        s = scaler or _prepare_similarity_scaler(template_vectors, stock_vectors)
        tpl_scaled = s.transform(tpl_matrix_raw)
        stock_scaled = s.transform(np.array(stock_vectors, dtype=np.float64))

        # For each stock vector compute max similarity to any template.
        max_sims = np.zeros(len(stock_scaled), dtype=np.float64)
        for tpl in tpl_scaled:
            sims = _compute_cosine_similarity_batched(tpl, stock_scaled)
            max_sims = np.maximum(max_sims, sims)

        stock_trade_start = len(trades)
        for idx, t in enumerate(stock_records):
            max_sim = float(max_sims[idx])
            if max_sim < similarity_threshold:
                continue
            for hold_days in hold_days_list:
                buy_idx = t + 1
                sell_idx = t + hold_days
                if buy_idx >= n or sell_idx >= n:
                    continue
                if not _can_buy_next_day(df, buy_idx, skip_limit_up_next_open):
                    continue
                buy_price, sell_price = opens[buy_idx], closes[sell_idx]
                if pd.isna(buy_price) or pd.isna(sell_price) or buy_price <= 0 or sell_price <= 0:
                    continue
                return_pct = _calc_return(float(buy_price), float(sell_price), fee_bps, slippage_bps)
                vol_ratio = volumes[t] / vol_avg_20[t] if pd.notna(vol_avg_20[t]) and vol_avg_20[t] > 0 else None
                trades.append({
                    "代码": code,
                    "信号日期": str(dates[t])[:10],
                    "买入日期": str(dates[buy_idx])[:10],
                    "卖出日期": str(dates[sell_idx])[:10],
                    "买入价": round(float(buy_price), 4),
                    "卖出价": round(float(sell_price), 4),
                    "持有天数": hold_days,
                    "收益率%": round(float(return_pct), 2),
                    "是否盈利": return_pct > 0,
                    "相似度": round(max_sim, 4),
                    "相似度%": round(max_sim * 100, 1),
                    "信号日收盘价": round(float(closes[t]), 4),
                    "信号日涨跌幅": round(float(pct_changes[t]), 2) if pd.notna(pct_changes[t]) else None,
                    "信号日量比": round(float(vol_ratio), 2) if vol_ratio is not None else None,
                    "信号日成交额": float(amounts[t]) if pd.notna(amounts[t]) else None,
                })
        if len(trades) > stock_trade_start:
            signal_stocks += 1
        if show_progress and (i == 1 or i % progress_every == 0 or i == total):
            elapsed = max(time.time() - start_ts, 0.001)
            speed = i / elapsed
            remain = (total - i) / speed if speed > 0 else 0
            print(f"\r  回测进度: {i}/{total} | 当前: {code} | 有效: {valid_stocks} | 有信号: {signal_stocks} | 交易: {len(trades)} | 预计剩余: {remain/60:.1f} 分钟", end="", flush=True)
    if show_progress:
        print()
    return pd.DataFrame(trades)


def summarize_ml_backtest(results_df: pd.DataFrame, hold_days: int | None = None) -> pd.DataFrame:
    if results_df.empty:
        return pd.DataFrame()
    df = results_df.copy()
    if hold_days is not None:
        df = df[df["持有天数"] == hold_days]
    if df.empty:
        return pd.DataFrame()
    wins = df[df["是否盈利"] == True]
    losses = df[df["是否盈利"] == False]
    avg_loss = abs(losses["收益率%"].mean()) if len(losses) else 0.0
    avg_win = wins["收益率%"].mean() if len(wins) else 0.0
    pl_ratio = avg_win / avg_loss if avg_loss > 0 else None
    return pd.DataFrame([{
        "持有天数": hold_days if hold_days is not None else "all",
        "信号次数": len(df),
        "盈利次数": len(wins),
        "亏损次数": len(losses),
        "胜率%": round(len(wins) / len(df) * 100, 2),
        "平均收益率%": round(df["收益率%"].mean(), 2),
        "中位数收益率%": round(df["收益率%"].median(), 2),
        "最大单笔收益%": round(df["收益率%"].max(), 2),
        "最大单笔亏损%": round(df["收益率%"].min(), 2),
        "平均盈利%": round(avg_win, 2),
        "平均亏损%": round(avg_loss, 2),
        "盈亏比": round(pl_ratio, 2) if pl_ratio else None,
    }])


def summarize_ml_by_hold_days(results_df: pd.DataFrame) -> pd.DataFrame:
    if results_df.empty:
        return pd.DataFrame()
    rows = []
    for hd in sorted(results_df["持有天数"].unique()):
        s = summarize_ml_backtest(results_df, int(hd))
        if not s.empty:
            rows.append(s)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def generate_similarity_report(
    similarity_detail: pd.DataFrame,
    similarity_stock: pd.DataFrame,
    model_stats: dict | None = None,
    template_info: list[dict] | None = None,
    backtest_trades: pd.DataFrame | None = None,
    backtest_summary: pd.DataFrame | None = None,
    output_file: str = "output/ml_similarity/report.xlsx",
):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        if similarity_stock is not None and not similarity_stock.empty:
            similarity_stock.to_excel(writer, sheet_name="相似度排名", index=False)
        if similarity_detail is not None and not similarity_detail.empty:
            similarity_detail.to_excel(writer, sheet_name="明细匹配", index=False)
        if template_info:
            pd.DataFrame(template_info).to_excel(writer, sheet_name="模板摘要", index=False)
        if backtest_summary is not None and not backtest_summary.empty:
            backtest_summary.to_excel(writer, sheet_name="回测汇总", index=False)
        if backtest_trades is not None and not backtest_trades.empty:
            backtest_trades.to_excel(writer, sheet_name="回测明细", index=False)
        if model_stats:
            rows = []
            for k, v in model_stats.items():
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        rows.append({"指标": f"{k}/{kk}", "值": vv})
                else:
                    rows.append({"指标": k, "值": v})
            pd.DataFrame(rows).to_excel(writer, sheet_name="模型统计", index=False)
    return output_file
