import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import intraday_sector_review as reviewer


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class IntradaySectorReviewTest(unittest.TestCase):
    def test_review_compares_individual_and_sector_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            day = root / "snapshots" / "2026-09-10"
            base = {
                "time": "2026-09-10 10:30:00", "market": {"upRatio": 60},
                "stocks": [
                    {"code": "600000", "name": "通过", "industry": "银行", "prevClose": 10,
                     "high": 10.3, "learnedMatch": True, "sectorEligible": True},
                    {"code": "600001", "name": "过滤", "industry": "弱行业", "prevClose": 10,
                     "high": 10.2, "learnedMatch": True, "sectorEligible": False},
                ],
            }
            final = {
                "time": "2026-09-10 14:59:00",
                "stocks": [
                    {"code": "600000", "high": 11.0},
                    {"code": "600001", "high": 10.5},
                ],
            }
            _write(day / "1030.json.gz", base)
            _write(day / "1459.json.gz", final)
            with (
                patch.object(reviewer, "SNAPSHOT_ROOT", root / "snapshots"),
                patch.object(reviewer, "OUTPUT_FILE", root / "result.json"),
            ):
                result = reviewer.review()

            self.assertEqual(result["reviewDays"], 1)
            self.assertEqual(result["individualStock"], {"selected": 2, "hits": 1, "precision": 50.0})
            self.assertEqual(result["withSector"], {"selected": 1, "hits": 1, "precision": 100.0})
            self.assertEqual(result["status"], "样本积累中")


if __name__ == "__main__":
    unittest.main()
