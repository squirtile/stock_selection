# test_tushare_realtime.py
# 测试 Tushare 是否能获取实时行情数据

import os
import pandas as pd
import tushare as ts


TOKEN = "W5yA7cE9gI1kM3oQ5sU7wY9aC1eG3iK5mO7qS9uW1yA3cE5gI7kM9oQ1sU3wY5aC7eG9iK1mO3qS"
PROXY_URL = "http://47.92.128.69:35721/dataapi"


def init_tushare():
    """
    初始化 Tushare。
    注意：
    pro._DataApi__http_url 主要影响 pro 接口。
    realtime_quote 是否走这个代理，要看你买的服务是否支持。
    """

    ts.set_token(TOKEN)

    pro = ts.pro_api(TOKEN)
    pro._DataApi__http_url = PROXY_URL

    return pro


def test_realtime_quote():
    """
    测试实时行情接口。
    """

    print("当前 tushare 版本：", ts.__version__)
    print("正在初始化 Tushare...")

    pro = init_tushare()

    # 先用几只常见股票测试
    # 000001.SZ 平安银行
    # 600519.SH 贵州茅台
    # 002351.SZ 漫步者
    # 603299.SH 苏盐井神
    test_codes = [
        "000001.SZ",
        "600519.SH",
        "002351.SZ",
        "603299.SH",
    ]

    code_str = ",".join(test_codes)

    print(f"正在测试实时行情：{code_str}")

    try:
        # Tushare 实时行情接口
        df = ts.realtime_quote(ts_code=code_str)

        if df is None:
            print("实时行情返回 None")
            return

        if df.empty:
            print("实时行情返回空表。")
            print("可能原因：")
            print("1. 当前不是 A 股交易时间")
            print("2. 你的 Tushare 版本不支持 realtime_quote")
            print("3. 你买的代理不支持实时行情接口")
            print("4. 实时行情源临时不可用")
            return

        print("实时行情获取成功！")
        print("返回字段：")
        print(df.columns.tolist())
        print()
        print("前几行数据：")
        print(df.head(10))

        output_file = "tushare_realtime_test.csv"
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
        print()
        print(f"实时行情测试结果已保存：{output_file}")

    except Exception as e:
        print("实时行情获取失败。")
        print("错误类型：", type(e).__name__)
        print("错误信息：", e)

        print()
        print("开始测试 pro 接口是否仍然正常...")

        try:
            df_basic = pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,area,industry,market,list_date"
            )

            print("pro.stock_basic 正常，说明 token 和代理地址基础接口可用。")
            print(df_basic.head())

        except Exception as e2:
            print("pro.stock_basic 也失败。")
            print("错误类型：", type(e2).__name__)
            print("错误信息：", e2)


if __name__ == "__main__":
    test_realtime_quote()