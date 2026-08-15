<h1 align="center">A股股票筛选与实时策略扫描工具</h1>

<p align="center">
  一个基于 Python 的 A 股主板股票筛选、日线主升信号扫描、盘中实时扫描、分钟级 B 点确认和盘后分钟缓存校准工程。
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/Sust2014/stock_selection?style=social" />
  <img src="https://img.shields.io/github/forks/Sust2014/stock_selection?style=social" />
  <img src="https://img.shields.io/github/issues/Sust2014/stock_selection" />
  <img src="https://img.shields.io/github/license/Sust2014/stock_selection" />
</p>

---

## ⚠️ 免责声明

本项目仅用于个人学习、数据分析和量化策略研究，不构成任何投资建议，不保证收益，不作为任何买卖依据。股市有风险，投资需谨慎。

---

## 一、项目简介

本项目用于对 A 股主板股票进行多层筛选和策略扫描。整体流程分为四层：

```text
基础股票池筛选
↓
日线主升 / 突破反转策略筛选
↓
盘中实时行情动态日K扫描
↓
分钟级B点确认：30分钟趋势 + 5分钟结构 / 缠论B点 + 可选1分钟精确买点
```

当前版本已经支持：

- 基础股票池筛选：只保留 A 股主板，排除创业板、科创板、北交所、ST 等股票；
- 市值与行业过滤：默认保留 100 亿至 1500 亿市值，排除银行、证券、保险、地产、钢铁、煤炭、航运等行业；
- 日线策略：箱体突破、底部放量反转、主升箱体突破、主升底部放量反转、缩量回调启动、均线多头排列；
- 盘中实时扫描：使用实时行情拼接动态日K，判断盘中是否触发日线策略；
- 分钟级B点：使用 30分钟确认趋势，5分钟确认结构和缠论买点；
- 1分钟精确买点：默认关闭，需要时通过参数开启；
- 分钟数据缓存：本地保存最近 N 天 1m / 5m / 30m 分钟K线；
- 盘后校准：盘后可用 `stk_mins` 强制覆盖刷新分钟缓存；
- 并发加速：实时行情获取和分钟级B点确认均支持多线程；
- 结果导出：支持 Excel 输出，包含实时增量结果、分钟B点结果、盘后校准明细等。

---

## 二、运行环境

建议环境：

```text
Python 3.9+
Windows / Linux / macOS
```

依赖安装：

```bash
pip install -r requirements.txt
```

如果下载速度较慢，可以使用清华源：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

当前主要依赖：

```text
tushare
akshare
pandas
openpyxl
tabulate
baostock
wcwidth
```

---

## 三、Tushare 配置

项目在 `config.py` 中配置 Tushare：

```python
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "这里填你的token")
TUSHARE_HTTP_URL = os.getenv("TUSHARE_HTTP_URL", "你的代理地址")
```

推荐使用环境变量，避免把 Token 上传到 GitHub：

### PowerShell

```powershell
$env:TUSHARE_TOKEN="你的token"
$env:TUSHARE_HTTP_URL="你的代理地址"
```

### CMD

```cmd
set TUSHARE_TOKEN=你的token
set TUSHARE_HTTP_URL=你的代理地址
```

### Linux / macOS

```bash
export TUSHARE_TOKEN="你的token"
export TUSHARE_HTTP_URL="你的代理地址"
```

---

## 四、基础筛选规则

基础股票池由 `main.py` 生成，默认规则如下。

| 条件 | 当前规则 |
|---|---|
| 市场范围 | 只保留 A 股主板 |
| 保留代码 | 上海主板 600、601、603、605；深圳主板 000、001、002、003 |
| 排除板块 | 创业板、科创板、北交所 |
| 排除股票 | ST、*ST |
| 市值范围 | 100 亿至 1500 亿 |
| 价格限制 | 最新价小于 100 元 |
| 排除行业 | 银行、证券、券商、保险、信托、房地产、地产、钢铁、煤炭、铁路运输、航运、水运、港口等 |

基础筛选结果默认保存到：

```text
output/a_stock_selected.xlsx
```

