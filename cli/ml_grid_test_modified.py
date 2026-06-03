#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量测试 ML 模板组合、训练参数和回测结果。

新增功能：
1. 支持手动传入模板股票代码：
   python cli/ml_grid_test.py --codes 603115,002980,600769 --threshold 0.80

2. 支持自动从候选股票池/缓存日线里选择强势模板股：
   python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2

自动强势股选择逻辑：
- 从候选股票池加载代码；
- 读取每只股票本地日线缓存；
- 根据最近 N 个交易日走势打分；
- 选择得分最高的 Top N 作为模板候选股；
- 再按 mode/combination/permutation/single 生成模板组合。
"""

import argparse
import itertools
import locale
import math
import re
import sys
import time
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

try:
    from tabulate import tabulate
except Exception:
    tabulate = None

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# 复用你工程里的股票池加载逻辑
try:
    from ml_engine.pattern_extract import load_candidate_codes
except Exception:
    load_candidate_codes = None


# ======================================================================================
# 基础参数解析
# ======================================================================================

def parse_int_list(s: str) -> List[int]:
    values: List[int] = []
    for x in str(s).split(','):
        x = x.strip()
        if not x:
            continue
        if '-' in x:
            a, b = x.split('-', 1)
            values.extend(list(range(int(a), int(b) + 1)))
        else:
            values.append(int(x))
    return sorted(set(values))


def parse_float_list(s: str) -> List[float]:
    values: List[float] = []
    for x in str(s).split(','):
        x = x.strip()
        if not x:
            continue
        if '-' in x:
            a, b = x.split('-', 1)
            start = int(float(a))
            end = int(float(b))
            values.extend([float(i) for i in range(start, end + 1)])
        else:
            values.append(float(x))
    return sorted(set(values))


def normalize_code(code: str) -> str:
    if code is None:
        return ''
    text = str(code).strip()
    if not text:
        return ''
    text = text.split('.')[0]
    return text.zfill(6)[-6:]


def build_templates(codes: List[str], mode: str, combo_size: int) -> List[str]:
    codes = [normalize_code(c) for c in codes if str(c).strip()]
    codes = list(dict.fromkeys(codes))
    if not codes:
        return []

    if mode == 'permutation':
        # 默认：全排列。3个代码 => 6种。
        items = itertools.permutations(codes, len(codes))
    elif mode == 'combination':
        # 固定数量组合。combo-size=2 时，ABCD => AB/AC/AD/BC/BD/CD。
        # 不传 combo-size 时，保持原逻辑：使用全部代码作为一组模板。
        size = combo_size if combo_size > 0 else len(codes)
        if size > len(codes):
            raise ValueError(f'combo-size={size} 大于代码数量={len(codes)}')
        items = itertools.combinations(codes, size)
    elif mode == 'combination_range':
        # 组合区间模式：生成 2只 到 N只 的所有无序组合，排除单股。
        # 例如：
        #   ABC  => AB/AC/BC/ABC
        #   ABCD => AB/AC/AD/BC/BD/CD/ABC/ABD/ACD/BCD/ABCD
        if len(codes) < 2:
            raise ValueError('combination_range 至少需要 2 个代码')
        max_size = combo_size if combo_size > 0 else len(codes)
        if max_size > len(codes):
            raise ValueError(f'combo-size={max_size} 大于代码数量={len(codes)}')
        if max_size < 2:
            raise ValueError('combination_range 的 combo-size 至少为 2')
        items = itertools.chain.from_iterable(
            itertools.combinations(codes, size)
            for size in range(2, max_size + 1)
        )
    elif mode == 'single':
        items = [(c,) for c in codes]
    else:
        raise ValueError(f'未知 mode: {mode}')

    templates = [','.join(x) for x in items]
    return list(dict.fromkeys(templates))


def target_to_name(target: float) -> str:
    # 和模型文件名中的 t5p0 / t7p0 风格保持一致
    return f"{float(target):.1f}".replace('.', 'p')


# ======================================================================================
# 自动选择强势模板股
# ======================================================================================

def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    根据中英文字段名找列，兼容 BaoStock / AkShare / 自定义缓存。
    """
    if df is None or df.empty:
        return None

    cols = list(df.columns)
    lower_map = {str(c).lower(): c for c in cols}

    for name in candidates:
        if name in df.columns:
            return name
        low = name.lower()
        if low in lower_map:
            return lower_map[low]

    # 模糊匹配
    for c in cols:
        cs = str(c).lower()
        for name in candidates:
            ns = str(name).lower()
            if ns and ns in cs:
                return c
    return None


