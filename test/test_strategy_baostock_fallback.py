import unittest
from unittest.mock import patch

import pandas as pd

import strategy


class DummyLoginResult:
    def __init__(self, error_code="1", error_msg="network error"):
        self.error_code = error_code
        self.error_msg = error_msg


class StrategyBaoStockFallbackTest(unittest.TestCase):
    def test_scan_main_rising_stocks_falls_back_to_local_cache_when_login_fails(self):
        with patch.object(strategy, "should_update_daily_cache", return_value=True), \
             patch.object(strategy.bs, "login", return_value=DummyLoginResult(error_code="1", error_msg="network error")), \
             patch.object(strategy, "check_main_rising_signal", return_value=(True, "测试策略", {"测试字段": 1})):

            stock_pool_df = pd.DataFrame([
                {"代码": "000001", "名称": "平安银行"},
            ])

            result = strategy.scan_main_rising_stocks(stock_pool_df, cache_only=False, force_update=True)

        self.assertFalse(result.empty)
        self.assertEqual(result.iloc[0]["命中策略"], "测试策略")
        self.assertEqual(result.iloc[0]["测试字段"], 1)


if __name__ == "__main__":
    unittest.main()
