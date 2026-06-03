# `cli/ml_grid_test.py` 使用说明

本文档适用于当前版本的 `cli/ml_grid_test.py`。这个脚本用于批量测试 ML 模板组合、训练参数和回测结果，支持两种方式：

1. 手动提供模板股票代码；
2. 自动从本地日线缓存 `cache/hist` 中选择强势股作为模板候选。

脚本的核心作用是：

> 批量训练多个 ML 形态模型，逐个回测，并统计哪组模板、训练参数、回测持有周期在历史上表现更好。

---

## 1. 脚本能做什么

`ml_grid_test.py` 会自动完成以下流程：

1. 获取模板股票代码；
2. 根据模板模式生成不同模板组合；
3. 遍历不同 `horizon` 和 `target` 参数；
4. 调用 `cli/ml_train.py` 训练模型并生成 `.pkl`；
5. 调用 `cli/ml_backtest.py` 对每个 `.pkl` 回测；
6. 读取每个回测 Excel；
7. 汇总所有组合的胜率、平均收益率、中位数收益率、盈亏比等；
8. 输出最优和最差组合；
9. 生成总汇总 Excel 和运行日志。

---

## 2. 当前脚本支持的两种模式

## 2.1 手动模板模式

你自己提供参考股票代码。

示例：

```bash
python cli/ml_grid_test.py --codes 603115,002980,600769 --threshold 0.80
```

这里的：

```text
603115,002980,600769
```

就是训练模板股。模型会学习这些股票历史上走出来的强势形态。

适合这种情况：

```text
我已经知道某几只股票走势很强；
我想用它们作为模板；
然后测试不同 horizon、target、hold-days 下的历史表现。
```

---

## 2.2 自动模板模式

脚本自己从本地日线缓存中筛选强势股作为模板。

示例：

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2
```

这个命令的意思是：

```text
从本地股票池里自动选择最近20个交易日最强的6只股票；
然后每次从这6只里取3只作为训练模板；
测试 horizon=2,3,4；
测试 target=6,7,8；
回测持有1,2,3天；
threshold=0.80；
用2个并发任务执行。
```

自动选模板股时，脚本默认读取：

```text
cache/hist
```

所以你需要确保这个目录下有日线级别的 CSV 数据。

---

## 3. 自动强势股选择逻辑

自动模板模式不是从 1100 多只股票中乱组合，而是先打分，再选前 N 只。

自动选股时，脚本会对每只股票计算一个“强势分”。

默认使用最近：

```text
--auto-lookback 20
```

也就是最近20个交易日。

### 3.1 强势分包含哪些条件

脚本会综合以下因素评分：

| 条件 | 含义 | 作用 |
|---|---|---|
| 近 N 日涨幅 | 最近 N 个交易日涨了多少 | 越高越强 |
| 距离近 N 日高点的回撤 | 当前价格距离近期高点回撤多少 | 回撤越小越好 |
| 近 N 日涨停次数 | 最近 N 日内涨停次数 | 涨停越多，活跃度越高 |
| 近5日量比 | 近5日均量 / 前20日均量 | 放量上涨更强 |
| 近 N 日振幅 | 最近 N 日波动幅度 | 有弹性的股票适当加分 |
| 阳线占比 | 收盘高于开盘的天数比例 | 阳线越多，趋势越健康 |
| 是否站上20日线 | 最新收盘是否在20日均线上方 | 站上20日线加分 |
| 是否接近60日新高 | 当前是否接近近60日高点 | 接近新高加分 |
| 近5日平均成交额 | 最近成交额大小 | 流动性越好越加分 |

### 3.2 强势评分的大致公式

脚本里的评分逻辑大致是：

```text
强势分 =
近N日涨幅 × 1.00
+ 当前距离高点回撤 × 0.60
+ 涨停次数 × 8.00
+ 放量程度 × 6.00
+ 振幅 × 0.10
+ 阳线占比 × 8.00
+ 站上20日线 × 5.00
+ 接近60日新高 × 5.00
+ 成交额加分
```

注意：

```text
强势分只是用来选择训练模板股，不是买入信号。
```

它的作用是先从 1100 多只股票中筛出最适合作为模板的强势股，避免直接全市场组合导致任务爆炸。

---

## 4. 重要参数说明

## 4.1 `--codes`

手动提供模板股票代码。

示例：

```bash
python cli/ml_grid_test.py --codes 603115,002980,600769
```

适合你已经知道参考股票的情况。

---

## 4.2 `--auto-codes`

自动选择模板股票。

示例：

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20
```

