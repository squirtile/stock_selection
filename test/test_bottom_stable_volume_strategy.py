import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import strategy
import daily_report
import main
from strategies.registry import evaluate_daily_strategies, get_strategy_type_map


STRATEGY_NAME = "底部均量后2倍放量"


def _history(*, unstable_volume: bool = False, failed_probe: bool = False) -> pd.DataFrame:
    size = 80
    rows = []
    for index, date in enumerate(pd.bdate_range("2026-05-01", periods=size)):
        rows.append({
            "日期": date,
            "开盘": 9.98,
            "收盘": 10.00,
            "最高": 10.10,
            "最低": 9.90,
            "成交量": 100.0,
            "成交额": 1_000_000.0,
            "涨跌幅": 0.2,
        })

    # 拉开60日价格区间，使最新收盘位于区间底部约32%。
    rows[25]["最高"] = 12.00
    rows[27]["最低"] = 9.50

    if failed_probe:
        probe = size - 20
        rows[probe].update({"开盘": 10.00, "收盘": 10.05, "最高": 10.30, "最低": 9.95, "成交量": 160.0, "涨跌幅": 0.5})

    if unstable_volume:
        for offset in range(1, 14):
            rows[-1 - offset]["成交量"] = 60.0 if offset % 2 else 140.0

    rows[-1].update({
        "开盘": 10.00,
        "收盘": 10.30,
        "最高": 10.35,
        "最低": 9.95,
        "成交量": 220.0,
        "成交额": 2_200_000.0,
        "涨跌幅": 3.0,
    })
    return pd.DataFrame(rows)


class BottomStableVolumeStrategyTest(unittest.TestCase):
    def _signals(self, frame: pd.DataFrame):
        prepared = strategy.prepare_hist_data(frame)
        return prepared.iloc[-1], evaluate_daily_strategies(prepared.iloc[-1])

    def test_selects_bottom_bullish_double_volume_after_stable_13_days(self):
        latest, signals = self._signals(_history(failed_probe=True))
        names = [signal.name for signal in signals]

        self.assertIn(STRATEGY_NAME, names)
        signal = next(signal for signal in signals if signal.name == STRATEGY_NAME)
        self.assertEqual(int(latest["前期放量突破失败次数"]), 1)
        self.assertIn("试盘1次", signal.reason)
        self.assertGreaterEqual(float(latest["底部放量倍数"]), 2.0)

    def test_rejects_double_volume_when_previous_13_days_are_not_stable(self):
        latest, signals = self._signals(_history(unstable_volume=True))

        self.assertGreater(float(latest["13日量能变异系数"]), 0.25)
        self.assertNotIn(STRATEGY_NAME, [signal.name for signal in signals])

    def test_registers_strategy_under_volume_start_group(self):
        strategy_map = get_strategy_type_map()

        self.assertEqual(strategy_map[STRATEGY_NAME]["groupKey"], "放量启动")

    def test_daily_card_metrics_are_only_exposed_for_this_strategy(self):
        row = pd.Series({
            "底部放量倍数": 2.2,
            "13日量能变异系数": 0.12,
            "前期放量突破失败次数": 1,
        })
        strategy_types = [{"name": STRATEGY_NAME, "group": "放量启动", "groupKey": "放量启动"}]

        metrics = daily_report._bottom_stable_volume_metrics(row, strategy_types)

        self.assertEqual(metrics, {
            "bottomVolumeMultiple": 2.2,
            "bottomVolumeVariationPct": 12.0,
            "bottomFailedProbeCount": 1,
        })
        self.assertEqual(daily_report._bottom_stable_volume_metrics(row, []), {})

    def test_signal_export_keeps_bottom_volume_metrics_for_daily_page(self):
        source = pd.DataFrame([{
            "代码": "002611", "名称": "东方精工", "K线日期": "2026-09-23",
            "信号类型": "突破反转", "突破反转策略": STRATEGY_NAME, "主升策略": "",
            "突破反转策略数": 1, "主升策略数": 0, "命中策略数": 1,
            "收盘价": 14.38, "今日涨跌幅": 3.38, "行业": "专用机械",
            "总市值_亿元": 100.0, "量比": 2.55, "15日涨停": 0,
            "13日量能变异系数": 0.125, "底部放量倍数": 2.552,
            "60日价格区间位置": 0.203, "前期放量突破失败次数": 1,
        }])

        exported = main.prepare_signal_export_df(source, {})

        self.assertEqual(float(exported.iloc[0]["底部放量倍数"]), 2.55)
        self.assertEqual(float(exported.iloc[0]["13日量能变异系数"]), 0.12)
        self.assertEqual(int(exported.iloc[0]["前期放量突破失败次数"]), 1)


if __name__ == "__main__":
    unittest.main()
