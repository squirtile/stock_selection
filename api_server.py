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
MINI_PROGRAM_JSON = "mini_program_stocks.json"  # daily_report.py 生成的 JSON

app = Flask(__name__)


# ------------------------------
# 工具函数
# ------------------------------

def _find_latest_json() -> Path | None:
    """优先读 daily_report.py 生成的 JSON。"""
    path = OUTPUT_DIR / MINI_PROGRAM_JSON
    return path if path.exists() else None


def _find_latest_signal_file() -> Path | None:
    """找到最新的信号输出文件。"""
    pattern = str(OUTPUT_DIR / SIGNAL_PATTERN)
    files = glob.glob(pattern)
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return Path(files[0])


def _find_fallback_file() -> Path | None:
    """找到基础池文件。"""
    path = OUTPUT_DIR / FALLBACK_FILE
    return path if path.exists() else None


def _load_stocks() -> tuple[list[dict[str, Any]], str, str]:
    """
    加载最新选股结果，返回 (股票列表, 更新时间, 数据来源)。

    优先级：
    1. mini_program_stocks.json（daily_report.py 生成，含 ML 数据）
    2. a_stock_signal_selected_*.xlsx（策略扫描结果）
    3. a_stock_selected.xlsx（基础池）
    """

    # -- 优先读 JSON --
    json_path = _find_latest_json()
    print(f"[API DEBUG] JSON path: {json_path}")
    if json_path is not None:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stocks = data.get("stocks", [])
            mtime = os.path.getmtime(str(json_path))
            update_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            source = f"{MINI_PROGRAM_JSON} ({data.get('source', 'daily_report')})"

            # 兼容：JSON 里 score 已由 daily_report 算好，确保字段齐全
            for s in stocks:
                s.setdefault("score", 50)
                s.setdefault("strategy", "")
                s.setdefault("price", None)
                s.setdefault("pct", None)
                s.setdefault("industry", "")
                s.setdefault("marketCap", None)
                s.setdefault("concept", "")
                s.setdefault("strategyCount", 0)
                s.setdefault("limitUpStatus", "")
                s.setdefault("mlScore", None)
                s.setdefault("mlModel", "")

            return stocks, update_time, source
        except Exception as e:
            print(f"[API] 读取 JSON 失败：{e}，回退到 xlsx")

    # -- 回退：读 xlsx --
    file_path = _find_latest_signal_file() or _find_fallback_file()

    if file_path is None:
        return [], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "无数据"

    df = pd.read_excel(file_path, dtype={"代码": str})
    if df.empty:
        return [], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "空文件"

    if "代码" in df.columns:
        df["代码"] = df["代码"].astype(str).str.zfill(6)

    mtime = os.path.getmtime(str(file_path))
    update_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    source = file_path.name

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

    return stocks, update_time, source


def _compute_score(row: pd.Series) -> int:
    """根据命中策略数和涨跌幅计算综合评分（0-100）。"""
    score = 50
    strategy_count = int(row.get("命中策略数", 0) or 0)
    score += min(strategy_count * 8, 40)
    pct = float(row.get("涨跌幅", 0) or 0)
    if 2 < pct <= 5:
        score += 5
    elif 5 < pct <= 8:
        score += 8
    elif pct > 8:
        score += 10
    elif pct < -5:
        score -= 10
    return max(0, min(100, int(score)))


def _get_strategy_text(row: pd.Series) -> str:
    """合并策略字段为展示文本。"""
    parts = []
    for col in ["突破反转策略", "主升策略", "启动回踩策略", "信号类型"]:
        val = row.get(col, "")
        if pd.notna(val) and str(val).strip():
            parts.append(str(val).strip())
    return " + ".join(parts) if parts else "综合策略命中"


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
        stocks, update_time, source = _load_stocks()

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


@app.route("/api/stock/<code>/kline", methods=["GET"])
def get_kline(code: str):
    """
    获取个股最近 30 日 K 线数据。

    数据来源：cache/hist/<code>_bs.csv（BaoStock 缓存）

    返回：
    {
        "success": true,
        "code": "603178",
        "name": "圣龙股份",
        "data": [
            {"date": "2026-05-29", "open": 15.0, "close": 15.5, "high": 15.8, "low": 14.9, "volume": 12345678},
            ...
        ]
    }
    """
    try:
        code = str(code).zfill(6)
        cache_file = PROJECT_ROOT / "cache" / "hist" / f"{code}_bs.csv"

        if not cache_file.exists():
            return jsonify({"success": False, "error": f"无缓存数据: {code}"}), 404

        df = pd.read_csv(cache_file, dtype={"代码": str})
        if df.empty:
            return jsonify({"success": False, "error": "缓存为空"}), 404

        # 列名映射（兼容不同来源）
        col_map = {
            "date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
            "amount": "amount",
            "pctChg": "pctChg",
        }
        # 实际列名可能是中文
        rename = {}
        for eng, chn in [("date", "日期"), ("open", "开盘"), ("close", "收盘"),
                          ("high", "最高"), ("low", "最低"), ("volume", "成交量")]:
            if chn in df.columns:
                rename[chn] = eng
        if rename:
            df = df.rename(columns=rename)

        date_col = "date" if "date" in df.columns else "日期"
        if date_col not in df.columns:
            return jsonify({"success": False, "error": "未找到日期列"}), 500

        # 转日期、排序、取最近30条
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df = df.sort_values(date_col).tail(30)

        kline_data = []
        for _, row in df.iterrows():
            d = row[date_col]
            date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
            item = {"date": date_str}
            for key in ["open", "close", "high", "low", "volume"]:
                val = row.get(key)
                item[key] = round(float(val), 2) if pd.notna(val) and key != "volume" else (int(val) if pd.notna(val) else 0)
            kline_data.append(item)

        return jsonify({
            "success": True,
            "code": code,
            "data": kline_data,
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
