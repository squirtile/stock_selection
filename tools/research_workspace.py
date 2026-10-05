"""Read-only aggregation for the browser research workspace.

The helpers in this module never invoke scanners or mutate strategy output.  A
broken optional data source is represented in the result instead of bubbling
up and hiding the rest of the workspace.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


_SOURCE_FILES = {
    "strategy": ("每日策略", "mini_program_stocks.json", 36 * 60),
    "intraday": ("盘中实时", "intraday_candidates.json", 15),
    "moneyflow": ("资金流向", "money_flow.json", 36 * 60),
    "sector": ("板块热度", "sector_heat.json", 72 * 60),
    "ladder": ("连板天梯", "limit_up_ladder.json", 72 * 60),
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _code(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    return text.zfill(6) if 1 <= len(text) <= 6 else ""


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:19] if "%H" in pattern else text[:10], pattern)
        except ValueError:
            continue
    return None


def _iso_day(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else ""


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None, "文件顶层不是对象"
        return value, ""
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _payload_time(payload: dict[str, Any], path: Path) -> datetime:
    candidates = (
        payload.get("time"), payload.get("generated_at"), payload.get("generatedAt"),
        payload.get("tradeDate"), payload.get("date"),
    )
    for value in candidates:
        parsed = _parse_datetime(value)
        if parsed:
            return parsed
    dates = payload.get("dates")
    if isinstance(dates, list):
        parsed_dates = [parsed for parsed in (_parse_datetime(item) for item in dates) if parsed]
        if parsed_dates:
            return max(parsed_dates)
    return datetime.fromtimestamp(path.stat().st_mtime)


def _source_health(root: Path, now: datetime) -> dict[str, dict[str, Any]]:
    output = root / "output"
    result: dict[str, dict[str, Any]] = {}
    for key, (label, filename, stale_minutes) in _SOURCE_FILES.items():
        path = output / filename
        item: dict[str, Any] = {
            "key": key, "label": label, "file": filename, "status": "missing",
            "dataTime": "", "ageMinutes": None, "message": "文件不存在",
        }
        payload, error = _read_json(path)
        if payload is None:
            if error != "missing":
                item.update(status="error", message=f"读取失败：{error}")
            result[key] = item
            continue
        data_time = _payload_time(payload, path)
        age = (now - data_time).total_seconds() / 60
        item["dataTime"] = data_time.strftime("%Y-%m-%d %H:%M:%S")
        item["ageMinutes"] = round(age, 1)
        if age < -5:
            item.update(status="future", message="数据时间晚于当前时间")
        elif age > stale_minutes:
            item.update(status="stale", message="数据已过期，页面继续使用最近快照")
        else:
            item.update(status="ok", message="数据可用")
        result[key] = item
    return result


def _snapshot_paths(root: Path, now: datetime | None = None) -> list[Path]:
    paths = list((root / "cache").glob("tushare_a_stock_spot_*.csv"))
    if not paths:
        return []
    cutoff = (now or datetime.now()).strftime("%Y%m%d")
    eligible = [path for path in paths if path.stem.rsplit("_", 1)[-1] <= cutoff]
    return sorted(eligible or paths, key=lambda path: path.stem, reverse=True)


def _read_snapshot(root: Path, now: datetime | None = None) -> tuple[list[dict[str, Any]], str, str]:
    paths = _snapshot_paths(root, now)
    if not paths:
        return [], "", "missing"
    path = paths[0]
    file_day = _iso_day(path.stem.rsplit("_", 1)[-1])
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                code = _code(raw.get("代码") or raw.get("code"))
                if not code:
                    continue
                row_day = _iso_day(raw.get("交易日") or raw.get("日期")) or file_day
                rows.append({
                    "code": code,
                    "name": str(raw.get("名称") or raw.get("name") or "").strip(),
                    "price": _number(raw.get("最新价", raw.get("close"))),
                    "pct": _number(raw.get("涨跌幅", raw.get("pctChg"))),
                    "industry": str(raw.get("行业") or "").strip(),
                    "marketCap": _number(raw.get("总市值_亿元", raw.get("marketCap"))),
                    "quoteTime": row_day,
                })
        return rows, file_day, ""
    except (OSError, UnicodeError, csv.Error) as exc:
        return [], file_day, str(exc)


def _breadth(root: Path, now: datetime) -> dict[str, Any]:
    rows, trade_day, error = _read_snapshot(root, now)
    values = [value for value in (_number(row.get("pct")) for row in rows) if value is not None]
    advances = sum(value > 0 for value in values)
    declines = sum(value < 0 for value in values)
    flat = sum(value == 0 for value in values)
    active = advances + declines
    up_ratio = round(advances / active * 100, 2) if active else None
    if up_ratio is None:
        temperature = "暂无"
    elif up_ratio >= 60:
        temperature = "偏强"
    elif up_ratio <= 40:
        temperature = "偏弱"
    else:
        temperature = "均衡"
    stale = bool(trade_day and trade_day != now.date().isoformat())
    return {
        "tradeDate": trade_day,
        "total": len(values),
        "advances": advances,
        "declines": declines,
        "flat": flat,
        "limitUp": sum(value >= 9.5 for value in values),
        "limitDown": sum(value <= -9.5 for value in values),
        "medianPct": round(statistics.median(values), 2) if values else None,
        "upRatio": up_ratio,
        "temperature": temperature,
        "stale": stale,
        "status": "error" if error not in ("", "missing") else ("missing" if not rows else ("stale" if stale else "ok")),
        "message": error if error not in ("", "missing") else ("暂无全市场行情快照" if not rows else ""),
    }


def build_workspace_overview(project_root: str | Path, now: datetime | None = None) -> dict[str, Any]:
    """Build market breadth and independent source-health status."""
    root = Path(project_root)
    current = now or datetime.now()
    sources = _source_health(root, current)
    healthy = sum(item["status"] == "ok" for item in sources.values())
    return {
        "success": True,
        "generatedAt": current.strftime("%Y-%m-%d %H:%M:%S"),
        "breadth": _breadth(root, current),
        "sources": sources,
        "healthySources": healthy,
        "totalSources": len(sources),
        "degraded": healthy != len(sources),
    }


def _strategy_names(stock: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in stock.get("strategyTypes") or []:
        name = str(item.get("name") if isinstance(item, dict) else item or "").strip()
        if name and name not in result:
            result.append(name)
    for key in ("briefReasons", "tailStrategies"):
        for value in stock.get(key) or []:
            name = str(value or "").strip()
            if name and name not in result:
                result.append(name)
    strategy = str(stock.get("strategy") or "").strip()
    if strategy and strategy not in result:
        result.append(strategy)
    return result


def _merge_record(records: dict[str, dict[str, Any]], raw: dict[str, Any], source: str, priority: int, data_time: str) -> None:
    code = _code(raw.get("code") or raw.get("代码") or raw.get("ts_code"))
    if not code:
        return
    item = records.setdefault(code, {
        "code": code, "name": "", "price": None, "pct": None, "industry": "",
        "marketCap": None, "score": None, "strategies": [], "categories": [],
        "sources": [], "hasSignal": False, "dataTime": "", "_priority": -1,
        "_rawBySource": {},
    })
    if source not in item["sources"]:
        item["sources"].append(source)
    item["_rawBySource"][source] = raw
    names = _strategy_names(raw)
    for name in names:
        if name not in item["strategies"]:
            item["strategies"].append(name)
    for category in raw.get("categories") or []:
        if category not in item["categories"]:
            item["categories"].append(category)
    if source != "行情快照" and (names or raw.get("categories") or raw.get("reasons")):
        item["hasSignal"] = True
    if priority < item["_priority"]:
        return
    item["_priority"] = priority
    for key in ("name", "price", "pct", "industry", "marketCap", "score"):
        value = raw.get(key)
        if value not in (None, "", "nan", "None"):
            item[key] = value
    item["dataTime"] = data_time or str(raw.get("quoteTime") or item["dataTime"])


def _catalog(project_root: str | Path) -> dict[str, dict[str, Any]]:
    root = Path(project_root)
    records: dict[str, dict[str, Any]] = {}
    snapshot_rows, snapshot_day, _ = _read_snapshot(root)
    for row in snapshot_rows:
        _merge_record(records, row, "行情快照", 1, snapshot_day)

    daily, _ = _read_json(root / "output" / "mini_program_stocks.json")
    if daily:
        data_time = str(daily.get("time") or "")
        for row in daily.get("stocks") or []:
            if isinstance(row, dict):
                _merge_record(records, row, "每日策略", 2, data_time)

    hit_paths = sorted((root / "output").glob("intraday_hits_*.json"), reverse=True)
    if hit_paths:
        hits, _ = _read_json(hit_paths[0])
        if hits:
            data_time = str(hits.get("time") or hit_paths[0].stem.rsplit("_", 1)[-1])
            for row in hits.get("stocks") or []:
                if isinstance(row, dict):
                    _merge_record(records, row, "今日累计", 3, data_time)

    intraday, _ = _read_json(root / "output" / "intraday_candidates.json")
    if intraday:
        data_time = str(intraday.get("time") or "")
        for row in intraday.get("stocks") or []:
            if isinstance(row, dict):
                _merge_record(records, row, "盘中实时", 4, data_time)
    return records


def _public_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def search_stocks(project_root: str | Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search the local stock catalog, deduplicated by six-digit code."""
    needle = str(query or "").strip().lower()[:60]
    if not needle:
        return []
    bounded_limit = max(1, min(int(limit or 20), 50))
    rows = []
    for item in _catalog(project_root).values():
        haystack = " ".join((item["code"], str(item.get("name") or ""), str(item.get("industry") or ""))).lower()
        if needle in haystack:
            rows.append(_public_record(item))
    rows.sort(key=lambda item: (
        0 if item["code"].startswith(needle) else 1,
        0 if str(item.get("name") or "").lower().startswith(needle) else 1,
        -int(item.get("score") or 0), item["code"],
    ))
    return rows[:bounded_limit]


