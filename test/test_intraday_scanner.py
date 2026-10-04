import gzip
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intraday_scanner as scanner


def _stock():
    return {
        "code": "600000", "name": "测试股票", "price": 10.2, "pct": 2.0,
        "volume": 200000, "amount": 200_000_000, "amplitude": 3.5,
        "turnover": 5.0, "volumeRatio": 2.0, "high": 10.25, "low": 9.9,
        "open": 10.11, "prevClose": 10.0, "marketCap": 500.0,
        "industry": "银行", "source": "东方财富",
    }


def _sector(pct=1.2, breadth=70.0):
    return {
        "type": "industry", "code": "BK0475", "name": "银行", "pct": pct,
        "amount": 10_000_000_000, "turnover": 1.0, "mainNetInflow": 500_000_000,
        "mainNetRatio": 5.0, "up": 28, "down": 10, "flat": 2, "breadth": breadth,
        "leader": "领涨股票", "leaderPct": 9.2, "pctAcceleration": 0.4,
    }


def _model():
    return {
        "thresholds": {
            "minPct": -2, "maxPct": 3, "minVolumeRatio": 1.5,
            "minDayPosition": 85, "maxAmplitude": 4, "minOpeningGap": 1,
            "minBodyPct": 0,
        },
        "validation": {"precision": 10, "lift": 11.29},
        "approved": True,
    }


