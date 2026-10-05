import copy
import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from tools.stock_card_data import enrich_signal_cards


class StockCardDataTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def csv(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def stock(self, category='缠论选股'):
        return {'code': '603215', 'name': '测试股', 'price': 14.05,
                'pct': None, 'industry': '', 'marketCap': None,
                'score': 85, 'strategyTypes': [{'name': '30分钟缠论二买'}],
                'categories': [category]}

    def history(self):
        self.csv('cache/hist/603215_bs.csv', [
            {'日期': '2026-09-30', '收盘': 15.63, '涨跌幅': 2.36},
            {'日期': '2026-10-09', '收盘': 17.1, '涨跌幅': 9.4},
        ])

    def spot(self, day='20260805', price=14.05, pct=-0.92):
        self.csv(f'cache/tushare_a_stock_spot_{day}.csv', [
            {'代码': '603215', '交易日': day, '最新价': price,
             '涨跌幅': pct, '行业': '家用电器', '总市值_亿元': 30.15},
        ])

    def test_both_categories_get_dated_quote_without_changing_signal_or_score(self):
        self.history()
        self.spot()
        for category in ['缠论选股', '背离信号']:
            stock = self.stock(category)
            original = copy.deepcopy(stock)
            enrich_signal_cards([stock], self.root, '2026-10-02 19:30:00')
            quote = stock.pop('cardQuote')
            self.assertEqual(stock, original)
            self.assertEqual(quote['price'], 15.63)
            self.assertEqual(quote['pct'], 2.36)
            self.assertEqual(quote['tradeDate'], '2026-09-30')
            self.assertEqual(quote['industry'], '家用电器')
            self.assertIsNone(quote['marketCap'])  # 8月市值不能冒充9月市值。

    def test_same_day_spot_supplies_market_cap_and_consistent_quote(self):
        self.history()
        self.spot('20260930', 15.64, 2.42)
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertEqual(stock['cardQuote']['price'], 15.64)
        self.assertEqual(stock['cardQuote']['pct'], 2.42)
        self.assertEqual(stock['cardQuote']['marketCap'], 30.15)

    def test_future_spot_does_not_leak_into_historical_report(self):
        self.history()
        self.spot('20261009', 19, 5)
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertEqual(stock['cardQuote']['price'], 15.63)
        self.assertIsNone(stock['cardQuote']['marketCap'])

    def test_missing_sources_clear_old_enrichment_instead_of_reusing_undated_price(self):
        stock = self.stock()
        stock['cardQuote'] = {'price': 99, 'tradeDate': '2026-10-01'}
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertIsNone(stock['cardQuote']['price'])
        self.assertIsNone(stock['cardQuote']['pct'])
        self.assertIsNone(stock['cardQuote']['marketCap'])
        self.assertEqual(stock['cardQuote']['tradeDate'], '')
        self.assertEqual(stock['price'], 14.05)

    def test_zero_pct_is_retained_and_nonfinite_values_are_not_rendered(self):
        self.csv('cache/hist/603215_bs.csv', [
            {'日期': '2026-09-29', '收盘': 15.63, '涨跌幅': 0},
            {'日期': '2026-09-30', '收盘': 'NaN', '涨跌幅': 'inf'},
        ])
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertEqual(stock['cardQuote']['pct'], 0)
        self.assertEqual(stock['cardQuote']['tradeDate'], '2026-09-29')

    def test_missing_pct_is_not_replaced_by_older_snapshot_pct(self):
        self.csv('cache/hist/603215_bs.csv', [{'日期': '2026-09-30', '收盘': 15.63}])
        self.spot()
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertEqual(stock['cardQuote']['price'], 15.63)
        self.assertIsNone(stock['cardQuote']['pct'])

    def test_unrelated_strategy_cards_are_not_changed(self):
        stock = self.stock('策略信号')
        original = copy.deepcopy(stock)
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertEqual(stock, original)

    def test_invalid_report_date_does_not_guess_current_date(self):
        self.history()
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '')
        self.assertIsNone(stock['cardQuote']['price'])

    def test_broken_csv_does_not_hide_the_page(self):
        self.csv('cache/hist/603215_bs.csv', [{'wrong': 'columns'}])
        stock = self.stock()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        self.assertIsNone(stock['cardQuote']['price'])

    def test_web_loader_enriches_old_json_without_overwriting_it(self):
        from web import views
        self.history()
        self.spot()
        output = self.root / 'output'
        output.mkdir()
        path = output / 'mini_program_stocks.json'
        source = json.dumps({'time': '2026-10-02 19:30:00', 'stocks': [self.stock()]})
        path.write_text(source)
        with patch.object(views, 'PROJECT_ROOT', self.root), patch.object(views, 'OUTPUT_DIR', output):
            data = views._load_stocks_data()
        self.assertEqual(data['stocks'][0]['cardQuote']['price'], 15.63)
        self.assertEqual(path.read_text(), source)

    def test_report_generation_enriches_new_cards(self):
        import daily_report
        self.history()
        self.spot()
        output = self.root / 'output'
        output.mkdir()
        with patch.object(daily_report, 'PROJECT_ROOT', str(self.root)), \
             patch.object(daily_report, 'OUTPUT_DIR', str(output)), \
             patch.object(daily_report, '_build_kline_data', return_value=[]), \
             patch.object(daily_report, '_load_market_context', return_value={}), \
             patch.object(daily_report, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 2, 19, 30)
            path = daily_report.build_mini_program_json('', {}, chanlun_data={
                'chanlun_stocks': [{'code': '603215', 'name': '测试股', 'price': 14.05,
                                    'frequency': '30分钟', 'buy_type': '2B'}],
            })
        data = json.loads(Path(path).read_text())
        quote = data['stocks'][0]['cardQuote']
        self.assertEqual(quote['price'], 15.63)
        self.assertEqual(quote['tradeDate'], '2026-09-30')

    def test_template_labels_quote_date_and_missing_fields(self):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'web/templates'))
        app.add_url_rule('/support-qr', endpoint='web.support_qr', view_func=lambda: '')
        stock = {**self.stock(), 'mlModels': [], 'strategyCount': 0, 'sectorLabel': ''}
        enrich_signal_cards([stock], self.root, '2026-10-02')
        from flask import render_template
        with app.test_request_context('/'):
            html = render_template('index.html', stocks=[stock], tabGroups=[], allTabs=[],
                                   marketContext={}, backtestReview={}, strategyDashboard={},
                                   indexDivergence={}, intradayInitial={}, time='', total=1)
        self.assertIn('价格暂无', html)
        self.assertIn('涨幅暂无', html)
        self.assertIn('行业暂无', html)
        self.assertIn('市值暂无', html)
        self.assertNotIn('¥14.05', html)
        self.history()
        self.spot()
        enrich_signal_cards([stock], self.root, '2026-10-02')
        with app.test_request_context('/'):
            html = render_template('index.html', stocks=[stock], tabGroups=[], allTabs=[],
                                   marketContext={}, backtestReview={}, strategyDashboard={},
                                   indexDivergence={}, intradayInitial={}, time='', total=1)
        self.assertIn('行情日期 2026-09-30', html)
        self.assertIn('¥15.63', html)
        self.assertIn('+2.36%', html)
        self.assertIn('家用电器', html)
        self.assertNotIn('¥14.05', html)


if __name__ == '__main__':
    unittest.main()
