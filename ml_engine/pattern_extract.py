"""
Pattern extraction utilities for daily K-line cache.

Key improvements in this version:
1. Supports candidate stock pool from output/a_stock_selected.xlsx or custom Excel/CSV.
2. Adds automatic launch/pre-launch window extraction for strong-stock templates.
3. Keeps the original fixed sliding-window extraction API for compatibility.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from collections import deque
from io import StringIO

import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from strategy import HIST_CACHE_DIR, prepare_hist_data
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "无法导入 strategy.HIST_CACHE_DIR / prepare_hist_data。\n"
        "请把 ml_engine 文件夹放到你的 stock_selection 工程根目录下，"
        "并确认根目录存在 strategy.py。"
    ) from exc

DEFAULT_LOOKBACK = 20

# Prefer ratio/shape features over absolute values to reduce price/market-cap distortion.
# The original indicator fields are still used as source columns after prepare_hist_data().
BASE_REQUIRED_COLUMNS = [
    "日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅", "代码"
]

ML_INDICATOR_COLUMNS = [
    "收盘相对SMA5",
    "收盘相对SMA10",
    "收盘相对SMA20",
    "收盘相对SMA60",
    "SMA5相对SMA20",
    "SMA10相对SMA20",
    "SMA20相对SMA60",
    "距60日最高收盘%",
    "距60日最低收盘%",
    "距40日最低价%",
    "近5日涨幅%",
    "近10日涨幅%",
    "近20日涨幅%",
    "近5日量能比20日",
    "成交额相对20日均额",
    "过去20日实体振幅",
    "近15日涨停次数",
    "涨跌幅",
]


def _safe_ratio(a, b, multiplier: float = 1.0):
    return np.where((pd.notna(b)) & (b != 0), a / b * multiplier, np.nan)


def _add_ml_shape_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add relative/shape features used for matching and ML."""
    df = df.copy()

    # Rolling features that may already exist from prepare_hist_data; create fallbacks if missing.
    for win in [5, 10, 20, 60]:
        col = f"SMA{win}"
        if col not in df.columns:
            df[col] = df["收盘"].rolling(win).mean()

    if "过去60日最高收盘" not in df.columns:
        df["过去60日最高收盘"] = df["收盘"].rolling(60).max()
    if "过去60日最低收盘" not in df.columns:
        df["过去60日最低收盘"] = df["收盘"].rolling(60).min()
    if "过去40日最低价" not in df.columns:
        df["过去40日最低价"] = df["最低"].rolling(40).min()
    if "过去20日平均成交量" not in df.columns:
        df["过去20日平均成交量"] = df["成交量"].rolling(20).mean()
    if "过去20日日均成交额" not in df.columns:
        df["过去20日日均成交额"] = df["成交额"].rolling(20).mean()
    if "过去20日实体振幅" not in df.columns:
        df["过去20日实体振幅"] = ((df["收盘"] - df["开盘"]).abs() / df["开盘"].replace(0, np.nan)).rolling(20).mean() * 100
    if "近15日涨停次数" not in df.columns:
        df["近15日涨停次数"] = (df["涨跌幅"] >= 9.85).rolling(15).sum()

    close = df["收盘"]
    df["收盘相对SMA5"] = _safe_ratio(close, df["SMA5"])
    df["收盘相对SMA10"] = _safe_ratio(close, df["SMA10"])
    df["收盘相对SMA20"] = _safe_ratio(close, df["SMA20"])
    df["收盘相对SMA60"] = _safe_ratio(close, df["SMA60"])
    df["SMA5相对SMA20"] = _safe_ratio(df["SMA5"], df["SMA20"])
    df["SMA10相对SMA20"] = _safe_ratio(df["SMA10"], df["SMA20"])
    df["SMA20相对SMA60"] = _safe_ratio(df["SMA20"], df["SMA60"])
    df["距60日最高收盘%"] = _safe_ratio(close - df["过去60日最高收盘"], df["过去60日最高收盘"], 100)
    df["距60日最低收盘%"] = _safe_ratio(close - df["过去60日最低收盘"], df["过去60日最低收盘"], 100)
    df["距40日最低价%"] = _safe_ratio(close - df["过去40日最低价"], df["过去40日最低价"], 100)
    df["近5日涨幅%"] = close.pct_change(5) * 100
    df["近10日涨幅%"] = close.pct_change(10) * 100
    df["近20日涨幅%"] = close.pct_change(20) * 100
    df["近5日量能比20日"] = _safe_ratio(df["成交量"].rolling(5).mean(), df["过去20日平均成交量"])
    df["成交额相对20日均额"] = _safe_ratio(df["成交额"], df["过去20日日均成交额"])

    for col in ML_INDICATOR_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def normalize_code(code: str | int) -> str:
    return str(code).strip().split(".")[0].zfill(6)


