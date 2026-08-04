#!/usr/bin/env python
"""预缓存板块成分股，避免 sector_heat.py --json 每次拉取"""
import sys, json, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_loader import disable_proxy, get_tushare_pro, get_latest_trade_date

disable_proxy()
pro = get_tushare_pro()
td = get_latest_trade_date(pro)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
CACHE = os.path.join(OUTPUT_DIR, "sector_member_cache.json")

cache = {}
if os.path.exists(CACHE):
    with open(CACHE) as f:
        cache = json.load(f)

df = pro.limit_cpt_list(trade_date=td)
codes = df['ts_code'].tolist()
print(f"Date={td}, sectors={len(codes)}, cached={len(cache)}")

new = 0
for c in codes:
    if c in cache:
        continue
    try:
        m = pro.ths_member(ts_code=c)
        if m is not None and not m.empty:
            cache[c] = [str(x) for x in m['con_code'].tolist()]
            new += 1
            print(f"  + {c} ({len(cache[c])} stocks)")
        time.sleep(0.3)
    except Exception as e:
        print(f"  ! {c}: {e}")

os.makedirs(OUTPUT_DIR, exist_ok=True)
with open(CACHE, 'w') as f:
    json.dump(cache, f, ensure_ascii=False)
print(f"Done: {len(cache)} sectors cached ({new} new)")
