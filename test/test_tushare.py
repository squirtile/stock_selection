# test_tushare.py
# 用于测试 Tushare Token + 代理地址是否可以正常获取 A股基础数据
# python -m pip install tushare pandas -i https://pypi.tuna.tsinghua.edu.cn/simple
import tushare as ts
import pandas as pd


TOKEN = "W5yA7cE9gI1kM3oQ5sU7wY9aC1eG3iK5mO7qS9uW1yA3cE5gI7kM9oQ1sU3wY5aC7eG9iK1mO3qS"
PROXY_URL = "http://47.92.128.69:35721/dataapi"


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
        print(f"测试数据已保存到：{output_file}")

    except Exception as e:
        print("测试失败，错误信息如下：")
        print(type(e).__name__, e)


if __name__ == "__main__":
    test_tushare()