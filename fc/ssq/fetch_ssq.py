"""
双色球历史开奖数据抓取脚本
==========================
数据来源: 中国福利彩票官网 (www.cwl.gov.cn) 官方API
开奖规则: 每周二、四、日开奖（非每天开奖）
红球: 1-33 选 6 个（不重复，不限顺序）
蓝球: 1-16 选 1 个

增量更新逻辑: 读取本地已有数据 → 从最后日期次日开始补 → 合并去重
"""

import requests
import pandas as pd
import os
import re
import time
from datetime import datetime, timedelta

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUTPUT_DIR, exist_ok=True)

API_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.cwl.gov.cn/",
}

DATA_FILE = os.path.join(OUTPUT_DIR, "双色球历史开奖数据.csv")

# 福彩官方最早数据
SSQ_FIRST_DATE = "2003-02-16"

# 双色球开奖日: 周二(1)、周四(3)、周日(6)
DRAW_WEEKDAYS = {1, 3, 6}


def _create_session():
    """创建绕过代理的请求会话"""
    s = requests.Session()
    s.trust_env = False
    return s


def fetch_ssq_page(session, page_no=1, page_size=100, start_date=None, end_date=None):
    """拉取单页双色球数据"""
    if start_date is None:
        start_date = SSQ_FIRST_DATE
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    params = {
        "name": "ssq",
        "issueCount": "",
        "issueStart": start_date,
        "issueEnd": end_date,
        "dayStart": start_date,
        "dayEnd": end_date,
        "pageNo": page_no,
        "pageSize": page_size,
        "week": "",
        "systemType": "PC",
    }
    r = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("state") != 0:
        raise RuntimeError(f"API返回异常: {data}")
    return data


def fetch_ssq_all(start_date=None, end_date=None):
    """拉取双色球全部历史开奖数据（分页）"""
    if start_date is None:
        start_date = SSQ_FIRST_DATE

    print("正在连接中国福利彩票官网...")
    session = _create_session()

    all_records = []
    page_no = 1
    page_size = 200

    while True:
        print(f"  正在拉取第 {page_no} 页...", end=" ")
        data = fetch_ssq_page(
            session,
            page_no=page_no,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
        )

        results = data.get("result", [])
        if not results:
            print("无数据，拉取完成！")
            break

        all_records.extend(results)
        print(f"获取 {len(results)} 条 (累计 {len(all_records)})")

        if len(results) < page_size:
            print("最后一页，拉取完成！")
            break

        page_no += 1
        time.sleep(0.3)

    print(f"共获取 {len(all_records)} 条记录")
    return all_records


def fetch_ssq_incremental():
    """
    增量拉取: 从本地已有数据的最新日期次日开始补数据。
    如果本地无数据，则全量拉取。
    """
    # 读取已有数据
    old_df = pd.DataFrame()
    last_date_str = SSQ_FIRST_DATE

    if os.path.exists(DATA_FILE):
        old_df = pd.read_csv(DATA_FILE, dtype={"期号": str})
        if not old_df.empty and "开奖日期" in old_df.columns:
            old_df["开奖日期"] = pd.to_datetime(old_df["开奖日期"], errors="coerce")
            old_df = old_df.dropna(subset=["开奖日期"])
            if not old_df.empty:
                last_date = old_df["开奖日期"].max()
                today = datetime.now()
                if last_date.strftime("%Y-%m-%d") >= today.strftime("%Y-%m-%d"):
                    print(f"数据已是最新（{last_date.strftime('%Y-%m-%d')}），无需更新。")
                    return old_df
                last_date_str = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
                print(f"增量更新：从 {last_date_str} 开始补数据...")

    # 拉取新数据
    end_date = datetime.now().strftime("%Y-%m-%d")
    records = fetch_ssq_all(start_date=last_date_str, end_date=end_date)

    if not records:
        print("没有新数据。")
        return old_df

    # 解析新数据
    new_df = parse_records(records)

    # 合并去重
    if not old_df.empty:
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined["开奖日期"] = pd.to_datetime(combined["开奖日期"], errors="coerce")
        combined = combined.drop_duplicates(subset=["期号"], keep="last")
        combined = combined.sort_values("开奖日期").reset_index(drop=True)
    else:
        combined = new_df

    # 保存
    combined.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
    print(f"已保存 {len(combined)} 条记录到 {DATA_FILE}")

    return combined


