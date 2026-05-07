# config.py

# 市值范围，单位：亿元
MIN_MARKET_VALUE = 100
MAX_MARKET_VALUE = 1500

# 排除行业关键词
EXCLUDE_INDUSTRIES = [
    "银行",
    "证券",
    "券商",
    "保险",
    "信托",
    "房地产",
    "钢铁",
    "煤炭",
    "煤炭开采",
    "铁路运输",
    "航运",
]

# 导出路径
OUTPUT_FILE = "output/a_stock_selected.xlsx"