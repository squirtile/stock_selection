# ml_engine_project：强势股形态相似度与回测模块

把本目录里的 `ml_engine/` 和 `cli/` 复制到你的 `stock_selection` 工程根目录下使用。工程根目录需要已有 `strategy.py`，并且 `strategy.py` 里能导出：

```python
HIST_CACHE_DIR
prepare_hist_data
```

也就是你原来日线策略工程里的缓存目录和指标计算函数。

## 这版主要改了什么

1. **多股票自动模板**不再简单拿模板股票所有历史窗口，而是优先自动识别近期启动点，提取“启动前窗口”。
2. **相似度标准化**修正为模板窗口和候选窗口一起 `fit StandardScaler`，避免只用模板拟合导致相似度失真。
3. **候选池**支持 `output/a_stock_selected.xlsx`，更符合你原来的选股流程。
4. **回测**支持对全部候选股票历史窗口做相似度回测，不再只能对当前 TopK 股票回测。
5. **特征**从原来的绝对均线/成交额，改为更多比例型形态特征，比如收盘相对均线、均线相对关系、距60日高低点、近5/10/20日涨幅、量能比。
6. 回测加入了基础的“次日涨停过滤”、手续费和滑点参数。

## 1. 指定一只强势股和一段日期，找当前相似股

```bash
python cli/ml_match.py --code 002179 --date-start 2026-04-20 --date-end 2026-05-10 --threshold 0.55 --top-k 20
```

只在你日线策略筛出的股票池里找：

```bash
python cli/ml_match.py --code 002179 --date-start 2026-04-20 --date-end 2026-05-10 --threshold 0.55 --top-k 20 --use-selected-file
```

指定候选文件：

```bash
python cli/ml_match.py --code 002179 --date-start 2026-04-20 --date-end 2026-05-10 --candidate-file output/a_stock_selected.xlsx
```

默认回测范围是全部候选历史。如果只想回测当前 TopK：

```bash
python cli/ml_match.py --code 002179 --date-start 2026-04-20 --date-end 2026-05-10 --backtest-scope topk
```

## 2. 提供几只强势股，自动提取启动前窗口，再找类似股

```bash
python cli/ml_similarity.py --template 002179,600498,000988 --template-mode auto --threshold 0.55 --top-k 30
```

`--template-mode` 可选：

- `auto`：默认，等同于 `prelaunch`，自动找启动点，取启动前窗口。
- `prelaunch`：只取启动前窗口。
- `launch`：取启动日窗口。
- `both`：启动前窗口 + 启动日窗口。
- `recent`：只取最近窗口，不做启动识别。
- `all`：普通滑动窗口。

结合你的日线选股结果：

```bash
python cli/ml_similarity.py --template 002179,600498,000988 --template-mode auto --threshold 0.55 --top-k 30 --use-selected-file
```

## 3. 自动选近期强势股作为模板

```bash
python cli/ml_similarity.py --auto-template --auto-top-n 20 --template-mode auto --threshold 0.55 --top-k 50
```

这个会按最近60日涨幅自动选模板股，然后自动提取启动前窗口。

## 4. 训练随机森林模型

```bash
python cli/ml_train.py --template 002179,600498,000988 --horizon 5 --target 5
```

生成：

```text
output/ml_models/ml_pattern_model.pkl
```

回测模型：

```bash
python cli/ml_backtest.py --model output/ml_models/ml_pattern_model.pkl --threshold 0.65 --hold-days 1,3,5,10
```

## 输出

默认输出 Excel 到：

```text
output/ml_similarity/
```

常见 Sheet：

- `相似度排名`
- `明细匹配`
- `模板摘要`
- `回测汇总`
- `回测明细`

## 注意

这套代码依赖你的本地日线缓存，不负责下载数据。如果 `cache/hist/xxxxxx_bs.csv` 不完整，需要先运行你原来的日线数据更新流程。

第一次测试建议阈值不要太高：

```bash
--threshold 0.45 或 --threshold 0.55
```

如果结果太杂，再提高到 0.60 以上。
