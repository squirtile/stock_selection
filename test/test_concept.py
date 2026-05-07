# test_concept.py

import os
import time
import requests
import akshare as ak
import pandas as pd


def disable_proxy():
    """
    测试脚本里单独禁用代理。
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


def safe_get_concept_name_df(max_retry: int = 5, sleep_seconds: int = 3) -> pd.DataFrame:
    """
    安全获取东方财富概念题材列表。
    如果接口临时断开，则自动重试。
    """

    last_error = None

    for i in range(max_retry):
        try:
            disable_proxy()
            print(f"正在获取东方财富概念题材列表，第 {i + 1}/{max_retry} 次尝试...")

            concept_name_df = ak.stock_board_concept_name_em()

            if concept_name_df is not None and not concept_name_df.empty:
                print(f"概念题材列表获取成功，共 {len(concept_name_df)} 个题材。")
                return concept_name_df

        except Exception as e:
            last_error = e
            print(f"概念题材列表获取失败，第 {i + 1}/{max_retry} 次。错误：{e}")
            time.sleep(sleep_seconds)

    print("概念题材列表多次获取失败。")
    print(f"最后一次错误：{last_error}")

    return pd.DataFrame()


def main():
    df = safe_get_concept_name_df(max_retry=5, sleep_seconds=3)

    if df.empty:
        print("没有获取到概念题材数据。")
        return

    print("\n获取到的字段：")
    print(df.columns.tolist())

    print("\n前20个概念题材：")
    print(df.head(20))

    os.makedirs("output", exist_ok=True)
    output_file = "output/test_concept_name.xlsx"
    df.to_excel(output_file, index=False)

    print(f"\n概念题材列表已导出：{output_file}")


if __name__ == "__main__":
    main()