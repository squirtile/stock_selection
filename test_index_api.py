#!/usr/bin/env python3
"""测试 Tushare 分钟数据接口权限"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import disable_proxy, get_tushare_pro

disable_proxy()
pro = get_tushare_pro()

tests = [
    # (接口名, 调用方式, 说明)
    ("stk_mins", lambda: pro.stk_mins(ts_code='000001.SZ', asset='E', freq='5min',
                                        start_date='2026-08-04 09:00:00',
                                        end_date='2026-08-04 15:00:00'), "个股历史分钟"),
    ("idx_mins", lambda: pro.idx_mins(ts_code='000001.SH', freq='5min',
                                       start_date='2026-08-04 09:00:00',
                                       end_date='2026-08-04 15:00:00'), "指数历史分钟"),
    ("index_daily", lambda: pro.index_daily(ts_code='000001.SH',
                                              start_date='20260801', end_date='20260804'), "指数日线"),
]

for name, func, desc in tests:
    try:
        df = func()
        if df is not None and not df.empty:
            print(f"✅ {name} ({desc}): 有权限, 返回 {len(df)} 行")
        else:
            print(f"⚠️  {name} ({desc}): 调用成功但返回为空")
    except Exception as e:
        err = str(e)[:120]
        if "权限" in err or "permission" in err or "无权" in err:
            print(f"❌ {name} ({desc}): 无权限")
        elif "频率" in err or "过快" in err or "rate" in err:
            print(f"⏳ {name} ({desc}): 限流 — {err}")
        else:
            print(f"❌ {name} ({desc}): {err}")
