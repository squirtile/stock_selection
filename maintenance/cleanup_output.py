#!/usr/bin/env python3
"""按时间归档可再生的输出文件；默认只预览，使用 --apply 才会移动文件。"""
from __future__ import annotations

import argparse
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
ARCHIVE = OUTPUT / "archive"

RULES = (
    ("daily_report_*.xlsx", 60, re.compile(r"daily_report_(\d{8})_")),
    ("a_stock_signal_selected_*.xlsx", 60, re.compile(r"a_stock_signal_selected_(\d{8})_")),
    ("intraday_hits_*.json", 30, re.compile(r"intraday_hits_(\d{4}-\d{2}-\d{2})")),
    ("intraday_tail_*.json", 30, re.compile(r"intraday_tail_(\d{4}-\d{2}-\d{2})")),
    ("strategy_backtest_*.json", 90, re.compile(r"strategy_backtest_(\d{8})")),
)


def _file_date(path: Path, pattern: re.Pattern[str]) -> date | None:
    match = pattern.search(path.name)
    if not match:
        return None
    raw = match.group(1)
    try:
        return datetime.strptime(raw, "%Y%m%d" if len(raw) == 8 else "%Y-%m-%d").date()
    except ValueError:
        return None


def candidates(today: date | None = None) -> list[tuple[Path, str]]:
    today = today or date.today()
    selected: list[tuple[Path, str]] = []
    for glob, days, pattern in RULES:
        files = [path for path in OUTPUT.glob(glob) if path.is_file() and path.name != "strategy_backtest_latest.json"]
        # 每个日期只保留最新文件；同日旧文件可以安全归档。
        latest: dict[date, Path] = {}
        for path in files:
            day = _file_date(path, pattern)
            if day is None or path.name.startswith("intraday_tail_candidates"):
                continue
            if day not in latest or path.stat().st_mtime > latest[day].stat().st_mtime:
                latest[day] = path
        for path in files:
            day = _file_date(path, pattern)
            if day is None:
                continue
            age = (today - day).days
            if path != latest.get(day):
                selected.append((path, f"同日旧版本（保留 {latest[day].name}）"))
            elif age > days:
                selected.append((path, f"{age}天前，超过{days}天保留期"))
    return sorted(selected, key=lambda item: str(item[0]))


def run(apply: bool = False) -> int:
    rows = candidates()
    print(f"待归档 {len(rows)} 个文件；模式：{'执行' if apply else '预览'}")
    for path, reason in rows:
        print(f"  {path.name}：{reason}")
        if apply:
            target = ARCHIVE / datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m") / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="将待归档文件移动到 output/archive，不删除")
    args = parser.parse_args()
    run(args.apply)
