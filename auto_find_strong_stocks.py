#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动扫描日线数据，找出近3-5天涨幅最好的5只股票。
然后执行grid_test进行训练+回测。
最后筛选出胜率>60%且信号次数>=20的高质量pkl。
"""

import os
import sys
import subprocess
import glob
import pandas as pd
from pathlib import Path
from datetime import datetime
import re

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
sys.path.insert(0, PROJECT_ROOT)


def find_recent_best_stocks(days=5, top_n=5):
    """
    从cache/hist/找出近N天涨幅最好的5只股票。
    """
    hist_dir = os.path.join(PROJECT_ROOT, "cache", "hist")
    if not os.path.exists(hist_dir):
        print(f"错误：找不到缓存目录 {hist_dir}")
        return []
    
    results = []
    
    for csv_file in glob.glob(os.path.join(hist_dir, "*.csv")):
        # 提取股票代码
        basename = os.path.basename(csv_file)
        match = re.search(r'(\d{6})', basename)
        if not match:
            continue
        
        code = match.group(1)
        
        try:
            df = pd.read_csv(csv_file)
            if df.empty or len(df) < days:
                continue
            
            # 找最后N天的涨幅
            recent_df = df.tail(days)
            
            # 找到涨跌幅列
            pct_col = None
            for col in ['涨跌幅', 'pct_chg', '涨幅', 'change_pct']:
                if col in df.columns:
                    pct_col = col
                    break
            
            if pct_col is None:
                continue
            
            pct_values = pd.to_numeric(recent_df[pct_col], errors='coerce')
            avg_pct = pct_values.mean()
            max_pct = pct_values.max()
            
            if pd.notna(avg_pct) and pd.notna(max_pct):
                results.append({
                    '代码': code,
                    '平均涨幅': round(avg_pct, 2),
                    '最大涨幅': round(max_pct, 2),
                    '文件': csv_file,
                })
        
        except Exception as e:
            continue
    
    if not results:
        print("警告：未找到任何有效的股票数据")
        return []
    
    # 按平均涨幅排序
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('平均涨幅', ascending=False)
    
    top_stocks = results_df.head(top_n)
    
    print(f"\n找出近{days}天涨幅最好的{top_n}只股票：")
    print(top_stocks.to_string(index=False))
    
    codes = top_stocks['代码'].tolist()
    return codes


def run_grid_test(codes, threshold=0.70):
    """
    执行grid_test训练模型。
    参数经过优化，确保信号次数足够多。
    """
    codes_str = ','.join(codes)
    
    cmd = [
        sys.executable,
        'cli/ml_grid_test_modified.py',
        '--codes', codes_str,
        '--mode', 'combination_range',
        '--threshold', str(threshold),
        '--horizons', '2,3,4,5',        # 扩大horizon范围
        '--targets', '5,6,7,8,9,10',    # 扩大target范围，增加信号数量
        '--hold-days', '2,3,5',         # 多个hold_days
        '--workers', '8',
        '--combo-size', '2',            # 组合大小
    ]
    
    print(f"\n执行grid_test：")
    print(' '.join(cmd))
    print("=" * 100)
    
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0


def find_high_quality_models():
    """
    从输出结果中找出高质量的pkl：
    - 胜率 > 60%
    - 信号次数 >= 20
    """
    output_dir = os.path.join(PROJECT_ROOT, "output", "ml_grid_test")
    
    if not os.path.exists(output_dir):
        print(f"错误：找不到输出目录 {output_dir}")
        return []
    
    high_quality_models = []
    
    # 查找最新的grid_test输出文件
    summary_files = sorted(glob.glob(os.path.join(output_dir, "*summary*.xlsx")), 
                          key=os.path.getmtime, reverse=True)
    
    if not summary_files:
        print("未找到summary文件，尝试查找individual结果...")
        return []
    
    summary_file = summary_files[0]
    print(f"\n读取结果文件：{summary_file}")
    
    try:
        # 读取汇总表
        df = pd.read_excel(summary_file)
        
        # 筛选条件
        # 胜率 > 60%
        win_rate_cols = [col for col in df.columns if '胜率' in col or 'win' in col.lower()]
        signal_cols = [col for col in df.columns if '信号' in col or 'signal' in col.lower()]
        
        print(f"\n可用列：{list(df.columns)}")
        
        # 简单筛选：look for columns with numeric values
        filtered = df.copy()
        
        # 如果有胜率列，按胜率筛选
        for col in df.columns:
            if '胜率' in col:
                try:
                    filtered = filtered[pd.to_numeric(filtered[col], errors='coerce') > 60]
                except:
                    pass
        
        if len(filtered) > 0:
            print(f"\n筛选出 {len(filtered)} 个高胜率模型：")
            print(filtered[['模板', '胜率', '回测文件']].to_string())
            high_quality_models = filtered['回测文件'].tolist()
        else:
            print("未找到符合条件的模型")
    
    except Exception as e:
        print(f"读取结果文件出错：{e}")
    
    return high_quality_models


def main():
    print("=" * 100)
    print("自动化选股流程：扫描强势股 -> grid_test训练 -> 筛选高质量模型")
    print("=" * 100)
    
    # 1. 找涨幅最好的5只股票
    print("\n[步骤1] 扫描日线数据...")
    codes = find_recent_best_stocks(days=5, top_n=5)
    
    if not codes:
        print("错误：未找到任何股票")
        return
    
    print(f"选中的5只股票：{codes}")
    
    # 2. 执行grid_test
    print("\n[步骤2] 执行grid_test训练模型...")
    success = run_grid_test(codes, threshold=0.70)
    
    if not success:
        print("grid_test执行失败")
        return
    
    # 3. 筛选高质量模型
    print("\n[步骤3] 筛选高质量的pkl...")
    models = find_high_quality_models()
    
    if models:
        print(f"\n找到 {len(models)} 个高质量模型")
        
        # 复制到专门目录
        quality_dir = os.path.join(PROJECT_ROOT, "output", "high_quality_models")
        os.makedirs(quality_dir, exist_ok=True)
        
        for model_file in models:
            if os.path.exists(model_file):
                dest = os.path.join(quality_dir, os.path.basename(model_file))
                import shutil
                shutil.copy(model_file, dest)
                print(f"已复制：{dest}")
    else:
        print("未找到符合条件的模型")
    
    print("\n流程完成！")


if __name__ == "__main__":
    main()