def to_num(s) -> pd.Series:
    return pd.to_numeric(s, errors='coerce')


def possible_daily_cache_dirs() -> List[Path]:
    """
    自动选模板股时默认从 cache/hist 读取日线数据。

    也保留少量常见兜底目录，防止以后缓存目录调整后完全找不到。
    """
    dirs = [
        PROJECT_ROOT / 'cache' / 'hist',   # 默认日线缓存目录
        PROJECT_ROOT / 'cahce' / 'hist',   # 兼容误拼写目录名
        PROJECT_ROOT / 'cache' / 'daily',
        PROJECT_ROOT / 'cache' / 'daily_k',
        PROJECT_ROOT / 'cache' / 'kline',
        PROJECT_ROOT / 'cache',
        PROJECT_ROOT / 'data' / 'daily',
        PROJECT_ROOT / 'output' / 'daily',
    ]

    # 去重，保持顺序。
    seen = set()
    out = []
    for d in dirs:
        p = Path(d)
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def find_daily_file(code: str) -> Optional[Path]:
    """
    从常见缓存目录里查找某只股票的日线文件。
    兼容：
    - 603115.csv
    - 603115_bs.csv
    - 603115_daily.csv
    - 603115.SH.csv / 603115.SZ.csv
    """
    code = normalize_code(code)
    if not code:
        return None

    suffixes = ['.SH', '.SZ']
    patterns = [
        f'{code}.csv',
        f'{code}_bs.csv',
        f'{code}_daily.csv',
        f'{code}_day.csv',
        f'{code}_k.csv',
        f'{code}.SH.csv',
        f'{code}.SZ.csv',
        f'{code}_*.csv',
        f'*{code}*.csv',
    ]

    for d in possible_daily_cache_dirs():
        if not d.exists() or not d.is_dir():
            continue
        for pat in patterns:
            files = list(d.glob(pat))
            if files:
                # 优先选文件名以代码开头的
                files = sorted(files, key=lambda p: (not p.name.startswith(code), len(p.name), p.name))
                return files[0]

    return None


def read_daily_df(code: str) -> pd.DataFrame:
    path = find_daily_file(code)
    if path is None or not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
    except Exception:
        try:
            df = pd.read_csv(path, encoding='gbk')
        except Exception:
            return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    date_col = find_col(df, ['日期', 'date', 'trade_date', 'datetime', 'time'])
    if date_col:
        df = df.copy()
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col]).sort_values(date_col)

    return df.reset_index(drop=True)


def calc_limit_count(pct_series: pd.Series) -> int:
    """
    粗略统计涨停次数：
    主板通常 10cm，这里用 >=9.7 近似；
    这里仅作为强势评分，不用于交易判断。
    """
    pct = to_num(pct_series)
    return int((pct >= 9.7).sum())


