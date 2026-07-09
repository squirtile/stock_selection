# config.example.py
# 
# 使用说明：
# 1. 复制此文件为 config.py：  cp config.example.py config.py
# 2. 编辑 config.py，填入你自己的 Token 和授权码
# 3. config.py 已被 .gitignore 忽略，不会提交到 Git

import os

# =========================
# Tushare 配置
# =========================
# 优先读取环境变量 TUSHARE_TOKEN，否则使用下面的值
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "你的Tushare_Token")

# Tushare 代理地址（如有）
TUSHARE_HTTP_URL = os.getenv("TUSHARE_HTTP_URL", "http://8.136.22.187:8011/")

# 飞书 Webhook（可选）
FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/你的飞书webhook"

# 可选：是否开启分钟B点飞书推送
FEISHU_MINUTE_PUSH_ENABLE = True

# =========================
# 基础股票池筛选条件
# =========================
MIN_MARKET_VALUE = 1      # 最小市值（亿元）
MAX_MARKET_VALUE = 5000   # 最大市值（亿元）

EXCLUDE_INDUSTRIES = [
    "银行", "证券", "券商", "保险", "信托",
    "房地产", "地产", "钢铁", "煤炭", "煤炭开采",
    "铁路运输", "航运", "水运", "港口",
]

OUTPUT_FILE = "output/a_stock_selected.xlsx"

# =========================
# 163 邮箱 SMTP 配置（可选）
# =========================
EMAIL_CONFIG = {
    "smtp_server": "smtp.163.com",
    "smtp_port": 465,
    "sender": "你的邮箱@163.com",
    "password": "你的163邮箱SMTP授权码",
    "receiver": "你的邮箱@163.com",
}
