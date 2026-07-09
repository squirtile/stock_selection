#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 163 邮箱 SMTP 发送邮件
"""

import smtplib
import sys
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from datetime import datetime

# 从 config.py 读取邮箱配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import EMAIL_CONFIG

SMTP_SERVER = EMAIL_CONFIG["smtp_server"]
SMTP_PORT   = EMAIL_CONFIG["smtp_port"]
SENDER_EMAIL = EMAIL_CONFIG["sender"]
SENDER_PASS  = EMAIL_CONFIG["password"]
RECEIVER     = EMAIL_CONFIG["receiver"]

def send_test_email():
    """发送一封测试邮件"""
    
    # 构造邮件
    msg = MIMEMultipart()
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = RECEIVER
    msg["Subject"] = Header(f"[测试] 163邮箱SMTP发送测试 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "utf-8")
    
    # 正文
    body = f"""
    <h2>✅ 163 邮箱 SMTP 测试成功！</h2>
    <p>发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p>如果你收到这封邮件，说明 SMTP 配置正确。</p>
    <hr>
    <p><b>配置信息：</b></p>
    <ul>
        <li>SMTP 服务器：{SMTP_SERVER}:{SMTP_PORT}</li>
        <li>发件人：{SENDER_EMAIL}</li>
        <li>使用 SSL 加密</li>
    </ul>
    """
    msg.attach(MIMEText(body, "html", "utf-8"))
    
    try:
        # SSL 直连
        print(f"正在连接 {SMTP_SERVER}:{SMTP_PORT} ...")
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15)
        server.set_debuglevel(1)  # 打印 SMTP 交互日志
        
        print(f"正在登录 {SENDER_EMAIL} ...")
        server.login(SENDER_EMAIL, SENDER_PASS)
        
        print(f"正在发送到 {RECEIVER} ...")
        server.sendmail(SENDER_EMAIL, RECEIVER, msg.as_string())
        
        server.quit()
        print("\n✅ 邮件发送成功！请检查收件箱。")
        return True
        
    except smtplib.SMTPAuthenticationError:
        print("\n❌ 登录失败：邮箱地址或授权码错误。")
        print("   请确认：1) SENDER_EMAIL 是否正确  2) 授权码是否已开启且正确")
        return False
        
    except smtplib.SMTPConnectError:
        print(f"\n❌ 无法连接 {SMTP_SERVER}:{SMTP_PORT}")
        print("   请检查网络和防火墙设置。")
        return False
        
    except Exception as e:
        print(f"\n❌ 发送失败：{e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("  163 邮箱 SMTP 发送测试")
    print("=" * 50)
    print(f"  发件人：{SENDER_EMAIL}")
    print(f"  收件人：{RECEIVER}")
    print(f"  服务器：{SMTP_SERVER}:{SMTP_PORT}")
    print("=" * 50)
    print()
    
    send_test_email()
