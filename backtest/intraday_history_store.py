"""SQLite 持久化盘中实时选股，并汇总策略的后续上涨胜率。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_NAME = "strategy_history.sqlite3"


def database_path(project_root: str | Path) -> Path:
    return Path(project_root) / "output" / DB_NAME


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _labels(stock: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    if stock.get("learnedMatch"):
        labels.append("低涨幅后续触板")
    if stock.get("bigYangPullbackMatch"):
        labels.append("大阳回调不破10日线")
    if stock.get("longShadowMatch"):
        labels.append("长上下影线")
    labels.extend(
        str(signal.get("name") or signal.get("type"))
        for signal in (stock.get("chanlunBuySignals") or [])
        if signal.get("name") or signal.get("type")
    )
    return list(dict.fromkeys(labels))


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_selection_records (
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL DEFAULT '',
            first_hit_time TEXT NOT NULL DEFAULT '',
            last_hit_time TEXT NOT NULL DEFAULT '',
            selected_price REAL,
            selected_pct REAL,
            close_price REAL,
            close_pct REAL,
            return_pct REAL,
            score INTEGER,
            industry TEXT NOT NULL DEFAULT '',
            sector_pct REAL,
            sector_main_net_ratio REAL,
            current_match INTEGER NOT NULL DEFAULT 0,
            hit_scans INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, stock_code)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_selection_strategies (
            trade_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            strategy TEXT NOT NULL,
            PRIMARY KEY (trade_date, stock_code, strategy),
            FOREIGN KEY (trade_date, stock_code)
                REFERENCES intraday_selection_records(trade_date, stock_code)
                ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_intraday_strategy_date "
        "ON intraday_selection_strategies(strategy, trade_date)"
    )
    return connection


def save_intraday_hits(
    project_root: str | Path,
    trade_date: str,
    stocks: list[dict[str, Any]],
    updated_at: str | None = None,
) -> int:
    """保存/更新当天全部盘中入选股票；重复扫描按代码更新，不重复累计。"""
    now = updated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    strategy_rows = []
    for stock in stocks:
        selected = _number(stock.get("selectedPrice"))
        close = _number(stock.get("closePrice"))
        selected_pct = _number(stock.get("selectedPct"))
        close_pct = _number(stock.get("closePct"))
        return_pct = (close / selected - 1) * 100 if selected and close else None
        sector = stock.get("sector") or {}
        code = str(stock.get("code") or "").zfill(6)
        if not code or code == "000000":
            continue
        records.append((
            trade_date, code, str(stock.get("name") or ""), str(stock.get("firstHitTime") or ""),
            str(stock.get("lastHitTime") or ""), selected, selected_pct, close, close_pct,
            return_pct, int(stock.get("score") or 0), str(stock.get("industry") or ""),
            _number(sector.get("pct")), _number(sector.get("mainNetRatio")),
            int(bool(stock.get("currentMatch"))), int(stock.get("hitScans") or 0), now,
        ))
        strategy_rows.extend((trade_date, code, label) for label in _labels(stock))
    if not records:
        return 0
    with _connect(database_path(project_root)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            """
            INSERT INTO intraday_selection_records (
                trade_date, stock_code, stock_name, first_hit_time, last_hit_time,
                selected_price, selected_pct, close_price, close_pct, return_pct,
                score, industry, sector_pct, sector_main_net_ratio, current_match,
                hit_scans, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                stock_name=excluded.stock_name, first_hit_time=excluded.first_hit_time,
                last_hit_time=excluded.last_hit_time, selected_price=excluded.selected_price,
                selected_pct=excluded.selected_pct, close_price=excluded.close_price,
                close_pct=excluded.close_pct, return_pct=excluded.return_pct,
                score=excluded.score, industry=excluded.industry,
                sector_pct=excluded.sector_pct, sector_main_net_ratio=excluded.sector_main_net_ratio,
                current_match=excluded.current_match, hit_scans=excluded.hit_scans,
                updated_at=excluded.updated_at
            """,
            records,
        )
        for record in records:
            trade, code = record[0], record[1]
            connection.execute(
                "DELETE FROM intraday_selection_strategies WHERE trade_date=? AND stock_code=?",
                (trade, code),
            )
        connection.executemany(
            "INSERT OR IGNORE INTO intraday_selection_strategies (trade_date, stock_code, strategy) VALUES (?, ?, ?)",
            strategy_rows,
        )
    return len(records)


def sync_json_history(project_root: str | Path) -> int:
    """将已有每日 JSON 一次性补入数据库，便于历史数据平滑迁移。"""
    root = Path(project_root)
    total = 0
    for path in sorted((root / "output").glob("intraday_hits_????-??-??.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            trade_date = str(payload.get("tradeDate") or path.stem.removeprefix("intraday_hits_"))
            total += save_intraday_hits(root, trade_date, payload.get("stocks") or [], payload.get("updatedAt"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return total


def load_intraday_dashboard(project_root: str | Path) -> dict[str, Any]:
    """返回盘中策略历史上涨胜率、平均涨幅和样本数。"""
    root = Path(project_root)
    sync_json_history(root)
    path = database_path(root)
    if not path.exists():
        return {"rows": [], "totalRecords": 0, "historyStart": "", "historyEnd": ""}
    with _connect(path) as connection:
        bounds = connection.execute(
            "SELECT MIN(trade_date) AS start_date, MAX(trade_date) AS end_date, "
            "COUNT(*) AS records FROM intraday_selection_records WHERE return_pct IS NOT NULL"
        ).fetchone()
        rows = connection.execute(
            """
            SELECT s.strategy, COUNT(*) AS evaluated,
                   SUM(CASE WHEN r.return_pct > 0 THEN 1 ELSE 0 END) AS wins,
                   AVG(r.return_pct) AS avg_return,
                   COUNT(DISTINCT s.trade_date) AS review_days
            FROM intraday_selection_strategies s
            JOIN intraday_selection_records r
              ON r.trade_date=s.trade_date AND r.stock_code=s.stock_code
            WHERE r.return_pct IS NOT NULL
            GROUP BY s.strategy
            """
        ).fetchall()
    result = []
    for row in rows:
        evaluated, wins = int(row["evaluated"]), int(row["wins"] or 0)
        result.append({
            "strategy": row["strategy"], "evaluated": evaluated, "wins": wins,
            "winRate": round(wins / evaluated * 100, 2) if evaluated else None,
            "avgReturn": round(float(row["avg_return"]), 2) if row["avg_return"] is not None else None,
            "reviewDays": int(row["review_days"]),
        })
    result.sort(key=lambda item: (item["winRate"] if item["winRate"] is not None else -1, item["evaluated"]), reverse=True)
    return {
        "rows": result, "totalRecords": int(bounds["records"] or 0),
        "historyStart": str(bounds["start_date"] or ""), "historyEnd": str(bounds["end_date"] or ""),
    }
