# data_loader.py

import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
import tushare as ts

from config import TUSHARE_TOKEN, TUSHARE_HTTP_URL


def disable_proxy():
    """
    强制禁用系统代理，避免本地代理影响 Tushare/东方财富接口访问。
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


def get_tushare_pro():
    """
    初始化 Tushare Pro。
    支持官方 Token + 第三方代理地址。
    """

    token = os.getenv("TUSHARE_TOKEN", TUSHARE_TOKEN)
    http_url = os.getenv("TUSHARE_HTTP_URL", TUSHARE_HTTP_URL)

    if not token or token == "这里填你的token":
        raise ValueError(
            "没有配置 Tushare Token。请在 config.py 里填写 TUSHARE_TOKEN，"
            "或者在 PowerShell 中设置环境变量：$env:TUSHARE_TOKEN='你的token'"
        )

    disable_proxy()

    pro = ts.pro_api(token)

    if http_url:
        pro._DataApi__http_url = http_url

    return pro


def call_with_retry(func, *args, max_retry: int = 5, sleep_seconds: int = 3, **kwargs) -> pd.DataFrame:
    """
    Tushare 接口安全调用，失败自动重试。

    支持把 exchange/list_status/fields 等参数继续传给 Tushare 接口。
    也兼容 functools.partial，因为 partial 对象没有 __name__ 属性。
    """

    func_name = getattr(func, "__name__", None)

    if func_name is None and hasattr(func, "func"):
        func_name = getattr(func.func, "__name__", "tushare_api")

    if func_name is None:
        func_name = "tushare_api"

    last_error = None

    for i in range(max_retry):
        try:
            print(f"正在请求 {func_name}，第 {i + 1}/{max_retry} 次尝试...")
            df = func(*args, **kwargs)

            if df is not None and not df.empty:
                print(f"{func_name} 请求成功，数据量：{len(df)}")
                return df

            print(f"{func_name} 返回为空。")

        except Exception as e:
            last_error = e
            print(f"{func_name} 请求失败，第 {i + 1}/{max_retry} 次：{e}")

        time.sleep(sleep_seconds)

    if last_error:
        raise last_error

    return pd.DataFrame()


def find_latest_daily_basic(pro, max_back_days: int = 15) -> pd.DataFrame:
    """
    获取最近一个有 daily_basic 数据的交易日。
    注意：当天未收盘、周末、节假日时，当日可能为空，所以向前回溯。
    """

    fields = (
        "ts_code,trade_date,close,turnover_rate,volume_ratio,"
        "pe,pb,total_mv,circ_mv"
    )

    today = datetime.now()

    for i in range(max_back_days):
        trade_date = (today - timedelta(days=i)).strftime("%Y%m%d")
        print(f"正在尝试获取 daily_basic：{trade_date}")

        df = pro.daily_basic(trade_date=trade_date, fields=fields)

        if df is not None and not df.empty:
            print(f"daily_basic 获取成功，交易日：{trade_date}，数量：{len(df)}")
            return df

        time.sleep(0.3)

    raise ValueError("最近多日都没有获取到 daily_basic 数据，请检查 Token、代理地址或交易日。")


def find_latest_daily_quote(pro, trade_date: str) -> pd.DataFrame:
    """
    获取指定交易日的日行情，用于补充涨跌幅、成交额等字段。
    Tushare daily 中 amount 单位通常为千元，这里后续会转换为元。
    """

    fields = "ts_code,trade_date,open,high,low,close,vol,amount,pct_chg"

    df = pro.daily(trade_date=trade_date, fields=fields)

    if df is None or df.empty:
        print(f"警告：{trade_date} daily 行情为空，将只使用 daily_basic 字段。")
        return pd.DataFrame()

    print(f"daily 行情获取成功，交易日：{trade_date}，数量：{len(df)}")
    return df


def load_stock_basic(pro) -> pd.DataFrame:
    """
    获取上市 A 股基础信息。
    """

    fields = "ts_code,symbol,name,area,industry,market,list_date"

    df = call_with_retry(
        pro.stock_basic,
        exchange="",
        list_status="L",
        fields=fields,
    )

    print(f"stock_basic 获取成功，数量：{len(df)}")
    return df


def load_a_stock_spot() -> pd.DataFrame:
    """
    使用 Tushare 获取 A 股基础股票池所需字段。

    输出字段尽量兼容原来的 AKShare 版本：
    代码、名称、最新价、涨跌幅、成交额、总市值、流通市值、行业、量比
    """

    pro = get_tushare_pro()

    print("正在使用 Tushare 获取 A 股基础数据...")

    basic_df = load_stock_basic(pro)
    daily_basic_df = find_latest_daily_basic(pro)

    latest_trade_date = str(daily_basic_df["trade_date"].iloc[0])
    daily_df = find_latest_daily_quote(pro, latest_trade_date)

    # 合并：基础信息 + 市值估值数据
    df = basic_df.merge(daily_basic_df, on="ts_code", how="inner")

    # 合并：日行情数据，补充涨跌幅和成交额
    if daily_df is not None and not daily_df.empty:
        quote_cols = ["ts_code", "pct_chg", "amount"]
        quote_cols = [col for col in quote_cols if col in daily_df.columns]
        df = df.merge(daily_df[quote_cols], on="ts_code", how="left")
    else:
        df["pct_chg"] = pd.NA
        df["amount"] = pd.NA

    result = pd.DataFrame()

    result["代码"] = df["symbol"].astype(str).str.zfill(6)
    result["名称"] = df["name"]
    result["地区"] = df.get("area")
    result["行业"] = df.get("industry")
    result["市场"] = df.get("market")
    result["上市日期"] = df.get("list_date")
    result["交易日"] = latest_trade_date

    # daily_basic 的 close 一般就是最新收盘价
    result["最新价"] = pd.to_numeric(df.get("close"), errors="coerce")
    result["涨跌幅"] = pd.to_numeric(df.get("pct_chg"), errors="coerce")

    # Tushare daily amount 单位通常是千元，转成元，兼容原 filters/main 的换算逻辑
    result["成交额"] = pd.to_numeric(df.get("amount"), errors="coerce") * 1000

    # Tushare daily_basic total_mv/circ_mv 单位通常是万元，转成元，兼容原 filters.py
    result["总市值"] = pd.to_numeric(df.get("total_mv"), errors="coerce") * 10000
    result["流通市值"] = pd.to_numeric(df.get("circ_mv"), errors="coerce") * 10000

    result["总市值_亿元"] = result["总市值"] / 100000000
    result["流通市值_亿元"] = result["流通市值"] / 100000000

    result["量比"] = pd.to_numeric(df.get("volume_ratio"), errors="coerce")
    result["市盈率"] = pd.to_numeric(df.get("pe"), errors="coerce")
    result["市净率"] = pd.to_numeric(df.get("pb"), errors="coerce")

    print("Tushare 数据整理完成。")
    print("当前字段：")
    print(result.columns.tolist())
    print(f"原始合并后股票数量：{len(result)}")

    os.makedirs("cache", exist_ok=True)
    cache_file = f"cache/tushare_a_stock_spot_{latest_trade_date}.csv"
    result.to_csv(cache_file, index=False, encoding="utf-8-sig")
    print(f"Tushare 原始数据缓存已保存：{cache_file}")

    return result
