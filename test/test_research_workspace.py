import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class ResearchWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "output").mkdir()
        (self.root / "cache").mkdir()

    def write_json(self, name, payload):
        path = self.root / "output" / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def write_snapshot(self, day="20261005", rows=None):
        rows = rows or []
        path = self.root / "cache" / f"tushare_a_stock_spot_{day}.csv"
        fields = ["代码", "名称", "最新价", "涨跌幅", "行业", "总市值_亿元", "交易日"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    @staticmethod
    def stock(code="600001", name="测试股份", **extra):
        row = {
            "code": code,
            "name": name,
            "price": 10.5,
            "pct": 2.1,
            "industry": "电子",
            "score": 82,
            "categories": ["策略信号"],
            "strategyTypes": [{"name": "测试买点", "groupKey": "趋势跟踪"}],
            "strategyCount": 1,
        }
        row.update(extra)
        return row

    def test_overview_calculates_breadth_and_isolates_broken_source(self):
        from tools.research_workspace import build_workspace_overview

        self.write_snapshot(rows=[
            {"代码": "600001", "名称": "甲", "最新价": 10, "涨跌幅": 1, "行业": "电子", "总市值_亿元": 10, "交易日": "20261005"},
            {"代码": "600002", "名称": "乙", "最新价": 11, "涨跌幅": -2, "行业": "医药", "总市值_亿元": 11, "交易日": "20261005"},
            {"代码": "600003", "名称": "丙", "最新价": 12, "涨跌幅": 0, "行业": "银行", "总市值_亿元": 12, "交易日": "20261005"},
            {"代码": "600004", "名称": "丁", "最新价": 13, "涨跌幅": 9.8, "行业": "机械", "总市值_亿元": 13, "交易日": "20261005"},
            {"代码": "600005", "名称": "戊", "最新价": 14, "涨跌幅": -9.6, "行业": "地产", "总市值_亿元": 14, "交易日": "20261005"},
        ])
        self.write_json("mini_program_stocks.json", {"time": "2026-10-05 14:30:00", "stocks": []})
        self.write_json("intraday_candidates.json", {"time": "2026-10-05 14:59:00", "stocks": []})
        (self.root / "output" / "money_flow.json").write_text("{broken", encoding="utf-8")

        result = build_workspace_overview(self.root, now=datetime(2026, 10, 5, 15, 0))

        self.assertEqual(result["breadth"]["tradeDate"], "2026-10-05")
        self.assertEqual(result["breadth"]["advances"], 2)
        self.assertEqual(result["breadth"]["declines"], 2)
        self.assertEqual(result["breadth"]["flat"], 1)
        self.assertEqual(result["breadth"]["limitUp"], 1)
        self.assertEqual(result["breadth"]["limitDown"], 1)
        self.assertEqual(result["breadth"]["medianPct"], 0.0)
        self.assertEqual(result["sources"]["strategy"]["status"], "ok")
        self.assertEqual(result["sources"]["intraday"]["status"], "ok")
        self.assertEqual(result["sources"]["moneyflow"]["status"], "error")
        self.assertTrue(result["degraded"])

    def test_old_embedded_date_is_stale_even_if_file_is_recent(self):
        from tools.research_workspace import build_workspace_overview

        self.write_json("intraday_candidates.json", {"time": "2026-10-02 14:59:00", "stocks": []})
        result = build_workspace_overview(self.root, now=datetime(2026, 10, 5, 15, 0))
        self.assertEqual(result["sources"]["intraday"]["status"], "stale")
        self.assertEqual(result["sources"]["intraday"]["dataTime"], "2026-10-02 14:59:00")

    def test_dated_source_rows_take_precedence_over_new_generation_time(self):
        from tools.research_workspace import build_workspace_overview

        self.write_json("sector_heat.json", {
            "generated_at": "2026-10-05 14:59:00",
            "dates": ["20261001"],
            "data": {},
        })
        result = build_workspace_overview(self.root, now=datetime(2026, 10, 5, 15, 0))
        self.assertEqual(result["sources"]["sector"]["status"], "stale")
        self.assertEqual(result["sources"]["sector"]["dataTime"], "2026-10-01 00:00:00")

    def test_search_deduplicates_sources_and_prefers_intraday_quote(self):
        from tools.research_workspace import search_stocks

        self.write_json("mini_program_stocks.json", {
            "time": "2026-10-05 08:30:00",
            "stocks": [self.stock(name="测试科技", price=10.0, pct=1.0)],
        })
        self.write_json("intraday_candidates.json", {
            "time": "2026-10-05 14:59:00",
            "stocks": [self.stock(name="测试科技", price=10.8, pct=8.0, reasons=["盘中放量"])],
        })
        self.write_snapshot(rows=[
            {"代码": "600001", "名称": "测试科技", "最新价": 10.6, "涨跌幅": 6.0, "行业": "电子", "总市值_亿元": 100, "交易日": "20261005"},
        ])

        rows = search_stocks(self.root, "测试", limit=20)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "600001")
        self.assertEqual(rows[0]["price"], 10.8)
        self.assertEqual(rows[0]["pct"], 8.0)
        self.assertEqual(set(rows[0]["sources"]), {"行情快照", "每日策略", "盘中实时"})
        self.assertTrue(rows[0]["hasSignal"])

    def test_search_uses_dated_card_quote_instead_of_undated_signal_price(self):
        from tools.research_workspace import search_stocks

        daily = self.stock(price=3.2, pct=None)
        daily["cardQuote"] = {
            "price": 10.7, "pct": 7.0, "tradeDate": "2026-10-05",
            "industry": "电子", "marketCap": 101,
        }
        self.write_json("mini_program_stocks.json", {
            "time": "2026-10-05 19:30:00", "stocks": [daily],
        })
        self.write_snapshot(rows=[
            {"代码": "600001", "名称": "测试股份", "最新价": 10.6, "涨跌幅": 6.0,
             "行业": "电子", "总市值_亿元": 100, "交易日": "20261005"},
        ])
        row = search_stocks(self.root, "600001")[0]
        self.assertEqual(row["price"], 10.7)
        self.assertEqual(row["pct"], 7.0)
        self.assertEqual(row["dataTime"], "2026-10-05")

    def test_newer_snapshot_quote_is_not_overwritten_by_older_daily_signal(self):
        from tools.research_workspace import search_stocks

        self.write_json("mini_program_stocks.json", {
            "time": "2026-10-02 19:30:00", "stocks": [self.stock(price=3.2, pct=1.0)],
        })
        self.write_snapshot(rows=[
            {"代码": "600001", "名称": "测试股份", "最新价": 10.6, "涨跌幅": 6.0,
             "行业": "电子", "总市值_亿元": 100, "交易日": "20261005"},
        ])
        row = search_stocks(self.root, "600001")[0]
        self.assertEqual(row["price"], 10.6)
        self.assertEqual(row["pct"], 6.0)
        self.assertEqual(row["dataTime"], "2026-10-05")

    def test_empty_or_huge_search_is_bounded(self):
        from tools.research_workspace import search_stocks

        self.assertEqual(search_stocks(self.root, "   "), [])
        self.write_snapshot(rows=[
            {"代码": str(600000 + i), "名称": f"测试{i}", "最新价": 10, "涨跌幅": 0, "行业": "", "总市值_亿元": 1, "交易日": "20261005"}
            for i in range(60)
        ])
        self.assertEqual(len(search_stocks(self.root, "测试", limit=999)), 50)

    def test_stock_research_uses_existing_score_breakdown_without_regrading(self):
        from tools.research_workspace import build_stock_research

        self.write_json("mini_program_stocks.json", {
            "time": "2026-10-05 08:30:00",
            "stocks": [self.stock(score=88)],
        })
        self.write_json("intraday_candidates.json", {
            "time": "2026-10-05 14:59:00",
            "stocks": [self.stock(
                score=67,
                scoreBreakdown={"base": 67, "sector": -9, "strategy": 7, "confidence": 2},
                reasons=["盘中放量", "30分钟缠论2买"],
                mainNetInflow=12000000,
                mainNetRatio=3.2,
            )],
        })
        (self.root / "cache" / "hist").mkdir()
        (self.root / "cache" / "hist" / "600001_bs.csv").write_text("date,open,close,high,low,volume\n2026-10-02,10,10.5,10.8,9.9,1000\n", encoding="utf-8")

        result = build_stock_research(self.root, "600001")

        self.assertEqual(result["current"]["score"], 67)
        self.assertEqual(result["scoreExplanation"]["total"], 67)
        self.assertEqual(result["scoreExplanation"]["mode"], "existing-breakdown")
        self.assertEqual(result["scoreExplanation"]["breakdown"]["sector"], -9)
        self.assertEqual(result["signals"][0]["source"], "盘中实时")
        self.assertTrue(result["klineAvailable"])
        self.assertEqual(result["moneyFlow"]["mainNetRatio"], 3.2)
        self.assertIsNone(build_stock_research(self.root, "ABC"))

    def test_watchlist_alert_ids_are_stable_and_sources_are_separate(self):
        from tools.research_workspace import build_watchlist_alerts

        self.write_json("mini_program_stocks.json", {
            "time": "2026-10-05 08:30:00",
            "stocks": [self.stock(signalDate="2026-10-05")],
        })
        self.write_json("intraday_candidates.json", {
            "time": "2026-10-05 14:59:00",
            "stocks": [self.stock(briefReasons=["30分钟缠论2买"])],
        })

        first = build_watchlist_alerts(self.root, ["600001", "bad", "600001"])
        second = build_watchlist_alerts(self.root, ["600001"])

        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertEqual(len({row["id"] for row in first}), 2)
        self.assertEqual({row["kind"] for row in first}, {"daily", "intraday"})


if __name__ == "__main__":
    unittest.main()
