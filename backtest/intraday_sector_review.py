#!/usr/bin/env python3
"""评价东方财富盘中快照里的行业前置条件，不重新使用Tushare/BaoStock。

以10:30附近快照作为观察点，用当天最后一份快照的累计最高价判断其后是否
触及主板涨停。分别统计旧个股形态与“个股形态+行业+市场”两组，避免把
实时叠加规则误称为已经历史验证的模型。
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = ROOT / "cache" / "intraday_snapshots"
OUTPUT_FILE = ROOT / "output" / "intraday_sector_validation.json"
MIN_REVIEW_DAYS = 20


def _load(path: Path) -> dict[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _minute(path: Path) -> int:
    try:
        value = path.stem.split(".")[0]
        return int(value[:2]) * 60 + int(value[2:4])
    except (ValueError, IndexError):
        return -1


def _checkpoint_file(files: list[Path]) -> Path | None:
    target = 10 * 60 + 30
    nearby = [path for path in files if abs(_minute(path) - target) <= 2]
    return min(nearby, key=lambda p: abs(_minute(p) - target)) if nearby else None


def _metrics(selected: int, hits: int) -> dict[str, Any]:
    return {
        "selected": selected, "hits": hits,
        "precision": round(hits / selected * 100, 2) if selected else None,
    }


def review() -> dict[str, Any]:
    daily = []
    for folder in sorted(SNAPSHOT_ROOT.glob("????-??-??")):
        files = sorted(folder.glob("*.json.gz"), key=_minute)
        checkpoint_path = _checkpoint_file(files)
        final_path = files[-1] if files else None
        if not checkpoint_path or not final_path or _minute(final_path) <= _minute(checkpoint_path):
            continue
        checkpoint, final = _load(checkpoint_path), _load(final_path)
        if not checkpoint or not final:
            continue
        final_stocks = {s.get("code"): s for s in final.get("stocks", [])}
        pattern_selected = pattern_hits = sector_selected = sector_hits = 0
        details = []
        market_ok = float(checkpoint.get("market", {}).get("upRatio", 0)) >= 25
        for stock in checkpoint.get("stocks", []):
            if not stock.get("learnedMatch"):
                continue
            end = final_stocks.get(stock.get("code"))
            if not end:
                continue
            pattern_selected += 1
            prev_close = float(stock.get("prevClose") or 0)
            touched = bool(prev_close and float(end.get("high") or 0) >= prev_close * 1.095)
            pattern_hits += int(touched)
            passed_sector = bool(stock.get("sectorEligible") and market_ok)
            if passed_sector:
                sector_selected += 1
                sector_hits += int(touched)
            details.append({
                "code": stock.get("code"), "name": stock.get("name"),
                "industry": stock.get("industry"), "sectorPassed": passed_sector,
                "laterTouchedLimit": touched,
            })
        daily.append({
            "date": folder.name, "checkpoint": checkpoint.get("time"), "final": final.get("time"),
            "individualStock": _metrics(pattern_selected, pattern_hits),
            "withSector": _metrics(sector_selected, sector_hits), "stocks": details,
        })

    old_selected = sum(d["individualStock"]["selected"] for d in daily)
    old_hits = sum(d["individualStock"]["hits"] for d in daily)
    sector_selected = sum(d["withSector"]["selected"] for d in daily)
    sector_hits = sum(d["withSector"]["hits"] for d in daily)
    result = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "东方财富免费网页行情分钟快照",
        "checkpoint": "10:30（允许前后2分钟）", "reviewDays": len(daily),
        "minimumReviewDays": MIN_REVIEW_DAYS,
        "status": "可进行初步比较" if len(daily) >= MIN_REVIEW_DAYS else "样本积累中",
        "individualStock": _metrics(old_selected, old_hits),
        "withSector": _metrics(sector_selected, sector_hits), "daily": daily,
        "warning": "触板不等于可成交或盈利；达到最少天数也仅代表可以开始比较，不代表策略已经有效。",
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    temp = OUTPUT_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUTPUT_FILE)
    return result


if __name__ == "__main__":
    data = review()
    print(
        f"板块规则复盘：{data['reviewDays']}/{data['minimumReviewDays']}个交易日，"
        f"当前状态={data['status']}，板块后候选={data['withSector']['selected']}"
    )
