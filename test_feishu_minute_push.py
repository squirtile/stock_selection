# test_feishu_minute_push.py
# 用法：
#   1. 先在 config.py 中配置 FEISHU_WEBHOOK_URL
#   2. 运行：python test_feishu_minute_push.py

import pandas as pd

from minute_strategy import push_minute_buy_points_to_feishu


def main():
    demo_df = pd.DataFrame([
        {
            "代码": "000001",
            "名称": "平安银行",
            "触发时间": "2026-05-21 10:30:00",
            "最新价": 11.25,
            "涨跌幅": 2.35,
            "行业": "银行",
            "日线分组": "主升趋势类",
            "30分钟结构": "30分钟趋势向上，回踩不破",
            "分钟B点": "5分钟二买、1分钟精确买点",
        }
    ])

    success_count, failed_count = push_minute_buy_points_to_feishu(demo_df)
    print(f"测试完成：成功 {success_count} 条，失败 {failed_count} 条")


if __name__ == "__main__":
    main()
