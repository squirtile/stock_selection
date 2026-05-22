"""Pattern similarity computation and ranking."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_cosine_similarity(query: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return np.zeros(len(candidates))
    c_norms = np.linalg.norm(candidates, axis=1)
    c_norms = np.where(c_norms == 0, 1.0, c_norms)
    return np.dot(candidates, query) / (q_norm * c_norms)


def _compute_cosine_similarity_batched(query: np.ndarray, candidates: np.ndarray, batch_size: int = 5000) -> np.ndarray:
    n = len(candidates)
    sims = np.empty(n, dtype=np.float64)
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return np.zeros(n)
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch = candidates[start:end]
        c_norms = np.linalg.norm(batch, axis=1)
        c_norms = np.where(c_norms == 0, 1.0, c_norms)
        sims[start:end] = np.dot(batch, query) / (q_norm * c_norms)
    return sims


def _dtw_distance(s1: np.ndarray, s2: np.ndarray, window: int = 3) -> float:
    n, m = len(s1), len(s2)
    window = max(window, abs(n - m))
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - window), min(m, i + window) + 1):
            cost = abs(s1[i - 1] - s2[j - 1])
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return float(dtw[n, m])


def compute_dtw_similarity(query_window: np.ndarray, candidate_window: np.ndarray, window_radius: int | None = None) -> float:
    lookback, n_ind = query_window.shape
    if window_radius is None:
        window_radius = max(3, lookback // 5)
    total = 0.0
    valid = 0
    for col in range(n_ind):
        q = query_window[:, col]
        c = candidate_window[:, col]
        rng = np.ptp(np.concatenate([q, c]))
        if rng == 0:
            continue
        dist = _dtw_distance(q, c, window=window_radius)
        total += dist / (lookback * rng)
        valid += 1
    if valid == 0:
        return 1.0
    return float(1.0 / (1.0 + total / valid))


def cosine_similarity_to_pct(sim: float) -> float:
    return max(0.0, sim * 100)


def rank_by_similarity(
    template_vectors: list[np.ndarray],
    candidate_pool: list[dict],
    min_similarity: float = 0.60,
    top_k: int = 50,
    batch_size: int = 5000,
    max_candidates: int = 0,
    scaler=None,
) -> pd.DataFrame:
    """
    Rank candidates by maximum cosine similarity to template vectors.

    Important: if scaler is None, a StandardScaler is fitted on template + candidate vectors together.
    This fixes the old issue where only template vectors were used to fit the scaler.
    Set max_candidates=0 to avoid downsampling and get strict full ranking.
    """
    if not template_vectors or not candidate_pool:
        return pd.DataFrame()

    if max_candidates and len(candidate_pool) > max_candidates:
        # Keep latest records if caller sorted each stock chronologically before extension.
        candidate_pool = candidate_pool[-max_candidates:]
        print(f"  (候选池过大，仅保留最近 {len(candidate_pool)} 个窗口；需要严格全量请设置 max_candidates=0)")

    cand_matrix = np.array([c["vector"] for c in candidate_pool], dtype=np.float64)
    tpl_matrix = np.array([np.asarray(v, dtype=np.float64) for v in template_vectors], dtype=np.float64)
    if cand_matrix.size == 0 or tpl_matrix.size == 0:
        return pd.DataFrame()

    if scaler is not None:
        cand_matrix = scaler.transform(cand_matrix)
        tpl_matrix = scaler.transform(tpl_matrix)
    else:
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        scaler.fit(np.vstack([tpl_matrix, cand_matrix]))
        tpl_matrix = scaler.transform(tpl_matrix)
        cand_matrix = scaler.transform(cand_matrix)

    all_matches = []
    for tidx, tpl_vec in enumerate(tpl_matrix):
        if not np.all(np.isfinite(tpl_vec)):
            continue
        sims = _compute_cosine_similarity_batched(tpl_vec, cand_matrix, batch_size=batch_size)
        idxs = np.where(sims >= min_similarity)[0]
        for i in idxs:
            c = candidate_pool[i]
            all_matches.append({
                "候选代码": c.get("code", ""),
                "候选日期": str(c.get("date", ""))[:10],
                "窗口开始": str(c.get("window_start", ""))[:10],
                "窗口结束": str(c.get("window_end", ""))[:10],
                "收盘价": c.get("close", None),
                "相似度%": round(cosine_similarity_to_pct(float(sims[i])), 1),
                "匹配模板索引": tidx,
                "模板来源": c.get("source", ""),
            })
    if not all_matches:
        return pd.DataFrame()
    df = pd.DataFrame(all_matches).sort_values("相似度%", ascending=False).reset_index(drop=True)
    return df.head(top_k) if top_k else df


def aggregate_stock_similarity(similarity_results: pd.DataFrame, stock_name_map: dict[str, str] | None = None) -> pd.DataFrame:
    if similarity_results.empty:
        return pd.DataFrame()
    grouped = (
        similarity_results.groupby("候选代码")
        .agg(
            平均相似度=("相似度%", "mean"),
            最大相似度=("相似度%", "max"),
            匹配次数=("相似度%", "count"),
            最新匹配日期=("候选日期", "max"),
        )
        .reset_index()
        .rename(columns={"候选代码": "代码"})
    )
    grouped["平均相似度%"] = grouped.pop("平均相似度").round(1)
    grouped["最大相似度%"] = grouped.pop("最大相似度").round(1)
    if stock_name_map:
        grouped["名称"] = grouped["代码"].map(stock_name_map).fillna("")
        cols = ["代码", "名称", "平均相似度%", "最大相似度%", "匹配次数", "最新匹配日期"]
    else:
        cols = ["代码", "平均相似度%", "最大相似度%", "匹配次数", "最新匹配日期"]
    grouped = grouped.sort_values(["平均相似度%", "最大相似度%", "匹配次数"], ascending=[False, False, False])
    return grouped[cols].reset_index(drop=True)
