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
- ✅ 排除创业板、科创板、北交所、ST 股票
- ✅ 支持按市值区间筛选
- ✅ 支持排除指定行业
- ✅ 支持历史 K 线数据获取
- ✅ 支持本地缓存，减少重复请求
- ✅ 可扩展技术指标和策略条件

---

## 📌 筛选条件

当前默认筛选规则如下：

| 条件 | 说明 |
|---|---|
| 市场范围 | A 股主板 |
| 排除板块 | 创业板、科创板、北交所 |
| 排除股票 | ST、*ST |
| 市值范围 | 100 亿至 1500 亿 |
| 排除行业 | 银行、券商、保险、信托、房地产、钢铁、煤炭开采、铁路运输、航运 |

---

## 🧰 技术栈

| 类型 | 工具 |
|---|---|
| 开发语言 | Python |
| 数据处理 | pandas |
| 行情数据 | BaoStock / AkShare |
| 数据缓存 | CSV |
| 运行环境 | Windows / Linux / macOS |

---

## 📦 安装依赖

```bash
pip install -r requirements.txt

```windows
python -m pip install -r requirements.txt