---

## 五、日线策略说明

当前日线策略已经模块化到 `strategies/daily_strategies.py`，注册入口在 `strategies/registry.py`。

### 1. 箱体突破

用于寻找前期横盘整理后放量突破的股票。

```text
1. 今日收盘价 > 过去60个交易日最高价，不含今日
2. 今日成交量 > 过去20日均量 × 1.3
3. 过去20个交易日K线实体振幅 <= 20%
```

### 2. 底部放量反转

用于寻找低位区域突然放量上涨的股票。

```text
1. 当前价格距离过去40个交易日最低点 < 20%
2. 今日涨幅 > 5%
3. 今日成交量 > 过去20日均量 × 2
```

### 3. 主升-箱体突破

用于寻找主升启动中的新高突破股票。

```text
1. 今日收盘价 > 过去60天最高收盘价，不含今日
2. 今日成交量 > 过去20日平均成交量 × 1.5
```

### 4. 主升-底部放量反转

用于寻找长期低位突然放量大涨的股票。

```text
1. 当前价格距离过去60日最低收盘价涨幅 < 30%
2. 今日涨幅 > 5%
3. 今日成交量 > 过去20日平均成交量 × 2
```

### 5. 主升-缩量回调启动

用于寻找趋势未坏、短期回调后重新启动的股票。

```text
1. SMA5 < SMA20
2. SMA60 > 5天前的SMA60
3. 今日收盘价 > SMA5
4. 今日成交量 > 过去20日平均成交量 × 1.5
```

### 6. 主升-均线多头排列

用于寻找趋势延续型股票。

```text
1. SMA5 > SMA10 > SMA20 > SMA60
2. 今日涨幅 > 2%
3. 今日成交量 > 过去20日平均成交量 × 1.2
```

### 7. 日线策略统一二次过滤

日线策略命中后，还会统一执行二次过滤：

```text
1. 过去20个交易日日均成交额 >= 5000万元
2. 过去15个交易日内，含今日，至少出现1次涨停
3. 主板涨停定义为单日涨幅 >= 9.95%
```

---

## 六、分钟级B点逻辑

分钟级B点不是替代日线策略，而是在日线候选股基础上做更精细的买点确认。

当前执行顺序：

```text
第一层：30分钟确认趋势
第二层：5分钟确认结构 / 缠论B点
第三层：1分钟精确买点，可选，默认关闭
```

### 1. 30分钟趋势确认

公共过滤函数：`check_30m_structure(df30)`。

核心思路：

```text
1. 30分钟K线数量充足
2. 最新30分钟收盘价 > MA5
3. MA5 >= MA10
4. 最新成交量 >= VOL20 × 0.8
```

只有 30分钟趋势结构有效，才会继续判断 5分钟结构和缠论买点。

### 2. 5分钟结构类B点

| 策略名称 | 适用分组 | 核心逻辑 |
|---|---|---|
| 5分钟回踩均线启动 | 主升趋势类 | 5分钟均线趋势向上，前一根回踩 MA10 或 MA20，最新K线重新站上 MA5 并突破前高，成交量放大 |
| 5分钟平台突破确认 | 突破类 / 其他 | 前12根5分钟K线振幅较小，最新收盘突破前12根高点，成交量放大 |
| 5分钟放量反包确认 | 放量启动类 | 最新5分钟K线站上 MA5，突破前一根高点，单根涨幅和成交量满足要求 |

### 3. 缠论类B点

缠论策略位于 `strategies/chanlun_strategies.py`，属于工程化简化版本，不是完整缠论原文逐字复刻。

| 策略名称 | 说明 | 风格 |
|---|---|---|
| 缠论一买B点 | 下跌末端背驰后的反转买点 | 偏左侧，风险较高 |
| 缠论二买B点 | 一买反弹后回踩不创新低，再次启动 | 确认性更强 |
| 缠论三买B点 | 突破中枢后回踩不回中枢，再次启动 | 最适合当前主升趋势跟随 |

缠论模块包括：

```text
K线去包含
顶/底分型识别
笔生成
中枢识别
MACD力度辅助判断
```