class IntradayScannerTest(unittest.TestCase):
    def test_eastmoney_stock_quote_includes_individual_main_money_flow(self):
        quote = {
            "f2": 10.2, "f3": 2.0, "f5": 200000, "f6": 200_000_000,
            "f7": 3.5, "f8": 5.0, "f10": 2.0, "f12": "600000",
            "f14": "测试股票", "f15": 10.25, "f16": 9.9, "f17": 10.11,
            "f18": 10.0, "f20": 50_000_000_000, "f62": 12_800_000,
            "f100": "银行", "f184": 3.2,
        }
        with patch.object(scanner, "_eastmoney_json", side_effect=[{"data": {"diff": [quote]}}, {"data": {"diff": []}}]) as request:
            stocks = scanner.fetch_eastmoney()

        self.assertEqual(stocks[0]["mainNetInflow"], 12_800_000.0)
        self.assertEqual(stocks[0]["mainNetRatio"], 3.2)
        self.assertIn("f62", request.call_args_list[0].args[0]["fields"])
        self.assertIn("f184", request.call_args_list[0].args[0]["fields"])

    def test_eastmoney_batch_money_flow_supplements_fallback_quotes(self):
        response = MagicMock()
        response.json.return_value = {
            "data": {"diff": [
                {"f12": "600000", "f62": 12_800_000, "f184": 3.2},
                {"f12": "000001", "f62": -6_500_000, "f184": -1.4},
            ]},
        }
        response.raise_for_status.return_value = None
        with patch.object(scanner, "_public_get", return_value=response) as request:
            flows = scanner.fetch_eastmoney_main_money(["600000", "000001"])

        self.assertEqual(flows["600000"], {"mainNetInflow": 12_800_000.0, "mainNetRatio": 3.2})
        self.assertEqual(flows["000001"], {"mainNetInflow": -6_500_000.0, "mainNetRatio": -1.4})
        params = request.call_args.kwargs["params"]
        self.assertIn("1.600000", params["secids"])
        self.assertIn("0.000001", params["secids"])

    def test_eastmoney_batch_money_flow_ignores_malformed_json_shape(self):
        response = MagicMock()
        response.json.return_value = None
        response.raise_for_status.return_value = None
        with patch.object(scanner, "_public_get", return_value=response):
            self.assertEqual(scanner.fetch_eastmoney_main_money(["600000"]), {})

    def test_daily_hits_keep_main_money_flow_timeline_and_mark_reversal(self):
        now = scanner.datetime(2026, 9, 28, 10, 15, 0)
        stock = _stock()
        stock.update({"mainNetInflow": 12_800_000.0, "mainNetRatio": 3.2})
        prior = _stock()
        prior.update({
            "currentMatch": True,
            "mainNetInflow": -2_000_000.0,
            "mainNetRatio": -0.5,
            "mainMoneyUpdatedAt": "2026-09-28 10:10:00",
            "mainMoneyFlowHistory": [
                {"time": "10:10", "mainNetInflow": -2_000_000.0, "mainNetRatio": -0.5, "price": 10.0, "pct": 0.2},
            ],
        })
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            hits = Path(folder) / "intraday_hits_2026-09-28.json"
            hits.write_text(json.dumps({"tradeDate": "2026-09-28", "stocks": [prior]}), encoding="utf-8")
            with (
                patch.object(scanner, "CACHE", cache),
                patch.object(scanner, "ROOT", Path(folder)),
            ):
                retained = scanner._retain_daily_hits(now, [stock], [stock])

        saved = retained[0]
        self.assertEqual(saved["mainMoneyTrend"], "由流出转流入")
        self.assertEqual(saved["mainMoneyUpdatedAt"], "2026-09-28 10:15:00")
        self.assertEqual([point["time"] for point in saved["mainMoneyFlowHistory"]], ["10:10", "10:15"])
        self.assertEqual(saved["mainMoneyFlowHistory"][-1]["mainNetInflow"], 12_800_000.0)

    def test_missing_main_money_quote_keeps_last_value_without_fake_zero(self):
        now = scanner.datetime(2026, 9, 28, 10, 15, 0)
        live = _stock()
        live["mainNetInflow"] = 99_000_000.0
        prior = _stock()
        prior.update({
            "currentMatch": False,
            "mainNetInflow": 8_000_000.0,
            "mainNetRatio": 1.8,
            "mainMoneyUpdatedAt": "2026-09-28 10:10:00",
            "mainMoneyFlowHistory": [
                {"time": "10:10", "mainNetInflow": 8_000_000.0, "mainNetRatio": 1.8, "price": 10.1, "pct": 1.0},
            ],
        })
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            hits = Path(folder) / "intraday_hits_2026-09-28.json"
            hits.write_text(json.dumps({"tradeDate": "2026-09-28", "stocks": [prior]}), encoding="utf-8")
            with (
                patch.object(scanner, "CACHE", cache),
                patch.object(scanner, "ROOT", Path(folder)),
            ):
                retained = scanner._retain_daily_hits(now, [], [live])

        saved = retained[0]
        self.assertEqual(saved["mainNetInflow"], 8_000_000.0)
        self.assertEqual(saved["mainNetRatio"], 1.8)
        self.assertEqual(saved["mainMoneyUpdatedAt"], "2026-09-28 10:10:00")
        self.assertEqual(len(saved["mainMoneyFlowHistory"]), 1)
        self.assertTrue(saved["mainMoneyStale"])

    def test_retained_stocks_outside_market_pool_receive_money_flow_only_update(self):
        now = scanner.datetime(2026, 9, 28, 14, 10, 0)
        market_stock = _stock()
        old_hit = _stock()
        old_hit["code"] = "000001"
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            hits = Path(folder) / "intraday_hits_2026-09-28.json"
            hits.write_text(json.dumps({"tradeDate": "2026-09-28", "stocks": [old_hit]}), encoding="utf-8")
            with (
                patch.object(scanner, "CACHE", cache),
                patch.object(scanner, "fetch_eastmoney_main_money", return_value={
                    "000001": {"mainNetInflow": 9_000_000.0, "mainNetRatio": 2.5},
                }),
            ):
                retention_rows, updated = scanner._with_retained_main_money([market_stock], now)

        self.assertEqual(updated, 1)
        self.assertEqual(len(retention_rows), 2)
        supplement = next(row for row in retention_rows if row["code"] == "000001")
        self.assertEqual(supplement["mainNetInflow"], 9_000_000.0)
        self.assertNotIn("price", supplement)
        self.assertEqual(len([row for row in [market_stock] if row.get("code")]), 1)

    def test_scan_deadline_returns_last_cache_without_hanging(self):
        cached = {
            "success": True, "time": "2026-09-23 11:26:11",
            "stocks": [{"code": "600000"}], "matched": 1,
        }

        def blocked_scan(_limit):
            time.sleep(0.5)
            return {"success": True, "stocks": []}

        runner = getattr(scanner, "_run_scan_with_deadline", None)
        self.assertIsNotNone(runner, "循环扫描需要整轮硬超时保护")
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            cache.write_text(json.dumps(cached), encoding="utf-8")
            started = time.monotonic()
            with (
                patch.object(scanner, "CACHE", cache),
                patch.object(scanner, "scan_intraday", side_effect=blocked_scan),
            ):
                result = runner(50, timeout_seconds=0.05)
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.3)
        self.assertTrue(result["success"])
        self.assertTrue(result["servedFromCache"])
        self.assertTrue(result["stale"])
        self.assertTrue(result["scanTimedOut"])
        self.assertEqual(result["stocks"][0]["code"], cached["stocks"][0]["code"])

    def test_public_request_bypasses_environment_proxy(self):
        response = MagicMock()
        session = MagicMock()
        session.get.return_value = response
        with patch.object(scanner.requests, "Session", return_value=session):
            self.assertIs(scanner._public_get("https://example.test/data", timeout=7), response)

        self.assertFalse(session.trust_env)
        session.get.assert_called_once_with("https://example.test/data", params=None, headers=None, timeout=7)

    def test_public_request_falls_back_to_environment_proxy(self):
        session = MagicMock()
        session.get.side_effect = scanner.requests.ConnectionError("direct unavailable")
        proxy_response = MagicMock()
        with (
            patch.object(scanner.requests, "Session", return_value=session),
            patch.object(scanner.requests, "get", return_value=proxy_response) as proxied_get,
        ):
            self.assertIs(scanner._public_get("https://example.test/data", params={"a": 1}, timeout=7), proxy_response)

        proxied_get.assert_called_once_with("https://example.test/data", params={"a": 1}, headers=None, timeout=7)

    def test_eastmoney_request_bypasses_environment_proxy(self):
        response = MagicMock()
        response.json.return_value = {"data": {"diff": []}}
        session = MagicMock()
        session.get.return_value = response
        with patch.object(scanner.requests, "Session", return_value=session):
            self.assertEqual(scanner._eastmoney_json({"pn": 1}), {"data": {"diff": []}})

        self.assertFalse(session.trust_env)
        session.get.assert_called_once()

    def test_failed_live_fetch_keeps_last_successful_cache(self):
        cached = {
            "success": True, "time": "2026-09-22 09:30:01",
            "stocks": [{"code": "600000", "mainNetInflow": 8_000_000.0, "mainNetRatio": 1.2}],
            "matched": 1,
        }
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            cache.write_text(json.dumps(cached), encoding="utf-8")
            with (
                patch.object(scanner, "CACHE", cache),
                patch.object(scanner, "_is_trading_session", return_value=True),
                patch.object(scanner, "fetch_eastmoney", side_effect=RuntimeError("upstream unavailable")),
                patch.object(scanner, "fetch_tencent_market", side_effect=RuntimeError("fallback unavailable")),
            ):
                result = scanner.scan_intraday()

        self.assertTrue(result["success"])
        self.assertTrue(result["servedFromCache"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["stocks"][0]["code"], cached["stocks"][0]["code"])
        self.assertTrue(result["stocks"][0]["mainMoneyStale"])
        self.assertIn("upstream unavailable", result["sourceError"])

    def test_selected_stock_does_not_turn_retained_money_into_fresh_quote(self):
        now = scanner.datetime(2026, 9, 28, 10, 15, 0)
        selected = _stock()
        prior = _stock()
        prior.update({
            "mainNetInflow": 8_000_000.0, "mainNetRatio": 1.8,
            "mainMoneyUpdatedAt": "2026-09-28 10:10:00", "mainMoneyTrend": "持续流入",
            "mainMoneyFlowHistory": [
                {"time": "10:10", "mainNetInflow": 8_000_000.0, "mainNetRatio": 1.8, "price": 10.1, "pct": 1.0},
            ],
        })
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            hits = Path(folder) / "intraday_hits_2026-09-28.json"
            hits.write_text(json.dumps({"tradeDate": "2026-09-28", "stocks": [prior]}), encoding="utf-8")
            with (patch.object(scanner, "CACHE", cache), patch.object(scanner, "ROOT", Path(folder))):
                retained = scanner._retain_daily_hits(now, [selected], [selected])

        saved = retained[0]
        self.assertEqual(saved["mainMoneyUpdatedAt"], "2026-09-28 10:10:00")
        self.assertEqual(len(saved["mainMoneyFlowHistory"]), 1)
        self.assertTrue(saved["mainMoneyStale"])

    def test_failed_retained_money_supplement_marks_departed_stock_stale(self):
        now = scanner.datetime(2026, 9, 28, 14, 10, 0)
        prior = _stock()
        prior.update({
            "code": "000001", "mainNetInflow": 9_000_000.0, "mainNetRatio": 2.5,
            "mainMoneyUpdatedAt": "2026-09-28 14:05:00",
            "mainMoneyFlowHistory": [
                {"time": "14:05", "mainNetInflow": 9_000_000.0, "mainNetRatio": 2.5, "price": 10.1, "pct": 1.0},
            ],
        })
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "intraday_candidates.json"
            hits = Path(folder) / "intraday_hits_2026-09-28.json"
            hits.write_text(json.dumps({"tradeDate": "2026-09-28", "stocks": [prior]}), encoding="utf-8")
            with (
                patch.object(scanner, "CACHE", cache), patch.object(scanner, "ROOT", Path(folder)),
                patch.object(scanner, "fetch_eastmoney_main_money", side_effect=RuntimeError("money unavailable")),
            ):
                retention_rows, updated = scanner._with_retained_main_money([], now)
                retained = scanner._retain_daily_hits(now, [], retention_rows)

        self.assertEqual(updated, 0)
        self.assertEqual(retained[0]["mainMoneyUpdatedAt"], "2026-09-28 14:05:00")
        self.assertTrue(retained[0]["mainMoneyStale"])

    def test_eastmoney_failure_uses_tencent_market_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with (
                patch.object(scanner, "SNAPSHOT_ROOT", temp / "snapshots"),
                patch.object(scanner, "CACHE", temp / "intraday_candidates.json"),
                patch.object(scanner, "fetch_eastmoney", side_effect=RuntimeError("eastmoney unavailable")),
                patch.object(scanner, "fetch_tencent_market", return_value=[_stock()]),
                patch.object(scanner, "fetch_eastmoney_sectors", side_effect=RuntimeError("sector unavailable")),
                patch.object(scanner, "fetch_eastmoney_market_context", return_value={"scope": "全A股", "tradeDate": "20260923", "total": 1, "up": 1, "down": 0, "flat": 0, "upRatio": 100.0, "medianPct": 2.0, "nearLimitUp": 0, "limitUp": 0}),
                patch.object(scanner, "_load_learned_strategy", return_value={"models": {"10:30": _model()}}),
                patch.object(scanner, "_active_learned_model", return_value=("10:30", _model())),
                patch.object(scanner, "_is_trading_session", return_value=True),
                patch.object(scanner, "_parse_tencent", return_value={}),
                patch.object(scanner, "_parse_sina", return_value={}),
            ):
                result = scanner.scan_intraday()

        self.assertEqual(result["sources"]["个股行情"], "腾讯降级")
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["stocks"][0]["code"], "600000")

    def test_scan_combines_stock_sector_and_writes_free_source_snapshot(self):
        sectors = {"industry": [_sector()], "concept": []}
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with (
                patch.object(scanner, "SNAPSHOT_ROOT", temp / "snapshots"),
                patch.object(scanner, "CACHE", temp / "intraday_candidates.json"),
                patch.object(scanner, "fetch_eastmoney", return_value=[_stock()]),
                patch.object(scanner, "fetch_eastmoney_sectors", return_value=sectors),
                patch.object(scanner, "fetch_eastmoney_market_context", return_value={"scope": "全A股", "total": 1, "up": 1, "down": 0, "flat": 0, "upRatio": 100.0, "medianPct": 2.0, "nearLimitUp": 0, "limitUp": 0}),
                patch.object(scanner, "_load_learned_strategy", return_value={"models": {"10:30": _model()}}),
                patch.object(scanner, "_active_learned_model", return_value=("10:30", _model())),
                patch.object(scanner, "_parse_tencent", return_value={"600000": 10.2}),
                patch.object(scanner, "_parse_sina", return_value={"600000": 10.2}),
                patch.object(scanner, "_is_trading_session", return_value=True),
            ):
                result = scanner.scan_intraday()

            self.assertTrue(result["success"])
            self.assertEqual(result["stockPatternMatched"], 1)
            self.assertEqual(result["matched"], 1)
            self.assertTrue(result["stocks"][0]["sectorEligible"])
            self.assertTrue(result["stocks"][0]["verified"])
            self.assertFalse(result["strategyProvenance"]["individualModelSectorHistoryIncluded"])
            snapshot = next((temp / "snapshots").rglob("*.json.gz"))
            with gzip.open(snapshot, "rt", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["source"], "东方财富免费网页行情")
            self.assertEqual(saved["stocks"][0]["industry"], "银行")
            self.assertEqual(saved["sectors"]["industry"][0]["mainNetRatio"], 5.0)

    def test_weak_sector_is_kept_but_penalized_after_historical_review(self):
        weak = _sector(pct=-1.0, breadth=30.0)
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with (
                patch.object(scanner, "SNAPSHOT_ROOT", temp / "snapshots"),
                patch.object(scanner, "CACHE", temp / "intraday_candidates.json"),
                patch.object(scanner, "fetch_eastmoney", return_value=[_stock()]),
                patch.object(scanner, "fetch_eastmoney_sectors", return_value={"industry": [weak], "concept": []}),
                patch.object(scanner, "fetch_eastmoney_market_context", return_value={"scope": "全A股", "total": 1, "up": 1, "down": 0, "flat": 0, "upRatio": 100.0, "medianPct": 2.0, "nearLimitUp": 0, "limitUp": 0}),
                patch.object(scanner, "_load_learned_strategy", return_value={"models": {"10:30": _model()}}),
                patch.object(scanner, "_active_learned_model", return_value=("10:30", _model())),
                patch.object(scanner, "_is_trading_session", return_value=True),
                patch.object(scanner, "_parse_tencent", return_value={}),
                patch.object(scanner, "_parse_sina", return_value={}),
            ):
                result = scanner.scan_intraday()

        self.assertEqual(result["stockPatternMatched"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["sectorFiltered"], 0)
        self.assertEqual(result["weakSectorCandidates"], 1)
        self.assertFalse(result["stocks"][0]["sectorEligible"])

    def test_sector_api_failure_does_not_discard_strategy_match(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with (
                patch.object(scanner, "SNAPSHOT_ROOT", temp / "snapshots"),
                patch.object(scanner, "CACHE", temp / "intraday_candidates.json"),
                patch.object(scanner, "fetch_eastmoney", return_value=[_stock()]),
                patch.object(scanner, "fetch_eastmoney_sectors", side_effect=RuntimeError("sector unavailable")),
                patch.object(scanner, "fetch_eastmoney_market_context", return_value={"scope": "全A股", "tradeDate": "20260923", "total": 1, "up": 1, "down": 0, "flat": 0, "upRatio": 100.0, "medianPct": 2.0, "nearLimitUp": 0, "limitUp": 0}),
                patch.object(scanner, "_load_learned_strategy", return_value={"models": {"10:30": _model()}}),
                patch.object(scanner, "_active_learned_model", return_value=("10:30", _model())),
                patch.object(scanner, "_is_trading_session", return_value=True),
                patch.object(scanner, "_parse_tencent", return_value={}),
                patch.object(scanner, "_parse_sina", return_value={}),
            ):
                result = scanner.scan_intraday()

        self.assertFalse(result["sectorFilterActive"])
        self.assertEqual(result["stockPatternMatched"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["stocks"][0]["code"], "600000")
        self.assertIn("行业数据降级", result["stocks"][0]["briefReasons"])

    def test_stock_that_already_touched_limit_does_not_match(self):
        stock = _stock()
        stock["high"] = 11.0
        scanner._score(stock)
        self.assertFalse(scanner._learned_match(stock, _model()))

    def test_empty_result_explains_unapproved_checkpoint_and_market_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            with (
                patch.object(scanner, "SNAPSHOT_ROOT", temp / "snapshots"),
                patch.object(scanner, "CACHE", temp / "intraday_candidates.json"),
                patch.object(scanner, "fetch_eastmoney", return_value=[_stock()]),
                patch.object(scanner, "fetch_eastmoney_sectors", return_value={"industry": [_sector()], "concept": []}),
                patch.object(scanner, "fetch_eastmoney_market_context", return_value={"scope": "全A股", "total": 100, "up": 5, "down": 95, "flat": 0, "upRatio": 5.0, "medianPct": -2.0, "nearLimitUp": 0, "limitUp": 0}),
                patch.object(scanner, "_load_learned_strategy", return_value={"models": {}}),
                patch.object(scanner, "_active_learned_model", return_value=("10:00", None)),
                patch.object(scanner, "_is_trading_session", return_value=True),
            ):
                result = scanner.scan_intraday()

        self.assertEqual(result["stocks"], [])
        self.assertTrue(any("10:00" in item for item in result["noCandidateReasons"]))
        self.assertTrue(any("5.0%" in item for item in result["noCandidateReasons"]))


if __name__ == "__main__":
    unittest.main()
