# data_sources/tushare.py
"""
Tushare 数据源实现。

支持：
- 个股分钟K线 (stk_mins, 需单独权限)
- 指数日线 (index_daily)
- 指数分钟线 (idx_mins, 需单独权限)

注意：stk_mins 和 idx_mins 都需要在 Tushare 权限中心单独开通。
"""

import pandas as pd
from datetime import datetime

from data_sources.base import (
    MinuteDataSource,
    IndexDataSource,
    minute_df_to_unified,
    daily_df_to_unified,
)
from data_loader import get_tushare_pro, disable_proxy


def _get_pro():
    disable_proxy()
    return get_tushare_pro()


def _ts_code(code: str) -> str:
    """6位代码 → Tushare ts_code。"""
    code = str(code).zfill(6)
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"{code}.SH"
    return f"{code}.SZ"


class TushareMinuteSource(MinuteDataSource):
    """Tushare 个股分钟数据源（stk_mins）。"""

    def name(self) -> str:
        return "tushare"

    def supports_frequency(self, frequency: str) -> bool:
        return str(frequency) in {"1", "5", "15", "30", "60"}

    def fetch_stock_minute(
        self, code: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        从 Tushare stk_mins 获取个股分钟K线。

        需要单独开通 stk_mins 权限。
        """
        pro = _get_pro()
        freq = f"{frequency}min"

        # start_date/end_date 需转为 datetime 字符串
        start_dt = f"{start_date} 09:00:00"
        end_dt = f"{end_date} 15:00:00"

        df = pro.stk_mins(
            ts_code=_ts_code(code),
            asset="E",
            start_date=start_dt,
            end_date=end_dt,
            freq=freq,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # 自身完成归一化，避免依赖 minute_strategy
        code_str = str(code).zfill(6)
        df = df.copy()

        # 列名映射
        col_map = {
            "trade_time": "datetime",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if "datetime" not in df.columns:
            return pd.DataFrame()

        # 兼容 rt_min 返回 HH:MM:SS 的情况
        dt_text = df["datetime"].astype(str)
        only_time_mask = dt_text.str.match(r"^\d{2}:\d{2}:\d{2}$", na=False)
        if only_time_mask.any():
            today = datetime.now().strftime("%Y-%m-%d")
            dt_text.loc[only_time_mask] = today + " " + dt_text.loc[only_time_mask]

        df["datetime"] = pd.to_datetime(dt_text, errors="coerce")
        df = df.dropna(subset=["datetime"])
        df["code"] = code_str

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep_cols = ["datetime", "code", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]
        df = df.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
        df = df.reset_index(drop=True)

        return minute_df_to_unified(df)


class TushareIndexSource(IndexDataSource):
    """Tushare 指数数据源。"""

    def name(self) -> str:
        return "tushare"

    def supports_index_minute(self) -> bool:
        return True  # idx_mins 接口存在，但需权限

    def _get_ts_code(self, index_key: str) -> str:
        """index_key → Tushare ts_code。"""
        info = self.INDEX_MAP.get(index_key)
        if not info:
            raise ValueError(f"不支持的指数: {index_key}")
        return info["tushare"]

    def fetch_index_daily(
        self, index_key: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """获取指数日线（index_daily）。"""
        pro = _get_pro()
        ts_code = self._get_ts_code(index_key)

        df = pro.index_daily(
            ts_code=ts_code,
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )

        if df is None or df.empty:
            return pd.DataFrame()

        result = pd.DataFrame({
            "date": pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce"),
            "code": index_key,
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["vol"], errors="coerce"),
            "amount": pd.to_numeric(df["amount"], errors="coerce") * 1000,  # 千元→元
            "pct_chg": pd.to_numeric(df["pct_chg"], errors="coerce"),
        })

        result = result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return daily_df_to_unified(result)

    def fetch_index_minute(
        self, index_key: str, frequency: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指数分钟K线（idx_mins）。

        需要单独开通 idx_mins 权限。
        """
        pro = _get_pro()
        ts_code = self._get_ts_code(index_key)
        freq = f"{frequency}min"

        start_dt = f"{start_date} 09:00:00"
        end_dt = f"{end_date} 19:00:00"

        df = pro.idx_mins(
            ts_code=ts_code,
            freq=freq,
            start_date=start_dt,
            end_date=end_dt,
        )

        if df is None or df.empty:
            return pd.DataFrame()

        # idx_mins 输出: ts_code, trade_time, open, close, high, low, vol, amount
        df = df.rename(columns={
            "trade_time": "datetime",
            "vol": "volume",
        })
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df["code"] = index_key

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["datetime"]).sort_values("datetime")
        return minute_df_to_unified(df[["datetime", "code", "open", "high", "low", "close", "volume", "amount"]])
