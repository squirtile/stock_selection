# -*- coding: utf-8 -*-
"""
Web 展示蓝图 —— 负责首页 HTML 页面渲染
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, render_template, jsonify, send_file, abort

# ------------------------------
# 路径配置
# ------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
MINI_PROGRAM_JSON = "mini_program_stocks.json"
BACKTEST_JSON = "strategy_backtest_latest.json"
SUPPORT_QR_FILE = PROJECT_ROOT / "IMG_5791.JPG"

# ------------------------------
# 蓝图
# ------------------------------
web_bp = Blueprint("web", __name__, template_folder="templates", static_folder="static")


@web_bp.after_request
def disable_page_cache(response):
    """首页包含盘中缓存，禁止浏览器/代理继续复用旧版空白页面。"""
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


def _load_stocks_data() -> dict[str, Any]:
    """加载 mini_program_stocks.json，返回渲染所需的数据。"""
    json_path = OUTPUT_DIR / MINI_PROGRAM_JSON
    if not json_path.exists():
        return {"stocks": [], "tabGroups": [], "marketContext": None, "backtestReview": {}, "time": "", "total": 0, "intradayInitial": {}}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        from tools.stock_card_data import enrich_signal_cards
        enrich_signal_cards(data.get("stocks", []), PROJECT_ROOT, data.get("time", ""))
        backtest_review = data.get("backtestReview", {})
        backtest_path = OUTPUT_DIR / BACKTEST_JSON
        if backtest_path.exists():
            try:
                with open(backtest_path, "r", encoding="utf-8") as f:
                    backtest_review = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        intraday_initial = {}
        try:
            intraday_path = OUTPUT_DIR / "intraday_candidates.json"
            if intraday_path.exists():
                with open(intraday_path, "r", encoding="utf-8") as f:
                    intraday_initial = json.load(f)
                intraday_initial["stocks"] = (intraday_initial.get("stocks") or [])[:20]
        except (OSError, json.JSONDecodeError):
            intraday_initial = {}
        return {
            "stocks": data.get("stocks", []),
            "tabGroups": data.get("tabGroups", []),
            "marketContext": data.get("marketContext"),
            "backtestReview": backtest_review,
            "time": data.get("time", ""),
            "total": data.get("total", 0),
            "intradayInitial": intraday_initial,
        }
    except Exception:
        return {"stocks": [], "tabGroups": [], "marketContext": None, "backtestReview": {}, "time": "", "total": 0, "intradayInitial": {}}


@web_bp.route("/")
def index():
    """首页 —— 模拟小程序盘前选股面板。"""
    data = _load_stocks_data()
    big_yang_stocks = [
        s for s in data["stocks"]
        if any(str(item.get("name", "")) == "主升-大阳回调不破10日线" for item in s.get("strategyTypes", []))
        or "主升-大阳回调不破10日线" in str(s.get("strategy", ""))
    ]
    # 将该策略作为“策略扫描 → 策略信号”的独立子标签展示。
    for group in data["tabGroups"]:
        if group.get("key") == "策略信号":
            children = group.setdefault("children", [])
            if not any(child.get("key") == "主升-大阳回调不破10日线" for child in children):
                children.append({
                    "key": "主升-大阳回调不破10日线",
                    "label": "主升-大阳回调不破10日线",
                    "count": len(big_yang_stocks),
                })
            break

    # 网页缠论仅展示买点；兼容仍带卖点标签的旧报表，不改写源文件。
    for group in data["tabGroups"]:
        if group.get("key") == "缠论选股":
            group["children"] = [child for child in group.get("children", [])
                                 if child.get("subgroup") != "卖点"
                                 and "卖" not in str(child.get("label", ""))]
            group["count"] = sum(child.get("count", 0) for child in group["children"])

    # 收集所有二级标签（扁平化）
    all_tabs = []
    for g in data["tabGroups"]:
        for child in g.get("children", []):
            all_tabs.append({
                "key": child["key"],
                "label": child["label"],
                "count": child["count"],
                "parentKey": g["key"],
                "parentLabel": g["label"],
            })

    try:
        from backtest.strategy_history_store import load_dashboard
        strategy_dashboard = load_dashboard(PROJECT_ROOT)
        strategy_dashboard["historyRows"] = [
            row for row in strategy_dashboard.get("historyRows", [])
            if row.get("direction") != "看跌" and "卖" not in str(row.get("strategy", ""))
        ]
        strategy_dashboard["totalRecords"] = sum(
            row.get("historyEvaluated", 0) for row in strategy_dashboard["historyRows"]
        )
        from backtest.intraday_history_store import load_intraday_dashboard
        strategy_dashboard["intraday"] = load_intraday_dashboard(PROJECT_ROOT)
    except Exception:
        strategy_dashboard = {"reviewDate": "", "rows": [], "todayRows": [], "historyRows": [], "totalRecords": 0, "intraday": {"rows": []}}

    return render_template(
        "index.html",
        time=data["time"],
        total=data["total"],
        tabGroups=data["tabGroups"],
        allTabs=all_tabs,
        stocks=data["stocks"],
        marketContext=data["marketContext"],
        backtestReview=data["backtestReview"],
        strategyDashboard=strategy_dashboard,
        indexDivergence=data["marketContext"].get("indexDivergence", {}) if data.get("marketContext") else {},
        bigYangStocks=big_yang_stocks,
        intradayInitial=data.get("intradayInitial", {}),
    )


@web_bp.route("/support-qr")
def support_qr():
    """首页支持卡片使用的微信收款码。"""
    if not SUPPORT_QR_FILE.is_file():
        abort(404)
    return send_file(SUPPORT_QR_FILE, mimetype="image/jpeg", max_age=86_400)