def score_strong_stock(code: str, lookback: int = 20) -> Optional[Dict[str, Any]]:
    """
    自动模板股强势评分。

    评分思路：
    1. 近 N 日涨幅越高越好；
    2. 当前越接近 N 日高点越好，避免已经大幅回落；
    3. 近 N 日涨停次数越多越好；
    4. 最近 5 日成交量相对前 20 日放大越好；
    5. 最近 5 日平均成交额越大越好，避免流动性太差；
    6. 近 N 日阳线占比越高越好；
    7. 当前在 20 日均线上方加分。
    """
    df = read_daily_df(code)
    min_need = max(lookback + 5, 30)
    if df.empty or len(df) < min_need:
        return None

    close_col = find_col(df, ['close', '收盘', '收盘价'])
    high_col = find_col(df, ['high', '最高', '最高价'])
    low_col = find_col(df, ['low', '最低', '最低价'])
    open_col = find_col(df, ['open', '开盘', '开盘价'])
    vol_col = find_col(df, ['volume', 'vol', '成交量'])
    amount_col = find_col(df, ['amount', '成交额', 'turnover'])
    pct_col = find_col(df, ['pct_chg', '涨跌幅', '涨幅', 'change_pct'])

    if close_col is None:
        return None

    data = df.copy()
    close = to_num(data[close_col])
    high = to_num(data[high_col]) if high_col else close
    low = to_num(data[low_col]) if low_col else close
    open_ = to_num(data[open_col]) if open_col else close.shift(1)
    volume = to_num(data[vol_col]) if vol_col else pd.Series([math.nan] * len(data))
    amount = to_num(data[amount_col]) if amount_col else pd.Series([math.nan] * len(data))

    if pct_col:
        pct = to_num(data[pct_col])
    else:
        pct = close.pct_change() * 100

    data['_close'] = close
    data['_high'] = high
    data['_low'] = low
    data['_open'] = open_
    data['_volume'] = volume
    data['_amount'] = amount
    data['_pct'] = pct

    data = data.dropna(subset=['_close'])
    if len(data) < min_need:
        return None

    recent = data.tail(lookback)
    if recent.empty:
        return None

    close_now = float(data['_close'].iloc[-1])
    close_start = float(data['_close'].iloc[-lookback])
    if close_start <= 0 or close_now <= 0:
        return None

    ret_n = (close_now / close_start - 1.0) * 100.0
    high_n = float(recent['_high'].max())
    low_n = float(recent['_low'].min())
    if high_n <= 0:
        return None

    # 当前距离近N日高点的回撤，越小越好
    drawdown_from_high = (close_now / high_n - 1.0) * 100.0

    # N日振幅
    amplitude_n = (high_n / low_n - 1.0) * 100.0 if low_n > 0 else 0.0

    limit_count = calc_limit_count(recent['_pct'])

    # 成交量放大：近5日均量 / 前20日均量
    vol_recent5 = data['_volume'].tail(5).mean()
    vol_prev20 = data['_volume'].tail(25).head(20).mean()
    if pd.isna(vol_recent5) or pd.isna(vol_prev20) or vol_prev20 <= 0:
        vol_ratio = 1.0
    else:
        vol_ratio = float(vol_recent5 / vol_prev20)

    # 成交额，兼容单位不统一：这里只做相对加分，不做硬过滤
    amount_recent5 = data['_amount'].tail(5).mean()
    if pd.isna(amount_recent5):
        amount_recent5 = 0.0

    # 阳线占比
    up_day_ratio = float((recent['_close'] > recent['_open']).mean()) if '_open' in recent else 0.0

    # 当前是否在20日均线上方
    ma20 = data['_close'].tail(20).mean()
    above_ma20 = 1 if close_now >= ma20 else 0

    # 是否接近新高：当前收盘距离近60日最高收盘
    recent60 = data.tail(min(60, len(data)))
    high_close_60 = float(recent60['_close'].max())
    near_60_high = 1 if high_close_60 > 0 and close_now / high_close_60 >= 0.95 else 0

    # 评分
    # 注意：这是“模板候选评分”，不是买入信号。
    score = 0.0
    score += ret_n * 1.00                         # 趋势涨幅
    score += max(drawdown_from_high, -30) * 0.60   # 回撤惩罚，回撤越大越扣分
    score += limit_count * 8.00                    # 涨停活跃度
    score += min(max(vol_ratio - 1.0, 0), 3) * 6.0 # 放量加分
    score += min(amplitude_n, 80) * 0.10           # 有弹性加少量分
    score += up_day_ratio * 8.00                   # 阳线占比
    score += above_ma20 * 5.00                     # 趋势位置
    score += near_60_high * 5.00                   # 接近60日新高
    score += min(float(amount_recent5) / 1e8, 20) * 0.30  # 成交额加分，上限保护

    return {
        '代码': normalize_code(code),
        '强势分': round(score, 4),
        f'近{lookback}日涨幅%': round(ret_n, 2),
        f'近{lookback}日回撤%': round(drawdown_from_high, 2),
        f'近{lookback}日振幅%': round(amplitude_n, 2),
        f'近{lookback}日涨停数': limit_count,
        '近5日量比': round(vol_ratio, 2),
        '近5日均成交额': round(float(amount_recent5), 2),
        '阳线占比': round(up_day_ratio, 2),
        '站上20日线': above_ma20,
        '接近60日新高': near_60_high,
        '最新收盘': round(close_now, 3),
        '数据行数': len(data),
    }


