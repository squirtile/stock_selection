# -*- coding: utf-8 -*-

import tushare as ts
import traceback


def main():
    print("正在初始化 Tushare 新接口...")

    pro = ts.pro_api("OaZRxcERYuAvUoZyhzJkwlvfbDvMSRtDlmLMvMUDzbCykDxYZHIuFMAlWXunwvev")

    # 关键：必须指定新的接口地址
    pro._DataApi__http_url = "http://8.136.22.187:8011/"

    print("初始化完成，开始测试 moneyflow...")

    # =========================================================
    # 测试 1：按交易日期获取全市场资金流向
    # =========================================================
    try:
        print("\n" + "=" * 80)
        print("测试 1：moneyflow 按 trade_date 获取全市场资金流向")
        print("=" * 80)

        df = pro.moneyflow(
            trade_date="20240510",
            limit=10
        )

        print("\nmoneyflow 返回结果：")
        print(df)

        if df is not None:
            print("\n返回行数：", len(df))
            print("返回字段：", list(df.columns))

    except Exception as e:
        print("\n测试 1 失败：")
        print(e)
        traceback.print_exc()

    # =========================================================
    # 测试 2：按单只股票 + 日期区间获取资金流向
    # =========================================================
    try:
        print("\n" + "=" * 80)
        print("测试 2：moneyflow 按 ts_code + 日期区间获取单股资金流向")
        print("=" * 80)

        df = pro.moneyflow(
            ts_code="000001.SZ",
            start_date="20240501",
            end_date="20240510"
        )

        print("\nmoneyflow 返回结果：")
        print(df)

        if df is not None:
            print("\n返回行数：", len(df))
            print("返回字段：", list(df.columns))

    except Exception as e:
        print("\n测试 2 失败：")
        print(e)
        traceback.print_exc()

    # =========================================================
    # 测试 3：指定 fields 获取核心字段
    # =========================================================
    try:
        print("\n" + "=" * 80)
        print("测试 3：moneyflow 指定 fields 获取核心字段")
        print("=" * 80)

        fields = (
            "ts_code,"
            "trade_date,"
            "buy_sm_vol,"
            "buy_sm_amount,"
            "sell_sm_vol,"
            "sell_sm_amount,"
            "buy_md_vol,"
            "buy_md_amount,"
            "sell_md_vol,"
            "sell_md_amount,"
            "buy_lg_vol,"
            "buy_lg_amount,"
            "sell_lg_vol,"
            "sell_lg_amount,"
            "buy_elg_vol,"
            "buy_elg_amount,"
            "sell_elg_vol,"
            "sell_elg_amount,"
            "net_mf_vol,"
            "net_mf_amount"
        )

        df = pro.moneyflow(
            ts_code="000001.SZ",
            start_date="20240501",
            end_date="20240510",
            fields=fields
        )

        print("\nmoneyflow 返回结果：")
        print(df)

        if df is not None:
            print("\n返回行数：", len(df))
            print("返回字段：", list(df.columns))

    except Exception as e:
        print("\n测试 3 失败：")
        print(e)
        traceback.print_exc()

    print("\n测试完成。")


if __name__ == "__main__":
    main()