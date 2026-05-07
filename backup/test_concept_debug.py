# test_concept_debug.py

import os
import requests


def disable_proxy_env():
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


disable_proxy_env()

url = "https://push2.eastmoney.com/api/qt/clist/get"

params = {
    "pn": "1",
    "pz": "20",
    "po": "1",
    "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2",
    "invt": "2",
    "fid": "f3",
    "fs": "m:90+t:3",
    "fields": "f12,f14,f3,f62",
}

headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/center/boardlist.html",
}

try:
    session = requests.Session()
    session.trust_env = False

    r = session.get(
        url,
        params=params,
        headers=headers,
        timeout=10,
        proxies={
            "http": None,
            "https": None,
        },
    )

    print("状态码：", r.status_code)
    print(r.text[:1000])

except Exception as e:
    print("请求失败：", e)