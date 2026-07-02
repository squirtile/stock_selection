"""
补充拉取2004-2012年福彩3D数据 (从500.com爬取)
"""

import requests
import pandas as pd
import re
import time
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output", "fc3d")

session = requests.Session()
session.trust_env = False
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def fetch_year_from_500(year):
    """从500.com获取指定年份的3D数据"""
    # 500.com historical data by year
    url = f'https://kaijiang.500.com/static/info/kaijiang/xml/sd/{year}.xml'
    r = session.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  {year}年: HTTP {r.status_code}")
        return []

    # Parse XML - extract row data
    content = r.text
    # Pattern: expect,opencode,opentime
    rows = re.findall(
        r'<row[^>]*expect="(\d+)"[^>]*opencode="(\d\s+\d\s+\d)"[^>]*opentime="([^"]*)"',
        content
    )
    records = []
    for expect, opencode, opentime in rows:
        balls = opencode.split()
        records.append({
            '期号': expect,
            '开奖日期': opentime[:10],
            '百位': int(balls[0]),
            '十位': int(balls[1]),
            '个位': int(balls[2]),
            '开奖号码': opencode,
            '销售额': None,
        })

    print(f"  {year}年: {len(records)} 条")
    return records


def fetch_old_data():
    """获取2004-2012年的数据"""
    all_records = []

    for year in range(2004, 2013):
        records = fetch_year_from_500(year)
        all_records.extend(records)
        time.sleep(1)  # Be polite

    return all_records


def main():
    print("=" * 60)
    print("[补充] 福彩3D 2004-2012年历史数据拉取")
    print("数据来源: 500.com")
    print("=" * 60)

    records = fetch_old_data()
    if not records:
        print("未获取到任何数据!")
        return

    df = pd.DataFrame(records)
    df['开奖日期'] = pd.to_datetime(df['开奖日期'], errors='coerce')
    df = df.sort_values('开奖日期', ascending=True).reset_index(drop=True)

    print(f"\n获取到 {len(df)} 条记录")
    print(f"日期范围: {df['开奖日期'].min().strftime('%Y-%m-%d')} ~ {df['开奖日期'].max().strftime('%Y-%m-%d')}")

    # Save
    csv_path = os.path.join(OUTPUT_DIR, "福彩3D历史数据_2004-2012.csv")
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"已保存: {csv_path}")

    # Merge with existing data
    existing_csv = os.path.join(OUTPUT_DIR, "福彩3D历史开奖数据.csv")
    if os.path.exists(existing_csv):
        existing_df = pd.read_csv(existing_csv, encoding='utf-8-sig')
        existing_df['开奖日期'] = pd.to_datetime(existing_df['开奖日期'], errors='coerce')

        # Deduplicate by 期号
        merged = pd.concat([df, existing_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=['期号'], keep='first')
        merged = merged.sort_values('开奖日期', ascending=True).reset_index(drop=True)

        print(f"\n合并后总计: {len(merged)} 条")
        print(f"日期范围: {merged['开奖日期'].min().strftime('%Y-%m-%d')} ~ {merged['开奖日期'].max().strftime('%Y-%m-%d')}")

        # Save merged
        merged_csv = os.path.join(OUTPUT_DIR, "福彩3D历史开奖数据_完整.csv")
        merged.to_csv(merged_csv, index=False, encoding='utf-8-sig')
        print(f"完整数据: {merged_csv}")

        # Excel
        try:
            excel_path = os.path.join(OUTPUT_DIR, "福彩3D历史开奖数据_完整.xlsx")
            merged.to_excel(excel_path, index=False, sheet_name='福彩3D')
            print(f"完整Excel: {excel_path}")
        except Exception as e:
            print(f"Excel保存失败: {e}")

        # Quick stats
        print(f"\n[统计]")
        print(f"最早10期:")
        for _, r in merged.head(10).iterrows():
            print(f"  {r['期号']} | {r['开奖日期'].strftime('%Y-%m-%d')} | {r['开奖号码']}")
        print(f"\n最近10期:")
        for _, r in merged.tail(10).iterrows():
            print(f"  {r['期号']} | {r['开奖日期'].strftime('%Y-%m-%d')} | {r['开奖号码']}")


if __name__ == "__main__":
    main()
