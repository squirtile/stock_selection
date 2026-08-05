# data_sources/baostock.py
"""
BaoStock 数据源实现。

支持：
- 个股分钟K线 (5/15/30/60 分钟)
- 指数日线
- 不支持指数分钟线

代码格式：
- 个股: sz.000001 / sh.600000
- 指数: sh.000001 / sz.399001
"""

import os
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

import baostock as bs

from data_sources.base import (
    MinuteDataSource,
    IndexDataSource,
    minute_df_to_unified,
    daily_df_to_unified,
)

# 缓存目录
STOCK_MINUTE_DIR = "cache/minute"
INDEX_CACHE_DIR = "cache/index"
INDEX_DAILY_DIR = os.path.join(INDEX_CACHE_DIR, "daily")
INDEX_MINUTE_DIR = os.path.join(INDEX_CACHE_DIR, "minute")

# BaoStock 支持的分钟频率
BAOSTOCK_MINUTE_FREQS = {"5", "15", "30", "60"}


def _ensure_login():
    """确保 Baostock 已登录，复用会话。"""
    if not hasattr(_ensure_login, "_logged_in"):
        _ensure_login._logged_in = False

    if not _ensure_login._logged_in:
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")
        _ensure_login._logged_in = True


def _ensure_logout():
    """登出 Baostock。"""
    if hasattr(_ensure_login, "_logged_in") and _ensure_login._logged_in:
        try:
            bs.logout()
        except Exception:
            pass
        _ensure_login._logged_in = False


def _stock_code_to_bs(code: str) -> str:
    """6位股票代码 → BaoStock 格式 (sz.000001 / sh.600000)。"""
    code = str(code).zfill(6)
    if code.startswith(("6", "68")):
        return f"sh.{code}"
    return f"sz.{code}"


def _merge_bs_datetime(date_str: str, time_str: str) -> str:
    """
    BaoStock 的 date(YYYY-MM-DD) + time(YYYYMMDDHHMMSSfff) → YYYY-MM-DD HH:MM:SS。
    """
    if not time_str or time_str == "0":
        return date_str + " 00:00:00"
    # time 格式: 20260804093500000 → 取前14位
    t = str(time_str)[:14]
    if len(t) == 14:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]}"
    return date_str + " 00:00:00"


class BaoStockMinuteSource(MinuteDataSource):
    """BaoStock 个股分钟数据源。"""

    def name(self) -> str:
        return "baostock"

    def supports_frequency(self, frequency: str) -> bool:
        return str(frequency) in BAOSTOCK_MINUTE_FREQS

    def fetch_stock_minute(
        self, code: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        从 BaoStock 获取个股分钟K线，返回统一格式。

        内部自动处理：
        - date + time → datetime
        - 列名映射为中文统一格式
        - 成交量/成交额单位与 Tushare 统一
        """
        if not self.supports_frequency(frequency):
            raise ValueError(f"BaoStock 不支持 {frequency} 分钟周期，支持: {BAOSTOCK_MINUTE_FREQS}")

        _ensure_login()
        bs_code = _stock_code_to_bs(code)

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency=str(frequency),
            adjustflag="1",  # 前复权
        )

        if rs.error_code != "0":
            raise RuntimeError(f"BaoStock 查询失败: {rs.error_msg}")

        data = rs.get_data()
        if data.empty:
            return pd.DataFrame()

        # 合并 date + time → datetime
        data["datetime"] = data.apply(
            lambda r: _merge_bs_datetime(r["date"], r["time"]), axis=1
        )
        data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
        data = data.dropna(subset=["datetime"]).sort_values("datetime")

        # 数值列转换
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            data[col] = pd.to_numeric(data[col], errors="coerce")

        # 构建统一格式
        result = pd.DataFrame({
            "datetime": data["datetime"],
            "code": str(code).zfill(6),
            "open": data["open"],
            "high": data["high"],
            "low": data["low"],
            "close": data["close"],
            "volume": data["volume"],
            "amount": data["amount"],  # BaoStock amount 单位是元
        })

        # 去重
        result = result.drop_duplicates(subset=["datetime"], keep="last")
        result = result.sort_values("datetime").reset_index(drop=True)

        return minute_df_to_unified(result)


class BaoStockIndexSource(IndexDataSource):
    """BaoStock 指数数据源。只支持日线，不支持分钟线。"""

    def name(self) -> str:
        return "baostock"

    def supports_index_minute(self) -> bool:
        return False

    def _get_bs_code(self, index_key: str) -> str:
        """index_key → BaoStock 代码。"""
        info = self.INDEX_MAP.get(index_key)
        if not info:
            raise ValueError(f"不支持的指数: {index_key}")
        return info["baostock"]

    def fetch_index_daily(
        self, index_key: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取指数日线。"""
        _ensure_login()
        bs_code = self._get_bs_code(index_key)

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3",  # 指数不复权
        )

        if rs.error_code != "0":
            raise RuntimeError(f"BaoStock 指数查询失败: {rs.error_msg}")

        data = rs.get_data()
        if data.empty:
            return pd.DataFrame()

        for col in ["open", "high", "low", "close", "volume", "amount", "pctChg"]:
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors="coerce")

        result = pd.DataFrame({
            "date": pd.to_datetime(data["date"], errors="coerce"),
            "code": index_key,
            "open": data.get("open"),
            "high": data.get("high"),
            "low": data.get("low"),
            "close": data.get("close"),
            "volume": data.get("volume"),
            "amount": data.get("amount"),
            "pct_chg": data.get("pctChg", 0.0),
        })

        result = result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return daily_df_to_unified(result)

    def fetch_index_minute(
        self, index_key: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """BaoStock 不支持指数分钟线。"""
        raise NotImplementedError("BaoStock 不支持指数分钟数据，请使用 Tushare idx_mins 接口")
