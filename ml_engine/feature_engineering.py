"""
Feature engineering: normalization, dimensionality reduction, vectorization.
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA


def normalize_windows(
    X: np.ndarray, scaler: StandardScaler | None = None
) -> tuple[np.ndarray, StandardScaler]:
    """
    Standardize feature matrix across samples.

    Args:
      X: shape (n_samples, n_features)
      scaler: pre-fitted scaler, or None to fit a new one.

    Returns:
      (X_scaled, scaler) — scaled array and fitted scaler.
    """
    if scaler is None:
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
    else:
        X_scaled = scaler.transform(X)
    return X_scaled, scaler


def reduce_dimensions(
    X: np.ndarray,
    pca: PCA | None = None,
    n_components: int = 50,
) -> tuple[np.ndarray, PCA]:
    """
    Optional PCA dimensionality reduction.

    If pca is None, fits a new PCA. The number of components is capped
    at min(n_samples, n_features, n_components).

    Returns:
      (X_reduced, pca)
    """
    max_components = min(X.shape[0], X.shape[1], n_components)
    if max_components < 2:
        return X, PCA(n_components=1)

    n_components = max_components

    if pca is None:
        pca = PCA(n_components=n_components)
        X_reduced = pca.fit_transform(X)
    else:
        X_reduced = pca.transform(X)
    return X_reduced, pca


def vectorize_window(window_df: pd.DataFrame) -> np.ndarray:
    """
    Flatten a window DataFrame (lookback rows × indicator columns) to a 1D array.

    Shape: (lookback * n_indicator_cols,)
    """
    return window_df.values.flatten()
