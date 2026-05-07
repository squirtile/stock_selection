# data_loader.py

# data_loader.py

import os
import requests
import akshare as ak
import pandas as pd


def disable_proxy():
    """
    强制禁用代理。
    注意：该函数可能会被 main.py、strategy.py、concept_analyzer.py 多次调用，
    所以必须避免重复 monkey patch requests.Session。
    """

    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ]

    for key in proxy_keys:
        os.environ.pop(key, None)

    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"

    if getattr(requests.Session, "_no_proxy_patched", False):
        return

    original_session = requests.Session

    class NoProxySession(original_session):
        _no_proxy_patched = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.trust_env = False

    requests.Session = NoProxySession


def load_industry_map() -> pd.DataFrame:
    """
    获取东方财富行业板块成分股，并生成：
    代码 - 行业
    """

    print("正在获取行业数据...")

    industry_df = ak.stock_board_industry_name_em()

    all_list = []

    for industry_name in industry_df["板块名称"].tolist():
        try:
            cons_df = ak.stock_board_industry_cons_em(symbol=industry_name)

            if cons_df is None or cons_df.empty:
                continue

            temp_df = cons_df[["代码", "名称"]].copy()
            temp_df["行业"] = industry_name

            all_list.append(temp_df)

        except Exception as e:
            print(f"行业 {industry_name} 获取失败，已跳过。错误：{e}")
            continue

    if not all_list:
        raise ValueError("行业数据获取失败，没有拿到任何行业成分股。")

    result = pd.concat(all_list, ignore_index=True)

    # 同一只股票可能出现在多个概念/行业里，这里按代码去重
    result = result.drop_duplicates(subset=["代码"], keep="first")

    print(f"行业映射数量：{len(result)}")

    return result[["代码", "行业"]]


def load_a_stock_spot() -> pd.DataFrame:
    """
    获取 A 股实时行情数据，并合并行业字段。
    """

    disable_proxy()

    try:
        df = ak.stock_zh_a_spot_em()
    except Exception as e:
        print("获取 A 股数据失败。")
        print("可能原因：代理异常、网络异常、东方财富接口临时不可用。")
        print("原始错误：")
        print(e)
        raise

    print("当前行情数据字段：")
    print(df.columns.tolist())

    # 统一代码格式
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    # 获取行业映射
    industry_map = load_industry_map()
    industry_map["代码"] = industry_map["代码"].astype(str).str.zfill(6)

    # 合并行业
    df = df.merge(industry_map, on="代码", how="left")

    print("合并行业后的字段：")
    print(df.columns.tolist())

    return df