def _read_csv_tail(file_path: str, tail_rows: int | None = None) -> pd.DataFrame:
    """Read a full CSV or only its last N data rows.

    Reading only the tail is much faster for current-window scanning because
    candidate matching only needs the latest lookback window plus enough warm-up
    rows for rolling indicators.
    """
    usecols = lambda c: c in BASE_REQUIRED_COLUMNS
    if tail_rows is None or tail_rows <= 0:
        return pd.read_csv(file_path, dtype={"代码": str}, usecols=usecols)

    encodings = ["utf-8-sig", "utf-8", "gbk"]
    last_error = None
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, newline="") as f:
                header = f.readline()
                rows = deque(f, maxlen=int(tail_rows))
            if not header:
                return pd.DataFrame()
            return pd.read_csv(StringIO(header + "".join(rows)), dtype={"代码": str}, usecols=usecols)
        except Exception as exc:
            last_error = exc
            continue
    # Fallback to normal pandas read so old files with unusual encodings still work.
    return pd.read_csv(file_path, dtype={"代码": str}, usecols=usecols)


def load_hist_cache(code: str, tail_rows: int | None = None) -> pd.DataFrame:
    code = normalize_code(code)
    file_path = os.path.join(HIST_CACHE_DIR, f"{code}_bs.csv")
    if not os.path.exists(file_path):
        return pd.DataFrame()

    try:
        df = _read_csv_tail(file_path, tail_rows=tail_rows)
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    for col in BASE_REQUIRED_COLUMNS:
        if col not in df.columns:
            return pd.DataFrame()

    df["代码"] = code
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额", "涨跌幅"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["日期", "开盘", "最高", "最低", "收盘"]).sort_values("日期").reset_index(drop=True)
    return df


def extract_indicator_matrix(code: str, min_rows: int = 80, tail_rows: int | None = None) -> pd.DataFrame:
    raw = load_hist_cache(code, tail_rows=tail_rows)
    if raw.empty or len(raw) < min_rows:
        return pd.DataFrame()
    df = prepare_hist_data(raw)
    df = _add_ml_shape_features(df)
    return df


def extract_recent_template_windows_fast(
    code: str,
    lookback: int = DEFAULT_LOOKBACK,
    recent_n: int = 1,
    min_rows: int = 80,
    tail_rows: int | None = None,
) -> list[dict]:
    """Fast path for Step 2 current candidate scanning.

    It only reads the last N rows from cache/hist and extracts the latest
    recent_n windows. This is intended for current matching only. Historical
    template extraction and historical backtests still use full data.
    """
    code = normalize_code(code)
    recent_n = max(1, int(recent_n or 1))
    if tail_rows is None:
        # Enough warm-up for SMA60, pct_change(20), rolling volume and the
        # earliest requested recent window. Keep it conservative for custom
        # prepare_hist_data logic.
        tail_rows = max(180, lookback + recent_n + 120)
    min_needed = max(min_rows, lookback + recent_n + 70)
    df = extract_indicator_matrix(code, min_rows=min(min_rows, tail_rows), tail_rows=tail_rows)
    if df.empty or len(df) < min(lookback, len(df)):
        return []

    records = []
    start_t = max(lookback - 1, len(df) - recent_n)
    for t in range(start_t, len(df)):
        rec = _window_to_record(code, df, t, lookback, source="recent_fast")
        if rec is not None:
            records.append(rec)
    return records


def _load_all_indicator_matrices(codes: list[str], min_rows: int = 80) -> dict[str, pd.DataFrame]:
    results = {}
    for code in codes:
        code = normalize_code(code)
        df = extract_indicator_matrix(code, min_rows=min_rows)
        if not df.empty:
            results[code] = df
    return results


