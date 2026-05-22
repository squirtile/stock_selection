"""
Global StandardScaler for consistent similarity computation.

Instead of fitting a new scaler per comparison (which distorts the
similarity metric), fit ONCE on a broad market sample and reuse.
"""

import os
import sys

import numpy as np
from sklearn.preprocessing import StandardScaler

try:
    import joblib
except ImportError:
    joblib = None

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_SCALER_PATH = os.path.join(PROJECT_ROOT, "output", "ml_models", "global_scaler.pkl")


def _load_descriptor_samples(
    codes: list[str],
    n_windows_per_stock: int = 5,
    lookback: int = 20,
) -> np.ndarray:
    """Load descriptor windows (8-dim) from each stock for scaler fitting."""
    from ml_engine.pattern_extract import extract_descriptor_windows

    all_windows = extract_descriptor_windows(
        codes, lookback=lookback, max_windows_per_stock=n_windows_per_stock
    )
    if not all_windows:
        return np.array([])
    return np.array([w["vector"] for w in all_windows], dtype=np.float64)


def fit_global_scaler(
    n_stocks: int = 500,
    scaler_path: str | None = None,
) -> StandardScaler:
    """
    Fit a StandardScaler on a representative market sample and save to disk.

    Args:
      n_stocks: number of random stocks to sample
      scaler_path: path to save the scaler (default: output/ml_models/global_scaler.pkl)

    Returns:
      fitted StandardScaler
    """
    if scaler_path is None:
        scaler_path = DEFAULT_SCALER_PATH

    from ml_engine.pattern_extract import list_cached_codes

    all_codes = list_cached_codes()
    if len(all_codes) > n_stocks:
        rng = np.random.RandomState(42)
        codes = rng.choice(all_codes, size=n_stocks, replace=False).tolist()
    else:
        codes = all_codes

    print(f"拟合全局 Scaler (8维形态描述符): 从 {len(codes)} 只股票采样...")
    X = _load_descriptor_samples(codes)
    print(f"  样本数: {len(X)} 个窗口, 特征维度: {X.shape[1]}")

    scaler = StandardScaler()
    scaler.fit(X)

    os.makedirs(os.path.dirname(scaler_path), exist_ok=True)
    if joblib is None:
        raise ImportError("joblib is required. Install with: pip install joblib")
    joblib.dump(scaler, scaler_path)
    print(f"  全局 Scaler 已保存: {scaler_path}")

    return scaler


def load_global_scaler(scaler_path: str | None = None) -> StandardScaler:
    """
    Load the global scaler from disk. Auto-fits if not found.

    Args:
      scaler_path: path to the saved scaler

    Returns:
      fitted StandardScaler
    """
    if scaler_path is None:
        scaler_path = DEFAULT_SCALER_PATH

    if os.path.exists(scaler_path):
        if joblib is None:
            raise ImportError("joblib is required. Install with: pip install joblib")
        return joblib.load(scaler_path)

    print("全局 Scaler 未找到, 自动拟合...")
    return fit_global_scaler(scaler_path=scaler_path)


def get_global_scaler(scaler_path: str | None = None) -> StandardScaler:
    """Get the global scaler (loads or auto-fits). Shorthand for load_global_scaler."""
    return load_global_scaler(scaler_path)