使用后，脚本会自动从本地日线缓存中筛选强势股。

---

## 4.3 `--auto-top-n`

自动选择多少只强势股。

示例：

```bash
--auto-top-n 6
```

表示自动选出强势分最高的6只股票。

建议：

```text
auto-top-n=5 或 6 比较合适；
不要一开始设太大。
```

原因是后面组合数量会快速增加。

例如使用：

```bash
--mode combination --combo-size 3
```

任务模板数量为：

```text
auto-top-n=5  -> C(5,3)=10组模板
auto-top-n=6  -> C(6,3)=20组模板
auto-top-n=8  -> C(8,3)=56组模板
auto-top-n=10 -> C(10,3)=120组模板
```

---

## 4.4 `--auto-lookback`

自动选强势股时回看多少个交易日。

示例：

```bash
--auto-lookback 20
```

意思是根据最近20个交易日的表现给股票打分。

常见选择：

| 参数 | 含义 | 适合场景 |
|---|---|---|
| `--auto-lookback 10` | 最近10日 | 偏短线强势 |
| `--auto-lookback 20` | 最近20日 | 默认推荐 |
| `--auto-lookback 30` | 最近30日 | 偏波段趋势 |

---

## 4.5 `--mode`

模板生成方式。

支持：

```text
permutation
combination
single
```

### `permutation`

全排列模式。

示例：

```bash
--mode permutation
```

如果你给3个股票：

```text
603115,002980,600769
```

会生成：

```text
603115,002980,600769
603115,600769,002980
002980,603115,600769
002980,600769,603115
600769,603115,002980
600769,002980,603115
```

3只股票会生成：

```text
3! = 6组模板
```

适合股票数量少时使用。

不建议对很多股票使用全排列。

---

### `combination`

组合模式。

示例：

```bash
--mode combination --combo-size 3
```

意思是从候选股票中每次取3只组合，不考虑顺序。

例如有6只股票，每次取3只：

```text
C(6,3)=20组模板
```

自动模板模式下最推荐这个模式。

---

### `single`

单股模式。

示例：

```bash
--mode single
```

意思是每只股票单独训练一个模型。

适合测试：

```text
哪一只股票最适合作为单独模板。
```

---

## 4.6 `--combo-size`

组合模式下每组取几只股票。

示例：

```bash
--mode combination --combo-size 3
```

意思是每次取3只股票作为模板。

推荐：

```text
combo-size=3
```

不建议太大，因为模板过多会增加训练耗时，而且不同类型股票混在一起容易让模型学习混乱。

---

## 4.7 `--horizons`

训练时的未来观察周期。

示例：

```bash
--horizons 2,3,4
```

或者：

```bash
--horizons 1-5
```

含义：

```text
horizon=3
```

表示模型训练时判断：

```text
某个形态出现后，未来3个交易日内是否达到目标涨幅。
```

常见理解：

| horizon | 含义 |
|---|---|
| 1 | 非常短线，偏次日冲高 |
| 2-3 | 短线强势，比较常用 |
| 4-5 | 小波段趋势 |

推荐先用：

```bash
--horizons 2,3,4
```

---

## 4.8 `--targets`

训练时的目标涨幅。

示例：

```bash
--targets 6,7,8
```

或者：

```bash
--targets 5-10
```

含义：

```text
target=8
```

表示训练时，把未来 horizon 天内能够上涨 8% 的样本视为“好样本”。

常见理解：

| target | 含义 |
|---|---|
| 5 | 要求低，信号多但可能质量一般 |
| 6-8 | 比较均衡 |
| 9-10 | 要求高，信号少，更偏强势股 |

推荐先用：

```bash
--targets 6,7,8
```

---

## 4.9 `--hold-days`

回测时实际持有天数。

示例：

```bash
--hold-days 1,2,3
```

含义：

```text
模型发出信号后，第二天买入，然后分别测试持有1天、2天、3天的收益。
```

注意：

```text
horizon 是训练参数；
hold-days 是回测统计参数；
二者不是一个东西。
```

推荐先用：

```bash
--hold-days 1,2,3
```

---

## 4.10 `--threshold`

ML 信号触发阈值。

示例：

```bash
--threshold 0.80
```

含义：

```text
只有 ML 分数 >= 0.80 的信号才参与回测。
```

