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


# ============================================================
# 1. 运行 main.py
# ============================================================

def run_main_py(force_update: bool = False) -> str:
    """运行 main.py，返回输出的 Excel 文件路径"""
    print("=" * 70)
    print("📊 第一步：运行 main.py 策略信号扫描")
    print("=" * 70)

    cmd = [sys.executable, "main.py", "--workers", "6", "--no-email"]
    if force_update:
        cmd.append("--force-update-daily")
    # 不加 --daily-cache-only，让 main.py 自动判断：
    # 17:30 前 → 用缓存（快）；17:30 后 → 自动拉 BaoStock 当天数据

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

def run_ml_scan_all_pkls(ml_scan_workers: int = 4) -> dict[str, str]:
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
# 4. 发送邮件
# ============================================================

def build_email_body(signal_file: str, ml_results: dict[str, str]) -> str:
    """构建邮件正文 HTML"""
    today = datetime.now().strftime('%Y-%m-%d')
    html = f"<h2>📊 每日综合选股报告 - {today}</h2>\n<hr>\n"

    # 策略信号摘要
    if signal_file and os.path.exists(signal_file):
        try:
            strategy_df = pd.read_excel(signal_file, sheet_name="全部信号")
            if not strategy_df.empty:
                cols = ["代码", "名称", "最新价", "涨跌幅", "信号类型", "命中策略数"]
                cols = [c for c in cols if c in strategy_df.columns]
                html += f"<h3>🔵 策略信号（{len(strategy_df)} 只）</h3>\n"
                html += "<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse;font-size:12px;'>\n"
                html += "<tr style='background:#4472C4;color:white;'>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>\n"
                for _, row in strategy_df.head(30).iterrows():
                    html += "<tr>" + "".join(f"<td>{row.get(c, '')}</td>" for c in cols) + "</tr>\n"
                html += "</table><br>\n"
        except Exception as e:
            html += f"<p>策略信号读取失败：{e}</p>\n"
    else:
        html += "<p>今日无策略信号。</p>\n"

    # ML 扫描摘要（TOP 10 可观察候选）
    html += "<h3>🤖 ML 模型扫描（可观察候选，TOP 10）</h3>\n"
    if ml_results:
        for pkl_name, filepath in ml_results.items():
            try:
                try:
                    df = pd.read_excel(filepath, sheet_name="可观察候选_未涨停")
                except ValueError:
                    df = pd.read_excel(filepath, sheet_name="触发ML信号_全部")
                if not df.empty:
                    total = len(df)
                    top10 = df.head(10)
                    cols = ["代码", "名称", "ML分数", "涨跌幅", "收盘价"]
                    cols = [c for c in cols if c in top10.columns]
                    html += f"<p><b>{pkl_name}.pkl：共 {total} 只触发，展示可信度最高 10 只</b></p>\n"
                    html += "<table border='1' cellpadding='4' cellspacing='0' style='border-collapse:collapse;font-size:12px;'>\n"
                    html += "<tr style='background:#4472C4;color:white;'>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>\n"
                    for _, row in top10.iterrows():
                        html += "<tr>" + "".join(f"<td>{row.get(c, '')}</td>" for c in cols) + "</tr>\n"
                    html += "</table><br>\n"
                else:
                    html += f"<p>{pkl_name}.pkl：无信号</p>\n"
            except Exception as e:
                html += f"<p>{pkl_name}.pkl：读取失败 ({e})</p>\n"
    else:
        html += "<p>无 ML 模型结果。</p>\n"

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
    """构建飞书消息内容（卡片消息，简洁版）"""
    today = datetime.now().strftime('%Y-%m-%d')
    elements = []

    # 策略信号
    strategy_lines = []
    if signal_file and os.path.exists(signal_file):
        try:
            strategy_df = pd.read_excel(signal_file, sheet_name="全部信号")
            if not strategy_df.empty:
                strategy_lines.append(f"**🔵 策略信号：{len(strategy_df)} 只**")
                # 优先展示：代码 名称 | 日期 | 涨幅 | 行业 | 命中策略
                for _, row in strategy_df.iterrows():
                    code = str(row.get("代码", "")).zfill(6)
                    name = str(row.get("名称", ""))
                    date = str(row.get("K线日期", row.get("日期", "")))[:10]
                    pct = row.get("涨跌幅", "")
                    pct_str = f"{float(pct):+.2f}%" if pd.notna(pct) else ""
                    industry = str(row.get("行业", ""))
                    strategy_hit = str(row.get("主升策略", row.get("突破反转策略", "")))
                    line = f"  {code} {name}"
                    extras = [x for x in [date, pct_str, industry, strategy_hit] if x and x != "nan"]
                    if extras:
                        line += f"  |  {' | '.join(extras)}"
                    strategy_lines.append(line)
            else:
                strategy_lines.append("策略信号：无")
        except Exception:
            strategy_lines.append("策略信号：读取失败")
    else:
        strategy_lines.append("策略信号：无")

    elements.append("\n".join(strategy_lines))

    # ML 信号摘要（优先展示策略共振结果，否则展示 TOP 10 可观察候选）
    if ml_results:
        elements.append("")
        elements.append("**🤖 ML 模型扫描（可观察候选，TOP 10）**")
        for pkl_name, filepath in ml_results.items():
            try:
                # 优先读"ML策略共振"（ML + 规则策略双确认），其次"可观察候选_未涨停"
                try:
                    df_resonance = pd.read_excel(filepath, sheet_name="ML策略共振")
                    # 只取未涨停的共振票
                    if "信号分类" in df_resonance.columns:
                        df_resonance = df_resonance[df_resonance["信号分类"] == "可观察候选_未涨停"]
                    df = df_resonance
                    has_resonance = True
                except (ValueError, KeyError):
                    has_resonance = False
                    try:
                        df = pd.read_excel(filepath, sheet_name="可观察候选_未涨停")
                    except ValueError:
                        df = pd.read_excel(filepath, sheet_name="触发ML信号_全部")

                if not df.empty:
                    total = len(df)
                    label = "🔗 策略共振" if has_resonance else "ML信号"
                    top10 = df.head(10)
                    elements.append(f"  {pkl_name}.pkl（{label}）：共 {total} 只，TOP 10：")
                    for _, row in top10.iterrows():
                        code = str(row.get("代码", "")).zfill(6)
                        name = str(row.get("名称", ""))
                        score = row.get("ML分数", "")
                        pct = row.get("涨跌幅", "")
                        strategies = row.get("命中策略", "")
                        score_str = f"{float(score):.4f}" if pd.notna(score) else ""
                        pct_str = f"{float(pct):+.2f}%" if pd.notna(pct) else ""
                        line = f"    {code} {name}"
                        extras = [x for x in [f"ML:{score_str}", pct_str] if x]
                        if strategies and str(strategies) != "nan":
                            extras.append(str(strategies))
                        if extras:
                            line += f"  |  {' | '.join(extras)}"
                        elements.append(line)
                else:
                    elements.append(f"  {pkl_name}.pkl：无信号")
            except Exception:
                elements.append(f"  {pkl_name}.pkl：读取失败")
    else:
        elements.append("ML 模型：无")

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
    args = parser.parse_args()

    total_start = time.time()

    # 1. 策略信号
    signal_file = run_main_py(force_update=args.force_update)

    # 2. ML 扫描
    ml_results = run_ml_scan_all_pkls()

    # 3. 合并
    summary_file = build_summary_excel(signal_file, ml_results)

    # 4. 发邮件
    send_report_email(summary_file, signal_file, ml_results)

    # 5. 发飞书
    send_feishu_message(signal_file, ml_results)

    total_elapsed = (time.time() - total_start) / 60
    print(f"\n{'=' * 70}")
    print(f"🏁 全部完成，总耗时 {total_elapsed:.1f} 分钟")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
