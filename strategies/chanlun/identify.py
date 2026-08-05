# strategies/chanlun/identify.py
"""
缠论结构识别引擎。

从30分钟K线 DataFrame 出发，依次完成：
  包含处理 → 分型识别 → 笔构建 → 线段构建 → 中枢识别 → 趋势分类

这是缠论分析的骨架，所有买卖点策略都依赖此模块的输出。
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

from .structures import (
    Fractal, Stroke, Segment, Pivot, TrendAnalysis, ChanlunContext,
)
from .utils import prepare_data


# ══════════════════════════════════════════════════════════════════
# 1. K线包含处理
# ══════════════════════════════════════════════════════════════════

def process_inclusion(df: pd.DataFrame) -> pd.DataFrame:
    """
    K线包含处理（缠论原文第65课）。

    规则：
    - 上升趋势中：高点取高，低点取高（向上合并）
    - 下降趋势中：高点取低，低点取低（向下合并）
    - 合并后的K线收盘价取被合并K线中后者

    方向判断：用前一根非包含K线的高点比较。
    """
    if df is None or len(df) < 2:
        return df.copy() if df is not None else pd.DataFrame()

    required_cols = ["最高", "最低", "开盘", "收盘"]
    for c in required_cols:
        if c not in df.columns:
            raise ValueError(f"缺少必需列: {c}")

    rows = []
    for _, row in df.iterrows():
        rows.append(row.to_dict())

    result = [rows[0]]
    direction = None  # None=未确定, 1=向上, -1=向下

    for i in range(1, len(rows)):
        cur = rows[i]
        prev = result[-1]

        # 判断是否包含
        is_include = (
            (cur["最高"] <= prev["最高"] and cur["最低"] >= prev["最低"])
            or (cur["最高"] >= prev["最高"] and cur["最低"] <= prev["最低"])
        )

        if not is_include:
            # 更新方向：用前一根非包含K线判断
            if len(result) >= 2:
                before = result[-2]
                direction = 1 if prev["最高"] > before["最高"] else -1
            else:
                direction = 1 if cur["收盘"] >= prev["收盘"] else -1
            result.append(cur)
            continue

        # 包含处理
        if direction is None:
            direction = 1 if cur["收盘"] >= prev["收盘"] else -1

        merged = prev.copy()

        if direction == 1:  # 向上：取高高
            merged["最高"] = max(prev["最高"], cur["最高"])
            merged["最低"] = max(prev["最低"], cur["最低"])
        else:  # 向下：取低低
            merged["最高"] = min(prev["最高"], cur["最高"])
            merged["最低"] = min(prev["最低"], cur["最低"])

        # 合并K线收盘价取后者
        merged["收盘"] = cur["收盘"]
        merged["开盘"] = prev["开盘"]
        merged["成交量"] = prev.get("成交量", 0) + cur.get("成交量", 0)
        merged["成交额"] = prev.get("成交额", 0) + cur.get("成交额", 0)
        merged["datetime"] = cur.get("datetime", prev.get("datetime"))

        result[-1] = merged

    return pd.DataFrame(result).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════
# 2. 分型识别
# ══════════════════════════════════════════════════════════════════

def find_fractals(df: pd.DataFrame) -> pd.DataFrame:
    """
    顶/底分型识别（缠论原文第62课）。

    顶分型：中间K线高点最高，低点最高（三根K线）
    底分型：中间K线低点最低，高点最低（三根K线）

    注意：这里在包含处理后的K线上找分型，每根K线代表一段小趋势。
    """
    data = df.copy().reset_index(drop=True)
    data["分型"] = ""
    data["分型价格"] = np.nan

    if len(data) < 3:
        return data

    for i in range(1, len(data) - 1):
        left = data.iloc[i - 1]
        mid = data.iloc[i]
        right = data.iloc[i + 1]

        # 顶分型
        is_top = (
            mid["最高"] > left["最高"]
            and mid["最高"] > right["最高"]
        )
        # 底分型
        is_bottom = (
            mid["最低"] < left["最低"]
            and mid["最低"] < right["最低"]
        )

        if is_top and not is_bottom:
            data.at[i, "分型"] = "顶"
            data.at[i, "分型价格"] = float(mid["最高"])
        elif is_bottom and not is_top:
            data.at[i, "分型"] = "底"
            data.at[i, "分型价格"] = float(mid["最低"])

    return data


# ══════════════════════════════════════════════════════════════════
# 3. 笔构建
# ══════════════════════════════════════════════════════════════════

def build_strokes(
    df: pd.DataFrame,
    min_bars_between_fractals: int = 3,
) -> List[Stroke]:
    """
    从分型构建笔（缠论原文第62-65课）。

    规则：
    1. 笔必须由一顶一底交替构成
    2. 相邻分型之间至少间隔 min_bars_between_fractals 根K线
    3. 连续同类分型，保留更极端的（顶取更高、底取更低）
    4. 笔内计算 MACD 面积用于后续力度比较

    Args:
        df: 含"分型"列的 DataFrame
        min_bars_between_fractals: 分型间最少K线数

    Returns:
        List[Stroke]: 按时间排序的笔列表
    """
    if df is None or df.empty or "分型" not in df.columns:
        return []

    # 提取分型
    fractals: list[dict] = []
    for i, row in df.iterrows():
        ftype = row.get("分型", "")
        if ftype not in {"顶", "底"}:
            continue
        price = row["最高"] if ftype == "顶" else row["最低"]
        fractals.append({
            "index": i,
            "type": ftype,
            "price": float(price),
            "time": row.get("datetime", i),
            "high": float(row.get("最高", price)),
            "low": float(row.get("最低", price)),
        })

    if len(fractals) < 2:
        return []

    # 去重：连续同类分型保留更极端的
    cleaned: list[dict] = [fractals[0]]
    for item in fractals[1:]:
        last = cleaned[-1]
        if item["type"] == last["type"]:
            # 同类：顶取更高，底取更低
            if item["type"] == "顶" and item["price"] > last["price"]:
                cleaned[-1] = item
            elif item["type"] == "底" and item["price"] < last["price"]:
                cleaned[-1] = item
        else:
            # 检查间隔
            if item["index"] - last["index"] >= min_bars_between_fractals:
                cleaned.append(item)

    if len(cleaned) < 2:
        return []

    # 构建笔
    strokes: List[Stroke] = []
    stroke_idx = 0

    for j in range(len(cleaned) - 1):
        prev = cleaned[j]
        cur = cleaned[j + 1]

        if prev["type"] == "底" and cur["type"] == "顶":
            direction = "up"
        elif prev["type"] == "顶" and cur["type"] == "底":
            direction = "down"
        else:
            continue

        start_i = int(prev["index"])
        end_i = int(cur["index"])
        segment_df = df.iloc[min(start_i, end_i):max(start_i, end_i) + 1]

        # MACD面积
        macd_area = 0.0
        if "MACD" in segment_df.columns:
            macd_vals = segment_df["MACD"]
            if direction == "down":
                macd_area = float(macd_vals.clip(upper=0).abs().sum())
            else:
                macd_area = float(macd_vals.clip(lower=0).sum())

        # 力度
        bars = len(segment_df)
        price_change = abs(cur["price"] - prev["price"])
        strength = price_change / bars if bars > 0 else 0.0

        strokes.append(Stroke(
            index=stroke_idx,
            start_index=start_i,
            end_index=end_i,
            start_time=prev["time"],
            end_time=cur["time"],
            direction=direction,
            start_price=float(prev["price"]),
            end_price=float(cur["price"]),
            high=float(segment_df["最高"].max()),
            low=float(segment_df["最低"].min()),
            bars=bars,
            macd_area=macd_area,
            strength=round(strength, 6),
        ))
        stroke_idx += 1

    return strokes


# ══════════════════════════════════════════════════════════════════
# 4. 线段构建
# ══════════════════════════════════════════════════════════════════

def build_segments(
    strokes: List[Stroke],
    min_strokes_per_segment: int = 3,
) -> List[Segment]:
    """
    从笔构建线段（缠论原文第65-70课）。

    线段是更高一级的结构，至少由3笔组成。
    线段的起点和终点必须是最高/最低点。

    简化规则：
    - 取连续3笔 → 若第1和第3笔方向相同 → 构成线段
    - 线段端点取该段内极值点

    Args:
        strokes: 笔列表
        min_strokes_per_segment: 最少笔数

    Returns:
        List[Segment]: 线段列表
    """
    if len(strokes) < min_strokes_per_segment:
        return []

    segments: List[Segment] = []
    seg_idx = 0

    # 滑动窗口：每次取 min_strokes_per_segment 笔
    for i in range(len(strokes) - min_strokes_per_segment + 1):
        group = strokes[i:i + min_strokes_per_segment]

        # 第1笔和第3笔方向相同 → 构成线段
        if group[0].direction == group[2].direction:
            direction = group[0].direction
            all_strokes = strokes[group[0].index:group[-1].index + 1]

            segments.append(Segment(
                index=seg_idx,
                start_stroke_idx=group[0].index,
                end_stroke_idx=group[-1].index,
                direction=direction,
                start_price=group[0].start_price,
                end_price=group[-1].end_price,
                high=max(s.high for s in all_strokes),
                low=min(s.low for s in all_strokes),
                strokes=list(all_strokes),
            ))
            seg_idx += 1

    return segments


# ══════════════════════════════════════════════════════════════════
# 5. 中枢识别
# ══════════════════════════════════════════════════════════════════

def find_pivots(
    segments: List[Segment],
    min_segments_per_pivot: int = 3,
) -> List[Pivot]:
    """
    从线段识别中枢（缠论原文第83-92课）。

    中枢定义：连续3段线段的价格重叠区间。
    ZG（中枢上沿）= min(重叠线段的高点)
    ZD（中枢下沿）= max(重叠线段的低点)

    ZG > ZD 才构成有效中枢（有重叠区间）。

    Returns:
        List[Pivot]: 按时间排序的中枢列表
    """
    if len(segments) < min_segments_per_pivot:
        return []

    pivots: List[Pivot] = []
    pivot_idx = 0

    for i in range(len(segments) - min_segments_per_pivot + 1):
        group = segments[i:i + min_segments_per_pivot]

        zg = min(s.high for s in group)  # 中枢上沿
        zd = max(s.low for s in group)   # 中枢下沿

        if zg <= zd:
            continue  # 无重叠区间，不构成中枢

        pivots.append(Pivot(
            index=pivot_idx,
            start_segment_idx=group[0].index,
            end_segment_idx=group[-1].index,
            zg=round(zg, 4),
            zd=round(zd, 4),
            zz=round((zg + zd) / 2, 4),
            high=max(s.high for s in group),
            low=min(s.low for s in group),
            segments=list(group),
        ))
        pivot_idx += 1

    return pivots


# ══════════════════════════════════════════════════════════════════
# 6. 趋势分类
# ══════════════════════════════════════════════════════════════════

def classify_trend(
    pivots: List[Pivot],
    latest_price: float,
) -> TrendAnalysis:
    """
    趋势分类。

    基于中枢位置和数量判断30分钟级别趋势：
    - 上涨趋势：至少2个中枢，中枢 ZG 逐步上移
    - 下跌趋势：至少2个中枢，中枢 ZD 逐步下移
    - 盘整：1个中枢或无中枢，或中枢重叠

    Args:
        pivots: 中枢列表
        latest_price: 最新价格

    Returns:
        TrendAnalysis
    """
    if not pivots:
        return TrendAnalysis(
            trend_type="consolidation",
            pivot_count=0,
            description="无中枢，暂无法判断趋势"
        )

    if len(pivots) == 1:
        p = pivots[-1]
        if latest_price > p.zg:
            return TrendAnalysis(
                trend_type="up",
                pivot_count=1,
                pivots=[p],
                description=f"单中枢上方运行，偏多"
            )
        elif latest_price < p.zd:
            return TrendAnalysis(
                trend_type="down",
                pivot_count=1,
                pivots=[p],
                description=f"单中枢下方运行，偏空"
            )
        else:
            return TrendAnalysis(
                trend_type="consolidation",
                pivot_count=1,
                pivots=[p],
                description=f"中枢内震荡，盘整"
            )

    # 多中枢：取最近2个比较
    p1 = pivots[-2]  # 较早
    p2 = pivots[-1]  # 较新

    if p2.zg > p1.zg and p2.zd > p1.zd:
        trend = "up"
        desc = f"2个中枢上移(ZG:{p1.zg:.1f}→{p2.zg:.1f})，上涨趋势"
    elif p2.zg < p1.zg and p2.zd < p1.zd:
        trend = "down"
        desc = f"2个中枢下移(ZD:{p1.zd:.1f}→{p2.zd:.1f})，下跌趋势"
    else:
        trend = "consolidation"
        desc = f"中枢重叠/无明确方向，盘整"

    return TrendAnalysis(
        trend_type=trend,
        pivot_count=len(pivots),
        pivots=[p1, p2],
        description=desc,
    )


# ══════════════════════════════════════════════════════════════════
# 7. 一键分析
# ══════════════════════════════════════════════════════════════════

def analyze(
    df: pd.DataFrame,
    min_strokes_per_segment: int = 3,
    min_segments_per_pivot: int = 3,
) -> ChanlunContext:
    """
    一键缠论分析：从原始K线到完整缠论上下文。

    Args:
        df: 30分钟K线 DataFrame (含 开盘/最高/最低/收盘/成交量/成交额)
        min_strokes_per_segment: 构成线段的最少笔数
        min_segments_per_pivot: 构成中枢的最少线段数

    Returns:
        ChanlunContext: 包含分型/笔/线段/中枢/趋势的完整上下文
    """
    raw = prepare_data(df)

    if raw is None or len(raw) < 5:
        return ChanlunContext(df_raw=raw)

    # 1. 包含处理
    no_include = process_inclusion(raw)

    # 2. 重新计算指标（包含处理后K线数变了）
    no_include = prepare_data(no_include)

    # 3. 分型
    fractal_df = find_fractals(no_include)

    # 4. 笔
    strokes = build_strokes(fractal_df)

    # 5. 线段
    segments = build_segments(strokes, min_strokes_per_segment)

    # 6. 中枢
    pivots = find_pivots(segments, min_segments_per_pivot)

    # 7. 趋势
    latest_price = float(raw["收盘"].iloc[-1]) if len(raw) > 0 else 0.0
    trend = classify_trend(pivots, latest_price)

    return ChanlunContext(
        df_raw=raw,
        df_no_include=no_include,
        df_fractals=fractal_df,
        strokes=strokes,
        segments=segments,
        pivots=pivots,
        trend=trend,
    )
