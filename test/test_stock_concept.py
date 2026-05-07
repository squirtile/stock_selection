# test_stock_concept.py

import os
import requests


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


def get_stock_raw_data(code: str):
    """
    测试东方财富个股信息接口原始返回。
    """

    code = str(code).zfill(6)
    market = get_market_prefix(code)

    url = "https://push2.eastmoney.com/api/qt/stock/get"

    params = {
        "secid": f"{market}.{code}",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fields": "f57,f58,f84,f85,f86,f100,f102,f103,f104,f105,f106,f111,f116,f117,f127,f128,f129,f130,f131,f132,f133,f134,f135,f136,f137,f138,f139,f140,f141,f142,f143,f144,f145,f146,f147,f148,f149,f150",
    }

    session = get_no_proxy_session()

    r = session.get(
        url,
        params=params,
        timeout=10,
        proxies={"http": None, "https": None},
    )

    print("状态码：", r.status_code)

    data = r.json()

    print("原始返回：")
    print(data)

    stock_data = data.get("data", {})

    print("\n字段列表：")
    for k, v in stock_data.items():
        print(k, "=", v)


if __name__ == "__main__":
    get_stock_raw_data("600736")