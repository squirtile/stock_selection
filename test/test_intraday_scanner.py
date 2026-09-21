import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