一般：

| threshold | 特点 |
|---|---|
| 0.60 | 信号多，质量可能一般 |
| 0.65 | 较宽松 |
| 0.75 | 较均衡 |
| 0.80 | 较严格，信号少但质量可能更高 |

推荐初期使用：

```bash
--threshold 0.80
```

如果信号太少，可以降到：

```bash
--threshold 0.75
```

---

## 4.11 `--workers`

并发任务数。

示例：

```bash
--workers 2
```

意思是同时跑2组训练和回测任务。

建议：

```text
workers=1：最稳，但慢；
workers=2：推荐；
workers=3：电脑性能好可以尝试；
workers>3：不建议，容易卡顿或崩溃。
```

注意，每个任务内部都会：

```text
训练模型 + 回测1000多只股票 + 写Excel
```

所以不要把 workers 设太大。

---

## 4.12 `--max-runs`

限制最多跑多少组任务。

示例：

```bash
--max-runs 10
```

适合先测试脚本是否正常。

例如：

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --max-runs 10
```

只跑前10组任务。

---

## 4.13 `--dry-run`

只预览任务，不执行训练和回测。

示例：

```bash
--dry-run
```

加了这个参数后，脚本会：

```text
自动选模板股；
生成模板组合；
打印任务数量；
打印前10组任务预览；
然后退出。
```

不会：

```text
训练模型；
生成 pkl；
跑回测；
生成 backtest Excel。
```

适合正式运行前确认任务数量。

---

## 4.14 `--candidate-file`

指定候选股票文件。

示例：

```bash
--candidate-file output/a_stock_selected.xlsx
```

这个参数会传给回测脚本，也会用于自动模板模式的候选池。

---

## 4.15 `--use-selected-file`

使用默认选股文件。

通常对应：

```text
output/a_stock_selected.xlsx
```

注意：

```text
这个参数会影响回测股票池。
```

如果你只是想使用所有本地缓存股票回测，可以不加。

---

## 5. 推荐命令

## 5.1 手动模板，快速测试

```bash
python cli/ml_grid_test.py --codes 603115,002980,600769 --mode permutation --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --max-runs 10
```

---

## 5.2 手动模板，正式测试

```bash
python cli/ml_grid_test.py --codes 603115,002980,600769 --mode permutation --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2
```

---

## 5.3 自动模板，先 dry-run

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --dry-run
```

---

## 5.4 自动模板，小批量测试

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --max-runs 10
```

---

## 5.5 自动模板，正式测试

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2
```

---

## 5.6 自动模板，更宽松阈值

