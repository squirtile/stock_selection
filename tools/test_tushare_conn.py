"""测试 Tushare 连接 — 从 config.py 读取 token 和 URL"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TUSHARE_TOKEN, TUSHARE_HTTP_URL
from data_loader import disable_proxy

# 关掉系统代理（VPN 开着时 Tushare 走代理会连不上）
disable_proxy()

import tushare as ts

pro = ts.pro_api(TUSHARE_TOKEN)
pro._DataApi__http_url = TUSHARE_HTTP_URL

# 测试基础接口
df = pro.stock_basic(limit=5)

if df is None:
    print("返回 None")
elif df.empty:
    print("返回空数据 — token 或镜像可能有问题")
else:
    print(f"连接成功！获取到 {len(df)} 条股票数据")
    print(df.to_string())

# 测试板块
df2 = pro.ths_index(limit=3)
if df2 is not None and not df2.empty:
    print(f"\n板块数据正常 ({len(df2)} 条)")
    print(df2.head(3).to_string())
else:
    print("\n板块数据为空")
