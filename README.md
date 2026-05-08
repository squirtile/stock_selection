<h1 align="center">A股股票筛选工具</h1>

<p align="center">
  一个基于 Python 的 A 股主板股票筛选与行情分析工程
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/Sust2014/stock_selection?style=social" />
  <img src="https://img.shields.io/github/forks/Sust2014/stock_selection?style=social" />
  <img src="https://img.shields.io/github/issues/Sust2014/stock_selection" />
  <img src="https://img.shields.io/github/license/Sust2014/stock_selection" />
</p>

---

## ⚠️ 免责声明

本项目仅用于个人学习、数据分析和量化策略研究，不构成任何投资建议。股市有风险，投资需谨慎。

---

## 🌟 功能特性

- ✅ 筛选 A 股主板股票
- ✅ 排除创业板、科创板、北交所、北交所、ST 股票
- ✅ 支持按市值区间筛选
- ✅ 支持排除指定行业
- ✅ 支持历史 K 线数据获取
- ✅ 支持本地缓存，减少重复请求
- ✅ 支持多种技术形态选股策略
- ✅ 可扩展技术指标和策略条件

---

## 📌 筛选条件与选股策略

本项目先进行基础股票池筛选，再基于日 K 线数据执行多种技术形态策略，用于辅助盘后选股分析。

---

### 一、基础筛选条件

当前默认股票池筛选规则如下：

| 条件 | 说明 |
|---|---|
| 市场范围 | A 股主板 |
| 排除板块 | 创业板、科创板、北交所 |
| 排除股票 | ST、*ST |
| 市值范围 | 100 亿至 1500 亿 |
| 排除行业 | 银行、券商、保险、信托、房地产、钢铁、煤炭开采、铁路运输、航运 |

---

### 二、选股策略

当前内置以下技术形态选股策略：

| 策略名称 | 核心逻辑 | 筛选条件 |
|---|---|---|
| 箱体突破 | 前期横盘后放量创新高 | 今日收盘价高于过去 60 个交易日最高价；今日成交量大于过去 20 日均量的 1.3 倍；过去 20 个交易日 K 线实体振幅不超过 20% |
| 底部放量反转 | 低位 V 型启动 | 当前价格距离过去 40 个交易日最低点小于 20%；今日涨幅大于 5%；今日成交量大于过去 20 日均量的 2 倍 |
| 缩量回调启动 | 短期回调结束后重新启动 | SMA(5) < SMA(20)；SMA(60) 大于 5 个交易日前的 SMA(60)；今日收盘价高于 SMA(5)；今日成交量大于过去 20 日均量的 1.5 倍 |
| 均线多头排列 | 趋势延续型启动 | SMA(5) > SMA(10) > SMA(20) > SMA(60)；今日涨幅大于 2%；今日成交量大于过去 20 日均量的 1.2 倍 |

---

### 三、策略说明

#### 1. 箱体突破

该策略用于寻找前期长期横盘整理后，突然放量突破前高的股票。

筛选逻辑：

```text
1. 今日收盘价 > 过去 60 个交易日最高价，不含今日
2. 今日成交量 > 过去 20 日均量 × 1.3
3. 过去 20 个交易日 K 线实体振幅 <= 20%
```

其中，箱体振幅使用每日 `open` 和 `close` 计算实体上下沿，避免长上影线或长下影线造成误判。

---

#### 2. 底部放量反转

该策略用于寻找低位区域出现明显放量上涨的股票，偏向 V 型反转启动形态。

筛选逻辑：

```text
1. 当前价格距离过去 40 个交易日最低点 < 20%
2. 今日涨幅 > 5%
3. 今日成交量 > 过去 20 日均量 × 2
```

---

#### 3. 缩量回调启动

该策略用于寻找中长期趋势未破坏，但短期回调后重新启动的股票。

筛选逻辑：

```text
1. SMA(5) < SMA(20)
2. SMA(60) > 5 个交易日前的 SMA(60)
3. 今日收盘价 > SMA(5)
4. 今日成交量 > 过去 20 日均量 × 1.5
```

其中，`SMA(5) < SMA(20)` 表示短期仍处于回调状态，`SMA(60)` 上行表示长期趋势没有明显走坏，今日重新站上 `SMA(5)` 则代表短期可能重新启动。

---

#### 4. 均线多头排列

该策略用于寻找趋势较强、均线系统呈现多头排列的股票。

筛选逻辑：

```text
1. SMA(5) > SMA(10) > SMA(20) > SMA(60)
2. 今日涨幅 > 2%
3. 今日成交量 > 过去 20 日均量 × 1.2
```

---

## 🧰 技术栈

| 类型 | 工具 |
|---|---|
| 开发语言 | Python |
| 数据处理 | pandas |
| 行情数据 | BaoStock / AkShare |
| 表格输出 | tabulate / wcwidth |
| Excel 支持 | openpyxl |
| 数据缓存 | CSV |
| 运行环境 | Windows / Linux / macOS |
| 容器化 | Docker |

