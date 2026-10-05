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

    def test_page_has_clear_market_status_risk_and_share_metadata(self):
        soup = self.render_home()
        self.assertEqual(soup.title.string, "A 股策略实验室｜市场观察与策略研究")
        self.assertTrue(soup.select_one('meta[name="description"]').get("content"))
        self.assertEqual(soup.select_one('meta[property="og:site_name"]').get("content"), "策略实验室")
        self.assertIn("strategy-lab-share", soup.select_one('meta[property="og:image"]').get("content"))
        self.assertIn("最近交易日：2026-10-05", soup.select_one("#marketSessionStatus").get_text(" ", strip=True))
        self.assertIsNotNone(soup.select_one("#methodologyButton"))
        self.assertIsNotNone(soup.select_one("#dailySummaryButton"))
        risk = soup.select_one("#researchRiskNotice").get_text(" ", strip=True)
        self.assertIn("不构成投资建议", risk)
        self.assertIn("历史表现不代表未来收益", risk)
        self.assertIn("独立判断并自行承担风险", risk)

    def test_watchlist_and_score_disclosures_are_visible_without_crowding_cards(self):
        soup = self.render_home()
        warning = soup.select_one("#watchlistStorageNotice").get_text(" ", strip=True)
        self.assertIn("仅保存在当前浏览器", warning)
        self.assertIn("清理浏览器数据后可能丢失", warning)
        score = soup.select_one("#stockList button[data-workspace-action='score-info']")
        self.assertEqual(score.get_text(" ", strip=True), "评分说明")

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
        self.assertTrue(any(src.endswith("/static/research_workspace.js?v=20261005-disclosure1") for src in scripts))

    def test_strategy_comparison_landmarks_are_in_replay_panel(self):
        soup = self.render_home()
        compare = soup.select_one("#strategyCompare")
        self.assertIsNotNone(compare)
        self.assertEqual(compare.get("aria-label"), "策略横向比较")
        self.assertIsNotNone(compare.select_one("#strategyCompareChoices"))
        self.assertEqual(compare.select_one("#strategyCompareResult").get("aria-live"), "polite")

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

    def test_javascript_comparison_limit_metrics_and_degraded_overview(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
const ws=require('./static/research_workspace.js');
let selected=[];
['A','B','C','D','E'].forEach(key=>{selected=ws.selectStrategyKeys(selected,key,4)});
const limited=selected;
selected=ws.selectStrategyKeys(selected,'B',4);
const compared=ws.buildStrategyComparison([
 {strategy:'A',historyWinRate:60,historyAvgPct:1.2,historyEvaluated:10,reviewDays:5},
 {strategy:'C',historyWinRate:45,historyAvgPct:-0.2,historyEvaluated:20,reviewDays:3}
],['A','C']);
const overview=ws.marketOverviewModel({healthySources:3,totalSources:5,degraded:true,breadth:{status:'missing',total:0}});
console.log(JSON.stringify({limited,selected,compared,overview}));
"""
        result = subprocess.run(["node", "-e", program], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["limited"], ["A", "B", "C", "D"])
        self.assertEqual(value["selected"], ["A", "C", "D"])
        self.assertEqual(value["compared"][0], {"strategy": "A", "winRate": 60, "avgPct": 1.2, "sample": 10, "reviewDays": 5})
        self.assertEqual(value["compared"][1]["avgPct"], -0.2)
        self.assertEqual(value["overview"]["state"], "degraded")
        self.assertEqual(value["overview"]["sourceText"], "3/5 数据源可用")
        self.assertEqual(value["overview"]["breadthText"], "市场宽度暂无")

    def test_javascript_rejects_empty_stock_and_does_not_rewrite_same_watch_label(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
const ws=require('./static/research_workspace.js');
let value='☆',writes=0;
const button={
  get textContent(){return value}, set textContent(next){writes+=1;value=next},
  classList:{toggle:()=>{}}, setAttribute:()=>{}, title:''
};
ws.updateWatchButton(button,false);
console.log(JSON.stringify({invalid:ws.toggleWatchlist([],{}),writes,value}));
"""
        result = subprocess.run(["node", "-e", program], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["invalid"], [])
        self.assertEqual(value["writes"], 0)
        self.assertEqual(value["value"], "☆")

    def test_switching_strategy_clears_the_previously_expanded_chart(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
const ws=require('./static/research_workspace.js');
const removed=[];
const collapsed=[];
const view={
  querySelectorAll(selector){
    if(selector==='.kline-area') return [{remove:()=>removed.push('chart')}];
    if(selector==='.stock-card.is-expanded') return [{classList:{remove:name=>collapsed.push(name)}}];
    return [];
  }
};
ws.clearExpandedCharts(view);
console.log(JSON.stringify({removed,collapsed}));
"""
        result = subprocess.run(["node", "-e", program], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"removed": ["chart"], "collapsed": ["is-expanded"]})

        soup = self.render_home()
        inline_scripts = "\n".join(tag.string or "" for tag in soup.find_all("script") if not tag.get("src"))
        self.assertIn("const list=document.getElementById('stockList')", inline_scripts)
        self.assertIn("ResearchWorkspace.clearExpandedCharts(list)", inline_scripts)

    def test_javascript_exposes_strategy_glossary_search_states_and_session_text(self):
        root = Path(__file__).resolve().parents[1]
        program = r"""
const ws=require('./static/research_workspace.js');
const definition=ws.findStrategyDefinition('30分钟缠论二买');
console.log(JSON.stringify({
  definition,
  loading:ws.searchStateMarkup('loading','宁德时代'),
  empty:ws.searchStateMarkup('empty','不存在'),
  error:ws.searchStateMarkup('error','宁德时代','网络异常'),
  session:ws.marketSessionText({latestTradeDate:'2026-10-08',stateLabel:'盘中实时',lastSuccessAt:'2026-10-08 10:29:00'})
}));
"""
        result = subprocess.run(["node", "-e", program], cwd=root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["definition"]["title"], "缠论二买")
        self.assertTrue(all(value["definition"].get(key) for key in ("logic", "period", "environment", "risks")))
        self.assertIn("正在搜索", value["loading"])
        self.assertIn("没有找到", value["empty"])
        self.assertIn("重新搜索", value["error"])
        self.assertIn("最后成功更新：2026-10-08 10:29:00", value["session"])


if __name__ == "__main__":
    unittest.main()
