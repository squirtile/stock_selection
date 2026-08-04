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

from flask import Blueprint, render_template, jsonify

# ------------------------------
# 路径配置
# ------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
MINI_PROGRAM_JSON = "mini_program_stocks.json"

# ------------------------------
# 蓝图
# ------------------------------
web_bp = Blueprint("web", __name__, template_folder="templates", static_folder="static")


def _load_stocks_data() -> dict[str, Any]:
    """加载 mini_program_stocks.json，返回渲染所需的数据。"""
    json_path = OUTPUT_DIR / MINI_PROGRAM_JSON
    if not json_path.exists():
        return {"stocks": [], "tabGroups": [], "marketContext": None, "time": "", "total": 0}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "stocks": data.get("stocks", []),
            "tabGroups": data.get("tabGroups", []),
            "marketContext": data.get("marketContext"),
            "time": data.get("time", ""),
            "total": data.get("total", 0),
        }
    except Exception:
        return {"stocks": [], "tabGroups": [], "marketContext": None, "time": "", "total": 0}


@web_bp.route("/")
def index():
    """首页 —— 模拟小程序盘前选股面板。"""
    data = _load_stocks_data()

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

    return render_template(
        "index.html",
        time=data["time"],
        total=data["total"],
        tabGroups=data["tabGroups"],
        allTabs=all_tabs,
        stocks=data["stocks"],
        marketContext=data["marketContext"],
    )