### 4. 1分钟精确买点

1分钟买点默认关闭。

原因是：

```text
1. 当前默认分钟数据主要来自 stk_mins，偏历史分钟数据；
2. 真正盘中实时的1分钟确认更适合接入 rt_min 后使用；
3. 1分钟条件更严格，开启后结果可能明显减少，甚至没有命中。
```

开启方式：

```bash
python realtime_strategy.py --max-workers 6 --loop --enable-1m-buy
```

开启后，系统会要求：

```text
30分钟趋势有效
5分钟结构 / 缠论B点有效
1分钟短线重新转强
1分钟突破上一根高点
距离5分钟MA5不能过远
1分钟量能温和放大
```

默认不开启时，系统只确认到：

```text
30分钟趋势 + 5分钟结构 / 缠论B点
```

---

## 七、分钟数据逻辑

### 1. 当前数据源

当前版本使用：

```text
stk_mins：历史分钟K线
get_realtime_quotes：盘中实时行情，用于动态日K，不用于构造分钟K线
```

后续如果开通 `rt_min`，推荐升级为：

```text
stk_mins：历史分钟底座 + 盘后校准
rt_min：盘中实时分钟K线
最终分钟数据 = 历史缓存 + 当天rt_min实时分钟K线
```

策略模块不关心数据来源，只要求字段统一为：

```text
datetime、开盘、最高、最低、收盘、成交量、成交额
```

### 2. 本地缓存命名

分钟缓存目录：

```text
cache/minute/
```

缓存文件命名：

```text
000001_1m.csv
000001_5m.csv
000001_30m.csv
```

当前默认只保留最近 10 天分钟数据，避免缓存无限增大。

### 3. 缓存更新逻辑

普通实时扫描时：

```text
1. 优先读取本地分钟缓存
2. 只保留最近 minute-days 天
3. 如果非交易时间且没有强制更新，直接使用缓存
4. 如果交易时间，比较缓存最新 datetime 是否足够接近当前时间
5. 如果缓存明显落后，则请求接口补数据
6. 合并旧缓存和新数据
7. 按 datetime 去重
8. 再次裁剪最近 minute-days 天
9. 保存回本地 csv
```

不同周期允许的缓存延迟：

| 周期 | 默认允许落后 |
|---|---:|
| 1分钟 | 2 分钟 |
| 5分钟 | 6 分钟 |
| 15分钟 | 16 分钟 |
| 30分钟 | 35 分钟 |
| 60分钟 | 65 分钟 |

---

## 八、常用运行命令

### 1. 生成基础股票池

首次运行或需要重新生成股票池时：

```bash
python main.py
```

输出：

```text
output/a_stock_selected.xlsx
```

### 2. 盘中实时扫描，默认开启分钟级B点，关闭1分钟精确买点

```bash
python realtime_strategy.py --max-workers 6 --loop
```

默认逻辑：

```text
日线实时扫描
分钟级B点确认
30分钟趋势 + 5分钟结构 / 缠论B点
不启用1分钟精确买点
```

### 3. 只执行一轮实时扫描

```bash
python realtime_strategy.py --max-workers 6 --once
```

也可以直接运行，不加 `--loop` 时默认只执行一轮：

```bash
python realtime_strategy.py --max-workers 6
```

### 4. 设置循环间隔

```bash
python realtime_strategy.py --max-workers 6 --loop --interval 60
```

表示每轮目标间隔为 60 秒。如果本轮扫描耗时超过 60 秒，则下一轮会立即开始。

### 5. 关闭分钟级B点确认

```bash
python realtime_strategy.py --max-workers 6 --loop --disable-minute
```

只做日线实时扫描，不做 30分钟 / 5分钟 / 1分钟确认。

### 6. 开启1分钟精确买点

```bash
python realtime_strategy.py --max-workers 6 --loop --enable-1m-buy
```

开启后会额外加载 1分钟数据，并要求 1分钟买点确认通过。

### 7. 测试前 N 只股票

```bash
python realtime_strategy.py --max-workers 6 --max-stocks 50
```

