#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量测试 ML 模板组合、训练参数和回测结果。

功能：
1. 用户只需要提供多个股票代码；
2. 自动生成模板代码的不同排列组合，默认使用全排列；
   例如 3 个代码会生成 3! = 6 种模板顺序；
3. 自动遍历训练 forward_horizon，例如 1~5；
4. 自动遍历训练 target_pct，例如 5~10；
5. 每组参数自动调用 cli/ml_train.py 训练 pkl；
6. 每个 pkl 自动调用 cli/ml_backtest.py 回测；
7. 自动汇总每个模型在不同持有天数下的胜率、平均收益、盈亏比等；
8. 输出一个总 Excel，方便查看最好和最差的组合。

示例：
python cli/ml_grid_test.py --codes 603115,002980,600769 --threshold 0.65 --use-selected-file

先只看会跑多少组，不真正执行：
python cli/ml_grid_test.py --codes 603115,002980,600769 --dry-run
"""

import argparse
import locale
import itertools
import sys
import time
import subprocess
from pathlib import Path
from tabulate import tabulate
from typing import List, Dict, Any, Optional

import pandas as pd

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


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
    return str(code).strip().split('.')[0].zfill(6)


def build_templates(codes: List[str], mode: str, combo_size: int) -> List[str]:
    codes = [normalize_code(c) for c in codes if str(c).strip()]
    if not codes:
        return []

    if mode == 'permutation':
        # 默认：全排列。3个代码 => 6种。
        items = itertools.permutations(codes, len(codes))
    elif mode == 'combination':
        size = combo_size if combo_size > 0 else len(codes)
        items = itertools.combinations(codes, size)
    elif mode == 'single':
        items = [(c,) for c in codes]
    else:
        raise ValueError(f'未知 mode: {mode}')

    templates = [','.join(x) for x in items]
    # 去重，防止重复代码导致重复模板
    return list(dict.fromkeys(templates))


def list_pkls(model_dir: Path) -> Dict[Path, float]:
    if not model_dir.exists():
        return {}
    return {p: p.stat().st_mtime for p in model_dir.glob('*.pkl')}


def find_new_model(model_dir: Path, before: Dict[Path, float], started_at: float) -> Optional[Path]:
    after = list_pkls(model_dir)

    new_files = [p for p in after.keys() if p not in before]
    if new_files:
        return max(new_files, key=lambda p: p.stat().st_mtime)

    # 有些情况下训练会覆盖同名文件，兜底找本次开始后修改的最新文件
    changed_files = [p for p, mtime in after.items() if mtime >= started_at - 1]
    if changed_files:
        return max(changed_files, key=lambda p: p.stat().st_mtime)

    return None


def should_hide_console_line(line: str) -> bool:
    """
    批量测试时减少高频进度行：
    日志完整保存；
    终端只显示每 100 只股票一次，以及最后完成行。
    """
    line_strip = line.strip()
    if not line_strip:
        return False

    progress_keywords = [
        "ML回测进度",
        "ML扫描进度",
        "ML�ز�",
        "MLɨ��",
    ]

    if not any(k in line for k in progress_keywords):
        return False

    if "/" not in line:
        return False

    import re
    m = re.search(r"(\d+)\s*/\s*(\d+)", line)
    if not m:
        return True

    current = int(m.group(1))
    total = int(m.group(2))

    # 每 100 只显示一次，最后一次也显示
    if current % 100 == 0 or current == total:
        return False

    return True


def run_cmd(cmd: List[str], cwd: Path, log_path: Path) -> int:
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write('\n' + '=' * 100 + '\n')
        f.write('CMD: ' + ' '.join(cmd) + '\n')
        f.write('=' * 100 + '\n')
        f.flush()

        # 稳定串行版：不改子进程环境变量，避免影响 Python 初始化。
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            # Windows PowerShell 下子进程通常按本地编码输出中文，例如 GBK/cp936。
            # 这里用系统首选编码解码，避免出现 “ѵ�� ML ģ��” 这类乱码。
            encoding=locale.getpreferredencoding(False),
            errors='replace',
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            f.write(line)
            f.flush()

            if should_hide_console_line(line):
                continue

            print(line, end='')

        proc.wait()
        f.write(f'\nRETURN_CODE: {proc.returncode}\n')
        f.flush()
        return proc.returncode


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


def main():
    parser = argparse.ArgumentParser(description='批量训练并回测 ML 模型，自动寻找最优和最差参数组合')
    parser.add_argument('--codes', required=True, help='股票代码，逗号分隔，例如 603115,002980,600769')

    parser.add_argument('--mode', default='permutation', choices=['permutation', 'combination', 'single'],
                        help='模板生成方式：permutation=全排列，3个代码生成6种；combination=组合；single=单股分别训练')
    parser.add_argument('--combo-size', type=int, default=0, help='mode=combination 时生效，表示每组几个代码；默认使用全部代码')

    parser.add_argument('--horizons', default='1-5', help='训练 forward_horizon 列表，例如 1-5 或 1,3,5')
    parser.add_argument('--targets', default='5-10', help='训练 target_pct 列表，例如 5-10 或 5,7,10')
    parser.add_argument('--lookback', type=int, default=20)
    parser.add_argument('--use-pca', action='store_true')

    parser.add_argument('--threshold', type=float, default=0.65, help='回测 ML 分数阈值')
    parser.add_argument('--hold-days', default='1,2,3,4,5', help='回测持有天数，默认 1,2,3,4,5')
    parser.add_argument('--candidate-file', default='', help='传给 ml_backtest.py 的候选股票文件')
    parser.add_argument('--use-selected-file', action='store_true', help='回测时使用默认选股文件')
    parser.add_argument('--include-train-templates', action='store_true', help='回测时不排除训练模板股')
    parser.add_argument('--fee-bps', type=float, default=0.0)
    parser.add_argument('--slippage-bps', type=float, default=0.0)
    parser.add_argument('--max-stocks', type=int, default=0, help='传给 ml_backtest.py，用于快速小样本测试')

    parser.add_argument('--output-dir', default='output/ml_grid_test')
    parser.add_argument('--max-runs', type=int, default=0, help='最多执行多少组训练+回测；0表示不限制')
    parser.add_argument('--dry-run', action='store_true', help='只打印任务数量和前几组任务，不实际训练回测')
    parser.add_argument('--force', action='store_true', help='任务数量很多时仍继续执行')
    args = parser.parse_args()

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
    print(f'  模板数量：{len(templates)}')
    print(f'  horizons：{horizons}')
    print(f'  targets：{targets}')
    print(f'  回测 threshold：{args.threshold}')
    print(f'  回测 hold-days：{args.hold_days}')
    print(f'  总任务数：{len(jobs)} 组训练 + 回测')

    print('\n前10组任务预览：')
    for i, (template, horizon, target) in enumerate(jobs[:10], start=1):
        print(f'  {i:02d}. template={template}, horizon={horizon}, target={target:g}')

    if args.dry_run:
        print('\n当前是 dry-run，只预览任务，不执行训练和回测。')
        return

    if len(jobs) > 300 and not args.force:
        print('\n任务数量超过 300，可能运行很久。')
        print('如果确认要跑，请加 --force；或者用 --max-runs 先小批量测试。')
        return

    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    model_dir = PROJECT_ROOT / 'output' / 'ml_models'
    log_path = out_dir / f'grid_run_{pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")}.log'

    all_hold_rows: List[pd.DataFrame] = []
    all_overall_rows: List[pd.DataFrame] = []
    run_logs: List[Dict[str, Any]] = []

    py = sys.executable
    total = len(jobs)

    for idx, (template, horizon, target) in enumerate(jobs, start=1):
        print('\n' + '#' * 100)
        print(f'[{idx}/{total}] 训练并回测：template={template}, horizon={horizon}, target={target:g}')
        print('#' * 100)

        before_pkls = list_pkls(model_dir)
        started_at = time.time()

        train_cmd = [
            py, 'cli/ml_train.py',
            '--template', template,
            '--lookback', str(args.lookback),
            '--horizon', str(horizon),
            '--target', str(target),
        ]
        if args.use_pca:
            train_cmd.append('--use-pca')

        train_rc = run_cmd(train_cmd, PROJECT_ROOT, log_path)
        model_path = find_new_model(model_dir, before_pkls, started_at) if train_rc == 0 else None

        record: Dict[str, Any] = {
            '序号': idx,
            '模板': template,
            'horizon': horizon,
            'target': target,
            '训练返回码': train_rc,
            '模型文件': str(model_path) if model_path else '',
            '回测返回码': '',
            '回测文件': '',
            '状态': '',
        }

        if train_rc != 0 or model_path is None:
            record['状态'] = '训练失败或未找到pkl'
            run_logs.append(record)
            print('本组训练失败或未找到新 pkl，跳过回测。')
            continue

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

        backtest_rc = run_cmd(backtest_cmd, PROJECT_ROOT, log_path)
        record['回测返回码'] = backtest_rc
        record['回测文件'] = str(backtest_output)

        if backtest_rc != 0 or not backtest_output.exists():
            record['状态'] = '回测失败或未生成报告'
            run_logs.append(record)
            print('本组回测失败或未生成 Excel，跳过汇总。')
            continue

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

        if not hold_df.empty:
            all_hold_rows.append(add_meta(hold_df, meta))
        if not overall_df.empty:
            all_overall_rows.append(add_meta(overall_df, meta))

        record['状态'] = '完成'
        run_logs.append(record)

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

    if not best_df.empty:
        print('\n胜率最高 TOP10：')
        show_cols = [c for c in ['模板', 'horizon', 'target', 'threshold', '持有天数', '信号次数', '胜率%', '平均收益率%', '中位数收益率%', '盈亏比'] if c in best_df.columns]
        # print(best_df[show_cols].head(10).to_string(index=False))
        print(tabulate(best_df[show_cols].head(10), headers="keys", tablefmt="pretty", showindex=False))

    if not worst_df.empty:
        print('\n表现最差 TOP10：')
        show_cols = [c for c in ['模板', 'horizon', 'target', 'threshold', '持有天数', '信号次数', '胜率%', '平均收益率%', '中位数收益率%', '盈亏比'] if c in worst_df.columns]
        # print(worst_df[show_cols].head(10).to_string(index=False))
        print(tabulate(worst_df[show_cols].head(10), headers="keys", tablefmt="pretty", showindex=False))


if __name__ == '__main__':
    main()
