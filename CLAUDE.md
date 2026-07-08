# Stock Selection Project

A股选股+策略扫描+回测系统。日线策略扫描 + 分钟B点确认 + 实时盘中监控。

## 项目结构

| 目录/文件 | 用途 |
|-----------|------|
| `main.py` | 入口：股票池筛选→日线信号→概念分析 |
| `strategy.py` | 日线策略引擎 (BaoStock K线, 指标计算, 策略检查) |
| `minute_strategy.py` | 分钟策略引擎 (Tushare, 5m/30m B点确认, 飞书推送) |
| `realtime_strategy.py` | 实时盘中扫描 |
| `strategies/` | 模块化策略包 (base/daily/minute/chanlun/registry) |
| `backtest/` | 日线回测 + 分钟回测 + 分钟数据预下载 |
| `config.py` | 全局配置 (Tushare token, 市值范围, 排除行业, 飞书URL) |
| `data_loader.py` | Tushare数据加载 |
| `filters.py` | 股票池过滤器 |
| `cache/hist/` | 1156只日线K线缓存 (BaoStock格式) |
| `cache/minute/` | 3468个分钟K线文件 (1m/5m/30m) |
| `output/` | 选股结果/回测报告/飞书推送记录 |
| `ml_engine/` | ML形态匹配引擎 |
| `cli/` | ML引擎命令行入口 |
| `similarity_selection.py` | 独立股票相似度筛选脚本 (统计画像法) |

## 常用命令

```bash
python main.py                              # 完整筛选流程
python backtest/backtest.py --hold-days 3   # 日线回测
python backtest/minute_backtest.py --hold-days 3 --minute-days 365  # 分钟回测
python realtime_strategy.py                 # 实时盘中扫描
```

## ML 形态匹配引擎

两条路：
- **路线A (推荐)**: 给1只股票+日期→找当前形态相似的股票→自动回测
- **路线B**: 给多只股票→训练ML模型→扫描→回测

### 路线A: 单股票形态匹配 (最常用)

```bash
python cli/ml_match.py --code 000009 --date-start 2024-03-01 --date-end 2024-03-20
```

### 路线A2: 多股票多时间段 → 生成pkl模型 🆕

```bash
# 最常用：朋友选的票 + 选股日期 → 自动生成策略pkl
python cli/ml_match_multi.py --codes 600288,000938,002350 --pick-date 2026-07-08 --lookback-days 20

# 完整流水线（训练+扫描+回测）
python cli/ml_match_multi.py --codes 600288,000938,002350 --pick-date 2026-07-08 --full-pipeline

# 每只票不同时间段
python cli/ml_match_multi.py --stocks "600288:2026-06-20:2026-07-08,000938:2026-06-15:2026-07-08"

# 输出到指定目录
python cli/ml_match_multi.py --codes 600288,000938,002350 --pick-date 2026-07-08 --output-dir 高胜率pkl
```

```python
from ml_engine.runner import match_single_stock_pattern
result = match_single_stock_pattern(
    template_code='000009', date_start='2024-03-01', date_end='2024-03-20',
    similarity_threshold=0.60, top_k=20, hold_days_list=[1,3,5,10],
)
```

### 路线B: ML模型流水线

```bash
python cli/ml_train.py --template 000009,000027 --full-pipeline  # 训练+扫描+回测
python cli/ml_similarity.py --template 000009,000027 --threshold 0.60 --top-k 50  # 只扫相似度
python cli/ml_backtest.py --model output/ml_models/ml_pattern_model.pkl --hold-days 3,5,10  # 只回测
```

**详细文档:** `ML引擎使用指南.md`

**核心模块:** `ml_engine/pattern_extract.py`(数据+窗口), `ml_engine/ml_classifier.py`(RandomForest), `ml_engine/similarity.py`(余弦/DTW), `ml_engine/runner.py`(流水线+单股匹配), `ml_engine/eval.py`(ML回测+相似度回测)

**关键参数:** 20天×14指标=280维, RandomForest 200棵树, 余弦相似度60%阈值, ML信号65%阈值

## 规则策略体系

6条日线策略: 箱体突破, 底部放量反转, V型反转, 主升-缩量回调启动, 主升-均线多头排列, 主升-大阳回调不破10日线

6条分钟策略: 5分钟回踩均线启动, 5分钟平台突破确认, 5分钟放量反包确认, 缠论二买B点, 缠论三买B点, 1分钟入场观察

## 技术栈

Python 3.10, pandas, numpy, scikit-learn, baostock, tushare, akshare, openpyxl, tabulate