---

## 📦 安装依赖

请先确保已经安装 Python，建议使用 Python 3.9 及以上版本。

项目依赖如下：

```txt
akshare
pandas
openpyxl
tabulate
baostock
wcwidth
```

推荐使用 `requirements.txt` 安装：

```bash
pip install -r requirements.txt
```

Windows 环境也可以使用：

```bash
python -m pip install -r requirements.txt
```

如果下载速度较慢，可以使用清华源：

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 🚀 快速开始

```bash
git clone git@github.com:Sust2014/stock_selection.git

cd stock_selection

python main.py
```

---

## 🐳 Docker 运行

项目支持 Docker 容器化部署，无需手动安装 Python 和依赖。

### 构建镜像

```bash
docker build -t stock-selection .
```

### 运行选股

```bash
docker run --rm \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/cache:/app/cache \
  stock-selection
```

运行结果会自动输出到本地 `output/` 目录，缓存数据保存在 `cache/` 目录。

### 使用 VS Code 任务

项目内置 `.vscode/tasks.json`，在 VS Code 中可通过 `Ctrl+Shift+P` → `Tasks: Run Task` 快速执行以下任务：

| 任务 | 说明 |
|---|---|
| 运行选股程序 | 直接运行 `python main.py`（默认构建任务） |
| 安装依赖 | 使用清华源安装 `requirements.txt` |
| Docker 构建镜像 | 构建 Docker 镜像 |
| Docker 运行选股 | 通过 Docker 容器运行选股 |
| 运行测试 | 执行 pytest 测试 |
| 清理缓存 | 清除 `cache/` 和 `__pycache__/` |

---

## 📁 项目结构

```text
stock_selection/
├── main.py
├── config.py
├── data_loader.py
├── filters.py
├── strategy.py
├── concept_analyzer.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .vscode/
│   └── tasks.json
├── cache/
├── output/
├── test/
└── README.md
```

| 文件 / 目录 | 功能说明 |
|---|---|
| `main.py` | 项目主程序入口，负责串联完整选股流程，包括加载基础股票池、执行主升信号扫描、整理导出结果，并在终端打印策略说明和股票预览结果。 |
| `config.py` | 项目配置文件，用于统一管理市值筛选范围、需要排除的行业关键词，以及最终基础股票池的导出路径。 |
| `data_loader.py` | 数据获取模块，主要负责通过 AkShare 获取 A 股实时行情数据，并从东方财富行业接口获取行业分类数据，同时支持本地行业缓存，减少重复请求。 |
| `filters.py` | 基础筛选模块，负责从全市场股票中筛选目标股票池，包括保留主板股票、排除 ST、限制市值范围、限制股价，并排除指定行业。 |
| `strategy.py` | 技术策略模块，负责通过 BaoStock 获取个股历史日 K 线数据，计算均线、成交量、涨停次数等指标，并执行箱体突破、底部放量反转等主升信号策略。 |
| `concept_analyzer.py` | 题材分析模块，负责从东方财富接口获取命中股票的概念题材，并统计多个股票共同命中的题材，用于辅助判断题材共振情况。 |
| `requirements.txt` | Python 依赖列表，记录项目运行所需的第三方库，例如 `akshare`、`pandas`、`openpyxl`、`baostock` 等。 |
| `Dockerfile` | Docker 容器构建文件，基于 `python:3.11-slim`，支持使用清华源加速依赖安装，并声明 `output/` 和 `cache/` 数据卷。 |
| `.dockerignore` | Docker 构建排除文件，排除 `.git`、`__pycache__`、`cache`、`output`、`test` 等非必要文件以减小镜像体积。 |
| `.vscode/tasks.json` | VS Code 任务配置文件，包含运行选股、安装依赖、Docker 构建/运行、测试和清理缓存等快捷任务。 |
| `cache/` | 本地缓存目录，用于保存行业映射、历史 K 线、题材数据等缓存文件，避免每次运行都重新请求接口。 |
| `output/` | 结果输出目录，用于保存基础股票池、主升信号筛选结果、题材共振结果等 Excel 文件。 |
| `test/` | 测试目录，可用于存放临时测试脚本、功能验证代码或接口调试文件。 |
| `README.md` | 项目说明文档，用于介绍项目功能、安装方式、筛选条件、选股策略、运行方法和项目结构。 |
```

---

## 🔧 后续计划

- [ ] 增加成交量筛选
- [ ] 增加均线趋势判断
- [ ] 增加 MACD 金叉判断
- [ ] 增加布林线突破判断
- [ ] 增加行业热度分析
- [ ] 增加代理池或数据源自动切换机制
- [ ] 增加图形化界面

---

## 📄 License

本项目基于 GPL-3.0 license 开源。