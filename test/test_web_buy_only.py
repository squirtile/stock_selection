import unittest
from unittest.mock import patch

from flask import Flask
from web.views import web_bp


class BuyOnlyWebTest(unittest.TestCase):
    def test_history_board_and_chanlun_filters_exclude_sell_signals(self):
        app = Flask(__name__)
        app.register_blueprint(web_bp)
        def row(name, direction, count):
            return {'strategy': name, 'direction': direction, 'historyEvaluated': count,
                    'historyWins': 1, 'historyWinRate': 50, 'historyAvgPct': 0.5,
                    'reviewDays': 1}
        dashboard = {'historyRows': [row('30分钟缠论二买', '看涨', 2),
                                     row('30分钟缠论二卖', '看跌', 4)],
                     'historyStart': '2026-09-01', 'historyEnd': '2026-09-30',
                     'totalRecords': 6}
        data = {'stocks': [], 'marketContext': {}, 'backtestReview': {},
                'time': '', 'total': 0, 'intradayInitial': {},
                'tabGroups': [{'key': '缠论选股', 'label': '缠论选股', 'count': 2,
                               'children': [
                                   {'key': 'chanlun_30分钟_2B', 'label': '30分钟·缠论二买',
                                    'count': 1, 'subgroup': '买点'},
                                   {'key': 'chanlun_30分钟_2S', 'label': '30分钟·缠论二卖',
                                    'count': 1, 'subgroup': '卖点'},
                               ]}]}
        with patch('web.views._load_stocks_data', return_value=data), \
             patch('backtest.strategy_history_store.load_dashboard', return_value=dashboard), \
             patch('backtest.intraday_history_store.load_intraday_dashboard', return_value={'rows': []}):
            response = app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('30分钟缠论二买', html)
        self.assertNotIn('30分钟缠论二卖', html)
        self.assertNotIn('30分钟·缠论二卖', html)
        self.assertNotIn('data-ctab="sell"', html)
        self.assertNotIn('>卖点<', html)
        self.assertIn('累计 2 条策略信号', html)


if __name__ == '__main__':
    unittest.main()
