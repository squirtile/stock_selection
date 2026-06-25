"""
ML classifier for stock pattern prediction.

Uses LightGBM to classify whether a 20-day indicator window
will be followed by >= target_pct return within forward_horizon days.
"""

import os
import sys

import numpy as np
import pandas as pd
try:
    from lightgbm import LGBMClassifier
except ImportError:
    LGBMClassifier = None
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    confusion_matrix,
)

try:
    import joblib
except ImportError:
    joblib = None

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import ML_INDICATOR_COLUMNS, DEFAULT_LOOKBACK


class MLPatternModel:
    """
    LightGBM-based classifier for stock patterns.

    Internally stores:
      - model: LGBMClassifier
      - scaler: StandardScaler (fitted)
      - pca: PCA or None
      - feature_cols: list of indicator column names
      - lookback: window length in days
      - params: training hyperparameters dict
    """

    def __init__(
        self,
        n_estimators: int = 400,
        max_depth: int = 12,
        use_pca: bool = False,
        n_components: int = 50,
        class_weight: str = "balanced",
        random_state: int = 42,
        min_samples_leaf: int = 5,
        lookback: int = DEFAULT_LOOKBACK,
        feature_cols: list[str] | None = None,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.use_pca = use_pca
        self.n_components = n_components
        self.class_weight = class_weight
        self.random_state = random_state
        self.min_samples_leaf = min_samples_leaf
        self.lookback = lookback
        self.feature_cols = feature_cols or list(ML_INDICATOR_COLUMNS)
        self.n_features = lookback * len(self.feature_cols)

        self.model = None  # LGBMClassifier
        self.scaler: StandardScaler | None = None
        self.pca: PCA | None = None
        self._fitted = False

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        validation_split: float = 0.0,
    ) -> dict:
        """
        Fit scaler, PCA (if enabled), and LightGBM on training data.

        Args:
          X: shape (n_samples, n_features)
          y: shape (n_samples,) binary labels
          validation_split: if > 0, fraction held out for validation metrics

        Returns:
          dict with training stats and validation metrics (if split requested).
        """
        stats = {"n_samples": len(X), "n_features": X.shape[1]}

        # Count class distribution
        unique, counts = np.unique(y, return_counts=True)
        stats["class_distribution"] = dict(zip(unique.astype(int).tolist(), counts.tolist()))
        stats["positive_ratio"] = float(np.mean(y))

        if validation_split > 0:
            X_train, X_val, y_train, y_val = train_test_split(
                X, y, test_size=validation_split, random_state=self.random_state,
                stratify=y if validation_split < 0.5 else None,
            )
        else:
            X_train, y_train = X, y
            X_val, y_val = None, None

        # Fit scaler
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)

        # Fit PCA
        if self.use_pca:
            max_comp = min(X_train_scaled.shape[0], X_train_scaled.shape[1], self.n_components)
            if max_comp >= 2:
                self.n_components = max_comp
                self.pca = PCA(n_components=max_comp)
                X_train_scaled = self.pca.fit_transform(X_train_scaled)
                stats["pca_components"] = max_comp
                stats["pca_explained_variance"] = float(self.pca.explained_variance_ratio_.sum())
            else:
                self.use_pca = False
                self.pca = None

        # Keep the transformed values as numpy arrays so both LightGBM and
        # older sklearn estimators (e.g. RandomForest) receive the same input shape.
        X_train_scaled = np.asarray(X_train_scaled, dtype=np.float64)
        if X_val is not None:
            X_val_scaled = self._transform(X_val)
        else:
            X_val_scaled = None

        # Fit model
        if LGBMClassifier is None:
            raise ImportError("LightGBM not installed. Run: pip install lightgbm")
        
        self.model = LGBMClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=self.min_samples_leaf,
            random_state=self.random_state,
            n_jobs=-1,
            verbose=-1,
        )
        self.model.fit(X_train_scaled, y_train)
        self._fitted = True

        # Train-set score
        stats["train_accuracy"] = float(self.model.score(X_train_scaled, y_train))

        # Validation
        if X_val_scaled is not None:
            val_stats = self._evaluate_df(X_val_scaled, y_val)
            stats["validation"] = val_stats

        return stats

    def _transform(self, X: np.ndarray) -> np.ndarray:
        """Apply scaler and PCA to input features and return a numpy array."""
        if self.scaler is None:
            raise RuntimeError("Model not fitted; call fit() first.")
        X_scaled = self.scaler.transform(X)
        if self.pca is not None:
            X_scaled = self.pca.transform(X_scaled)
        return np.asarray(X_scaled, dtype=np.float64)

    def _evaluate(self, X: np.ndarray, y: np.ndarray) -> dict:
        """Compute validation metrics."""
        X_t = self._transform(X)
        y_pred = self.model.predict(X_t)
        y_proba = self.model.predict_proba(X_t)[:, 1]

        tn, fp, fn, tp = confusion_matrix(y, y_pred).ravel()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        return {
            "accuracy": float(self.model.score(X_t, y)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0),
            "auc_roc": float(roc_auc_score(y, y_proba)),
            "true_positives": int(tp),
            "false_positives": int(fp),
            "true_negatives": int(tn),
            "false_negatives": int(fn),
        }

    def _evaluate_df(self, X_df: pd.DataFrame, y: np.ndarray) -> dict:
        """Compute validation metrics from DataFrame."""
        y_pred = self.model.predict(X_df)
        y_proba = self.model.predict_proba(X_df)[:, 1]

        tn, fp, fn, tp = confusion_matrix(y, y_pred).ravel()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        return {
            "accuracy": float(self.model.score(X_df, y)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0),
            "auc_roc": float(roc_auc_score(y, y_proba)),
            "true_positives": int(tp),
            "false_positives": int(fp),
            "true_negatives": int(tn),
            "false_negatives": int(fn),
        }

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Return probability of the positive class (pattern → good return).

        X can be a single sample (n_features,) or a batch (m, n_features).
        Returns float for single sample, (m,) array for batch.
        """
        if not self._fitted or self.model is None:
            raise RuntimeError("Model not fitted.")
        single = X.ndim == 1
        if single:
            X = X.reshape(1, -1)
        X_t = self._transform(X)
        proba = self.model.predict_proba(X_t)[:, 1]
        if single:
            return float(proba[0])
        return proba

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Binary prediction at given probability threshold."""
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(int)

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Return feature importance as a DataFrame.

        Each feature is named as "{indicator}_t-{offset}".
        """
        if not self._fitted or self.model is None:
            raise RuntimeError("Model not fitted.")

        if self.pca is not None:
            # With PCA, we report per-principal-component importance
            rows = []
            for i in range(self.n_components):
                rows.append({
                    "component": f"PC{i+1}",
                    "importance": self.model.feature_importances_[i],
                    "explained_variance": self.pca.explained_variance_ratio_[i],
                })
            return pd.DataFrame(rows)

        # Build readable feature names
        names = []
        for offset in range(self.lookback - 1, -1, -1):
            for col in self.feature_cols:
                names.append(f"{col}_t-{offset}")
        # Truncate to actual feature count
        names = names[: len(self.model.feature_importances_)]

        df = pd.DataFrame({
            "feature": names,
            "importance": self.model.feature_importances_,
        })
        return df.sort_values("importance", ascending=False).reset_index(drop=True)

    def save(self, file_path: str):
        """Persist model to disk."""
        if joblib is None:
            raise ImportError("joblib is required for model persistence. Install with: pip install joblib")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "scaler": self.scaler,
                "pca": self.pca,
                "feature_cols": self.feature_cols,
                "lookback": self.lookback,
                "use_pca": self.use_pca,
                "n_components": self.n_components,

                # 新增：保存训练模板信息
                "template_codes": getattr(self, "template_codes", []),
                "forward_horizon": getattr(self, "forward_horizon", None),
                "target_pct": getattr(self, "target_pct", None),
                "train_time": getattr(self, "train_time", None),

                "params": {
                    "n_estimators": self.n_estimators,
                    "max_depth": self.max_depth,
                    "class_weight": self.class_weight,
                    "random_state": self.random_state,
                    "min_samples_leaf": self.min_samples_leaf,
                },
            },
            file_path,
        )

    @classmethod
    def load(cls, file_path: str) -> "MLPatternModel":
        """Restore model from disk."""
        if joblib is None:
            raise ImportError("joblib is required. Install with: pip install joblib")
        data = joblib.load(file_path)
        params = data["params"]
        instance = cls(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            use_pca=data["use_pca"],
            n_components=data["n_components"],
            class_weight=params["class_weight"],
            random_state=params["random_state"],
            min_samples_leaf=params.get("min_samples_leaf", 5),
            lookback=data["lookback"],
            feature_cols=data["feature_cols"],
        )
        instance.model = data["model"]
        instance.scaler = data["scaler"]
        instance.pca = data["pca"]
        instance.template_codes = data.get("template_codes", [])
        instance.forward_horizon = data.get("forward_horizon", None)
        instance.target_pct = data.get("target_pct", None)
        instance.train_time = data.get("train_time", None)
        instance._fitted = True
        return instance

    def __repr__(self) -> str:
        status = "fitted" if self._fitted else "not fitted"
        return (
            f"MLPatternModel(lookback={self.lookback}, "
            f"n_features={self.n_features}, "
            f"n_estimators={self.n_estimators}, "
            f"max_depth={self.max_depth}, "
            f"use_pca={self.use_pca}, "
            f"status={status})"
        )
