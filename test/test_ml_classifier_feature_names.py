import unittest
import warnings

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from ml_engine.ml_classifier import MLPatternModel


class MLClassifierFeatureNameTest(unittest.TestCase):
    def test_predict_proba_works_without_feature_name_warnings(self):
        model = MLPatternModel(lookback=3, feature_cols=["a", "b"])
        X = np.array([
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            [0.8, 0.7, 0.6, 0.5, 0.4, 0.3],
        ], dtype=float)
        y = np.array([0, 0, 1, 1])

        # Fit a plain sklearn estimator inside the wrapper to mimic older pickles.
        model.model = RandomForestClassifier(random_state=0, n_estimators=10)
        model.model.fit(X, y)
        model.scaler = StandardScaler()
        model.scaler.fit(X)
        model._fitted = True

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            prob = model.predict_proba(np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=float))

        self.assertIsInstance(prob, float)
        self.assertFalse(any("feature names" in str(w.message) for w in caught))


if __name__ == "__main__":
    unittest.main()
