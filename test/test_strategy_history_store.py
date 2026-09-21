import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest.strategy_history_store import load_dashboard, save_review


class StrategyHistoryStoreTest(unittest.TestCase):
    def test_upsert_and_today_history_aggregation(self):
        review = {
            "sourceTime": "2026-09-09 18:00:00",
            "stocks": [
                {"status": "已评价", "signalDate": "2026-09-09", "tradeDate": "2026-09-10",
                 "code": "600001", "name": "上涨股", "todayPct": 2.0, "signalPrice": 10,
                 "latestClose": 10.2, "sinceSignalPct": 2.0, "strategies": ["买入策略"]},
                {"status": "已评价", "signalDate": "2026-09-09", "tradeDate": "2026-09-10",
                 "code": "600002", "name": "下跌股", "todayPct": -1.0, "signalPrice": 10,
                 "latestClose": 9.9, "sinceSignalPct": -1.0, "strategies": ["买入策略", "缠论二卖"]},
                {"status": "等待下一交易日", "signalDate": "2026-09-10", "tradeDate": "2026-09-10",
                 "code": "600003", "name": "等待股", "todayPct": 3.0, "strategies": ["买入策略"]},
            ],
        }
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(save_review(folder, review), 3)
            self.assertEqual(save_review(folder, review), 3)
            dashboard = load_dashboard(folder)

        self.assertEqual(dashboard["totalRecords"], 3)
        rows = {row["strategy"]: row for row in dashboard["rows"]}
        self.assertEqual(rows["买入策略"]["todayWinRate"], 50.0)
        self.assertEqual(rows["买入策略"]["historyEvaluated"], 2)
        self.assertEqual(rows["缠论二卖"]["direction"], "看跌")
        self.assertEqual(rows["缠论二卖"]["historyWinRate"], 100.0)
        self.assertEqual(dashboard["historyRows"][0]["strategy"], "缠论二卖")
        self.assertEqual(dashboard["todayRows"][0]["todayWinRate"], 100.0)


if __name__ == "__main__":
    unittest.main()