def _score_explanation(current: dict[str, Any], raw_by_source: dict[str, Any]) -> dict[str, Any]:
    intraday = raw_by_source.get("盘中实时") or raw_by_source.get("今日累计") or {}
    breakdown = intraday.get("scoreBreakdown")
    if isinstance(breakdown, dict):
        clean = {str(key): _number(value) for key, value in breakdown.items() if _number(value) is not None}
        return {
            "total": current.get("score"), "mode": "existing-breakdown",
            "breakdown": clean, "note": "展示扫描器已有评分明细，不重新评分",
        }
    daily = raw_by_source.get("每日策略") or {}
    return {
        "total": current.get("score"), "mode": "display-evidence", "breakdown": {},
        "evidence": {
            "strategyCount": int(daily.get("strategyCount") or len(current.get("strategies") or [])),
            "categories": list(current.get("categories") or []),
            "strategies": list(current.get("strategies") or []),
        },
        "note": "仅列出现有展示依据，不重新计算评分",
    }


def build_stock_research(project_root: str | Path, code: str) -> dict[str, Any] | None:
    normalized = _code(code)
    if not re.fullmatch(r"\d{6}", normalized):
        return None
    root = Path(project_root)
    row = _catalog(root).get(normalized)
    if not row:
        return None
    raw_by_source = row.get("_rawBySource") or {}
    signals: list[dict[str, Any]] = []
    for source in ("盘中实时", "今日累计", "每日策略"):
        raw = raw_by_source.get(source)
        if not raw:
            continue
        names = _strategy_names(raw)
        reasons = [str(value) for value in raw.get("reasons") or [] if str(value).strip()]
        signals.append({"source": source, "strategies": names, "reasons": reasons})
    intraday = raw_by_source.get("盘中实时") or raw_by_source.get("今日累计") or {}
    money_flow = None
    if any(key in intraday for key in ("mainNetInflow", "mainNetRatio", "mainMoneyTrend")):
        money_flow = {
            "mainNetInflow": _number(intraday.get("mainNetInflow")),
            "mainNetRatio": _number(intraday.get("mainNetRatio")),
            "trend": str(intraday.get("mainMoneyTrend") or ""),
            "updatedAt": str(intraday.get("mainMoneyUpdatedAt") or row.get("dataTime") or ""),
            "stale": bool(intraday.get("mainMoneyStale")),
        }
    history_stats: list[dict[str, Any]] = []
    try:
        from backtest.strategy_history_store import load_dashboard
        wanted = set(row.get("strategies") or [])
        history_stats = [item for item in load_dashboard(root).get("historyRows", [])
                         if item.get("strategy") in wanted and item.get("direction") != "看跌"]
    except Exception:
        history_stats = []
    return {
        "success": True,
        "code": normalized,
        "current": _public_record(row),
        "signals": signals,
        "scoreExplanation": _score_explanation(row, raw_by_source),
        "historyStats": history_stats,
        "moneyFlow": money_flow,
        "klineAvailable": (root / "cache" / "hist" / f"{normalized}_bs.csv").is_file(),
    }


