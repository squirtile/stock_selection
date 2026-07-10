# -*- coding: utf-8 -*-
"""
小程序后端 API 服务

读取 stock_selection 最新选股结果，以 JSON 格式提供给微信小程序。

启动方式：
    python api_server.py
    # 或指定端口：
    python api_server.py --port 8080

接口：
    GET /api/stocks        获取最新选股结果
    GET /api/stocks/refresh 触发重新扫描（耗时较长，建议异步）
    GET /api/health         健康检查
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from flask import Flask, jsonify, request

# ------------------------------
# 配置
# ------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SIGNAL_PATTERN = "a_stock_signal_selected_*.xlsx"
FALLBACK_FILE = "a_stock_selected.xlsx"

app = Flask(__name__)


# ------------------------------
# 工具函数
# ------------------------------

def _find_latest_signal_file() -> Path | None:
    """找到最新的信号输出文件。"""
    pattern = str(OUTPUT_DIR / SIGNAL_PATTERN)
    files = glob.glob(pattern)
    if not files:
        return None
    # 按修改时间排序，取最新
    files.sort(key=os.path.getmtime, reverse=True)
    return Path(files[0])


def _find_fallback_file() -> Path | None:
    """找到基础池文件。"""
    path = OUTPUT_DIR / FALLBACK_FILE
    return path if path.exists() else None


def _compute_score(row: pd.Series) -> int:
    """
    根据命中策略数和涨跌幅计算综合评分（0-100）。
    """
    score = 50  # 基础分

    # 命中策略数加分（每个策略 +8 分，上限 40）
    strategy_count = int(row.get("命中策略数", 0) or 0)
    score += min(strategy_count * 8, 40)

    # 涨跌幅加分
    pct = float(row.get("涨跌幅", 0) or 0)
    if 2 < pct <= 5:
        score += 5
    elif 5 < pct <= 8:
        score += 8
    elif pct > 8:
        score += 10
    elif pct < -5:
        score -= 10  # 跌幅过大扣分

    return max(0, min(100, int(score)))


def _get_strategy_text(row: pd.Series) -> str:
    """合并策略字段为展示文本。"""
    parts = []
    for col in ["突破反转策略", "主升策略", "启动回踩策略", "信号类型"]:
        val = row.get(col, "")
        if pd.notna(val) and str(val).strip():
            parts.append(str(val).strip())
    return " + ".join(parts) if parts else "综合策略命中"


def _load_stocks() -> tuple[list[dict[str, Any]], str]:
    """
    加载最新选股结果，返回 (股票列表, 更新时间)。
    """
    file_path = _find_latest_signal_file() or _find_fallback_file()

    if file_path is None:
        return [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    df = pd.read_excel(file_path, dtype={"代码": str})

    if df.empty:
        return [], datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 格式化代码
    if "代码" in df.columns:
        df["代码"] = df["代码"].astype(str).str.zfill(6)

    # 文件修改时间作为更新时间
    mtime = os.path.getmtime(str(file_path))
    update_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")

    stocks = []
    for _, row in df.iterrows():
        name = str(row.get("名称", ""))
        code = str(row.get("代码", ""))

        if not name or name == "nan":
            continue

        stock = {
            "code": code,
            "name": name,
            "score": _compute_score(row),
            "strategy": _get_strategy_text(row),
            "price": _safe_float(row.get("最新价")),
            "pct": _safe_float(row.get("涨跌幅")),
            "industry": str(row.get("行业", "")) if pd.notna(row.get("行业")) else "",
            "marketCap": _safe_float(row.get("市值_亿元")),
            "concept": str(row.get("题材", "")) if pd.notna(row.get("题材")) else "",
            "strategyCount": int(row.get("命中策略数", 0) or 0),
            "limitUpStatus": str(row.get("涨停状态", "")) if pd.notna(row.get("涨停状态")) else "",
        }
        stocks.append(stock)

    # 按评分降序排列
    stocks.sort(key=lambda x: x["score"], reverse=True)

    return stocks, update_time


def _safe_float(val: Any) -> float | None:
    """安全转换为 float。"""
    if val is None or pd.isna(val):
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


# ------------------------------
# API 路由
# ------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/stocks", methods=["GET"])
def get_stocks():
    """
    获取最新选股结果。

    返回格式：
    {
        "time": "2026-07-09 14:35:00",
        "source": "a_stock_signal_selected_20260709_081929.xlsx",
        "total": 15,
        "stocks": [
            {
                "code": "600288",
                "name": "大恒科技",
                "score": 82,
                "strategy": "主升-大阳回调不破10日线 + 二波形态",
                "price": 18.56,
                "pct": 5.32,
                "industry": "元器件",
                "marketCap": 85.3,
                "concept": "机器视觉",
                "strategyCount": 2,
                "limitUpStatus": ""
            }
        ]
    }
    """
    try:
        stocks, update_time = _load_stocks()

        file_path = _find_latest_signal_file() or _find_fallback_file()
        source = file_path.name if file_path else "无数据"

        return jsonify({
            "success": True,
            "time": update_time,
            "source": source,
            "total": len(stocks),
            "stocks": stocks,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": 0,
            "stocks": [],
        }), 500


@app.route("/api/stocks/refresh", methods=["POST"])
def refresh_stocks():
    """
    触发重新扫描（异步）。

    注意：完整扫描耗时较长（几分钟到十几分钟），
    生产环境建议用消息队列或后台任务。
    """
    try:
        import subprocess
        main_script = str(PROJECT_ROOT / "main.py")

        # 后台运行 main.py
        subprocess.Popen(
            [sys.executable, main_script],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return jsonify({
            "success": True,
            "message": "扫描已触发，请稍后刷新查看结果。",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ------------------------------
# 启动入口
# ------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="股票选股小程序 API 服务")
    parser.add_argument("--port", type=int, default=5000, help="服务端口（默认 5000）")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="绑定地址（默认 0.0.0.0）")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  股票选股 API 服务")
    print(f"  地址: http://{args.host}:{args.port}")
    print(f"  接口: http://{args.host}:{args.port}/api/stocks")
    print(f"  健康检查: http://{args.host}:{args.port}/api/health")
    print(f"{'=' * 60}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
