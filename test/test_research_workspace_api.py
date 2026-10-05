import unittest
from unittest.mock import patch


class ResearchWorkspaceApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import api_server
        cls.api_server = api_server
        cls.client = api_server.app.test_client()

    def test_overview_endpoint_returns_degraded_payload(self):
        payload = {"success": True, "degraded": True, "breadth": {"status": "missing"}}
        with patch("tools.research_workspace.build_workspace_overview", return_value=payload) as build:
            response = self.client.get("/api/workspace/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)
        build.assert_called_once_with(self.api_server.PROJECT_ROOT)

    def test_search_endpoint_handles_empty_query_and_bounds_limit(self):
        with patch("tools.research_workspace.search_stocks", return_value=[{"code": "600001"}]) as search:
            empty = self.client.get("/api/stocks/search?q=%20%20")
            response = self.client.get("/api/stocks/search?q=%E6%B5%8B%E8%AF%95&limit=999")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json()["results"], [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"], [{"code": "600001"}])
        search.assert_called_once_with(self.api_server.PROJECT_ROOT, "测试", 50)

    def test_research_endpoint_rejects_invalid_code_and_reports_missing(self):
        with patch("tools.research_workspace.build_stock_research", return_value=None) as build:
            invalid = self.client.get("/api/stock/ABC/research")
            missing = self.client.get("/api/stock/600001/research")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)
        build.assert_called_once_with(self.api_server.PROJECT_ROOT, "600001")

    def test_alert_endpoint_limits_codes_before_aggregation(self):
        codes = ",".join(f"{index:06d}" for index in range(120))
        with patch("tools.research_workspace.build_watchlist_alerts", return_value=[]) as build:
            response = self.client.get("/api/workspace/alerts", query_string={"codes": codes})
        self.assertEqual(response.status_code, 200)
        sent = build.call_args.args[1]
        self.assertEqual(len(sent), 100)
        self.assertEqual(sent[0], "000000")
        self.assertEqual(sent[-1], "000099")

    def test_home_context_exposes_filtered_history_and_catalog_without_mutating_dashboard(self):
        from web import views

        dashboard = {
            "historyRows": [
                {"strategy": "30分钟缠论二买", "direction": "看涨", "historyEvaluated": 3},
                {"strategy": "30分钟缠论二卖", "direction": "看跌", "historyEvaluated": 4},
            ],
            "totalRecords": 7,
        }
        data = {
            "stocks": [{"code": "600001", "name": "测试股份", "price": 10, "pct": 1,
                        "industry": "电子", "score": 82, "strategyTypes": [{"name": "测试策略"}]}],
            "tabGroups": [], "marketContext": {}, "backtestReview": {}, "time": "", "total": 1,
            "intradayInitial": {},
        }
        with patch("web.views._load_stocks_data", return_value=data), \
             patch("backtest.strategy_history_store.load_dashboard", return_value=dashboard), \
             patch("backtest.intraday_history_store.load_intraday_dashboard", return_value={"rows": []}), \
             patch("web.views.render_template", return_value="ok") as render:
            result = views.index()
        self.assertEqual(result, "ok")
        context = render.call_args.kwargs
        self.assertEqual([row["strategy"] for row in context["strategyHistoryJson"]], ["30分钟缠论二买"])
        self.assertEqual(context["stockCatalogJson"][0]["code"], "600001")
        self.assertEqual(len(dashboard["historyRows"]), 2)
        self.assertEqual(dashboard["totalRecords"], 7)


if __name__ == "__main__":
    unittest.main()
