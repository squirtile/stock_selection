# strategies/chanlun/__init__.py
"""
缠论分析模块（30分钟级别）。

提供完整的缠论技术分析工具链：
  1. K线包含处理
  2. 分型识别
  3. 笔构建
  4. 线段构建
  5. 中枢识别
  6. 趋势分类
  7. 一买/二买/三买检测

用法：
  from strategies.chanlun import analyze, detect_all_buy_points, ChanlunContext

  ctx = analyze(df30)                      # 完整缠论分析
  ctx, buy_points = detect_all_buy_points(df30)  # 一键检测买卖点

  print(ctx.trend.trend_type)              # 当前趋势
  for bp in buy_points:
      print(bp.type, bp.price, bp.confidence)
"""

from .structures import (
    Fractal,
    Stroke,
    Segment,
    Pivot,
    TrendAnalysis,
    BuyPoint,
    ChanlunContext,
)

from .identify import (
    process_inclusion,
    find_fractals,
    build_strokes,
    build_segments,
    find_pivots,
    classify_trend,
    analyze,
)

from .buypoints import (
    detect_first_buy,
    detect_second_buy,
    detect_third_buy,
    detect_all_buy_points,
)

from .utils import (
    prepare_data,
    find_bottom_divergence,
    find_macd_golden_cross_divergence,
    calc_volume_profile,
)

__all__ = [
    # 数据结构
    "Fractal", "Stroke", "Segment", "Pivot",
    "TrendAnalysis", "BuyPoint", "ChanlunContext",
    # 识别引擎
    "process_inclusion", "find_fractals", "build_strokes",
    "build_segments", "find_pivots", "classify_trend", "analyze",
    # 买卖点
    "detect_first_buy", "detect_second_buy", "detect_third_buy",
    "detect_all_buy_points",
    # 工具
    "prepare_data", "find_bottom_divergence",
    "find_macd_golden_cross_divergence", "calc_volume_profile",
]
