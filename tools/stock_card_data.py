"""为缠论/背离卡片补充带日期的本地行情，不修改原始信号或联网取数。"""

import csv
import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path


def _date(value):
    text = str(value or '').strip()
    try:
        pattern = '%Y%m%d' if re.fullmatch(r'\d{8}', text) else '%Y-%m-%d'
        return datetime.strptime(text[:10], pattern).date().isoformat()
    except ValueError:
        return ''


def _number(value):
    try:
        number = float(value)
        return round(number, 2) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _file_key(path):
    stat = path.stat()
    return str(path), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=128)
def _daily_quote(path, modified, size, as_of):
    # 修改时间只用于缓存失效，绝不作为行情日期。
    latest = {}
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            day = _date(row.get('日期') or row.get('date'))
            price = _number(row.get('收盘', row.get('close')))
            if not day or day > as_of or price is None or price <= 0:
                continue
            if day >= latest.get('tradeDate', ''):
                latest = {'tradeDate': day, 'price': price,
                          'pct': _number(row.get('涨跌幅', row.get('pctChg'))),
                          'source': '本地日线缓存'}
    return latest


@lru_cache(maxsize=8)
def _spot_rows(path, modified, size):
    file_date = _date(Path(path).stem.removeprefix('tushare_a_stock_spot_'))
    result = {}
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            code = str(row.get('代码') or '').zfill(6)
            day = _date(row.get('交易日') or file_date)
            if not re.fullmatch(r'\d{6}', code) or not day:
                continue
            price = _number(row.get('最新价'))
            cap = _number(row.get('总市值_亿元'))
            result[code] = {
                'tradeDate': day, 'price': price if price and price > 0 else None,
                'pct': _number(row.get('涨跌幅')),
                'industry': str(row.get('行业') or '').strip(),
                'marketCap': cap if cap and cap > 0 else None,
                'source': '本地行情快照',
            }
    return result


def enrich_signal_cards(stocks, project_root, as_of):
    """仅追加 cardQuote；价格/评分/分类保留原值，历史报表不读取未来行情。"""
    targets = [s for s in stocks if {'缠论选股', '背离信号'} & set(s.get('categories') or [])]
    if not targets:
        return
    cutoff = _date(as_of)
    root = Path(project_root) / 'cache'
    snapshots = {}
    if cutoff:
        codes = {str(s.get('code') or '').zfill(6) for s in targets}
        for path in sorted(root.glob('tushare_a_stock_spot_*.csv')):
            try:
                for code, row in _spot_rows(*_file_key(path)).items():
                    if code in codes and row['tradeDate'] <= cutoff:
                        if row['tradeDate'] >= snapshots.get(code, {}).get('tradeDate', ''):
                            snapshots[code] = row
            except (OSError, UnicodeError, csv.Error):
                continue
    for stock in targets:
        quote = {'price': None, 'pct': None, 'tradeDate': '', 'source': '',
                 'industry': '', 'industryDate': '', 'marketCap': None}
        code = str(stock.get('code') or '').zfill(6)
        if cutoff and re.fullmatch(r'\d{6}', code):
            snapshot = snapshots.get(code, {})
            try:
                quote.update(_daily_quote(*_file_key(root / 'hist' / f'{code}_bs.csv'), cutoff))
            except (OSError, UnicodeError, csv.Error):
                pass
            if snapshot.get('price') and snapshot['tradeDate'] >= quote['tradeDate']:
                quote.update({key: snapshot[key] for key in ('price', 'pct', 'tradeDate', 'source')})
            if snapshot.get('industry') not in (None, '', 'nan', '-', 'None'):
                quote['industry'] = snapshot['industry']
                quote['industryDate'] = snapshot['tradeDate']
            # 市值随价格变化，必须与显示行情同日；不按旧股本估算。
            if quote['tradeDate'] and snapshot.get('tradeDate') == quote['tradeDate']:
                quote['marketCap'] = snapshot.get('marketCap')
        stock['cardQuote'] = quote