分钟级确认只处理前 N 只日线命中股票：

```bash
python realtime_strategy.py --max-workers 6 --minute-max-stocks 10
```

### 8. 修改分钟数据范围

默认最近 10 天：

```bash
python realtime_strategy.py --max-workers 6 --minute-days 10
```

也可以调整，例如最近 5 天：

```bash
python realtime_strategy.py --max-workers 6 --minute-days 5
```

### 9. 强制更新分钟K线

忽略当前是否交易时间，强制请求 `stk_mins` 更新分钟K线，用于测试速度或检查缓存补全：

```bash
python realtime_strategy.py --max-workers 6 --force-update-minute
```

同时开启1分钟精确买点：

```bash
python realtime_strategy.py --max-workers 6 --force-update-minute --enable-1m-buy
```

### 10. 盘后分钟K线校准

盘后用 `stk_mins` 重新拉取并覆盖本地分钟缓存。

默认校准 5m / 30m：

```bash
python realtime_strategy.py --after-market-calibrate --max-workers 6
```

如果要同时校准 1m / 5m / 30m：

```bash
python realtime_strategy.py --after-market-calibrate --enable-1m-buy --max-workers 6
```

只校准前 50 只：

```bash
python realtime_strategy.py --after-market-calibrate --max-stocks 50 --max-workers 6
```

盘后校准会覆盖：

```text
cache/minute/000001_5m.csv
cache/minute/000001_30m.csv
```

如果加 `--enable-1m-buy`，也会覆盖：

```text
cache/minute/000001_1m.csv
```

---

## 九、输出文件说明

### 1. 基础股票池

```text
output/a_stock_selected.xlsx
```

保存基础筛选后的股票池。

### 2. 盘后信号结果

```text
output/a_stock_signal_selected_YYYYMMDD_HHMMSS.xlsx
```

包含全部信号、突破反转、主升信号、题材共振等 sheet。

### 3. 实时扫描增量结果

```text
output/realtime_incremental/realtime_incremental_YYYYMMDD.xlsx
```

同一股票同一策略组合当天只保存一次；如果后续策略发生变化，则追加为新记录。

### 4. 分钟级B点结果

```text
output/minute_buy_points/minute_buy_points_YYYYMMDD.xlsx
```

包含字段示例：

```text
代码
名称
触发时间
最新价
涨跌幅
行业
日线分组
日线策略
30分钟结构
分钟B点
保存时间
分钟Key
```

终端也会打印分钟级B点预览，方便查看是否命中：

```text
5分钟回踩均线启动
5分钟平台突破确认
5分钟放量反包确认
缠论一买B点
缠论二买B点
缠论三买B点
1分钟精确买点
```

### 5. 盘后校准明细

```text
output/minute_calibration/minute_calibration_YYYYMMDD_HHMMSS.xlsx
```

记录每只股票、每个周期校准是否成功、数据行数、最新时间、缓存文件和错误信息。

---

## 十、项目目录结构

```text
stock_selection/
├── main.py
├── realtime_strategy.py
├── realtime_strategy_timed.py
├── minute_strategy.py
├── strategy.py
├── config.py
├── data_loader.py
├── filters.py
├── concept_analyzer.py
├── requirements.txt
├── README.md
├── 策略模块化说明.md
├── strategies/
│   ├── __init__.py
│   ├── base_strategy.py
│   ├── daily_strategies.py
│   ├── minute_strategies.py
│   ├── chanlun_strategies.py
│   └── registry.py
├── cache/
│   ├── hist/
│   ├── minute/
│   └── concept/
└── output/
    ├── realtime_incremental/
    ├── minute_buy_points/
    └── minute_calibration/
```

---

## 十一、主要文件说明

