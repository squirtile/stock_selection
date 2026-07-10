#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书机器人 Webhook 发送测试
"""

import requests
import json
from datetime import datetime

# ========== 配置 ==========
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/1e3a68ab-7525-4786-8ecb-ca8058bcc40a"
# =========================

def send_text(text: str):
    """发送纯文本消息"""
    payload = {
        "msg_type": "text",
        "content": {
            "text": text
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return r.json()


def send_rich_text(title: str, content: list):
    """发送富文本消息（支持颜色、加粗等）"""
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue"
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": c}}
                for c in content
            ]
        }
    }
    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
    return r.json()


if __name__ == "__main__":
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 测试1：纯文本
    print("发送纯文本...")
    resp = send_text(f"✅ 飞书机器人测试成功！\n发送时间：{now}")
    print(f"  结果：{resp}")

    # 测试2：富文本卡片
    print("\n发送富文本卡片...")
    resp = send_rich_text(
        f"🤖 飞书机器人测试 - {now}",
        [
            "**测试项目**：Webhook 消息推送",
            f"**发送时间**：{now}",
            "",
            "✅ 纯文本消息 — 通过",
            "✅ 富文本卡片消息 — 通过",
            "",
            "---",
            "> 如果你看到这条消息，说明飞书机器人配置正确。",
        ]
    )
    print(f"  结果：{resp}")

    print("\n完成！请检查飞书群。")
