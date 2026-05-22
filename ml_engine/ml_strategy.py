"""
ML strategy evaluation that uses a trained MLPatternModel to score stocks.

Provides a standalone evaluation path (does not modify BaseDailyStrategy
interface) since ML needs multi-row context, not just a single row.
"""

import os
import sys

import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import (
    extract_indicator_matrix,
    ML_INDICATOR_COLUMNS,
    DEFAULT_LOOKBACK,
)
from ml_engine.ml_classifier import MLPatternModel


def evaluate_ml_signal(
    model: MLPatternModel,
    code: str,
    threshold: float = 0.65,
) -> dict | None:
    """
    Evaluate ML signal for the most recent trading day of a stock.

    Loads the stock's daily data, extracts the most recent lookback-day
    indicator window, and runs model inference.

    Returns:
      - dict with 'code', 'date', 'ml_score', 'signal' (bool),
        'future_return' (NaN if not yet known), or
      - None if data is insufficient.
    """
    df = extract_indicator_matrix(code, min_rows=model.lookback + 10)
    if df.empty or len(df) < model.lookback:
        return None

    indicator_arr = df[model.feature_cols].values

    # Most recent complete window
    t = len(df) - 1
    window = indicator_arr[t - model.lookback + 1 : t + 1, :]
    if not np.all(np.isfinite(window)):
        # Try one step back
        t = len(df) - 2
        window = indicator_arr[t - model.lookback + 1 : t + 1, :]
        if not np.all(np.isfinite(window)):
            return None

    vec = window.flatten().astype(np.float64)

    try:
        score = model.predict_proba(vec)
    except Exception:
        return None

    return {
        "code": code,
        "date": str(df.iloc[t]["日期"])[:10],
        "ml_score": round(float(score), 4),
        "signal": bool(score >= threshold),
        "close": float(df.iloc[t]["收盘"]),
    }


def scan_ml_signals(
    model: MLPatternModel,
    codes: list[str],
    threshold: float = 0.65,
) -> pd.DataFrame:
    """
    Scan multiple stocks for ML signals.

    Returns a DataFrame with columns: 代码, 日期, ML分数, ML信号, 收盘价,
    sorted by ML score descending.
    """
    results = []
    for code in codes:
        result = evaluate_ml_signal(model, code, threshold=threshold)
        if result is not None:
            results.append(result)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.rename(
        columns={
            "code": "代码",
            "date": "日期",
            "ml_score": "ML分数",
            "signal": "ML信号",
            "close": "收盘价",
        }
    )
    df = df.sort_values("ML分数", ascending=False).reset_index(drop=True)
    return df


def scan_ml_signals_historical(
    model: MLPatternModel,
    code: str,
    threshold: float = 0.65,
) -> list[dict]:
    """
    Scan all historical windows for a single stock.

    Returns a list of signal dicts for each valid window position,
    each containing: code, date, ml_score, signal, close.
    """
    df = extract_indicator_matrix(code, min_rows=model.lookback + 10)
    if df.empty or len(df) < model.lookback:
        return []

    indicator_arr = df[model.feature_cols].values
    closes = df["收盘"].values
    dates = df["日期"].values
    n = len(df)
    results = []

    for t in range(model.lookback - 1, n):
        window = indicator_arr[t - model.lookback + 1 : t + 1, :]
        if not np.all(np.isfinite(window)):
            continue

        vec = window.flatten().astype(np.float64)
        try:
            score = model.predict_proba(vec)
        except Exception:
            continue

        results.append({
            "code": code,
            "date": str(dates[t])[:10],
            "ml_score": round(float(score), 4),
            "signal": bool(score >= threshold),
            "close": float(closes[t]),
        })

    return results