| 文件 / 目录 | 说明 |
|---|---|
| `main.py` | 盘后选股主入口，负责加载或生成基础股票池，执行日线信号扫描，整理并导出结果。 |
| `realtime_strategy.py` | 盘中实时扫描入口，读取基础股票池和本地日K缓存，获取实时行情，构造动态日K，执行实时策略扫描，并调用分钟级B点确认。 |
| `realtime_strategy_timed.py` | 实时扫描的计时版本或备份版本，用于观察各步骤耗时。 |
| `minute_strategy.py` | 分钟数据加载、缓存更新、盘后校准、分钟级B点扫描、分钟结果保存和终端预览。 |
| `strategy.py` | 日K数据加载和日线指标计算，包含均线、过去高低点、成交量、日均成交额、涨停次数等指标，并执行日线策略总入口。 |
| `config.py` | 配置文件，包含 Tushare Token、代理地址、市值范围、排除行业、基础股票池输出路径。 |
| `data_loader.py` | Tushare 基础数据加载模块，用于获取股票基础信息、daily_basic、daily 行情，并整理为基础筛选字段。 |
| `filters.py` | 基础股票池筛选模块，包括主板判断、排除 ST、市值筛选、价格筛选和行业排除。 |
| `concept_analyzer.py` | 东方财富题材分析模块，只查询命中股票的概念题材，并统计题材共振。 |
| `strategies/base_strategy.py` | 策略基类，定义日线策略和分钟策略的统一接口。 |
| `strategies/daily_strategies.py` | 日线策略实现文件。 |
| `strategies/minute_strategies.py` | 30分钟结构过滤、5分钟结构B点、1分钟精确买点实现文件。 |
| `strategies/chanlun_strategies.py` | 简化缠论分钟级买点策略，包括一买、二买、三买。 |
| `strategies/registry.py` | 策略注册表，统一管理启用哪些日线策略和分钟级策略。 |
| `cache/hist/` | 日K历史缓存，主要保存 BaoStock 日K数据。 |
| `cache/minute/` | 分钟K线缓存，保存 1m / 5m / 30m 数据。 |
| `cache/concept/` | 命中股票题材缓存。 |
| `output/` | 所有结果输出目录。 |

---

## 十二、策略模块化说明

日线策略和分钟级策略已经拆分到 `strategies/` 目录。

### 新增日线策略

1. 在 `strategies/daily_strategies.py` 新增一个类，继承 `BaseDailyStrategy`；
2. 设置 `name` 和 `category`；
3. 实现 `match(self, row)`；
4. 在 `strategies/registry.py` 的 `get_daily_strategies()` 中注册。

示例：

```python
class MyDailyStrategy(BaseDailyStrategy):
    name = "我的日线策略"
    category = "主升"

    def match(self, row):
        return row["收盘"] > row["SMA20"]
```

### 新增分钟级B点策略

1. 在 `strategies/minute_strategies.py` 新增一个类，继承 `BaseMinuteStrategy`；
2. 设置 `name` 和 `support_groups`；
3. 实现 `match(self, row, df5, df30)`；
4. 在 `strategies/registry.py` 的 `get_minute_strategies()` 中注册。

如果是 1分钟策略，需要单独在 `evaluate_minute_strategies()` 里按 `df1` 调用。

---

## 十三、推荐使用流程

### 盘前或首次使用

```bash
python main.py
```

生成基础股票池。

### 盘中观察

默认只确认到 5分钟级别：

```bash
python realtime_strategy.py --max-workers 6 --loop
```

如果接入了实时 `rt_min`，并希望用 1分钟做最终精确买点：

```bash
python realtime_strategy.py --max-workers 6 --loop --enable-1m-buy
```

### 盘后校准

```bash
python realtime_strategy.py --after-market-calibrate --max-workers 6
```

如果需要校准 1分钟：

```bash
python realtime_strategy.py --after-market-calibrate --enable-1m-buy --max-workers 6
```

---

## 十四、当前版本注意事项

1. `stk_mins` 主要用于历史分钟数据。如果盘中该接口不更新，则盘中分钟级实时能力需要后续接入 `rt_min`。
2. 当前默认关闭 1分钟精确买点，因为没有实时 `rt_min` 时，1分钟更适合作为盘中实时触发层，而不是历史结构判断层。
3. `get_realtime_quotes()` 当前用于构造动态日K，不用于构造 1m / 5m / 30m 分钟K线。
4. 后续接入 `rt_min` 后，建议实现：`历史 stk_mins + 当天 rt_min + 合并去重 + 盘后 stk_mins 校准`。
5. 缓存文件会按最近 `minute-days` 天裁剪，不会无限增大。
6. 盘后校准是覆盖式更新，不是追加式更新。
7. 策略结果只作为研究辅助，不代表确定买点，更不构成投资建议。

