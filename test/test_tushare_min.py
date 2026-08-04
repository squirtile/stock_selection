# test/test_tushare_min.py

import sys
import os

# 将项目根目录加入 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
import time  # 用来计时

# -----------------------
# 1. 从 config.py 读取 token 和自定义 URL
# -----------------------
from config import TUSHARE_TOKEN, TUSHARE_HTTP_URL

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api(TUSHARE_TOKEN)
if TUSHARE_HTTP_URL:
    pro._DataApi__http_url = TUSHARE_HTTP_URL

# -----------------------
# 2. 获取测试股票列表
# -----------------------
stock_list_df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
stock_list = stock_list_df.head(20)['ts_code'].tolist()

# -----------------------
# 3. 定义时间范围
# -----------------------
end_date = datetime.now()
start_date = end_date - timedelta(days=3)
start_str = start_date.strftime('%Y%m%d')
end_str = end_date.strftime('%Y%m%d')

print(f"Fetching minute-level data from {start_str} to {end_str} for {len(stock_list)} stocks")

# -----------------------
# 4. 定义周期列表
# -----------------------
freq_list = ['1min', '5min', '10min']

# -----------------------
# 5. 获取数据
# -----------------------
all_data = {}

start_time = time.time()  # 开始计时

for ts_code in stock_list:
    print(f"Fetching data for {ts_code}")
    all_data[ts_code] = {}
    for freq in freq_list:
        try:
            df = pro.stk_mins(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
                freq=freq,
                adj='qfq'
            )
            all_data[ts_code][freq] = df
            print(f"  {freq} data: {len(df)} rows")
        except Exception as e:
            print(f"  Failed to fetch {freq} data for {ts_code}: {e}")

end_time = time.time()  # 结束计时
elapsed_time = end_time - start_time

# -----------------------
# 6. 保存为 Excel
# -----------------------
output_file = "tushare_min_test.xlsx"
with pd.ExcelWriter(output_file) as writer:
    for ts_code, freq_dict in all_data.items():
        for freq, df in freq_dict.items():
            if df is not None and not df.empty:
                sheet_name = f"{ts_code}_{freq}"[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)

print(f"Done! Data saved to {output_file}")
print(f"Total elapsed time: {elapsed_time:.2f} seconds (~{elapsed_time/60:.2f} minutes)")