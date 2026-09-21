"""刷新选股 JSON 前，对上一版策略命中股票做当日复盘。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if pd.notna(value) else None
    except (TypeError, ValueError):
        return None


def _normalize_date(value: Any, default_year: str) -> str:
    """兼容旧JSON中的 MM-DD 与新数据中的 YYYY-MM-DD。"""
    text = str(value or "").strip()[:10]
    if len(text) == 5 and text[2] == "-":
        text = f"{default_year}-{text}"
    parsed = pd.to_datetime(text, errors="coerce")
    return parsed.strftime("%Y-%m-%d") if pd.notna(parsed) else ""


def _latest_daily_quote(code: str, hist_dir: Path) -> dict[str, Any] | None:
    path = hist_dir / f"{str(code).zfill(6)}_bs.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or not {"日期", "收盘"}.issubset(df.columns):
            return None
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
        df = df.dropna(subset=["日期", "收盘"]).sort_values("日期")
        if df.empty:
            return None
        latest = df.iloc[-1]
        pct = _number(latest.get("涨跌幅"))
        if pct is None and len(df) > 1:
            pct = (float(latest["收盘"]) / float(df.iloc[-2]["收盘"]) - 1) * 100
        return {"date": latest["日期"].strftime("%Y-%m-%d"), "close": float(latest["收盘"]), "pct": pct}
    except Exception:
        return None


def review_previous_signals(project_root: str | Path, *, output_name: str = "strategy_backtest_latest.json") -> dict[str, Any]:
    """读取刷新前的小程序 JSON，按策略保存上一批信号的今日表现。

    这是一日复盘模块，不把未发生的分钟成交或收益当作真实回测：
    ``todayPct`` 是最新完整日线的当日涨跌幅，``sinceSignalPct`` 是相对
    旧 JSON 内信号价的变化。胜率定义为当日涨幅大于 0 的比例。
    """
    root = Path(project_root)
    output_dir = root / "output"
    source_path = output_dir / "mini_program_stocks.json"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result: dict[str, Any] = {
        "reviewTime": now, "sourceTime": "", "sourceTotal": 0,
        "total": 0, "pending": 0, "stocks": [], "strategyStats": [],
    }

    if not source_path.exists():
        return result
    try:
        previous = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result

    result["sourceTime"] = str(previous.get("time", ""))
    result["sourceTotal"] = len(previous.get("stocks", []))
    source_year = result["sourceTime"][:4] if len(result["sourceTime"]) >= 4 else str(datetime.now().year)
    stats: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in previous.get("stocks", []):
        strategy_types = [
            entry for entry in (stock.get("strategyTypes") or [])
            if "缠论一买" not in str(entry.get("name", ""))
            and "缠论1买" not in str(entry.get("name", ""))
            and not ("缠论" in str(entry.get("name", "")) and "卖" in str(entry.get("name", "")))
        ]
        if not strategy_types:
            continue
        quote = _latest_daily_quote(str(stock.get("code", "")), root / "cache" / "hist")
        if quote is None:
            continue
        signal_date = _normalize_date(stock.get("signalDate", ""), source_year)
        if not signal_date:
            klines = stock.get("klines") or []
            if klines:
                signal_date = _normalize_date(klines[-1].get("date", ""), source_year)
        if not signal_date:
            signal_date = _normalize_date(previous.get("time", ""), source_year)
        quote_date = _normalize_date(quote["date"], source_year)
        is_next_day = bool(signal_date and quote_date and quote_date > signal_date)
        signal_price = _number(stock.get("price"))
        since_signal_pct = None
        if signal_price and signal_price > 0:
            since_signal_pct = (quote["close"] / signal_price - 1) * 100
        item = {
            "code": str(stock.get("code", "")).zfill(6),
            "name": stock.get("name", ""),
            "signalDate": signal_date,
            "signalPrice": signal_price,
            "latestClose": quote["close"],
            "tradeDate": quote["date"],
            "todayPct": quote["pct"],
            "sinceSignalPct": since_signal_pct,
            "strategies": [entry.get("name", "") for entry in strategy_types if entry.get("name")],
            "status": "已评价" if is_next_day else "等待下一交易日",
        }
        result["stocks"].append(item)
        if is_next_day:
            for name in item["strategies"]:
                stats[name].append(item)
        else:
            result["pending"] += 1

    for name, items in sorted(stats.items()):
        values = [x["todayPct"] for x in items if x["todayPct"] is not None]
        is_sell = "卖" in name
        wins = sum(v < 0 for v in values) if is_sell else sum(v > 0 for v in values)
        result["strategyStats"].append({
            "strategy": name,
            "direction": "看跌" if is_sell else "看涨",
            "signals": len(items),
            "evaluated": len(values),
            "wins": wins,
            "winRate": round(wins / len(values) * 100, 2) if values else None,
            "avgTodayPct": round(sum(values) / len(values), 2) if values else None,
        })

    result["total"] = sum(item["status"] == "已评价" for item in result["stocks"])
    try:
        from backtest.strategy_history_store import save_review
        result["historyRecordsSaved"] = save_review(root, result)
        result["historyDatabase"] = "output/strategy_history.sqlite3"
    except Exception as exc:
        result["historyRecordsSaved"] = 0
        result["historyDatabaseError"] = str(exc)
    latest_path = output_dir / output_name
    dated_path = output_dir / f"strategy_backtest_{datetime.now():%Y%m%d}.json"
    for path in (latest_path, dated_path):
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    print(
        f"  回测复盘：上一版 {result['sourceTotal']} 只，"
        f"已评价 {result['total']} 只，等待下一交易日 {result['pending']} 只；"
        f"已写入 {latest_path.name}"
    )
    for stat in result["strategyStats"]:
        win_rate = "--" if stat["winRate"] is None else f"{stat['winRate']:.2f}%"
        avg_pct = "--" if stat["avgTodayPct"] is None else f"{stat['avgTodayPct']:+.2f}%"
        print(f"    {stat['strategy']}：{stat['wins']}/{stat['evaluated']} 胜率 {win_rate}，当日均涨幅 {avg_pct}")
    return result
