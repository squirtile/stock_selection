# test_tushare_rt_min.py
# 用于测试 Tushare Token + 代理地址是否可以正常获取 rt_min 实时分钟数据
# 接口：rt_min
# 描述：获取全A股票实时分钟数据，包括 1~60min
# freq 支持：1MIN, 5MIN, 15MIN, 30MIN, 60MIN

import tushare as ts
import pandas as pd
from datetime import datetime


TOKEN = "W5yA7cE9gI1kM3oQ5sU7wY9aC1eG3iK5mO7qS9uW1yA3cE5gI7kM9oQ1sU3wY5aC7eG9iK1mO3qS"
PROXY_URL = "http://47.92.128.69:35721/dataapi"


def test_tushare_rt_min():
    try:
        print("正在初始化 Tushare Pro 接口...")

        pro = ts.pro_api(TOKEN)

        # 设置代理地址
        pro._DataApi__http_url = PROXY_URL

        print("初始化成功！")
        print("正在获取 A 股股票基础信息，用于选取测试股票...")

        # 先获取股票基础信息，验证 token 和代理是否正常
        df_basic = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date"
        )

        if df_basic is None:
            print("获取股票基础信息失败：返回结果为 None")
            return

        if df_basic.empty:
            print("获取股票基础信息成功，但返回数据为空")
            return

        print("股票基础信息获取成功！")
        print(f"共获取到 {len(df_basic)} 条股票数据")
        print()
        print("前 10 行股票基础数据如下：")
        print(df_basic.head(10))

        # 保存股票基础数据，方便检查
        basic_output_file = "tushare_stock_basic_test.csv"
        df_basic.to_csv(basic_output_file, index=False, encoding="utf-8-sig")

        print()
        print(f"股票基础数据已保存到：{basic_output_file}")

        # -----------------------
        # 测试 rt_min 实时分钟数据
        # -----------------------

        # 默认使用浦发银行做测试，也可以改成 df_basic.iloc[0]["ts_code"]
        test_stock = "600000.SH"

        print()
        print("=" * 80)
        print(f"开始测试 rt_min 实时分钟数据接口，测试股票：{test_stock}")
        print("=" * 80)

        freq_list = ["1MIN", "5MIN", "15MIN", "30MIN", "60MIN"]

        all_data = {}

        for freq in freq_list:
            print()
            print(f"正在获取 {test_stock} 的 {freq} 实时分钟数据...")

            try:
                df_min = pro.rt_min(
                    ts_code=test_stock,
                    freq=freq
                )

                if df_min is None:
                    print(f"  {freq} 获取失败：返回结果为 None")
                    all_data[freq] = pd.DataFrame()
                    continue

                if df_min.empty:
                    print(f"  {freq} 获取成功，但返回数据为空")
                    all_data[freq] = pd.DataFrame()
                    continue

                all_data[freq] = df_min

                print(f"  {freq} 获取成功！")
                print(f"  数据条数：{len(df_min)}")
                print(f"  字段列表：{list(df_min.columns)}")
                print()
                print(f"  {freq} 前 5 行数据如下：")
                print(df_min.head(5))

            except Exception as e:
                print(f"  获取 {freq} 数据失败：{type(e).__name__}: {e}")
                all_data[freq] = pd.DataFrame()

        # -----------------------
        # 测试多个股票同时获取
        # -----------------------
        print()
        print("=" * 80)
        print("开始测试多个股票同时获取 rt_min 数据")
        print("=" * 80)

        multi_stocks = "600000.SH,000001.SZ,000002.SZ"
        multi_freq = "1MIN"

        try:
            print(f"正在获取多个股票 {multi_stocks} 的 {multi_freq} 实时分钟数据...")

            df_multi = pro.rt_min(
                ts_code=multi_stocks,
                freq=multi_freq
            )

            if df_multi is None:
                print("多个股票 rt_min 获取失败：返回结果为 None")
                df_multi = pd.DataFrame()
            elif df_multi.empty:
                print("多个股票 rt_min 获取成功，但返回数据为空")
            else:
                print("多个股票 rt_min 获取成功！")
                print(f"数据条数：{len(df_multi)}")
                print(f"字段列表：{list(df_multi.columns)}")
                print()
                print("前 10 行数据如下：")
                print(df_multi.head(10))

            all_data["multi_1MIN"] = df_multi

        except Exception as e:
            print(f"多个股票 rt_min 获取失败：{type(e).__name__}: {e}")
            all_data["multi_1MIN"] = pd.DataFrame()

        # -----------------------
        # 保存到 Excel
        # -----------------------
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"tushare_rt_min_test_{now_str}.xlsx"

        has_data = False

        with pd.ExcelWriter(output_file) as writer:
            for freq, df_min in all_data.items():
                if df_min is not None and not df_min.empty:
                    sheet_name = str(freq)[:31]
                    df_min.to_excel(writer, sheet_name=sheet_name, index=False)
                    has_data = True

        if has_data:
            print()
            print(f"rt_min 实时分钟数据已保存到：{output_file}")
        else:
            print()
            print("没有获取到有效 rt_min 数据，因此 Excel 文件可能为空或无有效 sheet。")

        print()
        print("rt_min 接口测试完成。")

    except Exception as e:
        print("测试失败，错误信息如下：")
        print(type(e).__name__, e)


if __name__ == "__main__":
    test_tushare_rt_min()