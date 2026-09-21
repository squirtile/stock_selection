"""用 SQLite 持久化每日策略信号结果，并生成当天/历史汇总。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_NAME = "strategy_history.sqlite3"


def database_path(project_root: str | Path) -> Path:
    return Path(project_root) / "output" / DB_NAME


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_signal_results (
            signal_date TEXT NOT NULL,
            review_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            strategy TEXT NOT NULL,
            direction TEXT NOT NULL,
            signal_price REAL,
            close_price REAL,
            today_pct REAL NOT NULL,
            since_signal_pct REAL,
            win INTEGER NOT NULL CHECK (win IN (0, 1)),
            source_time TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (signal_date, review_date, stock_code, strategy)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_strategy_results_strategy_date "
        "ON strategy_signal_results(strategy, review_date)"
    )
    return connection


def save_review(project_root: str | Path, review: dict[str, Any]) -> int:
    """保存一份有效复盘；重复运行按联合主键更新，不重复累计。"""
    rows = []
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_time = str(review.get("sourceTime") or "")
    for stock in review.get("stocks", []):
        if stock.get("status") != "已评价" or stock.get("todayPct") is None:
            continue
        signal_date, review_date = str(stock.get("signalDate") or ""), str(stock.get("tradeDate") or "")
        raw_code = str(stock.get("code") or "").strip()
        if not signal_date or not review_date or not raw_code:
            continue
        code = raw_code.zfill(6)
        today_pct = float(stock["todayPct"])
        for strategy in stock.get("strategies", []):
            strategy = str(strategy).strip()
            if not strategy:
                continue
            direction = "看跌" if "卖" in strategy else "看涨"
            win = int(today_pct < 0) if direction == "看跌" else int(today_pct > 0)
            rows.append((
                signal_date, review_date, code, str(stock.get("name") or ""), strategy, direction,
                stock.get("signalPrice"), stock.get("latestClose"), today_pct,
                stock.get("sinceSignalPct"), win, source_time, updated_at,
            ))
    if not rows:
        return 0
    with _connect(database_path(project_root)) as connection:
        connection.executemany(
            """
            INSERT INTO strategy_signal_results (
                signal_date, review_date, stock_code, stock_name, strategy, direction,
                signal_price, close_price, today_pct, since_signal_pct, win, source_time, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_date, review_date, stock_code, strategy) DO UPDATE SET
                stock_name=excluded.stock_name,
                direction=excluded.direction,
                signal_price=excluded.signal_price,
                close_price=excluded.close_price,
                today_pct=excluded.today_pct,
                since_signal_pct=excluded.since_signal_pct,
                win=excluded.win,
                source_time=excluded.source_time,
                updated_at=excluded.updated_at
            """,
            rows,
        )
    return len(rows)


def load_dashboard(project_root: str | Path) -> dict[str, Any]:
    """返回数据库最新评价日与全历史的策略胜率。"""
    path = database_path(project_root)
    if not path.exists():
        return {"reviewDate": "", "rows": [], "todayRows": [], "historyRows": [], "totalRecords": 0, "historyStart": "", "historyEnd": ""}
    with _connect(path) as connection:
        bounds = connection.execute(
            "SELECT MIN(review_date) AS start_date, MAX(review_date) AS end_date, COUNT(*) AS records "
            "FROM strategy_signal_results"
        ).fetchone()
        latest_date = str(bounds["end_date"] or "")
        if not latest_date:
            return {"reviewDate": "", "rows": [], "todayRows": [], "historyRows": [], "totalRecords": 0, "historyStart": "", "historyEnd": ""}
        history_rows = connection.execute(
            """
            SELECT strategy, direction, COUNT(*) AS evaluated, SUM(win) AS wins,
                   AVG(today_pct) AS avg_pct, COUNT(DISTINCT review_date) AS review_days
            FROM strategy_signal_results WHERE strategy NOT LIKE '%缠论一买' AND strategy NOT LIKE '%缠论%1买' GROUP BY strategy, direction
            """
        ).fetchall()
        today_rows = connection.execute(
            """
            SELECT strategy, direction, COUNT(*) AS evaluated, SUM(win) AS wins, AVG(today_pct) AS avg_pct
            FROM strategy_signal_results WHERE review_date = ? AND strategy NOT LIKE '%缠论一买' AND strategy NOT LIKE '%缠论%1买' GROUP BY strategy, direction
            """,
            (latest_date,),
        ).fetchall()
    today = {(row["strategy"], row["direction"]): row for row in today_rows}
    rows = []
    for history in history_rows:
        key = (history["strategy"], history["direction"])
        current = today.get(key)
        history_evaluated, history_wins = int(history["evaluated"]), int(history["wins"] or 0)
        today_evaluated, today_wins = (int(current["evaluated"]), int(current["wins"] or 0)) if current else (0, 0)
        rows.append({
            "strategy": history["strategy"], "direction": history["direction"],
            "todayEvaluated": today_evaluated, "todayWins": today_wins,
            "todayWinRate": round(today_wins / today_evaluated * 100, 2) if today_evaluated else None,
            "todayAvgPct": round(float(current["avg_pct"]), 2) if current and current["avg_pct"] is not None else None,
            "historyEvaluated": history_evaluated, "historyWins": history_wins,
            "historyWinRate": round(history_wins / history_evaluated * 100, 2) if history_evaluated else None,
            "historyAvgPct": round(float(history["avg_pct"]), 2) if history["avg_pct"] is not None else None,
            "reviewDays": int(history["review_days"]),
        })
    rows.sort(key=lambda row: (
        row["todayWinRate"] if row["todayWinRate"] is not None else -1,
        row["historyWinRate"] if row["historyWinRate"] is not None else -1,
        row["todayEvaluated"],
    ), reverse=True)
    today_rows_sorted = sorted(
        (row for row in rows if row["todayEvaluated"] > 0),
        key=lambda row: (
            row["todayWinRate"] if row["todayWinRate"] is not None else -1,
            row["todayEvaluated"], row["todayAvgPct"] if row["todayAvgPct"] is not None else -999,
        ),
        reverse=True,
    )
    history_rows_sorted = sorted(
        rows,
        key=lambda row: (
            row["historyWinRate"] if row["historyWinRate"] is not None else -1,
            row["historyEvaluated"], row["reviewDays"],
        ),
        reverse=True,
    )
    return {
        "reviewDate": latest_date, "historyStart": str(bounds["start_date"] or ""),
        "historyEnd": latest_date, "totalRecords": int(bounds["records"] or 0), "rows": rows,
        "todayRows": today_rows_sorted, "historyRows": history_rows_sorted,
    }
