# concept_analyzer.py

import os
import time
from datetime import datetime

import pandas as pd
import requests


CONCEPT_CACHE_DIR = "cache/concept"


def get_no_proxy_session() -> requests.Session:
    """
    创建一个不读取系统代理的 requests session。
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
            "Referer": "https://quote.eastmoney.com/center/boardlist.html",
        }
    )

    return session


def safe_get_json(url: str, params: dict, max_retry: int = 5, sleep_seconds: int = 2):
    """
    安全请求东方财富接口，失败自动重试。
    """

    last_error = None

    for i in range(max_retry):
        try:
            session = get_no_proxy_session()

            response = session.get(
                url,
                params=params,
                timeout=15,
                proxies={
                    "http": None,
                    "https": None,
                },
            )

            response.raise_for_status()

            data = response.json()

            if data and data.get("rc") == 0:
                return data

            last_error = data
            print(f"东方财富接口返回异常，第 {i + 1}/{max_retry} 次：{data}")

        except Exception as e:
            last_error = e
            print(f"东方财富接口请求失败，第 {i + 1}/{max_retry} 次：{e}")

        time.sleep(sleep_seconds)

    print(f"东方财富接口多次请求失败，最后一次错误：{last_error}")
    return None


def load_concept_name_df() -> pd.DataFrame:
    """
    获取东方财富概念题材列表。
    """

    url = "https://push2.eastmoney.com/api/qt/clist/get"

    params = {
        "pn": "1",
        "pz": "1000",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:3",
        "fields": "f12,f14,f3,f62",
    }

    print("正在获取东方财富概念题材列表...")

    data = safe_get_json(url, params)

    if not data:
        return pd.DataFrame(columns=["概念代码", "概念题材"])

    diff = data.get("data", {}).get("diff", [])

    if not diff:
        return pd.DataFrame(columns=["概念代码", "概念题材"])

    df = pd.DataFrame(diff)

    df = df.rename(
        columns={
            "f12": "概念代码",
            "f14": "概念题材",
            "f3": "涨跌幅",
            "f62": "主力净流入",
        }
    )

    df = df[["概念代码", "概念题材", "涨跌幅", "主力净流入"]]

    print(f"概念题材列表获取成功，共 {len(df)} 个题材。")

    return df


def load_single_concept_cons(concept_code: str, concept_name: str) -> pd.DataFrame:
    """
    获取单个东方财富概念题材成分股。
    """

    url = "https://push2.eastmoney.com/api/qt/clist/get"

    all_rows = []
    page = 1
    page_size = 100

    while True:
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": f"b:{concept_code}",
            "fields": "f12,f14,f2,f3,f5,f6,f20,f21",
        }

        data = safe_get_json(url, params, max_retry=3, sleep_seconds=5)

        if not data:
            break

        diff = data.get("data", {}).get("diff", [])
        total = data.get("data", {}).get("total", 0)

        if not diff:
            break

        all_rows.extend(diff)

        if page * page_size >= total:
            break

        page += 1
        time.sleep(1.5)

    if not all_rows:
        return pd.DataFrame(columns=["代码", "名称", "概念题材"])

    df = pd.DataFrame(all_rows)

    df = df.rename(
        columns={
            "f12": "代码",
            "f14": "名称",
            "f2": "最新价",
            "f3": "涨跌幅",
            "f5": "成交量",
            "f6": "成交额",
            "f20": "总市值",
            "f21": "流通市值",
        }
    )

    df["代码"] = df["代码"].astype(str).str.zfill(6)
    df["概念题材"] = concept_name

    return df[["代码", "名称", "概念题材"]]


def load_concept_map(use_cache: bool = True) -> pd.DataFrame:
    """
    获取东方财富概念题材成分股映射表。

    返回字段：
    代码、名称、概念题材
    """

    os.makedirs(CONCEPT_CACHE_DIR, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CONCEPT_CACHE_DIR, f"concept_map_{today}.csv")

    if use_cache and os.path.exists(cache_file):
        print(f"发现概念题材缓存：{cache_file}")
        concept_map = pd.read_csv(cache_file, dtype={"代码": str})
        concept_map["代码"] = concept_map["代码"].astype(str).str.zfill(6)
        return concept_map

    concept_name_df = load_concept_name_df()

    if concept_name_df.empty:
        print("概念题材列表为空，本次跳过题材共振分析。")
        return pd.DataFrame(columns=["代码", "名称", "概念题材"])

    all_list = []
    total = len(concept_name_df)

    temp_cache_file = os.path.join(CONCEPT_CACHE_DIR, f"concept_map_temp_{today}.csv")

    # 如果有临时缓存，先读出来，避免中断后从头开始
    if os.path.exists(temp_cache_file):
        print(f"发现临时概念缓存：{temp_cache_file}")
        temp_cache_df = pd.read_csv(temp_cache_file, dtype={"代码": str})
        temp_cache_df["代码"] = temp_cache_df["代码"].astype(str).str.zfill(6)
        all_list.append(temp_cache_df)

        fetched_concepts = set(temp_cache_df["概念题材"].dropna().unique().tolist())
    else:
        fetched_concepts = set()

    for idx, row in concept_name_df.iterrows():
        concept_code = row["概念代码"]
        concept_name = row["概念题材"]

        if concept_name in fetched_concepts:
            print(f"跳过已缓存题材 {idx + 1}/{total}：{concept_name}")
            continue

        print(f"正在获取概念题材 {idx + 1}/{total}：{concept_name} {concept_code}")

        try:
            cons_df = load_single_concept_cons(concept_code, concept_name)

            if cons_df is not None and not cons_df.empty:
                all_list.append(cons_df)
                fetched_concepts.add(concept_name)

                # 每成功一个题材就保存一次临时缓存
                temp_all_df = pd.concat(all_list, ignore_index=True)
                temp_all_df = temp_all_df.drop_duplicates(
                    subset=["代码", "概念题材"],
                    keep="first"
                )
                temp_all_df.to_csv(temp_cache_file, index=False, encoding="utf-8-sig")

                print(f"题材 {concept_name} 获取成功，已保存临时缓存。")

            # 放慢请求，避免被东方财富断开
            time.sleep(2)

        except Exception as e:
            print(f"概念题材 {concept_name} 获取失败，已跳过。错误：{e}")
            time.sleep(5)
            continue

    if not all_list:
        print("没有获取到任何概念成分股。")
        return pd.DataFrame(columns=["代码", "名称", "概念题材"])

    concept_map = pd.concat(all_list, ignore_index=True)

    concept_map = concept_map.drop_duplicates(
        subset=["代码", "概念题材"],
        keep="first"
    )

    concept_map.to_csv(cache_file, index=False, encoding="utf-8-sig")

    print(f"概念题材映射数量：{len(concept_map)}")
    print(f"概念题材缓存已保存：{cache_file}")

    return concept_map


def analyze_concept_resonance(signal_df: pd.DataFrame, min_count: int = 3):
    """
    对命中主升策略的股票进行东方财富概念题材共振分析。

    条件：
    同一概念题材下，当日命中股票数量 >= min_count，则标记为题材共振。

    返回：
    resonance_summary_df：题材共振汇总
    resonance_detail_df：题材共振明细
    stock_theme_map：每只股票对应的共振题材字典
    """

    if signal_df is None or signal_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    signal_df = signal_df.copy()
    signal_df["代码"] = signal_df["代码"].astype(str).str.zfill(6)

    hit_codes = set(signal_df["代码"].tolist())

    concept_map = load_concept_map(use_cache=True)

    if concept_map is None or concept_map.empty:
        print("概念题材数据为空，本次跳过题材共振分析。")
        return pd.DataFrame(), pd.DataFrame(), {}

    hit_concept_df = concept_map[concept_map["代码"].isin(hit_codes)].copy()

    if hit_concept_df.empty:
        print("命中股票没有匹配到东方财富概念题材。")
        return pd.DataFrame(), pd.DataFrame(), {}

    resonance_summary_df = (
        hit_concept_df
        .groupby("概念题材")
        .agg(
            命中数=("代码", "nunique"),
            命中股票=("名称", lambda x: "、".join(sorted(set(x))))
        )
        .reset_index()
    )

    resonance_summary_df = resonance_summary_df[
        resonance_summary_df["命中数"] >= min_count
    ].copy()

    if resonance_summary_df.empty:
        print("今日没有发现题材共振。")
        return pd.DataFrame(), pd.DataFrame(), {}

    resonance_summary_df = resonance_summary_df.sort_values(
        by="命中数",
        ascending=False
    )

    resonance_concepts = set(resonance_summary_df["概念题材"].tolist())

    resonance_detail_df = hit_concept_df[
        hit_concept_df["概念题材"].isin(resonance_concepts)
    ].copy()

    stock_theme_map = (
        resonance_detail_df
        .groupby("代码")["概念题材"]
        .apply(lambda x: "、".join(sorted(set(x))))
        .to_dict()
    )

    return resonance_summary_df, resonance_detail_df, stock_theme_map