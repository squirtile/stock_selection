# test_tushare_realtime_old.py
# 测试 Tushare 老版实时行情接口 get_realtime_quotes

import tushare as ts


def main():
    print("当前 tushare 版本：", ts.__version__)

    codes = [
        "000001",
        "600519",
        "002351",
        "603299",
    ]

    print("正在测试 get_realtime_quotes...")
    print("测试代码：", codes)

    try:
        df = ts.get_realtime_quotes(codes)

        if df is None:
            print("返回 None")
            return

        if df.empty:
            print("返回空表。可能当前不是交易时间，或实时行情源不可用。")
            return

        print("获取成功！")
        print("返回字段：")
        print(df.columns.tolist())
        print()
        print(df.head(10))

        df.to_csv("tushare_realtime_old_test.csv", index=False, encoding="utf-8-sig")
        print()
        print("已保存到：tushare_realtime_old_test.csv")

    except Exception as e:
        print("获取失败。")
        print("错误类型：", type(e).__name__)
        print("错误信息：", e)


if __name__ == "__main__":
    main()