def load_auto_candidate_codes(candidate_file: str = '', use_selected_file: bool = False) -> List[str]:
    """
    自动选模板时的候选股票池：
    优先复用工程里的 load_candidate_codes；
    如果不可用，则从本地日线缓存文件名里提取代码。
    """
    if load_candidate_codes is not None:
        try:
            codes = load_candidate_codes(candidate_file or None, default_selected=use_selected_file)
            codes = [normalize_code(c) for c in codes if normalize_code(c)]
            if codes:
                return sorted(set(codes))
        except Exception as exc:
            print(f'[提示] load_candidate_codes 失败，改用缓存文件扫描：{exc}')

    codes = []
    for d in possible_daily_cache_dirs():
        if not d.exists() or not d.is_dir():
            continue
        for p in d.glob('*.csv'):
            m = re.search(r'(\d{6})', p.name)
            if m:
                codes.append(m.group(1))
    return sorted(set(codes))


def auto_select_strong_codes(
    top_n: int,
    lookback: int,
    candidate_file: str = '',
    use_selected_file: bool = False,
    output_dir: Optional[Path] = None,
) -> List[str]:
    """
    从候选股票池里自动选择强势模板股。
    """
    codes = load_auto_candidate_codes(candidate_file, use_selected_file)
    if not codes:
        raise RuntimeError('自动选股失败：没有找到候选股票代码。请检查缓存日线或 candidate-file。')

    print(f'\n开始自动选择强势模板股：候选股票数 {len(codes)}，lookback={lookback}，top_n={top_n}')

    rows = []
    start = time.time()
    total = len(codes)

    for i, code in enumerate(codes, start=1):
        row = score_strong_stock(code, lookback=lookback)
        if row:
            rows.append(row)

        if i == 1 or i % 100 == 0 or i == total:
            elapsed = time.time() - start
            speed = i / elapsed if elapsed > 0 else 0
            remain = (total - i) / speed / 60 if speed > 0 else 0
            print(
                f'  自动选模板进度: {i}/{total} | 有效: {len(rows)} | '
                f'当前: {code} | 预计剩余: {remain:.1f} 分钟',
                flush=True,
            )

    if not rows:
        raise RuntimeError('自动选股失败：没有可用于评分的日线数据。')

    df = pd.DataFrame(rows).sort_values(
        ['强势分', f'近{lookback}日涨幅%', f'近{lookback}日涨停数'],
        ascending=[False, False, False],
    )

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f'auto_template_candidates_{pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        df.to_excel(path, index=False)
        print(f'自动模板候选明细已保存：{path}')

    top_df = df.head(top_n)
    selected = top_df['代码'].astype(str).tolist()

    print('\n自动选择出的模板候选股：')
    show_cols = [
        '代码', '强势分', f'近{lookback}日涨幅%', f'近{lookback}日回撤%',
        f'近{lookback}日涨停数', '近5日量比', '阳线占比', '站上20日线', '接近60日新高'
    ]
    show_cols = [c for c in show_cols if c in top_df.columns]
    if tabulate:
        print(tabulate(top_df[show_cols], headers='keys', tablefmt='pretty', showindex=False))
    else:
        print(top_df[show_cols].to_string(index=False))

    return selected


# ======================================================================================
# 模型文件查找、命令执行、Excel 汇总
# ======================================================================================

def find_model_by_job(model_dir: Path, template: str, lookback: int, horizon: int, target: float, started_at: float) -> Optional[Path]:
    """
    并发下不能靠“最新 pkl”判断模型文件，否则可能拿到其他任务的 pkl。
    这里按模板、lookback、horizon、target 精确匹配本组模型。
    """
    safe_template = template.replace(',', '_')
    t = target_to_name(target)
    pattern = f"ml_pattern_{safe_template}_lb{lookback}_h{horizon}_t{t}_*.pkl"
    candidates = []
    if model_dir.exists():
        for p in model_dir.glob(pattern):
            try:
                if p.stat().st_mtime >= started_at - 2:
                    candidates.append(p)
            except OSError:
                pass
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