---

## 十五、后续计划

- [ ] 接入 `rt_min`，实现盘中实时分钟K线构造
- [ ] 将分钟数据源进一步抽象为独立模块
- [ ] 增加交易日历判断，区分工作日和 A 股真实开市日
- [ ] 增加回测模块和参数化回测报告
- [ ] 增加更多分钟级止损、止盈和卖点逻辑
- [ ] 增加概念题材共振的稳定缓存和接口降级方案
- [ ] 增加图形化界面或 Web Dashboard
- [ ] 增加日志文件输出，便于长期盘中运行排查

---

## 十六、常见问题

### 1. 为什么关闭1分钟能看到B点，开启1分钟反而没有？

因为关闭1分钟时，系统只要求：

```text
30分钟趋势有效 + 5分钟结构 / 缠论B点有效
```

开启1分钟后，还要求：

```text
1分钟精确买点也确认
```

条件更严格，所以数量会减少。没有实时 `rt_min` 时，建议默认关闭1分钟。

### 2. 分钟缓存会不会越来越大？

正常不会。每次保存前都会按 `minute-days` 裁剪，只保留最近 N 天。

### 3. 盘后校准会不会追加重复数据？

不会。盘后校准是覆盖式更新，用 `stk_mins` 重新拉取最近 N 天数据后直接覆盖对应 csv。

### 4. 实时扫描结果为什么显示昨天的行情？

如果当前不是交易时间，实时行情接口可能返回上一个交易日收盘数据。需要结合运行时间和接口返回的 `行情日期`、`行情时间` 判断。

### 5. 后续接入 `rt_min` 后是否需要改策略？

一般不需要大改策略。只要把 `rt_min` 返回结果整理成统一字段：

```text
datetime、开盘、最高、最低、收盘、成交量、成交额
```

就可以继续复用现有 30分钟、5分钟、缠论和1分钟策略。

## 十七、OpenSpec 规范驱动开发

本项目已集成 [OpenSpec](https://github.com/Fission-AI/OpenSpec)（规范驱动开发，Spec-driven Development）。开发前先写规格（spec），AI 按规格实现，避免"改了又改"。

### 目录结构

| 路径 | 用途 |
|------|------|
| `openspec/config.yaml` | OpenSpec 配置 + 项目上下文（喂给 AI 的技术栈/模块说明） |
| `openspec/specs/` | 主规格（归档后生成，事实来源） |
| `openspec/changes/` | 变更提案（proposal / specs 增量 / design / tasks） |
| `openspec/changes/archive/` | 已归档的变更 |
| `.openspec-cli/` | 本地固定的 CLI 安装（已 gitignore，非项目依赖） |
| `.claude/commands/opsx/` | Claude Code 斜杠命令 `/opsx:propose` 等 |
| `.claude/skills/` | OpenSpec 工作流技能（propose/apply/archive/sync/…） |

### 使用流程（推荐用 Claude Code）

1. **提出变更**：`/opsx:propose 你的想法` → 生成 proposal、specs 增量、design、tasks
2. **评审**：人工确认规格无误
3. **实现**：`/opsx:apply 变更名` → AI 按 tasks 实现，改完归档
4. **归档**：`/opsx:archive 变更名` → 增量合并进 `openspec/specs/` 主规格

### 命令行方式

```bash
openspec --version                # CLI 已全局安装 (/usr/bin/openspec)
openspec list --specs             # 查看已有规格
openspec new change "<变更名>"     # 手动创建变更
openspec validate                 # 校验变更与规格
openspec view                     # 交互式仪表盘
```

> 说明：CLI 全局安装版本可能与 `.openspec-cli/` 内固定的本地版本不同；以全局为准，本地副本用于版本锁定。
