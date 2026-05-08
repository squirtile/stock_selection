# test_realtime_pool.py
# 测试：读取基础股票池，然后批量获取实时行情

import os
import time
import pandas as pd
import tushare as ts


BASE_POOL_FILE = "../output/a_stock_selected.xlsx"
BATCH_SIZE = 80


def load_base_pool():
    if not os.path.exists(BASE_POOL_FILE):
        raise FileNotFoundError(f"没有找到基础股票池文件：{BASE_POOL_FILE}")

    df = pd.read_excel(BASE_POOL_FILE, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    print(f"基础股票池数量：{len(df)}")
    return df


def get_realtime_quotes_batch(codes, batch_size=80, sleep_seconds=0.3):
    """
    分批获取实时行情，避免一次请求太多导致失败。
    """

    all_list = []
    total = len(codes)

    start_time = time.time()

    for start in range(0, total, batch_size):
        batch_codes = codes[start:start + batch_size]
        batch_no = start // batch_size + 1
        total_batch = (total + batch_size - 1) // batch_size

        print(f"正在获取实时行情 {batch_no}/{total_batch}，数量：{len(batch_codes)}")

        try:
            df = ts.get_realtime_quotes(batch_codes)

            if df is not None and not df.empty:
                all_list.append(df)
                print(f"本批成功：{len(df)}")
            else:
                print("本批返回空。")

        except Exception as e:
            print(f"本批失败：{e}")

        time.sleep(sleep_seconds)

    elapsed = time.time() - start_time

    if not all_list:
        print("没有获取到任何实时行情。")
        return pd.DataFrame()

    result = pd.concat(all_list, ignore_index=True)

    print(f"实时行情获取完成，数量：{len(result)}，耗时：{elapsed:.2f} 秒")
    return result


def format_realtime_df(rt_df):
    """
    整理实时行情字段，转成后续策略容易用的格式。
    """

    df = rt_df.copy()

    df["代码"] = df["code"].astype(str).str.zfill(6)
    df["名称"] = df["name"]

    numeric_cols = [
        "open",
        "pre_close",
        "price",
        "high",
        "low",
        "volume",
        "amount",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["实时涨跌幅"] = (df["price"] / df["pre_close"] - 1) * 100

    result = pd.DataFrame()
    result["代码"] = df["代码"]
    result["名称"] = df["名称"]
    result["行情日期"] = df["date"]
    result["行情时间"] = df["time"]
    result["开盘"] = df["open"]
    result["最高"] = df["high"]
    result["最低"] = df["low"]
    result["最新价"] = df["price"]
    result["昨收"] = df["pre_close"]
    result["涨跌幅"] = df["实时涨跌幅"]
    result["成交量"] = df["volume"]
    result["成交额"] = df["amount"]

    result = result.dropna(subset=["最新价"])

    return result


def main():
    pool_df = load_base_pool()

    codes = pool_df["代码"].tolist()

    rt_df = get_realtime_quotes_batch(
        codes,
        batch_size=BATCH_SIZE,
        sleep_seconds=0.3
    )

    if rt_df.empty:
        print("实时行情为空，测试结束。")
        return

    result = format_realtime_df(rt_df)

    print()
    print("实时行情整理后前 20 行：")
    print(result.head(20))

    output_file = "realtime_pool_test.csv"
    result.to_csv(output_file, index=False, encoding="utf-8-sig")

    print()
    print(f"已保存：{output_file}")


if __name__ == "__main__":
    main()