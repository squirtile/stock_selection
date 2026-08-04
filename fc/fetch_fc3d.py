"""
福彩3D历史开奖数据抓取脚本
数据来源: 中国福利彩票官网 (www.cwl.gov.cn) 官方API
起始时间: 2004-10-18
"""

import requests
import pandas as pd
import os
import re
import time
from datetime import datetime

OUTPUT_DIR = os.path.dirname(__file__)
os.makedirs(OUTPUT_DIR, exist_ok=True)

API_URL = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.cwl.gov.cn/",
}


def _create_session():
    s = requests.Session()
    s.trust_env = False  # 绕过系统代理
    return s


def fetch_fc3d_page(session, page_no=1, page_size=100, start_date="2004-10-18", end_date=None):
    """拉取单页数据"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    params = {
        "name": "3d",
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
    return r.json()


def fetch_fc3d_all():
    """拉取福彩3D全部历史开奖数据（分页）"""
    print("正在连接中国福利彩票官网...")
    session = _create_session()

    all_records = []
    page_no = 1
    page_size = 200

    while True:
        print(f"  正在拉取第 {page_no} 页...", end=" ")
        data = fetch_fc3d_page(session, page_no=page_no, page_size=page_size)

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
        time.sleep(0.3)  # 礼貌延迟，避免被封

    print(f"共获取 {len(all_records)} 条记录")
    return all_records


def parse_records(records: list) -> pd.DataFrame:
    """解析原始JSON为DataFrame"""
    rows = []
    for item in records:
        date_str = item.get("date", "")
        # 提取日期: "2026-06-30(二)" → "2026-06-30"
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
        clean_date = date_match.group(1) if date_match else date_str

        red = item.get("red", "")
        parts = red.split(",") if red else ["", "", ""]
        bai = int(parts[0]) if len(parts) > 0 and parts[0] else None
        shi = int(parts[1]) if len(parts) > 1 and parts[1] else None
        ge = int(parts[2]) if len(parts) > 2 and parts[2] else None

        sales = item.get("sales", "")
        try:
            sales = int(sales) if sales else None
        except ValueError:
            sales = None

        rows.append({
            "期号": item.get("code", ""),
            "开奖日期": clean_date,
            "开奖号码": red.replace(",", " "),
            "百位": bai,
            "十位": shi,
            "个位": ge,
            "销售额": sales,
        })

    df = pd.DataFrame(rows)
    df["开奖日期"] = pd.to_datetime(df["开奖日期"], errors="coerce")
    df = df.sort_values("开奖日期", ascending=True).reset_index(drop=True)
    df["年份"] = df["开奖日期"].dt.year
    return df


def save_data(df: pd.DataFrame):
    """保存数据"""
    excel_path = os.path.join(OUTPUT_DIR, "福彩3D历史开奖数据.xlsx")
    csv_path = os.path.join(OUTPUT_DIR, "福彩3D历史开奖数据.csv")

    # CSV (不含年份辅助列)
    save_df = df.drop(columns=["年份"])
    save_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"CSV已保存: {csv_path}")

    # 按年份分sheet的Excel
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        save_df.to_excel(writer, sheet_name="全部数据", index=False)
        for year, group in df.groupby("年份"):
            group.drop(columns=["年份"]).to_excel(
                writer, sheet_name=str(year), index=False
            )
    print(f"Excel已保存: {excel_path}")


def print_summary(df: pd.DataFrame):
    """打印统计摘要"""
    print("\n" + "=" * 60)
    print("[统计] 福彩3D历史数据摘要")
    print("=" * 60)

    date_min = df["开奖日期"].min().strftime("%Y-%m-%d")
    date_max = df["开奖日期"].max().strftime("%Y-%m-%d")
    print(f"时间范围: {date_min} ~ {date_max}")
    print(f"总期数: {len(df)}")

    # 各位置热号
    for pos, col in [("百位", "百位"), ("十位", "十位"), ("个位", "个位")]:
        top5 = df[col].value_counts().head(5)
        print(f"{pos}热号: {dict(top5)}")

    # 和值统计
    df["和值"] = df["百位"] + df["十位"] + df["个位"]
    print(f"和值范围: {df['和值'].min()} ~ {df['和值'].max()}, 均值: {df['和值'].mean():.1f}")
    print(f"最常见和值: {df['和值'].mode().tolist()}")

    # 形态统计
    df["组三"] = (df["百位"] == df["十位"]) | (df["十位"] == df["个位"]) | (df["百位"] == df["个位"])
    df["豹子"] = (df["百位"] == df["十位"]) & (df["十位"] == df["个位"])
    df["组六"] = ~df["组三"]

    n = len(df)
    g3 = df["组三"].sum()
    bz = df["豹子"].sum()
    g6 = df["组六"].sum()
    print(f"组三: {g3}期 ({g3/n*100:.1f}%), "
          f"豹子: {bz}期 ({bz/n*100:.1f}%), "
          f"组六: {g6}期 ({g6/n*100:.1f}%)")

    # 最近10期
    print(f"\n[最近10期]:")
    display_cols = ["期号", "开奖日期", "开奖号码", "和值"]
    recent = df.tail(10)[display_cols].copy()
    recent["开奖日期"] = recent["开奖日期"].dt.strftime("%Y-%m-%d")
    print(recent.to_string(index=False))

    print("=" * 60)


if __name__ == "__main__":
    import sys
    import io
    # Fix Unicode encoding on Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("[福彩3D] 历史开奖数据抓取")
    print(f"   数据来源: 中国福利彩票官网 (cwl.gov.cn)")
    print()

    records = fetch_fc3d_all()
    df = parse_records(records)
    save_data(df)
    print_summary(df)

    print(f"\n[完成] 数据文件在: {OUTPUT_DIR}")
