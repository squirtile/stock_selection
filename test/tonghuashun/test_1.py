# -*- coding: utf-8 -*-

from iFinDPy import *
from datetime import datetime


USERNAME = "sjjksy081"
PASSWORD = "NFS6anh7"


def login():
    ret = THS_iFinDLogin(USERNAME, PASSWORD)
    print("登录返回码:", ret)
    if ret not in {0, -201}:
        raise RuntimeError(f"登录失败: {ret}")


def test_indicators():
    code = "600000.SH"
    today = datetime.today().strftime("%Y-%m-%d")

    candidates = [
        "ths_market_value_stock",
        "ths_total_mv_stock",
        "ths_total_market_value_stock",
        "ths_stock_short_name_stock",
        "ths_stock_name_stock",
        "ths_stock_abbr_stock",
    ]

    for ind in candidates:
        print("\n测试字段:", ind)
        try:
            data = THS_BD(code, ind, f"{today},100")
            print("errorcode:", data.errorcode)
            print("errmsg:", data.errmsg)
            print(data.data)
        except Exception as e:
            print("异常:", e)


def main():
    login()
    try:
        test_indicators()
    finally:
        THS_iFinDLogout()


if __name__ == "__main__":
    main()