def extract_model_path_from_output(text: str) -> Optional[Path]:
    """
    优先从训练输出中解析“模型已保存: xxx.pkl”。
    这样并发时不会误拿别的任务的模型。
    """
    patterns = [
        r"模型已保存[:：]\s*(.+?\.pkl)",
        r"model saved[:：]\s*(.+?\.pkl)",
        r"saved[:：]\s*(.+?\.pkl)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).strip().strip('"').strip("'")
            p = Path(raw)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            return p
    return None


def should_hide_console_line(line: str) -> bool:
    """
    批量测试时减少高频进度行：
    日志文件完整保存；
    终端只显示每 100 只股票一次，以及最后完成行。
    """
    line_strip = line.strip()
    if not line_strip:
        return False

    progress_keywords = [
        'ML回测进度',
        'ML扫描进度',
        'ML�ز�',
        'MLɨ��',
    ]

    if not any(k in line for k in progress_keywords):
        return False

    if '/' not in line:
        return False

    m = re.search(r'(\d+)\s*/\s*(\d+)', line)
    if not m:
        return True

    current = int(m.group(1))
    total = int(m.group(2))

    # 每 100 只显示一次，最后一次也显示。
    if current % 100 == 0 or current == total:
        return False

    return True


def safe_console_print(text: str, console_lock: threading.Lock) -> None:
    with console_lock:
        print(text, end='')


def run_cmd(
    cmd: List[str],
    cwd: Path,
    log_path: Path,
    log_lock: threading.Lock,
    console_lock: threading.Lock,
    prefix: str = '',
) -> Tuple[int, str]:
    """
    执行子命令，返回 return_code 和完整输出。
    不修改子进程环境变量，避免影响 Python 初始化。
    """
    output_lines: List[str] = []
    enc = locale.getpreferredencoding(False)

    with log_lock:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('\n' + '=' * 100 + '\n')
            f.write('CMD: ' + ' '.join(cmd) + '\n')
            f.write('=' * 100 + '\n')
            f.flush()

    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=enc,
        errors='replace',
        bufsize=1,
    )
    assert proc.stdout is not None

    for line in proc.stdout:
        output_lines.append(line)

        with log_lock:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(line)
                f.flush()

        if should_hide_console_line(line):
            continue

        if prefix:
            safe_console_print(prefix + line, console_lock)
        else:
            safe_console_print(line, console_lock)

    proc.wait()

    with log_lock:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'\nRETURN_CODE: {proc.returncode}\n')
            f.flush()

    return proc.returncode, ''.join(output_lines)