def _alert(kind: str, code: str, stock: dict[str, Any], data_time: str) -> dict[str, Any]:
    day = _iso_day(stock.get("signalDate") or data_time) or date.today().isoformat()
    names = _strategy_names(stock)
    source = "每日策略" if kind == "daily" else "盘中实时"
    return {
        "id": f"{kind}:{day}:{code}",
        "kind": kind,
        "code": code,
        "name": str(stock.get("name") or code),
        "source": source,
        "time": data_time,
        "title": f"{source}命中",
        "message": "、".join(names[:3]) or "进入当前选股结果",
    }


def build_watchlist_alerts(project_root: str | Path, codes: Iterable[str]) -> list[dict[str, Any]]:
    root = Path(project_root)
    wanted = {normalized for value in list(codes)[:100] if (normalized := _code(value))}
    if not wanted:
        return []
    result: list[dict[str, Any]] = []
    daily, _ = _read_json(root / "output" / "mini_program_stocks.json")
    if daily:
        for stock in daily.get("stocks") or []:
            code = _code(stock.get("code")) if isinstance(stock, dict) else ""
            if code in wanted:
                result.append(_alert("daily", code, stock, str(daily.get("time") or "")))
    intraday, _ = _read_json(root / "output" / "intraday_candidates.json")
    if intraday:
        for stock in intraday.get("stocks") or []:
            code = _code(stock.get("code")) if isinstance(stock, dict) else ""
            if code in wanted:
                result.append(_alert("intraday", code, stock, str(intraday.get("time") or "")))
    result.sort(key=lambda item: (item["time"], item["id"]), reverse=True)
    return result
