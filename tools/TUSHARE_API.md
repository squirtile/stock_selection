# Tushare API 接口文档

> Token: 见 config.py 中的 TUSHARE_TOKEN
> 镜像地址: 见 config.py 中的 TUSHARE_HTTP_URL
> 调用方式: `pro._DataApi__http_url = "http://..."`
> 本机测试: `python test/test_tushare.py`

---

## 一、板块相关

### 1. 同花顺行业/概念板块列表
```python
df = pro.ths_index()
# 返回: ts_code, name, count(成分股数), exchange, list_date, type
# type: N=概念板块, I=行业板块, S=地域板块, ST=风格板块
```
| 参数 | 说明 |
|------|------|
| exchange | 可选, a=沪深, hk=港股 |
| type | 可选, N/I/S/ST |

### 2. 同花顺板块日线行情
```python
df = pro.ths_daily(ts_code='883910.TI', start_date='20260701', end_date='20260710')
# 返回: ts_code, trade_date, open, high, low, close, pct_change, vol, amount 等
```

### 3. 同花顺板块成分股
```python
df = pro.ths_member(ts_code='883910.TI')
# 返回板块包含的所有股票代码
```

### 4. 申万行业分类
```python
df = pro.index_classify(level='L1')  # L1=一级行业
# SW 行业体系，经典行业分类
```

### 5. 申万板块日线
```python
df = pro.index_daily(ts_code='801010.SI', start_date='20260701', end_date='20260710')
```

---

## 二、涨停/连板相关

### 1. 每日涨跌停统计
```python
df = pro.limit_list(trade_date='20260710', limit_type='U')
# limit_type: U=涨停, D=跌停
# 返回: ts_code, name, pct_change, limit_times(连板数), open_times(炸板次数)
df_limit = pro.limit_list_d(trade_date='20260710', limit_type='U')  # 新版
```

### 2. 每日涨停板明细(炸板、封单等)
```python
df = pro.stk_limit(trade_date='20260710')
# 返回更详细的涨停信息: 封单量、炸板次数、封板时间等
```

### 3. 连板天数（从个股日线推导）
用 `pro.daily()` 获取多日涨跌幅，自己算连续涨停天数。

---

## 三、资金流向

### 1. 个股资金流向
```python
df = pro.moneyflow(ts_code='000001.SZ', start_date='20260701', end_date='20260710')
# 返回: 主力净流入, 超大单净流入, 大单净流入, 中单, 小单 等
```

### 2. 板块资金流向（同花顺）
```python
df = pro.moneyflow_ths(trade_date='20260710')
# 按板块统计的资金流入流出排名
```

### 3. 行业资金流向（申万）
```python
df = pro.moneyflow_ind(trade_date='20260710')
# SW 行业资金流向
```

---

## 四、市场情绪/恐慌指数

### 1. 沪深市场统计
```python
df = pro.daily_basic(trade_date='20260710')  # 全市场PE/PB/换手率
df_all = pro.daily_basic(ts_code='', trade_date='20260710')  # 全部股票
```

### 2. 融资融券
```python
df = pro.margin(trade_date='20260710')  # 融资融券余额
df_detail = pro.margin_detail(trade_date='20260710')  # 个股融资融券明细
```

### 3. 北向资金(沪股通/深股通)
```python
df = pro.moneyflow_hsgt(start_date='20260701', end_date='20260710')
# 北向资金每日流向
```

### 4. 涨跌家数统计
```python
df = pro.limit_list(trade_date='20260710')
# 统计涨停家数 / 跌停家数 = 市场热度
```

---

## 五、个股数据（已有 Baostock 备份）

### 日线
```python
df = pro.daily(ts_code='000001.SZ', start_date='20260701', end_date='20260710')
# 返回: open, high, low, close, pct_change, vol, amount
```

### 分钟线
```python
df = pro.stk_mins(ts_code='000001.SZ', freq='5min', start_date='20260710', end_date='20260710')
```

---

## 六、使用示例

```python
import tushare as ts
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from config import TUSHARE_TOKEN, TUSHARE_HTTP_URL

pro = ts.pro_api(TUSHARE_TOKEN)
pro._DataApi__http_url = TUSHARE_HTTP_URL

# 获取今日所有涨停股
df = pro.limit_list(trade_date='20260710', limit_type='U')

# 获取板块资金流向排名
df = pro.moneyflow_ths(trade_date='20260710')
print(df.sort_values('net_amount', ascending=False).head(10))
```
