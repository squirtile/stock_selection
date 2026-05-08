# backtest/prefetch_minute_data.py
# 预下载过滤后股票池的 5分钟 / 30分钟 K线数据

import os
import sys
import time
import argparse
from datetime import datetime

import pandas as pd
import baostock as bs


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from minute_strategy import get_minute_data_baostock


BASE_POOL_FILE = os.path.join(PROJECT_ROOT, "output", "a_stock_selected.xlsx")


def load_base_pool() -> pd.DataFrame:
    """
    读取过滤后的基础股票池。
    """

    if not os.path.exists(BASE_POOL_FILE):
        raise FileNotFoundError(
            f"没有找到基础股票池文件：{BASE_POOL_FILE}\n"
            "请先运行 python main.py 生成基础股票池。"
        )

    df = pd.read_excel(BASE_POOL_FILE, dtype={"代码": str})
    df["代码"] = df["代码"].astype(str).str.zfill(6)

    return df


def prefetch_minute_data(
    minute_days: int = 365,
    max_stocks: int = 0,
    force_refresh: bool = False,
    sleep_seconds: float = 0.05,
):
    """
    预下载过滤后股票池的分钟K线。

    默认下载：
    1. 5分钟K线
    2. 30分钟K线
    """

    pool_df = load_base_pool()

    if max_stocks and max_stocks > 0:
        pool_df = pool_df.head(max_stocks).copy()

    total = len(pool_df)

    print(f"过滤后股票池数量：{total}")
    print(f"开始预下载分钟K线：最近 {minute_days} 个自然日")
    print(f"是否强制重新下载：{force_refresh}")
    print("下载周期：5分钟 + 30分钟")

    lg = bs.login()

    if lg.error_code != "0":
        print(f"BaoStock 登录失败：{lg.error_msg}")
        return

    start_time = time.time()
    success_count = 0
    fail_count = 0

    try:
        for idx, row in pool_df.iterrows():
            scan_no = idx + 1
            code = str(row["代码"]).zfill(6)
            name = row.get("名称", "")

            try:
                df5 = get_minute_data_baostock(
                    code=code,
                    frequency="5",
                    days=minute_days,
                    use_cache=not force_refresh,
                )

                df30 = get_minute_data_baostock(
                    code=code,
                    frequency="30",
                    days=minute_days,
                    use_cache=not force_refresh,
                )

                if df5 is not None and not df5.empty and df30 is not None and not df30.empty:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                fail_count += 1
                print(f"\n{code} {name} 分钟K线下载失败：{e}")

            elapsed = time.time() - start_time
            avg = elapsed / scan_no
            remain = avg * (total - scan_no)

            print(
                f"分钟K线预下载进度：{scan_no}/{total} | "
                f"当前：{code} {name} | "
                f"成功：{success_count} | "
                f"失败：{fail_count} | "
                f"累计耗时：{elapsed / 60:.2f} 分钟 | "
                f"预计剩余：{remain / 60:.2f} 分钟",
                end="\r",
                flush=True,
            )

            time.sleep(sleep_seconds)

        print()

    finally:
        bs.logout()

    total_seconds = time.time() - start_time

    print("\n分钟K线预下载完成。")
    print(f"股票数量：{total}")
    print(f"成功数量：{success_count}")
    print(f"失败数量：{fail_count}")
    print(f"总耗时：{total_seconds / 60:.2f} 分钟")


def main():
    parser = argparse.ArgumentParser(description="预下载过滤后股票池的分钟K线数据")

    parser.add_argument(
        "--minute-days",
        type=int,
        default=365,
        help="获取最近多少个自然日的分钟K线，默认365天。",
    )

    parser.add_argument(
        "--max-stocks",
        type=int,
        default=0,
        help="测试用：只下载前N只股票。默认0表示全部。",
    )

    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="强制重新下载，忽略本地已有分钟缓存。",
    )

    parser.add_argument(
        "--sleep",
        type=float,
        default=0.05,
        help="每只股票下载后的等待秒数，默认0.05。",
    )

    args = parser.parse_args()

    prefetch_minute_data(
        minute_days=args.minute_days,
        max_stocks=args.max_stocks,
        force_refresh=args.force_refresh,
        sleep_seconds=args.sleep,
    )


if __name__ == "__main__":
    main()