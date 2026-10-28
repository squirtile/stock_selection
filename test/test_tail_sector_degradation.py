from contextlib import ExitStack
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import intraday_scanner as scanner
from test_intraday_scanner import _stock, _sector


class TailSectorDegradationTest(unittest.TestCase):
    def test_tail_preserves_hits_with_sector_data(self):
        result, saved = self._scan_shadow({'industry': [_sector()], 'concept': []})
        self._assert_shadow_selected(result, saved)
        self.assertNotIn('行业数据降级', result['tailStocks'][0]['briefReasons'])

    def test_tail_survives_sector_service_failure(self):
        result, saved = self._scan_shadow(RuntimeError('sector unavailable'))
        self._assert_shadow_selected(result, saved)
        self.assertFalse(result['sectorFilterActive'])
        self.assertIn('行业数据降级', saved['stocks'][0]['briefReasons'])

    def test_tail_survives_empty_sector_response(self):
        result, saved = self._scan_shadow({'industry': [], 'concept': []})
        self._assert_shadow_selected(result, saved)
        self.assertIn('行业数据降级', saved['stocks'][0]['briefReasons'])

    def test_tail_survives_missing_industry_mapping(self):
        result, saved = self._scan_shadow({
            'industry': [dict(_sector(), name='其他行业')], 'concept': [],
        })
        self._assert_shadow_selected(result, saved)
        self.assertTrue(result['sectorFilterActive'])
        self.assertIn('行业数据降级', saved['stocks'][0]['briefReasons'])

    def _assert_shadow_selected(self, result, saved):
        self.assertTrue(result['tailReady'])
        self.assertEqual(result['tailMatched'], 1)
        self.assertEqual(result['total'], 2)
        self.assertEqual([r['code'] for r in result['tailStocks']], ['600001'])
        self.assertEqual(result['tailStocks'][0]['tailStrategies'], ['长上下影线'])
        self.assertEqual(saved['stocks'], result['tailStocks'])
        self.assertEqual(result['stocks'], [])

    def _scan_shadow(self, sectors):
        now = scanner.datetime(2026, 10, 22, 14, 45)
        low = dict(_stock(), code='600001', volumeRatio=2.0, open=10, high=10.3, low=9.5)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'hist').mkdir()
            pd.DataFrame([
                {'日期':'2026-10-20','开盘':10,'最高':10.3,'最低':9.9,'收盘':10,'成交量':10000000},
                {'日期':'2026-10-21','开盘':10,'最高':10.7,'最低':9.9,'收盘':10.1,'成交量':10000000},
            ]).to_csv(root/'hist/600001_bs.csv', index=False)
            patches = [
                patch.object(scanner, 'datetime'),
                patch.object(scanner, 'ROOT', root),
                patch.object(scanner, 'HIST_ROOT', root/'hist'),
                patch.object(scanner, 'SNAPSHOT_ROOT', root/'snapshots'),
                patch.object(scanner, 'CACHE', root/'output/live.json'),
                patch.object(scanner, 'TAIL_CACHE', root/'output/tail.json'),
                patch.object(scanner, 'OUTPUT', root/'output'),
                patch.object(scanner, 'fetch_eastmoney', return_value=[_stock(), low]),
                patch.object(scanner, 'fetch_eastmoney_sectors',
                             side_effect=sectors if isinstance(sectors, Exception) else None,
                             return_value=sectors),
                patch.object(scanner, 'fetch_eastmoney_market_context', return_value={'tradeDate': '20261022', 'upRatio': 60}),
                patch.object(scanner, '_load_intraday_strategy_history', return_value={}),
                patch.object(scanner, '_load_learned_strategy', return_value={}),
                patch.object(scanner, '_active_learned_model', return_value=('', None)),
                patch.object(scanner, '_apply_daily_big_yang', return_value=0),
                patch.object(scanner, '_apply_chanlun', return_value=0),
                patch.object(scanner, '_with_retained_main_money', side_effect=lambda s,n: (s, 0)),
                patch.object(scanner, '_parse_tencent', return_value={}),
                patch.object(scanner, '_parse_sina', return_value={}),
            ]
            with ExitStack() as stack:
                for item in patches:
                    value = stack.enter_context(item)
                    if item.attribute == "datetime": clock = value
                clock.now.return_value = now
                result = scanner.scan_intraday()
            saved = json.loads((root/'output/tail.json').read_text())
            return result, saved
