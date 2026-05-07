# filters.py

import pandas as pd
from config import MIN_MARKET_VALUE, MAX_MARKET_VALUE, EXCLUDE_INDUSTRIES


def is_main_board(code: str) -> bool:
    """
    判断是否为 A 股主板股票。

    主板常见代码：
    上海主板：600、601、603、605 开头
    深圳主板：000、001、002、003 开头

    排除：
    创业板：300、301
    科创板：688
    北交所：8、4 开头常见
    """
    code = str(code).zfill(6)

    main_board_prefixes = (
        "600", "601", "603", "605",
        "000", "001", "002", "003",
    )

    return code.startswith(main_board_prefixes)


def remove_st(df: pd.DataFrame) -> pd.DataFrame:
    """
    排除 ST、*ST 股票。
    """
    return df[~df["名称"].astype(str).str.contains("ST", case=False, na=False)]


def filter_market_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    按总市值筛选。
    AKShare 东方财富接口里的“总市值”通常单位是元。
    这里转换成亿元。
    """
    df = df.copy()

    df["总市值"] = pd.to_numeric(df["总市值"], errors="coerce")
    df["总市值_亿元"] = df["总市值"] / 100000000

    return df[
        (df["总市值_亿元"] >= MIN_MARKET_VALUE)
        & (df["总市值_亿元"] <= MAX_MARKET_VALUE)
    ]


def exclude_industries(df: pd.DataFrame) -> pd.DataFrame:
    """
    排除指定行业。
    如果没有行业字段，则直接返回原数据。
    """

    if "行业" not in df.columns:
        print("警告：当前数据没有【行业】字段，已跳过行业排除。")
        return df

    pattern = "|".join(EXCLUDE_INDUSTRIES)

    return df[
        ~df["行业"].fillna("").astype(str).str.contains(pattern, na=False)
    ]

def filter_price(df: pd.DataFrame) -> pd.DataFrame:
    """
    筛选股价小于 100 元的股票。
    """
    df = df.copy()

    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce")

    return df[df["最新价"] < 100]


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    综合筛选逻辑。
    """
    df = df.copy()

    # 1. 只保留主板
    df = df[df["代码"].apply(is_main_board)]

    # 2. 排除 ST
    df = remove_st(df)

    # 3. 市值 100-1500 亿
    df = filter_market_value(df)

    # 4. 价格小于 100 元
    df = filter_price(df)

    # 5. 排除行业
    df = exclude_industries(df)

    # 6. 排序：按总市值从小到大
    df = df.sort_values(by="总市值_亿元", ascending=True)

    return df