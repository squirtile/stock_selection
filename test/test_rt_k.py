# -*- coding: utf-8 -*-

import tushare as ts

TOKEN = "OaZRxcERYuAvUoZyhzJkwlvfbDvMSRtDlmLMvMUDzbCykDxYZHIuFMAlWXunwvev"
HTTP_URL = "http://8.136.22.187:8011/"


def test_single_stock(pro):
    """
    测试单只股票实时日K
    """
    print("=" * 80)
    print("测试 rt_k：单只股票 000001.SZ")

    df = pro.rt_k(ts_code="000001.SZ")

    print(df.head())
    print(df.tail())
    print("返回行数：", 0 if df is None else len(df))
    print("字段：", [] if df is None else list(df.columns))


def test_multi_stock(pro):
    """
    测试多只股票实时日K
    """
    print("=" * 80)
    print("测试 rt_k：多只股票 000001.SZ,600000.SH")

    df = pro.rt_k(ts_code="000001.SZ,600000.SH")

    print(df.head())
    print(df.tail())
    print("返回行数：", 0 if df is None else len(df))
    print("字段：", [] if df is None else list(df.columns))


def test_wildcard_stock(pro):
    """
    测试通配符获取创业板股票
    注意：这个可能返回很多数据，接口权限和速度受限制。
    """
    print("=" * 80)
    print("测试 rt_k：通配符 3*.SZ，创业板实时日K")

    df = pro.rt_k(ts_code="3*.SZ")

    print(df.head())
    print(df.tail())
    print("返回行数：", 0 if df is None else len(df))
    print("字段：", [] if df is None else list(df.columns))


def main():
    pro = ts.pro_api(TOKEN)
    pro._DataApi__http_url = HTTP_URL

    test_single_stock(pro)
    test_multi_stock(pro)

    # 如果只是先验证接口是否可用，建议先不要打开这个。
    # 通配符一次会返回很多数据，等单只/多只测试正常后再打开。
    # test_wildcard_stock(pro)


if __name__ == "__main__":
    main()