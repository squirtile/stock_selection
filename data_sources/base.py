# data_sources/base.py
"""
数据源抽象基类。

所有数据源实现必须遵循此接口，确保输出格式统一，上层调用无需关心底层是 Baostock 还是 Tushare。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd


@dataclass
class UnifiedMinuteRow:
    """统一分钟K线行格式。"""
    datetime: str       # YYYY-MM-DD HH:MM:SS
    code: str           # 6位股票代码 或 指数代码(SH000001)
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float       # 成交额（元）


@dataclass
class UnifiedDailyRow:
    """统一日线行格式。"""
    date: str           # YYYY-MM-DD
    code: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float       # 成交额（元）
    pct_chg: Optional[float] = None  # 涨跌幅(%), 指数有, 个股可能没有


# 统一输出列名（与现有 minute_strategy.py 的 normalize_stk_mins_df 保持一致）
MINUTE_COLUMNS = ["datetime", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "代码"]
DAILY_COLUMNS = ["date", "开盘", "最高", "最低", "收盘", "成交量", "成交额", "代码", "涨跌幅"]


def minute_df_to_unified(df: pd.DataFrame) -> pd.DataFrame:
    """将统一格式的分钟 DataFrame 标准化列名。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=MINUTE_COLUMNS)
    df = df.copy()
    # 确保列名统一
    col_map = {
        "datetime": "datetime", "code": "代码", "open": "开盘", "high": "最高",
        "low": "最低", "close": "收盘", "volume": "成交量", "amount": "成交额",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    for col in MINUTE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[MINUTE_COLUMNS]


def daily_df_to_unified(df: pd.DataFrame) -> pd.DataFrame:
    """将统一格式的日线 DataFrame 标准化列名。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    df = df.copy()
    col_map = {
        "date": "date", "code": "代码", "open": "开盘", "high": "最高",
        "low": "最低", "close": "收盘", "volume": "成交量", "amount": "成交额",
        "pct_chg": "涨跌幅",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    for col in DAILY_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df[DAILY_COLUMNS]


class MinuteDataSource(ABC):
    """个股分钟数据源抽象基类。"""

    @abstractmethod
    def fetch_stock_minute(
        self, code: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取单只股票分钟K线。

        Args:
            code: 6位股票代码, e.g. "000001"
            frequency: "5" | "30" | "60"
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            DataFrame with columns: datetime, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 代码
        """
        ...

    @abstractmethod
    def supports_frequency(self, frequency: str) -> bool:
        """检查是否支持指定分钟周期。"""
        ...

    @abstractmethod
    def name(self) -> str:
        """数据源名称，用于日志。"""
        ...


class IndexDataSource(ABC):
    """指数数据源抽象基类。"""

    # 四大指数定义
    INDEX_MAP = {
        "SH000001": {"name": "上证指数", "baostock": "sh.000001", "tushare": "000001.SH"},
        "SZ399001": {"name": "深证成指", "baostock": "sz.399001", "tushare": "399001.SZ"},
        "SZ399006": {"name": "创业板指", "baostock": "sz.399006", "tushare": "399006.SZ"},
        "SH000688": {"name": "科创50", "baostock": "sh.000688", "tushare": "000688.SH"},
    }

    @abstractmethod
    def fetch_index_daily(
        self, index_key: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指数日线。

        Args:
            index_key: "SH000001" | "SZ399001" | "SZ399006" | "SH000688"
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            DataFrame with columns: date, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 代码, 涨跌幅
        """
        ...

    @abstractmethod
    def fetch_index_minute(
        self, index_key: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指数分钟K线。

        Returns:
            DataFrame with columns: datetime, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 代码
        """
        ...

    @abstractmethod
    def supports_index_minute(self) -> bool:
        """是否支持指数分钟数据。"""
        ...

    @abstractmethod
    def name(self) -> str:
        """数据源名称。"""
        ...
