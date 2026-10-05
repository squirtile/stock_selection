import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from flask import Flask

from web.views import web_bp


class ResearchWorkspaceUiTest(unittest.TestCase):
    def render_home(self):
        app = Flask(__name__)
        app.register_blueprint(web_bp)
        stock = {
            "code": "600001", "name": "测试股份", "price": 10.5, "pct": 2.1,
            "industry": "电子", "marketCap": 100, "score": 82,
            "categories": ["策略信号"], "strategyCount": 1,
            "strategyTypes": [{"name": "测试策略", "group": "趋势", "groupKey": "趋势"}],
            "mlModels": [], "sectorLabel": "",
        }
        data = {
            "stocks": [stock], "marketContext": {"tradeDate": "20261005"},
            "backtestReview": {}, "time": "2026-10-05 15:00:00", "total": 1,
            "intradayInitial": {},
            "tabGroups": [{"key": "策略信号", "label": "策略信号", "count": 1,
                           "children": [{"key": "测试策略", "label": "测试策略", "count": 1}]}],
        }
        dashboard = {
            "historyRows": [{"strategy": "测试策略", "direction": "看涨", "historyEvaluated": 10,
                             "historyWins": 6, "historyWinRate": 60, "historyAvgPct": 1.2,
                             "reviewDays": 5}],
            "historyStart": "2026-09-01", "historyEnd": "2026-10-05", "totalRecords": 10,
        }
        with patch("web.views._load_stocks_data", return_value=data), \
             patch("backtest.strategy_history_store.load_dashboard", return_value=dashboard), \
             patch("backtest.intraday_history_store.load_intraday_dashboard", return_value={"rows": []}):
            response = app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.get_data(as_text=True), "html.parser")

    def test_page_keeps_registered_name_and_priority_navigation_order(self):
        soup = self.render_home()
        self.assertEqual(soup.select_one(".topbar-brand").get_text(" ", strip=True).split()[-1], "策略实验室")
        for count in soup.select("#mainTabs .nav-count"):
            count.extract()
        labels = [tab.get_text(" ", strip=True) for tab in soup.select("#mainTabs .main-tab")]
        self.assertEqual(labels[:4], ["📊 策略扫描", "⚡ 盘中实时", "📈 策略复盘", "⭐ 个人观察"])

    def test_accessible_search_watchlist_alert_and_drawer_landmarks_exist(self):
        soup = self.render_home()
        search = soup.select_one("#globalStockSearch")
        self.assertIsNotNone(search)
        self.assertEqual(search.get("aria-controls"), "globalSearchResults")
        self.assertIsNotNone(soup.select_one("#globalSearchResults[role=listbox]"))
        self.assertEqual(soup.select_one("#alertCenterButton").get("aria-label"), "打开信号提醒")
        self.assertEqual(soup.select_one("#sourceStatusButton").get("aria-label"), "查看数据源状态")
        self.assertIsNotNone(soup.select_one("#panel-watchlist"))
        self.assertEqual(soup.select_one("#researchDrawer").get("role"), "dialog")
        self.assertEqual(soup.select_one("#workspaceUtilityDrawer").get("role"), "dialog")

    def test_initial_stock_card_has_separate_watch_and_research_buttons(self):
        soup = self.render_home()
        card = soup.select_one("#stockList .stock-card[data-code='600001']")
        self.assertIsNotNone(card)
        watch = card.select_one("button[data-workspace-action='watch']")
        research = card.select_one("button[data-workspace-action='research']")
        self.assertEqual(watch.get("aria-label"), "收藏测试股份")
        self.assertEqual(research.get("aria-label"), "研究测试股份")

    def test_embedded_data_and_external_progressive_script_are_present(self):
        soup = self.render_home()
        payload = json.loads(soup.select_one("#researchWorkspaceData").string)
        self.assertEqual(payload["stocks"][0]["code"], "600001")
        self.assertEqual(payload["strategies"][0]["strategy"], "测试策略")
        scripts = [tag.get("src", "") for tag in soup.find_all("script")]
        self.assertTrue(any(src.endswith("/static/research_workspace.js?v=20261005-1") for src in scripts))

    def test_javascript_storage_helpers_fail_closed_and_deduplicate_alerts(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
const ws=require('./static/research_workspace.js');
const corrupt={getItem:()=>'{bad'};
const denied={getItem:()=>{throw new Error('denied')}};
const original=[{code:'600001',name:'甲'}];
const added=ws.toggleWatchlist(original,{code:'600002',name:'乙'});
const removed=ws.toggleWatchlist(added,{code:'600001',name:'甲'});
const alerts=ws.uniqueAlerts([{id:'a'},{id:'a'},{id:'b'}],['b']);
console.log(JSON.stringify({
  corrupt:ws.loadStoredArray(corrupt,'x'), denied:ws.loadStoredArray(denied,'x'),
  original, added, removed, alerts
}));
"""
        result = subprocess.run(["node", "-e", program], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["corrupt"], [])
        self.assertEqual(value["denied"], [])
        self.assertEqual(value["original"], [{"code": "600001", "name": "甲"}])
        self.assertEqual([row["code"] for row in value["added"]], ["600001", "600002"])
        self.assertEqual([(row["code"], row["name"]) for row in value["removed"]], [("600002", "乙")])
        self.assertEqual(value["alerts"], {"all": [{"id": "a"}, {"id": "b"}], "unread": [{"id": "a"}]})


if __name__ == "__main__":
    unittest.main()
