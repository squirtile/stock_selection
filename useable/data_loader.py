# data_loader.py

# data_loader.py

import os
import requests
import akshare as ak
import pandas as pd
import time


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

def safe_load_a_stock_spot(max_retry: int = 5, sleep_seconds: int = 5) -> pd.DataFrame:
    """
    安全获取 A 股实时行情。
    东方财富接口偶尔会断开连接，所以这里加重试。
    """

    last_error = None

    for i in range(max_retry):
        try:
            disable_proxy()

            print(f"正在获取 A 股行情，第 {i + 1}/{max_retry} 次尝试...")

            df = ak.stock_zh_a_spot_em()

            if df is not None and not df.empty:
                print("A 股行情获取成功。")
                return df

        except Exception as e:
            last_error = e
            print(f"A 股行情获取失败，第 {i + 1}/{max_retry} 次。错误：{e}")
            time.sleep(sleep_seconds)

    print("A 股行情多次获取失败。")
    print(f"最后一次错误：{last_error}")

    raise last_error

def load_industry_map(use_cache: bool = True) -> pd.DataFrame:
    """
    获取东方财富行业板块成分股，并生成：
    代码 - 行业

    增加缓存，避免每次重新请求东方财富行业接口。
    """

    os.makedirs("cache", exist_ok=True)

    cache_file = "cache/industry_map.csv"

    if use_cache and os.path.exists(cache_file):
        print(f"发现行业缓存：{cache_file}")
        result = pd.read_csv(cache_file, dtype={"代码": str})
        result["代码"] = result["代码"].astype(str).str.zfill(6)
        return result[["代码", "行业"]]

    print("正在获取行业数据...")

    max_retry = 5
    last_error = None

    industry_df = None

    for i in range(max_retry):
        try:
            disable_proxy()
            print(f"正在获取行业列表，第 {i + 1}/{max_retry} 次尝试...")
            industry_df = ak.stock_board_industry_name_em()

            if industry_df is not None and not industry_df.empty:
                break

        except Exception as e:
            last_error = e
            print(f"行业列表获取失败，第 {i + 1}/{max_retry} 次：{e}")
            time.sleep(5)

    if industry_df is None or industry_df.empty:
        raise ValueError(f"行业列表获取失败，最后错误：{last_error}")

    all_list = []

    for idx, industry_name in enumerate(industry_df["板块名称"].tolist()):
        try:
            print(f"正在获取行业 {idx + 1}/{len(industry_df)}：{industry_name}")

            disable_proxy()

            cons_df = ak.stock_board_industry_cons_em(symbol=industry_name)

            if cons_df is None or cons_df.empty:
                continue

            temp_df = cons_df[["代码", "名称"]].copy()
            temp_df["代码"] = temp_df["代码"].astype(str).str.zfill(6)
            temp_df["行业"] = industry_name

            all_list.append(temp_df)

            # 限速，别太快
            time.sleep(0.8)

        except Exception as e:
            print(f"行业 {industry_name} 获取失败，已跳过。错误：{e}")
            time.sleep(2)
            continue

    if not all_list:
        raise ValueError("行业数据获取失败，没有拿到任何行业成分股。")

    result = pd.concat(all_list, ignore_index=True)

    result = result.drop_duplicates(subset=["代码"], keep="first")

    result.to_csv(cache_file, index=False, encoding="utf-8-sig")

    print(f"行业映射数量：{len(result)}")
    print(f"行业缓存已保存：{cache_file}")

    return result[["代码", "行业"]]

def load_a_stock_spot() -> pd.DataFrame:
    """
    获取 A 股实时行情数据，并合并行业字段。
    """

    disable_proxy()

    try:
        # df = ak.stock_zh_a_spot_em()
        df = safe_load_a_stock_spot(max_retry=5, sleep_seconds=8)
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