def _window_to_record(code: str, df: pd.DataFrame, t: int, lookback: int, source: str = "") -> dict | None:
    indicator_arr = df[ML_INDICATOR_COLUMNS].values
    window = indicator_arr[t - lookback + 1: t + 1, :]
    if window.shape[0] != lookback or not np.all(np.isfinite(window)):
        return None
    return {
        "code": normalize_code(code),
        "date": df.iloc[t]["日期"],
        "window_start": df.iloc[t - lookback + 1]["日期"],
        "window_end": df.iloc[t]["日期"],
        "window_df": df.iloc[t - lookback + 1: t + 1].copy(),
        "vector": window.flatten().astype(np.float64).copy(),
        "close": float(df.iloc[t]["收盘"]),
        "source": source,
    }


def build_window_dataset(
    codes: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    forward_horizon: int = 5,
    target_pct: float = 5.0,
    min_rows: int = 80,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    X_list, y_list, meta_list = [], [], []
    matrices = _load_all_indicator_matrices(codes, min_rows=min_rows)

    for code, df in matrices.items():
        closes = df["收盘"].values
        n = len(df)
        for t in range(lookback - 1, n - forward_horizon):
            rec = _window_to_record(code, df, t, lookback, source="train")
            if rec is None:
                continue
            current_close = closes[t]
            future_close = closes[t + forward_horizon]
            if pd.isna(current_close) or pd.isna(future_close) or current_close <= 0:
                continue
            future_return = (future_close / current_close - 1) * 100
            X_list.append(rec["vector"])
            y_list.append(1 if future_return >= target_pct else 0)
            meta_list.append({
                "code": code,
                "date": df.iloc[t]["日期"],
                "window_start": rec["window_start"],
                "window_end": rec["window_end"],
                "future_return": round(float(future_return), 2),
            })

    if not X_list:
        return np.array([]), np.array([]), []
    return np.array(X_list, dtype=np.float64), np.array(y_list, dtype=np.int32), meta_list


def extract_template_windows(
    template_codes: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    date_range: tuple[str, str] | None = None,
    min_rows: int = 80,
    recent_n: int | None = None,
) -> list[dict]:
    matrices = _load_all_indicator_matrices(template_codes, min_rows=min_rows)
    templates = []
    start = pd.Timestamp(date_range[0]) if date_range else None
    end = pd.Timestamp(date_range[1]) if date_range else None

    for code, df in matrices.items():
        records = []
        for t in range(lookback - 1, len(df)):
            d = df.iloc[t]["日期"]
            if start is not None and not (start <= d <= end):
                continue
            rec = _window_to_record(code, df, t, lookback, source="manual_range" if date_range else "all")
            if rec is not None:
                records.append(rec)
        if recent_n is not None and len(records) > recent_n:
            records = records[-recent_n:]
        templates.extend(records)
    return templates


@dataclass
class LaunchRule:
    """Rules used to detect recent launch points in strong stocks."""
    lookback_low_days: int = 60
    search_recent_days: int = 80
    launch_pct: float = 5.0
    volume_ratio: float = 1.5
    max_pre_20d_return: float = 25.0
    max_distance_from_60d_low_pct: float = 45.0
    require_above_ma20: bool = True


def find_launch_points(df: pd.DataFrame, rule: LaunchRule | None = None) -> list[int]:
    """Detect launch/start bars. Returns row indices ordered from old to new."""
    if rule is None:
        rule = LaunchRule()
    if df.empty or len(df) < max(80, rule.lookback_low_days + 5):
        return []

    pct = df["涨跌幅"].astype(float)
    close = df["收盘"].astype(float)
    vol = df["成交量"].astype(float)
    vol20 = df.get("过去20日平均成交量", vol.rolling(20).mean())
    low60 = df.get("过去60日最低收盘", close.rolling(60).min())
    ma20 = df.get("SMA20", close.rolling(20).mean())

    start_idx = max(rule.lookback_low_days, len(df) - rule.search_recent_days)
    candidates = []
    for t in range(start_idx, len(df)):
        if pd.isna(pct.iloc[t]) or pct.iloc[t] < rule.launch_pct:
            continue
        if pd.isna(vol20.iloc[t]) or vol20.iloc[t] <= 0 or vol.iloc[t] / vol20.iloc[t] < rule.volume_ratio:
            continue
        if rule.require_above_ma20 and (pd.isna(ma20.iloc[t]) or close.iloc[t] < ma20.iloc[t]):
            continue
        if pd.notna(low60.iloc[t]) and low60.iloc[t] > 0:
            dist_low = (close.iloc[t] / low60.iloc[t] - 1) * 100
            if dist_low > rule.max_distance_from_60d_low_pct:
                continue
        if t >= 20:
            pre_ret = (close.iloc[t - 1] / close.iloc[t - 20] - 1) * 100 if close.iloc[t - 20] > 0 else 999
            if pre_ret > rule.max_pre_20d_return:
                continue
        candidates.append(t)

    # Avoid multiple adjacent launch bars: keep the first within a 5-day cluster.
    filtered = []
    for t in candidates:
        if not filtered or t - filtered[-1] > 5:
            filtered.append(t)
    return filtered


def extract_auto_launch_template_windows(
    template_codes: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    mode: str = "prelaunch",
    min_rows: int = 80,
    per_stock_limit: int = 3,
    rule: LaunchRule | None = None,
) -> list[dict]:
    """
    Automatically extract windows around detected launch points.

    mode:
      - prelaunch: window ends one day before launch bar. Best for finding stocks before acceleration.
      - launch: window ends at launch bar. Best for finding stocks already starting.
      - both: use both prelaunch and launch windows.
      - recent: only most recent windows, no launch detection.
    """
    mode = mode.lower()
    if mode == "recent":
        return extract_template_windows(template_codes, lookback=lookback, min_rows=min_rows, recent_n=per_stock_limit)

    matrices = _load_all_indicator_matrices(template_codes, min_rows=min_rows)
    templates = []
    for code, df in matrices.items():
        launch_points = find_launch_points(df, rule=rule)
        if per_stock_limit and len(launch_points) > per_stock_limit:
            launch_points = launch_points[-per_stock_limit:]

        for launch_t in launch_points:
            end_indices = []
            if mode in ("prelaunch", "both"):
                end_indices.append(launch_t - 1)
            if mode in ("launch", "both"):
                end_indices.append(launch_t)

            for end_t in end_indices:
                if end_t < lookback - 1:
                    continue
                rec = _window_to_record(code, df, end_t, lookback, source=f"auto_{mode}")
                if rec is None:
                    continue
                rec["launch_date"] = df.iloc[launch_t]["日期"]
                rec["launch_pct"] = float(df.iloc[launch_t]["涨跌幅"])
                templates.append(rec)

    return templates


def list_cached_codes() -> list[str]:
    codes = []
    if not os.path.isdir(HIST_CACHE_DIR):
        return []
    for fname in os.listdir(HIST_CACHE_DIR):
        if fname.endswith("_bs.csv"):
            codes.append(fname.replace("_bs.csv", ""))
    return sorted(set(codes))


def load_candidate_codes(candidate_file: str | None = None, default_selected: bool = False) -> list[str]:
    """Load candidate codes from an Excel/CSV file. Falls back to all cached codes."""
    path = candidate_file
    if not path and default_selected:
        path = os.path.join(PROJECT_ROOT, "output", "a_stock_selected.xlsx")
    if not path:
        return list_cached_codes()
    if not os.path.exists(path):
        print(f"[提示] 候选文件不存在，改用全部缓存股票: {path}")
        return list_cached_codes()

    try:
        if path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
    except Exception as exc:
        print(f"[提示] 候选文件读取失败，改用全部缓存股票: {exc}")
        return list_cached_codes()

    code_col = None
    for c in df.columns:
        lc = str(c).lower()
        if "代码" in str(c) or "code" in lc or "ts_code" in lc:
            code_col = c
            break
    if code_col is None:
        print("[提示] 候选文件未找到代码列，改用全部缓存股票")
        return list_cached_codes()
    codes = [normalize_code(x) for x in df[code_col].dropna().tolist()]
    cached = set(list_cached_codes())
    return sorted([c for c in set(codes) if c in cached])


def load_stock_name_map() -> dict[str, str]:
    name_map = {c: c for c in list_cached_codes()}
    return name_map


def try_load_stock_name_map() -> dict[str, str]:
    for path in [
        os.path.join(PROJECT_ROOT, "output", "a_stock_selected.xlsx"),
        os.path.join(PROJECT_ROOT, "a_stock_all.xlsx"),
    ]:
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_excel(path)
        except Exception:
            continue
        code_col = None
        name_col = None
        for c in df.columns:
            s = str(c).lower()
            if code_col is None and ("代码" in str(c) or "code" in s or "ts_code" in s):
                code_col = c
            if name_col is None and ("名称" in str(c) or "name" in s):
                name_col = c
        if code_col is not None and name_col is not None:
            df[code_col] = df[code_col].apply(normalize_code)
            return dict(zip(df[code_col], df[name_col]))
    return load_stock_name_map()
