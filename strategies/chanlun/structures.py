# strategies/chanlun/structures.py
"""
缠论核心数据结构。

基于30分钟K线，定义笔(SBI)、线段(XD)、中枢(ZS)、趋势类型、买卖点。
命名沿用缠论原文习惯，括号内为拼音缩写。

数据结构层级：
  K线 → 包含处理 → 分型 → 笔(SBI) → 线段(XD) → 中枢(ZS) → 趋势 → 买卖点
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal


@dataclass
class Fractal:
    """顶/底分型"""
    index: int
    type: Literal["顶", "底"]  # 顶分型 / 底分型
    price: float               # 顶取最高价, 底取最低价
    time: object               # datetime
    high: float
    low: float


@dataclass
class Stroke:
    """
    笔 (SBI / Stroke)

    定义：连续顶底分型之间的连线，至少5根K线（不含包含关系后的K线）。
    方向：底→顶=向上笔(up)，顶→底=向下笔(down)。
    """

    index: int                  # 编号, 从0开始
    start_index: int            # 起始K线索引
    end_index: int              # 结束K线索引
    start_time: object
    end_time: object
    direction: Literal["up", "down"]
    start_price: float          # 底分型低点(up笔) / 顶分型高点(down笔)
    end_price: float
    high: float                 # 笔内最高价
    low: float                  # 笔内最低价
    bars: int                   # 包含的K线数
    macd_area: float = 0.0      # MACD面积(下跌笔取绿柱面积取绝对值，上涨笔取红柱面积)
    strength: float = 0.0       # 笔的力度 = 涨跌幅 / bars（标准化力度）


@dataclass
class Segment:
    """
    线段 (XD / Segment)

    定义：至少由3笔构成，第1笔和第3笔方向相同。
    线段是比笔更稳定的结构，用于确定更可靠的趋势。
    """

    index: int
    start_stroke_idx: int       # 起始笔编号
    end_stroke_idx: int         # 结束笔编号
    direction: Literal["up", "down"]
    start_price: float
    end_price: float
    high: float
    low: float
    strokes: List[Stroke] = field(default_factory=list)


@dataclass
class Pivot:
    """
    中枢 (ZS / Pivot)

    定义：连续3段线段的价格重叠区间。
    ZG = 中枢上沿 = min(线段高点)
    ZD = 中枢下沿 = max(线段低点)
    ZZ = 中枢中轴 = (ZG + ZD) / 2
    """

    index: int
    start_segment_idx: int      # 起始线段编号
    end_segment_idx: int        # 结束线段编号
    zg: float                   # 中枢上沿 (高点中最低)
    zd: float                   # 中枢下沿 (低点中最高)
    zz: float                   # 中枢中轴
    high: float                 # 中枢区间最高
    low: float                  # 中枢区间最低
    segments: List[Segment] = field(default_factory=list)


@dataclass
class TrendAnalysis:
    """
    趋势分析结果。

    基于30分钟线段和中枢，判断当前处于：
    - 上涨趋势 (UP): 至少2个同向中枢，中枢上移
    - 下跌趋势 (DOWN): 至少2个同向中枢，中枢下移
    - 盘整 (CONSOLIDATION): 只有一个中枢或中枢重叠
    """

    trend_type: Literal["up", "down", "consolidation"]
    pivot_count: int            # 同向中枢数量
    pivots: List[Pivot] = field(default_factory=list)
    description: str = ""


@dataclass
class BuyPoint:
    """
    缠论买卖点。

    一买(1B): 下跌趋势末端，底背驰后反转 → 左侧买点
    二买(2B): 一买反弹后回踩不创新低 → 确认买点
    三买(3B): 突破中枢后回踩不跌回中枢上沿 → 趋势跟随买点
    """

    type: Literal["1B", "2B", "3B"]
    index: int                  # K线索引位置
    time: object
    price: float
    pivot: Optional[Pivot] = None  # 相关中枢
    confidence: float = 0.0     # 置信度 0~1
    reason: str = ""


@dataclass
class SellPoint:
    """
    缠论卖点。

    一卖(1S): 上涨趋势末端，顶背驰后反转 → 左侧卖点
    二卖(2S): 一卖回落后反弹不创新高 → 确认卖点
    三卖(3S): 跌破中枢后反弹不站回中枢下沿 → 趋势跟随卖点
    """

    type: Literal["1S", "2S", "3S"]
    index: int                  # K线索引位置
    time: object
    price: float
    pivot: Optional[Pivot] = None  # 相关中枢
    confidence: float = 0.0     # 置信度 0~1
    reason: str = ""


# ── 缠论上下文 ────────────────────────────────────────────
@dataclass
class ChanlunContext:
    """
    一次完整的缠论分析上下文。

    从原始30分钟K线 → 分型 → 笔 → 线段 → 中枢 → 趋势 → 买卖点。
    """

    df_raw: object = None               # 原始DataFrame(含MA/MACD)
    df_no_include: object = None         # 包含处理后的DataFrame
    df_fractals: object = None           # 含分型标记的DataFrame
    strokes: List[Stroke] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)
    pivots: List[Pivot] = field(default_factory=list)
    trend: Optional[TrendAnalysis] = None
    buy_points: List[BuyPoint] = field(default_factory=list)
    sell_points: List[SellPoint] = field(default_factory=list)
