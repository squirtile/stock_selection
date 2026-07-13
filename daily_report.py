#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日综合报告脚本
=================
1. 运行 main.py 获取策略信号
2. 运行 ml_scan.py 对 pkl/ 下所有模型扫描
3. 合并结果到一份汇总 Excel
4. 发送邮件到 163 邮箱

用法：
  python3 daily_report.py
  python3 daily_report.py --force-update  (强制更新日线缓存)
"""

import os
import sys
import subprocess
import glob
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header

import pandas as pd
import requests

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
from config import EMAIL_CONFIG, FEISHU_DAILY_REPORT_URL

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
PKL_DIR = os.path.join(PROJECT_ROOT, "pkl")

# 自动检测CPU核数，适配从2核云服到18核笔记本
_CPU_COUNT = os.cpu_count() or 2
_WORKERS_MAIN = max(1, min(_CPU_COUNT - 2, 12))      # main.py 留2核给系统
_WORKERS_ML = max(1, min(_CPU_COUNT // 2, 6))         # ml_scan 用一半核


# ============================================================
# 1. 运行 main.py
# ============================================================

def run_main_py(force_update: bool = False, cache_only: bool = False) -> str:
    """运行 main.py，返回输出的 Excel 文件路径"""
    print("=" * 70)
    print("📊 第一步：运行 main.py 策略信号扫描")
    print("=" * 70)

    cmd = [sys.executable, "main.py", "--workers", str(_WORKERS_MAIN), "--no-email"]
    if cache_only:
        cmd.append("--daily-cache-only")
    elif force_update:
        cmd.append("--force-update-daily")
    # --daily-cache-only：强制只用缓存（周末/调试用）
    # 不加参数：17:30 前用缓存，17:30 后自动拉 BaoStock

    t0 = time.time()
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    elapsed = (time.time() - t0) / 60

    if result.returncode != 0:
        print(f"⚠️ main.py 返回码 {result.returncode}，耗时 {elapsed:.1f} 分钟")
        return ""
    print(f"✅ main.py 完成，耗时 {elapsed:.1f} 分钟")

    # 找最新的信号文件
    signal_files = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "a_stock_signal_selected_*.xlsx")),
        key=os.path.getmtime, reverse=True,
    )
    if signal_files:
        print(f"   最新信号文件：{os.path.basename(signal_files[0])}")
        return signal_files[0]
    print("⚠️ 未找到信号输出文件")
    return ""


# ============================================================
# 2. 运行 ml_scan.py 对所有 pkl
# ============================================================

def run_ml_scan_all_pkls(ml_scan_workers: int = _WORKERS_ML) -> dict[str, str]:
    """对 pkl/ 下所有 .pkl 运行 ml_scan.py，返回 {pkl名: 输出xlsx路径}"""
    print("\n" + "=" * 70)
    print("🤖 第二步：ML 模型扫描")
    print("=" * 70)

    pkl_files = sorted(glob.glob(os.path.join(PKL_DIR, "*.pkl")))
    if not pkl_files:
        print("⚠️ pkl/ 目录下没有 .pkl 文件")
        return {}

    results = {}
    for pkl_path in pkl_files:
        pkl_name = os.path.splitext(os.path.basename(pkl_path))[0]
        output_file = os.path.join(OUTPUT_DIR, f"ml_scan_{pkl_name}.xlsx")
        print(f"\n  扫描模型：{pkl_name}.pkl ...")

        cmd = [
            sys.executable, "cli/ml_scan.py",
            "--model", pkl_path,
            "--threshold", "0.60",
            "--use-selected-file",
            "--workers", str(ml_scan_workers),
            "--output", output_file,
        ]
        # 二波类模型开启趋势过滤（剔除下跌趋势/破位票，比策略共振更务实）
        if "二波" in pkl_name or "wave" in pkl_name.lower():
            cmd.append("--trend-filter")
            print(f"    📉 已启用趋势过滤（排除下跌/破位票）")
        t0 = time.time()
        r = subprocess.run(cmd, cwd=PROJECT_ROOT)
        elapsed = (time.time() - t0) / 60

        if r.returncode == 0 and os.path.exists(output_file):
            print(f"  ✅ {pkl_name} 完成，耗时 {elapsed:.1f} 分钟 → {os.path.basename(output_file)}")
            results[pkl_name] = output_file
        else:
            print(f"  ⚠️ {pkl_name} 失败（返回码 {r.returncode}）")
    return results


# ============================================================
# 3. 合并汇总
# ============================================================

def build_summary_excel(signal_file: str, ml_results: dict[str, str]) -> str:
    """合并策略信号和所有 ML 扫描结果到一个 Excel"""
    print("\n" + "=" * 70)
    print("📋 第三步：合并汇总")
    print("=" * 70)

    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = os.path.join(OUTPUT_DIR, f"daily_report_{today}.xlsx")

    with pd.ExcelWriter(summary_file, engine="openpyxl") as writer:
        # Sheet 1: 策略信号（直接复制）
        if signal_file and os.path.exists(signal_file):
            strategy_df = pd.read_excel(signal_file, sheet_name="全部信号")
            strategy_df.to_excel(writer, sheet_name="策略信号_全部", index=False)
            print(f"  策略信号：{len(strategy_df)} 只")
        else:
            strategy_df = pd.DataFrame()
            print("  策略信号：无")

        # Sheet 2+: 每个 ML 模型的结果
        all_ml_signals = {}  # {代码: {pkl名: 评分}}
        for pkl_name, filepath in ml_results.items():
            try:
                df = pd.read_excel(filepath, sheet_name="全部ML评分")
                # 确保列名兼容
                code_col = next((c for c in ["股票代码", "代码", "code"] if c in df.columns), None)
                score_col = next((c for c in ["ML分数", "ML评分", "评分", "score", "信号强度", "平均相似度", "相似度"] if c in df.columns), None)
                if code_col and score_col:
                    df[code_col] = df[code_col].astype(str).str.zfill(6)
                    sheet_name = f"ML_{pkl_name}"[:31]
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    print(f"  ML_{pkl_name}：{len(df)} 只")

                    # 收集信号
                    for _, row in df.iterrows():
                        code = str(row[code_col]).zfill(6)
                        score = row[score_col]
                        all_ml_signals.setdefault(code, {})[pkl_name] = score
                else:
                    print(f"  ⚠️ ML_{pkl_name}：未找到评分列（实际列：{list(df.columns)}）")
            except Exception as e:
                print(f"  ⚠️ ML_{pkl_name} 读取失败：{e}")

        # Sheet: 对比汇总
        if all_ml_signals:
            rows = []
            for code in sorted(all_ml_signals.keys()):
                row = {"代码": code}
                for pkl_name in sorted(ml_results.keys()):
                    row[f"{pkl_name}"] = round(all_ml_signals[code].get(pkl_name, 0), 4)
                # 是否在策略信号中
                if not strategy_df.empty and "代码" in strategy_df.columns:
                    row["策略命中"] = "是" if code in strategy_df["代码"].astype(str).str.zfill(6).values else ""
                else:
                    row["策略命中"] = ""
                rows.append(row)

            summary_df = pd.DataFrame(rows)
            if not summary_df.empty:
                # 按最高 ML 评分排
                score_cols = [c for c in summary_df.columns if c not in ("代码", "策略命中")]
                if score_cols:
                    summary_df["最高ML评分"] = summary_df[score_cols].max(axis=1)
                    summary_df = summary_df.sort_values("最高ML评分", ascending=False)
                summary_df.to_excel(writer, sheet_name="对比汇总", index=False)
                print(f"  对比汇总：{len(summary_df)} 只（多模型交集）")

    print(f"\n✅ 汇总报告：{summary_file}")
    return summary_file


# ============================================================
# 3.5 生成小程序 JSON（供 api_server.py 读取）
# ============================================================

MINI_PROGRAM_JSON = "mini_program_stocks.json"

# ============================================================
# 动态策略映射（从 registry.py 自动读取，新增策略无需改这里）
# ============================================================

def _get_strategy_type_map() -> dict[str, dict[str, str]]:
    """从 registry.py 动态读取策略名→分组映射。"""
    try:
        from strategies.registry import get_strategy_type_map
        return get_strategy_type_map()
    except Exception:
        # 回退硬编码（兼容旧版）
        return {
            "主升-均线多头排列":       {"group": "趋势跟踪", "groupKey": "趋势跟踪"},
            "二波埋伏":                {"group": "回调买入", "groupKey": "回调买入"},
            "二波形态":                {"group": "回调买入", "groupKey": "回调买入"},
            "主升-大阳回调不破10日线": {"group": "突破",     "groupKey": "突破"},
            "年线突破":                {"group": "突破",     "groupKey": "突破"},
        }


def _get_strategy_group_order() -> list[str]:
    """从 registry.py 读取策略分组顺序（按注册顺序，去重）。"""
    try:
        from strategies.registry import get_daily_strategies
        seen = []
        for s in get_daily_strategies():
            gk = getattr(s, "group", "") or s.category
            if gk and gk not in seen:
                seen.append(gk)
        return seen
    except Exception:
        return ["趋势跟踪", "回调买入", "突破"]


def _get_ml_model_display(pkl_name: str) -> str:
    """获取 ML 模型的显示名称（从文件名推导，可在此手动覆盖特殊命名）。"""
    # 特殊命名覆盖（文件名 → 显示名）
    overrides = {
        "W_V2":       "W双底",
        "二波形态_v1": "二波形态",
    }
    if pkl_name in overrides:
        return overrides[pkl_name]
    # 默认：去掉 _v1/_v2 后缀和下划线
    import re
    name = re.sub(r"[_\-]\s*v?\d+$", "", pkl_name)
    return name.replace("_", " ").strip() or pkl_name


def _parse_strategy_types(row) -> list[dict]:
    """从 Excel 行中提取具体的策略名称列表，映射到分组。

    返回: [{"group": "回调买入", "groupKey": "回调买入", "name": "二波形态"}, ...]
    """
    import re
    strategy_map = _get_strategy_type_map()
    result = []
    for col in ["主升策略", "突破反转策略"]:
        val = row.get(col, "")
        if pd.isna(val) or not str(val).strip():
            continue
        # 拆分多策略组合（分隔符可能是 " + "、"、", " 等）
        parts = re.split(r"\s*\+\s*|\s*、\s*|\s*,\s*", str(val).strip())
        for name in parts:
            name = name.strip()
            if not name:
                continue
            info = strategy_map.get(name)
            if info:
                result.append({
                    "group": info["group"],
                    "groupKey": info["groupKey"],
                    "name": name,
                })
    return result


def _safe(val, default=""):
    """安全取值：None / NaN → 默认值"""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return val
    except Exception:
        return default


def _safe_float(val):
    """安全转 float，失败返回 None"""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def _compute_stock_score(strategy_count: int, pct: float | None, ml_max: float | None) -> int:
    """
    综合评分 0-100：
    - 策略命中 + ML 双确认 → 高分
    - 仅策略命中 → 中分
    - 仅 ML 命中 → 基础分
    """
    score = 80  # 基础分

    # 策略命中加分
    if strategy_count > 0:
        score += min(strategy_count * 8, 32)

    # ML 模型加分
    if ml_max is not None and ml_max > 0:
        score += min(int(ml_max * 30), 28)  # ML 最高分归一化到 0-28

    # 涨幅加分
    if pct is not None:
        if 2 < pct <= 5:
            score += 4
        elif 5 < pct <= 8:
            score += 6
        elif pct > 8:
            score += 8

    return max(0, min(100, score))


def _collect_strategy_text(row, strategy_types: list[dict]) -> str:
    """合并策略字段为展示文本（只显示具体策略名，不显示冗余的"主升"等分类）"""
    names = [s["name"] for s in strategy_types]
    if names:
        return " + ".join(names)
    # 回退：旧式多列合并
    parts = []
    for col in ["突破反转策略", "主升策略", "启动回踩策略", "信号类型"]:
        val = row.get(col, "")
        if pd.notna(val) and str(val).strip():
            parts.append(str(val).strip())
    return " + ".join(parts) if parts else "综合策略命中"


def _build_kline_data(code: str, hist_dir: str, days: int = 30) -> list[dict]:
    """读取缓存，用60天计算MA5/10/20/30，只返回最近 N 天"""
    fpath = os.path.join(hist_dir, f'{code}_bs.csv')
    if not os.path.exists(fpath):
        return []

    df = pd.read_csv(fpath)
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期').copy()

    # 用最近60天计算MA（保证MA30有足够数据）
    df_calc = df.tail(60).copy()
    close = pd.to_numeric(df_calc['收盘'], errors='coerce')
    df_calc['MA5'] = close.rolling(5, min_periods=5).mean().round(2)
    df_calc['MA10'] = close.rolling(10, min_periods=10).mean().round(2)
    df_calc['MA20'] = close.rolling(20, min_periods=20).mean().round(2)
    df_calc['MA30'] = close.rolling(30, min_periods=30).mean().round(2)

    # 只输出最近 N 天
    df_out = df_calc.tail(days)

    klines = []
    for _, row in df_out.iterrows():
        klines.append({
            'date': row['日期'].strftime('%m-%d'),
            'open': _safe_float(row.get('开盘')),
            'high': _safe_float(row.get('最高')),
            'low': _safe_float(row.get('最低')),
            'close': _safe_float(row.get('收盘')),
            'volume': int(row['成交量']) if pd.notna(row.get('成交量')) else 0,
            'ma5': _safe_float(row.get('MA5')),
            'ma10': _safe_float(row.get('MA10')),
            'ma20': _safe_float(row.get('MA20')),
            'ma30': _safe_float(row.get('MA30')),
        })
    return klines


def build_mini_program_json(signal_file: str, ml_results: dict[str, str]) -> str:
    """
    合并策略信号 + ML 扫描结果，生成小程序可直接展示的 JSON 文件。

    返回 JSON 文件路径。
    """
    import json

    print("\n" + "=" * 70)
    print("📱 第 3.5 步：生成小程序 JSON")
    print("=" * 70)

    output_path = os.path.join(OUTPUT_DIR, MINI_PROGRAM_JSON)
    stocks_dict: dict[str, dict] = {}  # {代码: 合并后的股票信息}

    # ---------- 从策略信号读取 ----------
    strategy_df = pd.DataFrame()
    if signal_file and os.path.exists(signal_file):
        try:
            strategy_df = pd.read_excel(signal_file, sheet_name="全部信号")
            strategy_df["代码"] = strategy_df["代码"].astype(str).str.zfill(6)
            print(f"  策略信号：{len(strategy_df)} 只")
        except Exception as e:
            print(f"  ⚠️ 读取策略信号失败：{e}")

    for _, row in strategy_df.iterrows():
        code = str(row["代码"]).zfill(6)
        name = str(_safe(row.get("名称")))
        if not name or name == "nan":
            continue
        strategy_types = _parse_strategy_types(row)
        stocks_dict[code] = {
            "code": code,
            "name": name,
            "price": _safe_float(row.get("最新价")),
            "pct": _safe_float(row.get("涨跌幅")),
            "industry": str(_safe(row.get("行业"))),
            "marketCap": _safe_float(row.get("市值_亿元")),
            "concept": str(_safe(row.get("题材"))),
            "strategy": _collect_strategy_text(row, strategy_types),
            "strategyCount": int(_safe(row.get("命中策略数"), 0) or 0),
            "strategyTypes": strategy_types,
            "limitUpStatus": str(_safe(row.get("涨停状态"))),
            "mlScore": None,       # 待 ML 数据补齐
            "mlModel": "",         # 命中的 ML 模型名
            "mlModels": [],        # ML 模型列表
        }

    # ---------- 从 ML 扫描结果读取 ----------
    # 收集所有出现过的 ML 模型
    all_ml_models: dict[str, str] = {}  # {pkl_name: displayName}
    for pkl_name, filepath in ml_results.items():
        try:
            df = pd.read_excel(filepath, sheet_name="全部ML评分")
        except ValueError:
            try:
                df = pd.read_excel(filepath, sheet_name="触发ML信号_全部")
            except ValueError:
                continue

        code_col = next((c for c in ["股票代码", "代码", "code"] if c in df.columns), None)
        score_col = next((c for c in ["ML分数", "ML评分", "评分", "score", "信号强度", "平均相似度", "相似度"] if c in df.columns), None)
        name_col = next((c for c in ["股票名称", "名称", "name"] if c in df.columns), None)

        if not code_col or not score_col:
            continue

        df[code_col] = df[code_col].astype(str).str.zfill(6)
        ml_count = 0
        display_name = _get_ml_model_display(pkl_name)
        all_ml_models[pkl_name] = display_name

        for _, row in df.iterrows():
            code = str(row[code_col]).zfill(6)
            ml_score = _safe_float(row.get(score_col))
            if ml_score is None:
                continue

            ml_count += 1
            ml_model_info = {"key": pkl_name, "displayName": display_name, "score": ml_score}

            if code in stocks_dict:
                # 已存在：追加 ML 信息（支持多模型命中）
                existing = stocks_dict[code]
                existing["mlModels"] = existing.get("mlModels", [])
                existing["mlModels"].append(ml_model_info)
                # 保留最高分的 ML 模型作为主模型
                if existing.get("mlScore") is None or ml_score > existing["mlScore"]:
                    existing["mlScore"] = ml_score
                    existing["mlModel"] = pkl_name
            else:
                # 纯 ML 信号（无策略命中）
                name = str(_safe(row.get(name_col))) if name_col else ""
                if name == "nan":
                    name = ""
                stocks_dict[code] = {
                    "code": code,
                    "name": name,
                    "price": _safe_float(row.get("收盘价") or row.get("最新价")),
                    "pct": _safe_float(row.get("涨跌幅")),
                    "industry": str(_safe(row.get("行业"))),
                    "marketCap": _safe_float(row.get("市值_亿元")),
                    "concept": "",
                    "strategy": f"ML-{display_name}",
                    "strategyCount": 0,
                    "strategyTypes": [],
                    "limitUpStatus": "",
                    "mlScore": ml_score,
                    "mlModel": pkl_name,
                    "mlModels": [ml_model_info],
                }
        print(f"  ML_{pkl_name}（{display_name}）：{ml_count} 只")

    # ---------- 计算综合评分、分类标签 ----------
    stocks_list = []
    for code, s in stocks_dict.items():
        s["score"] = _compute_stock_score(
            strategy_count=s.get("strategyCount", 0) or 0,
            pct=s.get("pct"),
            ml_max=s.get("mlScore"),
        )

        # 确保必要字段存在
        s.setdefault("strategyTypes", [])
        s.setdefault("mlModels", [])

        # 构建层级分类标签
        # Level 1 categories: "策略信号", "ML模型信号"
        categories_level1 = []
        if (s.get("strategyCount") or 0) > 0:
            categories_level1.append("策略信号")
        if s.get("mlModels"):
            categories_level1.append("ML模型信号")

        s["categories"] = categories_level1
        stocks_list.append(s)

    # ---------- 每类只取 TOP 10（按二级分组：每个策略分组/每个ML模型各取10只）----------
    TOP_N = 10
    # 按二级分组（groupKey / mlModel key），一只股票可属多个二级分组
    level2_groups: dict[str, list] = {}  # {groupKey: [stocks]}
    for s in stocks_list:
        for st in s.get("strategyTypes", []):
            gk = st["groupKey"]
            level2_groups.setdefault(gk, []).append(s)
        for ml in s.get("mlModels", []):
            gk = ml["key"]
            level2_groups.setdefault(gk, []).append(s)

    picked_codes: set = set()
    final_stocks: list = []

    # 排序：策略分组优先（按 registry 注册顺序），然后 ML 模型按字母
    strategy_group_order = _get_strategy_group_order()
    ml_model_keys = sorted([k for k in level2_groups if k not in strategy_group_order])
    sort_order = [k for k in strategy_group_order if k in level2_groups] + ml_model_keys

    for gk in sort_order:
        group = sorted(level2_groups[gk], key=lambda x: x["score"], reverse=True)
        added = 0
        for s in group:
            if s["code"] not in picked_codes and added < TOP_N:
                picked_codes.add(s["code"])
                final_stocks.append(s)
                added += 1
        print(f"  {gk}：取 TOP {added}（共 {len(group)} 只）")

    # ---------- 构建层级 Tab 结构（基于最终筛选结果） ----------
    strategy_groups_seen: dict[str, dict] = {}   # {groupKey: {group, codes: set}}
    ml_models_seen: dict[str, dict] = {}          # {key: {key, displayName, codes: set}}

    for s in final_stocks:
        for st in s.get("strategyTypes", []):
            gk = st.get("groupKey", "other")
            if gk not in strategy_groups_seen:
                strategy_groups_seen[gk] = {
                    "group": st["group"],
                    "groupKey": gk,
                    "codes": set(),
                }
            strategy_groups_seen[gk]["codes"].add(s["code"])

        for ml in s.get("mlModels", []):
            key = ml["key"]
            if key not in ml_models_seen:
                ml_models_seen[key] = {
                    "key": key,
                    "displayName": ml["displayName"],
                    "codes": set(),
                }
            ml_models_seen[key]["codes"].add(s["code"])

    # 计算每类最多显示的只数（上限 TOP_N）
    TOP_N = 10
    tab_groups = []

    # 策略信号 tab 组（按 registry 注册顺序排列子标签）
    strategy_children = []
    strategy_group_order = _get_strategy_group_order()
    for gk in strategy_group_order:
        if gk in strategy_groups_seen:
            info = strategy_groups_seen[gk]
            actual = len(info["codes"])
            strategy_children.append({
                "key": gk,
                "label": info["group"],
                "count": min(actual, TOP_N),
            })
    for gk, info in strategy_groups_seen.items():
        if gk not in strategy_group_order:
            actual = len(info["codes"])
            strategy_children.append({
                "key": gk,
                "label": info["group"],
                "count": min(actual, TOP_N),
            })

    strategy_codes = set()
    for info in strategy_groups_seen.values():
        strategy_codes |= info["codes"]
    if strategy_codes:
        tab_groups.append({
            "key": "策略信号",
            "label": "策略信号",
            "count": len(strategy_codes),
            "children": strategy_children,
        })

    # ML 模型信号 tab 组
    ml_children = []
    for key, info in ml_models_seen.items():
        actual = len(info["codes"])
        ml_children.append({
            "key": key,
            "label": info["displayName"],
            "count": min(actual, TOP_N),
        })
    ml_codes = set()
    for info in ml_models_seen.values():
        ml_codes |= info["codes"]
    if ml_codes:
        ml_count = len(ml_codes)
        # 一级标签数量不超过"模型数 × TOP_N"
        ml_count = min(ml_count, len(ml_models_seen) * TOP_N)
        tab_groups.append({
            "key": "ML模型信号",
            "label": "ML模型信号",
            "count": ml_count,
            "children": ml_children,
        })

    # ---------- 补充 K 线 + 均线数据 ----------
    hist_dir = os.path.join(PROJECT_ROOT, "cache", "hist")
    kline_count = 0
    for s in final_stocks:
        klines = _build_kline_data(s['code'], hist_dir)
        s['klines'] = klines
        if klines:
            kline_count += 1
            # 仅二波策略才提取波峰/低点信息
            strategy_names = [t['name'] for t in s.get('strategyTypes', [])]
            is_wave = '二波埋伏' in strategy_names or '二波形态' in strategy_names
            if is_wave:
                highs = [k['high'] for k in klines if k['high'] is not None]
                lows  = [k['low'] for k in klines if k['low'] is not None]
                if highs and lows:
                    # 峰值：最高价
                    peak_val = max(highs)
                    peak_idx = highs.index(peak_val)
                    # 峰值之后的最低点（这才是回调低点）
                    low_after = lows[peak_idx:]
                    if low_after:
                        low_val = min(low_after)
                        low_idx = peak_idx + low_after.index(low_val)
                        s['wavePeakDate'] = klines[peak_idx]['date']
                        s['wavePeakPrice'] = round(peak_val, 2)
                        s['waveLowDate'] = klines[low_idx]['date']
                        s['waveLowPrice'] = round(low_val, 2)
                        s['wavePullback'] = round((low_val / peak_val - 1) * 100, 1)
    print(f"  K线数据：{kline_count}/{len(final_stocks)} 只")

    # ---------- 写 JSON ----------
    result = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": f"daily_report + {len(ml_results)} ML models",
        "total": len(final_stocks),
        "tabGroups": tab_groups,
        "stocks": final_stocks,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"  策略命中：{sum(1 for s in stocks_list if s['strategyCount'] > 0)} 只")
    print(f"  ML 命中：{sum(1 for s in stocks_list if s['mlScore'] is not None)} 只")
    print(f"  筛选后总计：{len(final_stocks)} 只（原始 {len(stocks_list)} 只，每类 TOP 10）")
    print(f"  Tab 层级：{len(tab_groups)} 个一级分组")
    print(f"  ✅ JSON 已生成：{output_path}")
    return output_path


# ============================================================
# 4. 发送邮件
# ============================================================

def _build_grouped_stocks_from_json(json_path: str) -> dict[str, list[dict]]:
    """
    从 mini_program_stocks.json 读取数据，按二级分组（策略名/ML模型名）整理，
    每类只保留 TOP 10。

    返回: { "突破": [...], "回调买入": [...], "W双底": [...] }
    """
    import json

    groups: dict[str, list[dict]] = {}

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stocks = data.get("stocks", [])

    # 按二级分组归类（策略分组 groupKey + ML模型 key）
    for s in stocks:
        for st in s.get("strategyTypes", []):
            gk = st.get("groupKey", "other")
            groups.setdefault(gk, []).append(s)
        for ml in s.get("mlModels", []):
            gk = ml.get("displayName", ml.get("key", "ML"))
            groups.setdefault(gk, []).append(s)

    # 去重 + 排序 + TOP 10
    result: dict[str, list[dict]] = {}
    for gk, stock_list in groups.items():
        seen = set()
        unique = []
        for s in sorted(stock_list, key=lambda x: x.get("score", 0), reverse=True):
            code = s.get("code", "")
            if code not in seen:
                seen.add(code)
                unique.append(s)
                if len(unique) >= 10:
                    break
        result[gk] = unique

    # 按策略注册顺序排列分组
    ordered = {}
    strategy_order = _get_strategy_group_order()
    for gk in strategy_order:
        if gk in result:
            ordered[gk] = result.pop(gk)
    # ML 模型按字母排
    for gk in sorted(result.keys()):
        ordered[gk] = result[gk]

    return ordered


def build_email_body(signal_file: str, ml_results: dict[str, str]) -> str:
    """构建邮件正文 HTML（按策略分组，每个策略只显示前10只）"""

    today = datetime.now().strftime('%Y-%m-%d')
    html = f"<h2>📊 每日综合选股报告 - {today}</h2>\n<hr>\n"

    json_path = os.path.join(OUTPUT_DIR, MINI_PROGRAM_JSON)
    if not os.path.exists(json_path):
        html += "<p>暂无选股数据。</p>\n"
        return html

    groups = _build_grouped_stocks_from_json(json_path)
    if not groups:
        html += "<p>今日无信号。</p>\n"
        return html

    for gk, stocks in groups.items():
        html += f"<h3>📌 {gk}（{len(stocks)} 只）</h3>\n"
        html += "<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse;font-size:12px;'>\n"
        html += "<tr style='background:#4472C4;color:white;'><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>行业</th><th>评分</th></tr>\n"
        for s in stocks:
            code = s.get("code", "")
            name = s.get("name", "")
            price = s.get("price") or ""
            pct = s.get("pct")
            pct_str = f"{pct:+.2f}%" if pct is not None else ""
            industry = s.get("industry", "")
            score = s.get("score", "")
            html += f"<tr><td>{code}</td><td>{name}</td><td>{price}</td><td>{pct_str}</td><td>{industry}</td><td>{score}</td></tr>\n"
        html += "</table><br>\n"

    html += "<hr><p style='color:#888;font-size:11px;'>完整结果见附件 Excel。本邮件由系统自动发送。</p>"
    return html


def send_report_email(summary_file: str, signal_file: str, ml_results: dict[str, str]):
    """发送综合报告邮件"""
    print("\n" + "=" * 70)
    print("📧 第四步：发送邮件")
    print("=" * 70)

    cfg = EMAIL_CONFIG
    today = datetime.now().strftime('%Y-%m-%d')

    body = build_email_body(signal_file, ml_results)

    msg = MIMEMultipart()
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]
    msg["Subject"] = Header(f"每日选股报告 {today}", "utf-8")
    msg.attach(MIMEText(body, "html", "utf-8"))

    # 附件
    if os.path.exists(summary_file):
        with open(summary_file, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(summary_file)}")
            msg.attach(part)

    try:
        server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15)
        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receiver"], msg.as_string())
        server.quit()
        print(f"✅ 邮件已发送至 {cfg['receiver']}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


# ============================================================
# 5. 发送飞书消息
# ============================================================

def build_feishu_msg(signal_file: str, ml_results: dict[str, str]) -> list:
    """构建飞书消息内容（按策略分组，每个策略只显示前10只）"""

    today = datetime.now().strftime('%Y-%m-%d')
    elements = []

    json_path = os.path.join(OUTPUT_DIR, MINI_PROGRAM_JSON)
    if not os.path.exists(json_path):
        elements.append("暂无选股数据。")
        return elements

    groups = _build_grouped_stocks_from_json(json_path)
    if not groups:
        elements.append("今日无信号。")
        return elements

    total_stocks = sum(len(v) for v in groups.values())
    elements.append(f"**📊 选股信号：{total_stocks} 只（按策略分组，每类 TOP 10）**")

    for gk, stocks in groups.items():
        lines = [f"\n**📌 {gk}（{len(stocks)} 只）**"]
        for s in stocks:
            code = s.get("code", "").zfill(6)
            name = s.get("name", "")
            pct = s.get("pct")
            pct_str = f"{pct:+.2f}%" if pct is not None else ""
            industry = s.get("industry", "")
            score = s.get("score", "")
            line = f"  {code} {name}"
            extras = [x for x in [pct_str, industry, f"评分{score}"] if x]
            if extras:
                line += f"  |  {' | '.join(extras)}"
            lines.append(line)
        elements.append("\n".join(lines))

    elements.append("")
    elements.append(f"📎 详细数据见邮件附件 | {datetime.now().strftime('%H:%M')}")

    return elements


def send_feishu_message(signal_file: str, ml_results: dict[str, str]):
    """发送选股摘要到飞书群"""
    print("\n" + "=" * 70)
    print("📢 第五步：发送飞书消息")
    print("=" * 70)

    if not FEISHU_DAILY_REPORT_URL:
        print("⚠️ 未配置飞书 Webhook，跳过。")
        return

    today = datetime.now().strftime('%Y-%m-%d')
    elements = build_feishu_msg(signal_file, ml_results)

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📊 每日选股报告 {today}"},
                "template": "blue"
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": c}}
                for c in elements
            ]
        }
    }

    try:
        r = requests.post(FEISHU_DAILY_REPORT_URL, json=payload, timeout=10)
        result = r.json()
        if result.get("code") == 0:
            print("✅ 飞书消息已发送")
        else:
            print(f"⚠️ 飞书发送返回：{result}")
    except Exception as e:
        print(f"❌ 飞书消息发送失败: {e}")


# ============================================================
# 主入口
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="每日综合选股报告")
    parser.add_argument("--force-update", action="store_true", help="强制更新 BaoStock 日线缓存")
    parser.add_argument("--cache-only", action="store_true", help="强制只用本地缓存（周末/调试用，不请求BaoStock）")
    parser.add_argument("--no-email", action="store_true", help="跳过邮件和飞书发送")
    args = parser.parse_args()

    start_time = datetime.now()
    print(f"\n⏰ 开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    total_start = time.time()

    # 1. 策略信号
    signal_file = run_main_py(force_update=args.force_update, cache_only=args.cache_only)

    # 2. ML 扫描
    ml_results = run_ml_scan_all_pkls()

    # 3. 合并
    summary_file = build_summary_excel(signal_file, ml_results)

    # 3.5 生成小程序 JSON
    build_mini_program_json(signal_file, ml_results)

    if args.no_email:
        print("\n" + "=" * 70)
        print("⏭️ 跳过邮件和飞书发送（--no-email）")
        print("=" * 70)
    else:
        # 4. 发邮件
        send_report_email(summary_file, signal_file, ml_results)

        # 5. 发飞书
        send_feishu_message(signal_file, ml_results)

    total_elapsed = (time.time() - total_start) / 60
    end_time = datetime.now()
    print(f"\n{'=' * 70}")
    print(f"🏁 全部完成，总耗时 {total_elapsed:.1f} 分钟")
    print(f"⏰ 开始：{start_time.strftime('%Y-%m-%d %H:%M:%S')}  →  结束：{end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