def parse_records(records: list) -> pd.DataFrame:
    """解析原始JSON为DataFrame。

    API返回格式示例:
    {
      "code": "2026070",
      "date": "2026-06-21(日)",
      "red": "01,02,03,04,05,06",
      "blue": "07",
      "sales": "123456789",
      "poolmoney": "1234567890"
    }
    """
    rows = []
    for item in records:
        date_str = item.get("date", "")
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
        clean_date = date_match.group(1) if date_match else date_str

        red_str = item.get("red", "")
        blue_str = item.get("blue", "")

        # 解析红球
        red_parts = red_str.split(",") if red_str else []
        red_balls = [int(x) for x in red_parts if x.strip()] if red_parts else []

        # 蓝球
        try:
            blue_ball = int(blue_str) if blue_str else None
        except ValueError:
            blue_ball = None

        # 销售额
        sales = item.get("sales", "")
        try:
            sales = int(sales) if sales else None
        except ValueError:
            sales = None

        # 奖池
        pool = item.get("poolmoney", "")
        try:
            pool = int(pool) if pool else None
        except ValueError:
            pool = None

        # 构建行: 红球1~6 + 蓝球 + 汇总
        row = {
            "期号": item.get("code", ""),
            "开奖日期": clean_date,
            "红球": red_str.replace(",", " "),
            "蓝球": blue_str,
        }
        for i in range(6):
            row[f"红{i+1}"] = red_balls[i] if i < len(red_balls) else None
        row["蓝球"] = blue_ball
        row["销售额"] = sales
        row["奖池金额"] = pool

        # 统计特征
        if red_balls and len(red_balls) == 6 and blue_ball:
            row["红球和值"] = sum(red_balls)
            row["红球跨度"] = max(red_balls) - min(red_balls)
            row["红球奇偶比"] = f"{sum(1 for b in red_balls if b % 2 == 1)}:{sum(1 for b in red_balls if b % 2 == 0)}"
            row["红球大小比"] = f"{sum(1 for b in red_balls if b >= 17)}:{sum(1 for b in red_balls if b <= 16)}"
            row["红球三区比"] = _zone_ratio(red_balls)
            row["蓝球奇偶"] = "奇" if blue_ball % 2 == 1 else "偶"
            row["蓝球大小"] = "大" if blue_ball >= 9 else "小"

        rows.append(row)

    df = pd.DataFrame(rows)
    if "开奖日期" in df.columns:
        df["开奖日期"] = pd.to_datetime(df["开奖日期"], errors="coerce")
        df = df.sort_values("开奖日期", ascending=True).reset_index(drop=True)
        df["年份"] = df["开奖日期"].dt.year
    return df


def _zone_ratio(reds: list) -> str:
    """三区比: 1-11 / 12-22 / 23-33"""
    z1 = sum(1 for b in reds if 1 <= b <= 11)
    z2 = sum(1 for b in reds if 12 <= b <= 22)
    z3 = sum(1 for b in reds if 23 <= b <= 33)
    return f"{z1}:{z2}:{z3}"


def get_latest_draw_date() -> str:
    """获取最近一次开奖日期（根据开奖规则推断）。"""
    today = datetime.now()
    # 从今天往前找，直到找到周二/四/日
    for i in range(7):
        check_date = today - timedelta(days=i)
        if check_date.weekday() in DRAW_WEEKDAYS:
            return check_date.strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")


def is_draw_day(date=None) -> bool:
    """判断是否为双色球开奖日。"""
    if date is None:
        date = datetime.now()
    return date.weekday() in DRAW_WEEKDAYS


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="双色球历史数据抓取")
    parser.add_argument("--full", action="store_true", help="强制全量重新拉取")
    parser.add_argument("--check", action="store_true", help="只检查是否为开奖日")
    args = parser.parse_args()

    if args.check:
        today = datetime.now()
        dow = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
        is_draw = is_draw_day(today)
        print(f"今天是周{dow}，{'是' if is_draw else '不是'}双色球开奖日。")
        if is_draw:
            print(f"开奖时间通常为 21:15，建议 21:30 后执行拉取。")
        exit(0)

    if args.full or not os.path.exists(DATA_FILE):
        print("全量拉取双色球历史数据...")
        records = fetch_ssq_all()
        df = parse_records(records)
        df.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")
        print(f"已保存 {len(df)} 条到 {DATA_FILE}")
    else:
        print("增量更新双色球数据...")
        df = fetch_ssq_incremental()

    if len(df) > 0:
        latest = df.iloc[-1]
        print(f"\n最新一期: {latest['期号']}  {latest['开奖日期'].strftime('%Y-%m-%d')}")
        print(f"红球: {latest['红球']}  蓝球: {latest['蓝球']}")
