import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from flask import Flask

from web.views import web_bp


class WebDisplayPolishTest(unittest.TestCase):
    def render_home(self):
        app = Flask(__name__)
        app.register_blueprint(web_bp)
        data = {
            "stocks": [],
            "marketContext": {"tradeDate": "20261002"},
            "backtestReview": {
                "sourceTime": "2026-10-02 18:30:00",
                "reviewTime": "2026-10-05 09:00:00",
                "total": 1,
                "pending": 0,
                "stocks": [{
                    "status": "已评价",
                    "name": "测试股份",
                    "code": "600000",
                    "signalDate": "2026-10-02",
                    "tradeDate": "2026-10-05",
                    "signalPrice": 10.0,
                    "latestClose": 10.5,
                    "todayPct": 5.0,
                    "strategies": ["测试策略"],
                }],
            },
            "time": "2026-10-02 18:30:00",
            "total": 0,
            "intradayInitial": {},
            "tabGroups": [],
        }
        with patch("web.views._load_stocks_data", return_value=data), \
             patch("backtest.strategy_history_store.load_dashboard", return_value={"historyRows": []}), \
             patch("backtest.intraday_history_store.load_intraday_dashboard", return_value={"rows": []}):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.get_data(as_text=True), "html.parser")

    def test_backtest_rows_expose_mobile_card_labels(self):
        soup = self.render_home()
        row = soup.select_one("#backtestDetailTable tbody tr")
        self.assertIsNotNone(row)
        self.assertEqual(
            [cell.get("data-label") for cell in row.select("td")],
            ["状态", "股票", "选股日", "评价日", "信号价", "收盘价", "当日涨幅", "策略"],
        )

    def test_header_distinguishes_data_date_from_page_refresh_time(self):
        soup = self.render_home()
        self.assertIn("最近交易日：2026-10-02", soup.select_one(".status-row .time").get_text(" ", strip=True))
        refresh_time = soup.select_one("#pageRefreshTime")
        self.assertIsNotNone(refresh_time)
        self.assertEqual(refresh_time.get("aria-live"), "polite")

    def test_async_panels_share_loading_state_markup(self):
        soup = self.render_home()
        loading_panels = soup.select(".state-panel.state-loading")
        self.assertGreaterEqual(len(loading_panels), 4)


if __name__ == "__main__":
    unittest.main()
