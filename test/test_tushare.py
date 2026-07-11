# test_tushare.py
# 用于测试 Tushare Token + 代理地址是否可以正常获取 A股基础数据
# 并获取前1行股票过去1天的分钟数据
import tushare as ts
import pandas as pd
from datetime import datetime, timedelta

TOKEN = "mMug3jKblBu2rVLuRzFbPKyv68iUjNbAIbdBX93XZafNqjQyt9tnUkM1"
PROXY_URL = "http://165.99.43.204:24629/"


def test_tushare():
    try:
        print("正在初始化 Tushare Pro 接口...")

        pro = ts.pro_api(TOKEN)

        # 设置代理地址
        pro._DataApi__http_url = PROXY_URL

        print("初始化成功，正在获取 A股股票基础信息...")

        df = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date"
        )

        if df is None:
            print("获取失败：返回结果为 None")
            return

        if df.empty:
            print("获取成功，但返回数据为空")
            return

        print("获取成功！")
        print(f"共获取到 {len(df)} 条股票数据")
        print()
        print("前 10 行数据如下：")
        print(df.head(10))

        # 保存到本地，方便检查
        output_file = "tushare_stock_basic_test.csv"
        df.to_csv(output_file, index=False, encoding="utf-8-sig")

        print()
        print(f"股票基础数据已保存到：{output_file}")

        # -----------------------
        # 获取前1行股票过去1天的分钟级数据
        # -----------------------
        first_stock = df.iloc[0]['ts_code']
        print(f"\n正在获取股票 {first_stock} 过去1天的分钟数据...")

        end_date = datetime.now()
        start_date = end_date - timedelta(days=1)
        start_str = start_date.strftime('%Y%m%d')
        end_str = end_date.strftime('%Y%m%d')

        freq_list = ['1min', '5min', '15min']
        all_data = {}

        for freq in freq_list:
            try:
                df_min = pro.stk_mins(
                    ts_code=first_stock,
                    start_date=start_str,
                    end_date=end_str,
                    freq=freq,
                    adj='qfq'  # 前复权
                )
                all_data[freq] = df_min
                print(f"  {freq} 数据条数: {len(df_min)}")
            except Exception as e:
                print(f"  获取 {freq} 数据失败: {e}")
                all_data[freq] = pd.DataFrame()

        # 保存到 Excel
        output_min_file = f"tushare_min_{first_stock}.xlsx"
        with pd.ExcelWriter(output_min_file) as writer:
            for freq, df_min in all_data.items():
                if df_min is not None and not df_min.empty:
                    sheet_name = f"{first_stock}_{freq}"[:31]  # sheet名最长31字符
                    df_min.to_excel(writer, sheet_name=sheet_name, index=False)

        print(f"分钟数据已保存到：{output_min_file}")

    except Exception as e:
        print("测试失败，错误信息如下：")
        print(type(e).__name__, e)


if __name__ == "__main__":
    test_tushare()