如果 `threshold=0.80` 信号太少，可以用：

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.75 --workers 2
```

---

## 6. 任务数量怎么计算

任务数量公式：

```text
总任务数 = 模板数量 × horizon数量 × target数量
```

如果使用自动模板：

```bash
--auto-top-n 6 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8
```

模板数量为：

```text
C(6,3)=20
```

horizon 数量：

```text
2,3,4 = 3个
```

target 数量：

```text
6,7,8 = 3个
```

所以总任务：

```text
20 × 3 × 3 = 180组训练 + 回测
```

---

## 7. 输出文件说明

默认输出目录：

```text
output/ml_grid_test/
```

会生成：

### 7.1 自动模板候选明细

自动模板模式会生成：

```text
auto_template_candidates_时间.xlsx
```

里面包含所有候选股票的强势评分。

重点字段：

```text
代码
强势分
近20日涨幅%
近20日回撤%
近20日振幅%
近20日涨停数
近5日量比
近5日均成交额
阳线占比
站上20日线
接近60日新高
最新收盘
数据行数
```

### 7.2 单组回测报告

每一组模型都会生成一个回测文件：

```text
backtest_0001_tpl_xxx_h2_t6p0.xlsx
```

### 7.3 总汇总报告

最终会生成：

```text
ml_grid_summary_时间.xlsx
```

重点看这些 sheet：

| Sheet | 含义 |
|---|---|
| 全部按持有期统计 | 所有模型、所有持有天数的统计结果 |
| 全部总体统计 | 每个模型总体表现 |
| 胜率最高TOP30 | 按胜率、平均收益、盈亏比等排序后的前30 |
| 表现最差TOP30 | 表现最差的前30 |
| 运行日志 | 每组任务是否完成、模型文件和回测文件 |

### 7.4 运行日志

还会生成：

```text
grid_run_时间.log
```

里面保存完整训练和回测输出。

---

## 8. 怎么看结果

不要只看胜率。

优先看这些指标：

```text
信号次数
胜率%
平均收益率%
中位数收益率%
盈亏比
最大亏损
```

### 8.1 推荐筛选标准

较理想的组合：

```text
信号次数 >= 20
胜率 >= 55%
平均收益率 > 0
中位数收益率 > 0
盈亏比 > 1.2
```

如果：

```text
胜率很高，但信号次数只有 2 或 3
```

参考价值不大。

如果：

```text
平均收益率为正，但中位数收益率为负
```

说明可能靠少数大涨票拉高，稳定性不够。

如果：

```text
盈亏比 < 1
```

说明赚的时候赚得少，亏的时候亏得多。

---

## 9. 找到最优模型后怎么用

假设汇总结果里某组表现较好：

```text
模板：603115,002980,600769
horizon：3
target：8
threshold：0.80
持有天数：2
```

对应模型文件是：

```text
output/ml_models/ml_pattern_603115_002980_600769_lb20_h3_t8p0_xxxxx.pkl
```

后续用 `ml_scan.py` 扫当前股票池：

```bash
python cli/ml_scan.py --model output/ml_models/ml_pattern_603115_002980_600769_lb20_h3_t8p0_xxxxx.pkl --threshold 0.80 --use-selected-file --workers 8
```

`ml_grid_test.py` 的作用是筛模型参数。

`ml_scan.py` 的作用才是用最优模型找当前候选股票。

---

## 10. 常见问题

## 10.1 `dry-run` 为什么没有生成 pkl？

因为 `--dry-run` 只预览，不执行训练和回测。

去掉 `--dry-run` 才会真正训练模型。

---

## 10.2 自动模板为什么有效数量为 0？

通常是日线缓存目录找不到，或者 CSV 字段名不匹配。

当前脚本默认读取：

```text
cache/hist
```

需要确保这个目录下有日线 CSV 文件。

---

## 10.3 为什么名称为空？

名称只是展示字段，不影响训练和回测。

模型和回测主要依赖股票代码。

---

## 10.4 为什么不用 1100 只股票全组合？

因为组合数量会爆炸。

例如从 1100 只股票中选 3 只：

```text
C(1100,3) 约等于 2.2 亿组
```

再乘以 horizon 和 target，会达到几十亿级任务，无法执行。

所以正确做法是：

```text
先自动选出最强的 5-10 只模板候选股；
再从里面组合训练和回测。
```

---

## 10.5 为什么并发不要开太高？

每个任务都会：

```text
训练模型
加载 pandas/sklearn/numpy
回测1000多只股票
写 Excel 文件
```

这是 CPU、内存、磁盘 IO 都比较重的任务。

建议：

```text
workers=2 最稳
workers=3 可尝试
workers>=4 不建议
```

---

## 10.6 为什么终端不是每只股票都显示进度？

脚本会隐藏高频进度行，避免刷屏。

目前逻辑是：

```text
日志文件完整保存；
终端只显示每100只左右的进度和关键结果。
```

完整输出在：

```text
output/ml_grid_test/grid_run_时间.log
```

---

## 11. 推荐使用流程

### 第一步：先 dry-run

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --dry-run
```

确认自动选出的模板股是否合理。

---

### 第二步：小批量跑 10 组

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2 --max-runs 10
```

确认流程正常。

---

### 第三步：正式跑完整自动测试

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2
```

---

### 第四步：查看结果

打开：

```text
output/ml_grid_test/ml_grid_summary_时间.xlsx
```

重点看：

```text
胜率最高TOP30
全部按持有期统计
运行日志
```

---

### 第五步：用最优 pkl 扫描当前股票

```bash
python cli/ml_scan.py --model output/ml_models/你的最优模型.pkl --threshold 0.80 --use-selected-file --workers 8
```

---

## 12. 一句话总结

```text
ml_grid_test.py 不是直接选明天买什么股票，
而是用历史数据帮你找出更可靠的 ML 模板组合和参数组合。
```

推荐默认实用配置：

```bash
python cli/ml_grid_test.py --auto-codes --auto-top-n 6 --auto-lookback 20 --mode combination --combo-size 3 --horizons 2,3,4 --targets 6,7,8 --hold-days 1,2,3 --threshold 0.80 --workers 2
```

找到最优模型后，再用 `ml_scan.py` 做当日扫描。