def safe_read_excel(path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except Exception:
        return pd.DataFrame()


def add_meta(df: pd.DataFrame, meta: Dict[str, Any]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for k, v in reversed(list(meta.items())):
        out.insert(0, k, v)
    return out


def make_backtest_output_name(out_dir: Path, run_id: int, template: str, horizon: int, target: float) -> Path:
    safe_template = template.replace(',', '_')
    target_s = str(target).replace('.', 'p')
    return out_dir / f'backtest_{run_id:04d}_tpl_{safe_template}_h{horizon}_t{target_s}.xlsx'


def run_one_job(
    idx: int,
    total: int,
    template: str,
    horizon: int,
    target: float,
    args: argparse.Namespace,
    py: str,
    model_dir: Path,
    out_dir: Path,
    log_path: Path,
    log_lock: threading.Lock,
    console_lock: threading.Lock,
) -> Dict[str, Any]:
    # 并发时错峰启动，避免多个 Python 子进程同时初始化和导入大库。
    if args.workers > 1 and args.start_delay > 0:
        time.sleep(((idx - 1) % args.workers) * args.start_delay)

    with console_lock:
        print('\n' + '#' * 100)
        print(f'[{idx}/{total}] 训练并回测：template={template}, horizon={horizon}, target={target:g}')
        print('#' * 100)

    started_at = time.time()

    record: Dict[str, Any] = {
        '序号': idx,
        '模板': template,
        'horizon': horizon,
        'target': target,
        '训练返回码': '',
        '模型文件': '',
        '回测返回码': '',
        '回测文件': '',
        '状态': '',
        '_hold_df': pd.DataFrame(),
        '_overall_df': pd.DataFrame(),
    }

    train_cmd = [
        py, 'cli/ml_train.py',
        '--template', template,
        '--lookback', str(args.lookback),
        '--horizon', str(horizon),
        '--target', str(target),
    ]
    if args.use_pca:
        train_cmd.append('--use-pca')

    prefix = f'[{idx}/{total}] ' if args.workers > 1 else ''
    train_rc, train_output = run_cmd(train_cmd, PROJECT_ROOT, log_path, log_lock, console_lock, prefix=prefix)
    record['训练返回码'] = train_rc

    model_path = extract_model_path_from_output(train_output)
    if model_path is None or not model_path.exists():
        model_path = find_model_by_job(model_dir, template, args.lookback, horizon, target, started_at)

    record['模型文件'] = str(model_path) if model_path else ''

    if train_rc != 0 or model_path is None or not model_path.exists():
        record['状态'] = '训练失败或未找到pkl'
        with console_lock:
            print(f'[{idx}/{total}] 本组训练失败或未找到新 pkl，跳过回测。')
        return record

    backtest_output = make_backtest_output_name(out_dir, idx, template, horizon, target)
    backtest_cmd = [
        py, 'cli/ml_backtest.py',
        '--model', str(model_path),
        '--threshold', str(args.threshold),
        '--hold-days', args.hold_days,
        '--output', str(backtest_output),
        '--fee-bps', str(args.fee_bps),
        '--slippage-bps', str(args.slippage_bps),
    ]
    if args.candidate_file:
        backtest_cmd += ['--candidate-file', args.candidate_file]
    if args.use_selected_file:
        backtest_cmd.append('--use-selected-file')
    if args.include_train_templates:
        backtest_cmd.append('--include-train-templates')
    if args.max_stocks and args.max_stocks > 0:
        backtest_cmd += ['--max-stocks', str(args.max_stocks)]

    backtest_rc, _ = run_cmd(backtest_cmd, PROJECT_ROOT, log_path, log_lock, console_lock, prefix=prefix)
    record['回测返回码'] = backtest_rc
    record['回测文件'] = str(backtest_output)

    if backtest_rc != 0 or not backtest_output.exists():
        record['状态'] = '回测失败或未生成报告'
        with console_lock:
            print(f'[{idx}/{total}] 本组回测失败或未生成 Excel，跳过汇总。')
        return record

    meta = {
        '序号': idx,
        '模板': template,
        'horizon': horizon,
        'target': target,
        'threshold': args.threshold,
        '模型文件': model_path.name,
        '回测文件': backtest_output.name,
    }

    hold_df = safe_read_excel(backtest_output, '按持有期统计')
    overall_df = safe_read_excel(backtest_output, '总体统计')

    record['_hold_df'] = add_meta(hold_df, meta) if not hold_df.empty else pd.DataFrame()
    record['_overall_df'] = add_meta(overall_df, meta) if not overall_df.empty else pd.DataFrame()
    record['状态'] = '完成'

    with console_lock:
        print(f'[{idx}/{total}] 本组完成：{backtest_output.name}')

    return record


# ======================================================================================
# 主程序
# ======================================================================================

def main():
    parser = argparse.ArgumentParser(description='批量训练并回测 ML 模型，自动寻找最优和最差参数组合')

    parser.add_argument('--codes', default='', help='股票代码，逗号分隔，例如 603115,002980,600769')
    parser.add_argument('--auto-codes', action='store_true', help='自动从候选股票池中选择强势股作为模板候选')
    parser.add_argument('--auto-top-n', type=int, default=6, help='自动选择强势模板股数量，默认 6')
    parser.add_argument('--auto-lookback', type=int, default=20, help='自动选择强势股时回看最近多少个交易日，默认 20')

    parser.add_argument('--mode', default='permutation', choices=['permutation', 'combination', 'combination_range', 'single'],
                        help='模板生成方式：permutation=全排列；combination=固定数量组合；combination_range=生成2只到N只的所有组合；single=单股分别训练')
    parser.add_argument('--combo-size', type=int, default=0, help='mode=combination 时表示每组几个代码；mode=combination_range 时表示最大组合数量；默认使用全部代码')

    parser.add_argument('--horizons', default='1-5', help='训练 forward_horizon 列表，例如 1-5 或 1,3,5')
    parser.add_argument('--targets', default='5-10', help='训练 target_pct 列表，例如 5-10 或 5,7,10')
    parser.add_argument('--lookback', type=int, default=20)
    parser.add_argument('--use-pca', action='store_true')

    parser.add_argument('--threshold', type=float, default=0.65, help='回测 ML 分数阈值')
    parser.add_argument('--hold-days', default='1,2,3,4,5', help='回测持有天数，默认 1,2,3,4,5')
    parser.add_argument('--candidate-file', default='', help='传给 ml_backtest.py 的候选股票文件，也用于 auto-codes 候选池')
    parser.add_argument('--use-selected-file', action='store_true', help='回测时使用默认选股文件；auto-codes 时也优先从该文件选模板')
    parser.add_argument('--include-train-templates', action='store_true', help='回测时不排除训练模板股')
    parser.add_argument('--fee-bps', type=float, default=0.0)
    parser.add_argument('--slippage-bps', type=float, default=0.0)
    parser.add_argument('--max-stocks', type=int, default=0, help='传给 ml_backtest.py，用于快速小样本测试')

    parser.add_argument('--output-dir', default='output/ml_grid_test')
    parser.add_argument('--max-runs', type=int, default=0, help='最多执行多少组训练+回测；0表示不限制')
    parser.add_argument('--dry-run', action='store_true', help='只打印任务数量和前几组任务，不实际训练回测')
    parser.add_argument('--force', action='store_true', help='任务数量很多时仍继续执行')

    parser.add_argument('--workers', type=int, default=1,
                        help='并发执行任务数，默认 1。建议先用 2，不建议超过 3。')
    parser.add_argument('--start-delay', type=float, default=2.0,
                        help='并发启动错峰秒数，默认 2 秒，避免多个 Python 子进程同时初始化。')
    args = parser.parse_args()

    if args.workers < 1:
        args.workers = 1

    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.auto_codes:
        print(f'自动选模板股默认日线目录：{PROJECT_ROOT / "cache" / "hist"}')
        codes = auto_select_strong_codes(
            top_n=args.auto_top_n,
            lookback=args.auto_lookback,
            candidate_file=args.candidate_file,
            use_selected_file=args.use_selected_file,
            output_dir=out_dir,
        )
        # 自动选股时，如果用户没指定 mode，建议用 combination，避免 auto_top_n=6 时 permutation 爆炸。
        if args.mode == 'permutation' and args.auto_top_n > 4:
            print('\n[提示] 当前 auto-top-n 较大且 mode=permutation，全排列任务会爆炸。')
            print('建议使用：--mode combination --combo-size 3')
    else:
        if not args.codes:
            print('请提供 --codes 或使用 --auto-codes')
            sys.exit(1)
        codes = [normalize_code(c) for c in args.codes.split(',') if c.strip()]

    templates = build_templates(codes, args.mode, args.combo_size)
    horizons = parse_int_list(args.horizons)
    targets = parse_float_list(args.targets)

    jobs = list(itertools.product(templates, horizons, targets))
    if args.max_runs and args.max_runs > 0:
        jobs = jobs[:args.max_runs]

    print('\n批量 ML 参数测试配置：')
    print(f'  股票代码：{codes}')
    print(f'  模板模式：{args.mode}')
    if args.mode == 'combination':
        print(f'  组合大小 combo-size：{args.combo_size if args.combo_size > 0 else len(codes)}')
    elif args.mode == 'combination_range':
        print(f'  组合范围：2 到 {args.combo_size if args.combo_size > 0 else len(codes)} 只')
    print(f'  模板数量：{len(templates)}')
    print(f'  horizons：{horizons}')
    print(f'  targets：{targets}')
    print(f'  回测 threshold：{args.threshold}')
    print(f'  回测 hold-days：{args.hold_days}')
    print(f'  总任务数：{len(jobs)} 组训练 + 回测')
    print(f'  并发 workers：{args.workers}')

    print('\n前10组任务预览：')
    for i, (template, horizon, target) in enumerate(jobs[:10], start=1):
        print(f'  {i:02d}. template={template}, horizon={horizon}, target={target:g}')

    if args.dry_run:
        print('\n当前是 dry-run，只预览任务，不执行训练和回测。')
        return

    if len(jobs) > 300 and not args.force:
        print('\n任务数量超过 300，可能运行很久。')
        print('如果确认要跑，请加 --force；或者缩小 --auto-top-n / --horizons / --targets / --max-runs。')
        return

    if args.workers > 3:
        print('\n提示：workers 大于 3 可能导致 CPU/磁盘/内存压力过大。')
        print('建议先用 --workers 2 或 --workers 3。')

    model_dir = PROJECT_ROOT / 'output' / 'ml_models'
    log_path = out_dir / f'grid_run_{pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")}.log'

    py = sys.executable
    total = len(jobs)

    log_lock = threading.Lock()
    console_lock = threading.Lock()

    run_records: List[Dict[str, Any]] = []

    if args.workers == 1:
        for idx, (template, horizon, target) in enumerate(jobs, start=1):
            rec = run_one_job(
                idx, total, template, horizon, target,
                args, py, model_dir, out_dir, log_path,
                log_lock, console_lock,
            )
            run_records.append(rec)
    else:
        print(f'\n已开启并发模式：workers={args.workers}')
        print('提示：每个任务都会训练+回测，建议 workers 先用 2，稳定后再尝试 3。')

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {}
            for idx, (template, horizon, target) in enumerate(jobs, start=1):
                fut = executor.submit(
                    run_one_job,
                    idx, total, template, horizon, target,
                    args, py, model_dir, out_dir, log_path,
                    log_lock, console_lock,
                )
                future_map[fut] = idx

            for fut in as_completed(future_map):
                idx = future_map[fut]
                try:
                    run_records.append(fut.result())
                except Exception as exc:
                    run_records.append({
                        '序号': idx,
                        '模板': '',
                        'horizon': '',
                        'target': '',
                        '训练返回码': '',
                        '模型文件': '',
                        '回测返回码': '',
                        '回测文件': '',
                        '状态': f'异常：{exc}',
                        '_hold_df': pd.DataFrame(),
                        '_overall_df': pd.DataFrame(),
                    })
                    with console_lock:
                        print(f'[{idx}/{total}] 任务异常：{exc}')

    run_records = sorted(run_records, key=lambda x: int(x.get('序号') or 0))

    all_hold_rows: List[pd.DataFrame] = []
    all_overall_rows: List[pd.DataFrame] = []
    run_logs: List[Dict[str, Any]] = []

    for rec in run_records:
        hold_df = rec.pop('_hold_df', pd.DataFrame())
        overall_df = rec.pop('_overall_df', pd.DataFrame())
        if isinstance(hold_df, pd.DataFrame) and not hold_df.empty:
            all_hold_rows.append(hold_df)
        if isinstance(overall_df, pd.DataFrame) and not overall_df.empty:
            all_overall_rows.append(overall_df)
        run_logs.append(rec)

    hold_all = pd.concat(all_hold_rows, ignore_index=True) if all_hold_rows else pd.DataFrame()
    overall_all = pd.concat(all_overall_rows, ignore_index=True) if all_overall_rows else pd.DataFrame()
    log_df = pd.DataFrame(run_logs)

    # 排名规则：优先胜率，其次平均收益率，再次信号次数。
    if not hold_all.empty:
        sort_cols = []
        ascending = []
        for col in ['胜率%', '平均收益率%', '盈亏比', '信号次数']:
            if col in hold_all.columns:
                sort_cols.append(col)
                ascending.append(False)

        best_df = hold_all.sort_values(sort_cols, ascending=ascending).head(30) if sort_cols else hold_all.head(30)

        worst_sort_cols = []
        worst_ascending = []
        for col in ['胜率%', '平均收益率%', '盈亏比']:
            if col in hold_all.columns:
                worst_sort_cols.append(col)
                worst_ascending.append(True)
        worst_df = hold_all.sort_values(worst_sort_cols, ascending=worst_ascending).head(30) if worst_sort_cols else hold_all.tail(30)
    else:
        best_df = pd.DataFrame()
        worst_df = pd.DataFrame()

    summary_path = out_dir / f'ml_grid_summary_{pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    with pd.ExcelWriter(summary_path, engine='openpyxl') as writer:
        if not hold_all.empty:
            hold_all.to_excel(writer, sheet_name='全部按持有期统计', index=False)
        if not overall_all.empty:
            overall_all.to_excel(writer, sheet_name='全部总体统计', index=False)
        if not best_df.empty:
            best_df.to_excel(writer, sheet_name='胜率最高TOP30', index=False)
        if not worst_df.empty:
            worst_df.to_excel(writer, sheet_name='表现最差TOP30', index=False)
        log_df.to_excel(writer, sheet_name='运行日志', index=False)

    print('\n' + '=' * 100)
    print('批量测试完成')
    print(f'汇总报告：{summary_path}')
    print(f'运行日志：{log_path}')

    # 终端只展示核心列，模型文件太长，Excel 里保留完整字段。
    terminal_cols = ['模板', 'horizon', 'target', 'threshold', '持有天数', '信号次数', '胜率%', '平均收益率%', '中位数收益率%', '盈亏比']

    if not best_df.empty:
        print('\n胜率最高 TOP10：')
        show_cols = [c for c in terminal_cols if c in best_df.columns]
        show_df = best_df[show_cols].head(10)
        if tabulate:
            print(tabulate(show_df, headers='keys', tablefmt='pretty', showindex=False))
        else:
            print(show_df.to_string(index=False))

    if not worst_df.empty:
        print('\n表现最差 TOP10：')
        show_cols = [c for c in terminal_cols if c in worst_df.columns]
        show_df = worst_df[show_cols].head(10)
        if tabulate:
            print(tabulate(show_df, headers='keys', tablefmt='pretty', showindex=False))
        else:
            print(show_df.to_string(index=False))


if __name__ == '__main__':
    main()
