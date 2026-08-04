# data_sources/__init__.py
"""
数据源抽象层。

支持通过配置切换 Baostock / Tushare，输出统一格式的分钟K线和指数数据。

配置项（config.py）：
    MINUTE_DATA_SOURCE = "baostock"   # 个股分钟数据源
    INDEX_DATA_SOURCE  = "baostock"   # 指数数据源
"""

from data_sources.base import (
    MinuteDataSource,
    IndexDataSource,
    UnifiedMinuteRow,
    UnifiedDailyRow,
)

from data_sources.baostock import BaoStockMinuteSource, BaoStockIndexSource
from data_sources.tushare import TushareMinuteSource, TushareIndexSource

# 根据配置创建默认实例
def get_minute_source() -> MinuteDataSource:
    """根据 config.MINUTE_DATA_SOURCE 返回分钟数据源实例。"""
    from config import MINUTE_DATA_SOURCE
    if MINUTE_DATA_SOURCE == "tushare":
        return TushareMinuteSource()
    return BaoStockMinuteSource()


def get_index_source() -> IndexDataSource:
    """根据 config.INDEX_DATA_SOURCE 返回指数数据源实例。"""
    from config import INDEX_DATA_SOURCE
    if INDEX_DATA_SOURCE == "tushare":
        return TushareIndexSource()
    return BaoStockIndexSource()
