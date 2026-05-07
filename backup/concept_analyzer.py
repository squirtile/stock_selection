# concept_analyzer.py

import os
import time
from datetime import datetime

import pandas as pd
import requests


CONCEPT_CACHE_DIR = "cache/concept"


def get_no_proxy_session() -> requests.Session:
    """
    创建一个不走系统代理的 requests session。
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

    session = requests.Session()
    session.trust_env = False

    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        }
    )

    return session


def get_market_prefix(code: str) -> str:
    """
    东方财富 secid 前缀：
    上交所：1
    深交所：0
    """
    code = str(code).zfill(6)

    if code.startswith(("600", "601", "603", "605", "688")):
        return "1"

    return "0"


def safe_get_stock_json(code: str, max_retry: int = 3, sleep_seconds: int = 2):
    """
    安全获取单只股票东方财富个股信息。
    """

    code = str(code).zfill(6)
    market = get_market_prefix(code)

    url = "https://push2.eastmoney.com/api/qt/stock/get"

    params = {
        "secid": f"{market}.{code}",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fields": (
            "f57,f58,"
            "f127,f128,f129,"
            "f116,f117"
        ),
    }

    last_error = None

    for i in range(max_retry):
        try:
            session = get_no_proxy_session()

            response = session.get(
                url,
                params=params,
                timeout=10,
                proxies={"http": None, "https": None},
            )

            response.raise_for_status()

            data = response.json()

            if data and data.get("rc") == 0 and data.get("data"):
                return data.get("data")

        except Exception as e:
            last_error = e
            print(f"{code} 题材接口请求失败，第 {i + 1}/{max_retry} 次：{e}")
            time.sleep(sleep_seconds)

    print(f"{code} 题材接口多次失败，最后错误：{last_error}")
    return {}


def split_concepts(concept_text: str) -> list:
    """
    拆分东方财富 f129 概念题材字段。
    """

    if not concept_text or not isinstance(concept_text, str):
        return []

    text = concept_text.strip()

    for sep in ["，", "、", ";", "；"]:
        text = text.replace(sep, ",")

    concepts = []

    for item in text.split(","):
        item = item.strip()

        if not item:
            continue

        # 去掉一些不太像“题材主线”的常见标签
        exclude_items = {
            "融资融券",
            "沪股通",
            "深股通",
            "机构重仓",
            "富时罗素",
            "证金持股",
            "MSCI中国",
            "标准普尔",
        }

        if item in exclude_items:
            continue

        concepts.append(item)

    return concepts


def get_stock_concepts_from_em(code: str) -> list:
    """
    从东方财富个股信息接口提取单只股票的概念题材。
    主要使用 f129 字段。
    """

    data = safe_get_stock_json(code)

    if not data:
        return []

    concept_text = data.get("f129", "")

    return split_concepts(concept_text)


def load_signal_stock_concept_map(signal_df: pd.DataFrame, use_cache: bool = True) -> pd.DataFrame:
    """
    只查询命中股票的概念题材。
    """

    os.makedirs(CONCEPT_CACHE_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CONCEPT_CACHE_DIR, f"signal_stock_concepts_{today}.csv")

    signal_df = signal_df.copy()
    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    if use_cache and os.path.exists(cache_file):
        print(f"发现命中股票题材缓存：{cache_file}")
        concept_map = pd.read_csv(cache_file, dtype={"代码": str})
        concept_map["代码"] = concept_map["代码"].astype(str).str.zfill(6)
        return concept_map

    result_list = []

    total = len(signal_df)

    for idx, row in signal_df.iterrows():
        code = str(row["代码"]).zfill(6)
        name = row["名称"]

        print(f"正在获取股票题材 {idx + 1}/{total}：{code} {name}")

        concepts = get_stock_concepts_from_em(code)

        if concepts:
            for concept in concepts:
                result_list.append(
                    {
                        "代码": code,
                        "名称": name,
                        "概念题材": concept,
                    }
                )
        else:
            print(f"{code} {name} 未获取到题材。")

        # 逐只股票查询，放慢一点
        time.sleep(0.8)

    if not result_list:
        print("没有获取到任何命中股票题材。")
        return pd.DataFrame(columns=["代码", "名称", "概念题材"])

    concept_map = pd.DataFrame(result_list)

    concept_map = concept_map.drop_duplicates(
        subset=["代码", "概念题材"],
        keep="first"
    )

    concept_map.to_csv(cache_file, index=False, encoding="utf-8-sig")

    print(f"命中股票题材映射已保存：{cache_file}")
    print(f"题材映射数量：{len(concept_map)}")

    return concept_map


def analyze_concept_resonance(signal_df: pd.DataFrame, min_count: int = 3):
    """
    对命中股票进行题材共振分析。

    逻辑：
    只查询命中股票的题材，而不是全市场所有题材。
    """

    if signal_df is None or signal_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    signal_df = signal_df.copy()
    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    concept_map = load_signal_stock_concept_map(signal_df, use_cache=True)

    if concept_map is None or concept_map.empty:
        print("命中股票题材为空，本次跳过题材共振分析。")
        return pd.DataFrame(), pd.DataFrame(), {}

    # 统计每个题材下命中了几只股票
    resonance_summary_df = (
        concept_map
        .groupby("概念题材")
        .agg(
            命中数=("代码", "nunique"),
            命中股票=("名称", lambda x: "、".join(sorted(set(x))))
        )
        .reset_index()
    )

    # 同一题材下 >= 3 只票当日入选，标记为题材共振
    resonance_summary_df = resonance_summary_df[
        resonance_summary_df["命中数"] >= min_count
    ].copy()

    if resonance_summary_df.empty:
        print("今日没有发现题材共振。")
        return pd.DataFrame(), pd.DataFrame(), {}

    # 按命中数降序
    resonance_summary_df = resonance_summary_df.sort_values(
        by="命中数",
        ascending=False
    )

    resonance_concepts = set(resonance_summary_df["概念题材"].tolist())

    # 共振明细
    resonance_detail_df = concept_map[
        concept_map["概念题材"].isin(resonance_concepts)
    ].copy()

    # 每只股票可能属于多个共振题材
    stock_theme_map = (
        resonance_detail_df
        .groupby("代码")["概念题材"]
        .apply(lambda x: "、".join(sorted(set(x))))
        .to_dict()
    )

    return resonance_summary_df, resonance_detail_df, stock_theme_map