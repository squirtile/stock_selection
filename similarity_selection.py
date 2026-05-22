import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.metrics.pairwise import cosine_similarity

def compute_features(df):
    """
    计算特征：
    - MA5, MA10, MA20
    - 均线斜率
    - 振幅
    - 成交量均值
    - 收盘价距离MA20
    """
    df = df.copy()
    df['收盘'] = pd.to_numeric(df['收盘'], errors='coerce')
    df['最高'] = pd.to_numeric(df['最高'], errors='coerce')
    df['最低'] = pd.to_numeric(df['最低'], errors='coerce')
    df['成交量'] = pd.to_numeric(df['成交量'], errors='coerce')

    df['MA5'] = df['收盘'].rolling(5).mean()
    df['MA10'] = df['收盘'].rolling(10).mean()
    df['MA20'] = df['收盘'].rolling(20).mean()
    df['VOL20'] = df['成交量'].rolling(20).mean()
    df['振幅'] = (df['最高'] - df['最低']) / df['最低']

    df['MA5_slope'] = df['MA5'].diff()
    df['MA10_slope'] = df['MA10'].diff()
    df['MA20_slope'] = df['MA20'].diff()
    df['close_dist_ma20'] = df['收盘'] / df['MA20'] - 1

    df = df.dropna()
    feature_cols = ['MA5', 'MA10', 'MA20', 'VOL20', '振幅', 'MA5_slope', 'MA10_slope', 'MA20_slope', 'close_dist_ma20']
    return df[feature_cols]

def read_stock_data(file_path):
    """读取股票 CSV/Excel"""
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path, dtype={'代码': str})
    else:
        df = pd.read_excel(file_path, dtype={'代码': str})
    return df

def find_similar_stocks(strong_stock_file, pool_file, n_top=20, days=30):
    # 1. 读取强势股
    strong_df = read_stock_data(strong_stock_file)
    # 取最近 days 天
    strong_df['日期'] = pd.to_datetime(strong_df['日期'])
    strong_df = strong_df.sort_values('日期')
    strong_recent = strong_df.groupby('代码').tail(days)

    # 2. 提取特征
    strong_features_list = []
    for code, g in strong_recent.groupby('代码'):
        feats = compute_features(g)
        if not feats.empty:
            strong_features_list.append(feats.values.mean(axis=0))
    strong_features = np.array(strong_features_list)

    # 3. 读取股票池
    pool_df = read_stock_data(pool_file)
    pool_df['日期'] = pd.to_datetime(pool_df['日期'])
    pool_df = pool_df.sort_values('日期')
    pool_features_list = []
    pool_codes = []
    for code, g in pool_df.groupby('代码'):
        g_recent = g.tail(days)
        feats = compute_features(g_recent)
        if not feats.empty:
            pool_features_list.append(feats.values.mean(axis=0))
            pool_codes.append(code)

    pool_features = np.array(pool_features_list)

    # 4. 标准化
    scaler = StandardScaler()
    all_features = np.vstack([strong_features, pool_features])
    scaler.fit(all_features)
    strong_scaled = scaler.transform(strong_features)
    pool_scaled = scaler.transform(pool_features)

    # 5. 计算欧氏距离和余弦相似度
    euclidean_dists = np.linalg.norm(pool_scaled[:, np.newaxis] - strong_scaled[np.newaxis, :], axis=2)
    min_dists = euclidean_dists.min(axis=1)
    cosine_sims = cosine_similarity(pool_scaled, strong_scaled)
    max_sims = cosine_sims.max(axis=1)

    # 6. 结果汇总
    result = pd.DataFrame({
        '代码': pool_codes,
        '欧氏距离': min_dists,
        '余弦相似度': max_sims
    })

    # 7. 按余弦相似度排序，取前 n_top
    top_stocks = result.sort_values('余弦相似度', ascending=False).head(n_top)

    output_file = 'top_similar_stocks.xlsx'
    top_stocks.to_excel(output_file, index=False)
    print(f'前 {n_top} 相似股票已保存到 {output_file}')

    return top_stocks

if __name__ == "__main__":
    # 示例用法
    strong_file = "strong_stocks.csv"  # 你的历史强势股文件
    pool_file = "output/a_stock_selected.xlsx"  # 股票池文件
    find_similar_stocks(strong_file, pool_file)