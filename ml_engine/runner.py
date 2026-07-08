"""Pipeline orchestration for ML training, similarity detection, and backtesting."""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ml_engine.pattern_extract import (
    DEFAULT_LOOKBACK,
    ML_INDICATOR_COLUMNS,
    build_window_dataset,
    extract_template_windows,
    extract_recent_template_windows_fast,
    extract_auto_launch_template_windows,
    list_cached_codes,
    load_candidate_codes,
    try_load_stock_name_map,
    normalize_code,
    extract_indicator_matrix,
    _window_to_record,
)
from ml_engine.ml_classifier import MLPatternModel
from ml_engine.similarity import rank_by_similarity, aggregate_stock_similarity
from ml_engine.eval import (
    compute_ml_backtest,
    compute_similarity_backtest,
    summarize_ml_by_hold_days,
    generate_similarity_report,
)

DEFAULT_MODEL_DIR = "output/ml_models"
DEFAULT_SIMILARITY_DIR = "output/ml_similarity"


def _template_info(templates: list[dict]) -> list[dict]:
    rows = []
    for i, t in enumerate(templates):
        rows.append({
            "模板索引": i,
            "模板代码": t.get("code", ""),
            "模板日期": str(t.get("date", ""))[:10],
            "窗口开始": str(t.get("window_start", ""))[:10],
            "窗口结束": str(t.get("window_end", ""))[:10],
            "来源": t.get("source", ""),
            "启动日": str(t.get("launch_date", ""))[:10] if t.get("launch_date") is not None else "",
            "启动日涨跌幅": round(float(t.get("launch_pct", 0)), 2) if t.get("launch_pct") is not None else "",
        })
    return rows


def train_model(
    template_codes: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    forward_horizon: int = 5,
    target_pct: float = 5.0,
    use_pca: bool = False,
    validation_split: float = 0.2,
    model_dir: str = DEFAULT_MODEL_DIR,
    only_template: bool = False,
) -> tuple[MLPatternModel, dict]:
    print(f"训练 ML 模型: {len(template_codes)} 只模板股票")
    template_codes = [normalize_code(c) for c in template_codes]
    t0 = time.time()
    X, y, _ = build_window_dataset(template_codes, lookback, forward_horizon, target_pct)
    if len(X) < 50:
        if only_template:
            print("  [提示] 已启用 --only-template，仅使用模板股票自身样本训练，不从全市场补充训练样本。")
        else:
            print("  [提示] 模板股票样本偏少，从全市场补充训练样本...")
            others = [c for c in list_cached_codes() if c not in set(template_codes)][:500]
            X2, y2, _ = build_window_dataset(others, lookback, forward_horizon, target_pct)
            if len(X2):
                X = np.vstack([X, X2]) if len(X) else X2
                y = np.concatenate([y, y2]) if len(y) else y2
    if len(X) < 50:
        raise RuntimeError(f"训练样本不足：{len(X)}，请增加模板股票或检查 cache/hist 数据")

    model = MLPatternModel(
        lookback=lookback,
        feature_cols=list(ML_INDICATOR_COLUMNS),
        use_pca=use_pca,
        n_components=min(50, max(2, X.shape[1] // 2)),
    )
    stats = model.fit(X, y, validation_split=validation_split)
    model.template_codes = template_codes
    model.forward_horizon = forward_horizon
    model.target_pct = target_pct
    model.train_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    stats.update({
        "template_codes": template_codes,
        "lookback": lookback,
        "forward_horizon": forward_horizon,
        "target_pct": target_pct,
        "train_time_seconds": round(time.time() - t0, 1),
    })
    os.makedirs(model_dir, exist_ok=True)
    safe_codes = "_".join(template_codes[:3])
    if len(template_codes) > 3:
        safe_codes += f"_plus{len(template_codes) - 3}"

    target_str = str(target_pct).replace(".", "p")
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    model_name = f"ml_pattern_{safe_codes}_lb{lookback}_h{forward_horizon}_t{target_str}_{ts}.pkl"
    model_path = os.path.join(model_dir, model_name)

    model.save(model_path)
    stats["model_path"] = model_path
    print(f"  模型已保存: {model_path}")
    if "validation" in stats:
        v = stats["validation"]
        print(f"  验证集: Acc={v['accuracy']:.3f} Prec={v['precision']:.3f} Recall={v['recall']:.3f} F1={v['f1']:.3f} AUC={v['auc_roc']:.3f}")
    return model, stats


def build_template_set(
    template_codes: list[str],
    lookback: int = DEFAULT_LOOKBACK,
    template_mode: str = "auto",
    date_start: str | None = None,
    date_end: str | None = None,
    recent_n: int = 3,
) -> list[dict]:
    template_codes = [normalize_code(c) for c in template_codes]
    if date_start and date_end:
        return extract_template_windows(template_codes, lookback=lookback, date_range=(date_start, date_end))
    if template_mode in ("auto", "prelaunch", "launch", "both", "recent"):
        mode = "prelaunch" if template_mode == "auto" else template_mode
        templates = extract_auto_launch_template_windows(
            template_codes,
            lookback=lookback,
            mode=mode,
            per_stock_limit=recent_n,
        )
        if templates:
            return templates
        print("  [提示] 自动启动窗口未找到，退回最近窗口模式")
        return extract_auto_launch_template_windows(template_codes, lookback=lookback, mode="recent", per_stock_limit=recent_n)
    return extract_template_windows(template_codes, lookback=lookback, recent_n=recent_n)


def _extract_candidate_windows_for_code(code: str, lookback: int, recent_windows: int) -> tuple[str, list[dict], str | None]:
    """Worker helper: extract recent windows for one candidate stock.

    Fast path: only read the tail of the CSV because Step 2 only compares
    current/recent windows. This avoids recalculating indicators over years of
    historical data for every stock.
    """
    try:
        tpls = extract_recent_template_windows_fast(code, lookback=lookback, recent_n=recent_windows)
        for t in tpls:
            t["code"] = code
        return code, tpls, None
    except Exception as exc:
        return code, [], str(exc)


def build_candidate_pool(
    candidate_codes: list[str],
    template_codes: list[str] | None = None,
    lookback: int = DEFAULT_LOOKBACK,
    recent_windows: int = 3,
    show_progress: bool = True,
    progress_every: int = 25,
    max_workers: int = 1,
) -> list[dict]:
    """Build current/recent candidate windows from the cached stock pool.

    In this project, cache/hist is treated as the user's stock pool.
    max_workers > 1 enables concurrent CSV reading and indicator extraction.
    Progress is printed in-place so long scans do not look frozen.
    """
    template_set = {normalize_code(c) for c in (template_codes or [])}
    codes = [normalize_code(c) for c in candidate_codes if normalize_code(c) not in template_set]
    total = len(codes)
    pool: list[dict] = []
    ok_stocks = 0
    done = 0
    start_ts = time.time()
    max_workers = max(1, int(max_workers or 1))

    def print_progress(current_code: str, force: bool = False) -> None:
        if not show_progress:
            return
        if not force and not (done == 1 or done % progress_every == 0 or done == total):
            return
        elapsed = max(time.time() - start_ts, 0.001)
        speed = done / elapsed if done else 0
        remain = (total - done) / speed if speed > 0 else 0
        msg = (
            f"\r  候选扫描进度: {done}/{total} | 当前: {current_code} "
            f"| 有效股票: {ok_stocks} | 窗口: {len(pool)} "
            f"| 并发: {max_workers} | 快速尾部读取 | 预计剩余: {remain/60:.1f} 分钟"
        )
        print(msg, end="", flush=True)

    if total == 0:
        return pool

    if max_workers <= 1:
        for code in codes:
            done += 1
            code, tpls, err = _extract_candidate_windows_for_code(code, lookback, recent_windows)
            if err and show_progress:
                print(f"\n  [跳过] {code} 提取窗口失败: {err}")
            if tpls:
                ok_stocks += 1
                pool.extend(tpls)
            print_progress(code)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_extract_candidate_windows_for_code, code, lookback, recent_windows): code
                for code in codes
            }
            for future in as_completed(future_map):
                done += 1
                code = future_map[future]
                try:
                    code, tpls, err = future.result()
                except Exception as exc:
                    tpls = []
                    err = str(exc)
                if err and show_progress:
                    print(f"\n  [跳过] {code} 提取窗口失败: {err}")
                if tpls:
                    ok_stocks += 1
                    pool.extend(tpls)
                print_progress(code)

    if show_progress:
        print_progress(codes[-1], force=True)
        print()
    return pool


def find_similar_stocks(
    template_codes: list[str],
    candidate_codes: list[str] | None = None,
    lookback: int = DEFAULT_LOOKBACK,
    min_similarity: float = 0.60,
    top_k: int = 50,
    output_dir: str = DEFAULT_SIMILARITY_DIR,
    template_mode: str = "auto",
    recent_windows: int = 3,
    template_recent_n: int = 3,
    candidate_file: str | None = None,
    use_selected_file: bool = False,
    workers: int = 1,
    date_start: str | None = None,
    date_end: str | None = None,
) -> pd.DataFrame:
    template_codes = [normalize_code(c) for c in template_codes]
    if candidate_codes is None:
        candidate_codes = load_candidate_codes(candidate_file, default_selected=use_selected_file)
    else:
        candidate_codes = [normalize_code(c) for c in candidate_codes]

    print(f"相似度扫描: {len(template_codes)} 只模板 → {len(candidate_codes)} 只候选")
    t0 = time.time()
    templates = build_template_set(template_codes, lookback, template_mode, date_start, date_end, recent_n=template_recent_n)
    if not templates:
        print("  [!] 无法提取模板窗口")
        return pd.DataFrame()
    template_vectors = [t["vector"] for t in templates]
    print(f"  模板窗口: {len(templates)} 个")
    for info in _template_info(templates)[:10]:
        print(f"    {info['模板代码']} {info['窗口开始']}~{info['窗口结束']} 来源={info['来源']} 启动日={info['启动日']}")

    candidate_pool = build_candidate_pool(candidate_codes, template_codes, lookback, recent_windows, show_progress=True, max_workers=workers)
    print(f"  候选窗口: {len(candidate_pool)} 个（每股最近 {recent_windows} 个）")

    detail_df = rank_by_similarity(
        template_vectors,
        candidate_pool,
        min_similarity=min_similarity,
        top_k=top_k * 20,
        max_candidates=0,
        scaler=None,
    )
    if detail_df.empty:
        print(f"  [!] 无匹配结果，相似度均低于 {min_similarity * 100:.0f}%")
        return pd.DataFrame()
    detail_df = detail_df[~detail_df["候选代码"].isin(template_codes)]
    name_map = try_load_stock_name_map()
    stock_df = aggregate_stock_similarity(detail_df, stock_name_map=name_map).head(top_k)
    print(f"  完成 ({time.time() - t0:.1f}s): 输出 {len(stock_df)} 只股票")

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"similarity_scan_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    generate_similarity_report(detail_df, stock_df, template_info=_template_info(templates), output_file=path)
    print(f"  报告已保存: {path}")
    return stock_df


def match_single_stock_pattern(
    template_code: str,
    date_start: str,
    date_end: str,
    lookback: int = DEFAULT_LOOKBACK,
    similarity_threshold: float = 0.60,
    top_k: int = 20,
    hold_days_list: list[int] | None = None,
    recent_windows: int = 3,
    output_dir: str = DEFAULT_SIMILARITY_DIR,
    candidate_file: str | None = None,
    use_selected_file: bool = False,
    backtest_scope: str = "all_candidates",
    skip_backtest: bool = False,
    workers: int = 1,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict:
    if hold_days_list is None:
        hold_days_list = [1, 3, 5, 10]
    template_code = normalize_code(template_code)
    results = {}

    print("\n" + "=" * 60)
    print(f"Step 1/3: 提取模板形态 — {template_code} ({date_start} ~ {date_end})")
    print("=" * 60)
    templates = extract_template_windows([template_code], lookback=lookback, date_range=(date_start, date_end))
    if not templates:
        raise RuntimeError(f"无法从 {template_code} 在 {date_start}~{date_end} 提取模板窗口")
    template_vectors = [t["vector"] for t in templates]
    for info in _template_info(templates):
        print(f"  模板{info['模板索引']}: {info['窗口开始']}~{info['窗口结束']}")

    print("\n" + "=" * 60)
    print("Step 2/3: 扫描 cache/hist 股票池当前最近形态")
    print("=" * 60)
    candidate_codes = [c for c in load_candidate_codes(candidate_file, default_selected=use_selected_file) if c != template_code]
    candidate_pool = build_candidate_pool(candidate_codes, [template_code], lookback, recent_windows, show_progress=True, max_workers=workers)
    print(f"  候选股票: {len(candidate_codes)} 只；候选窗口: {len(candidate_pool)} 个")
    detail_df = rank_by_similarity(template_vectors, candidate_pool, min_similarity=similarity_threshold, top_k=top_k * 20, max_candidates=0, scaler=None)
    if detail_df.empty:
        print("  [!] 无匹配结果")
        return {"similarity_df": pd.DataFrame(), "backtest_trades": pd.DataFrame(), "backtest_summary": pd.DataFrame()}
    name_map = try_load_stock_name_map()
    stock_df = aggregate_stock_similarity(detail_df, stock_name_map=name_map).head(top_k)
    results["similarity_df"] = stock_df
    results["template_info"] = _template_info(templates)
    print(f"  Top {len(stock_df)} 相似股票:")
    for _, row in stock_df.iterrows():
        print(f"    {row['代码']} {row.get('名称', '')}: 平均{row['平均相似度%']}% 最大{row['最大相似度%']}% 匹配{int(row['匹配次数'])}次")

    print("\n" + "=" * 60)
    print("Step 3/3: 相似度历史回测")
    print("=" * 60)

    trades_df = pd.DataFrame()
    summary = pd.DataFrame()

    if skip_backtest:
        print("  已跳过历史回测，只输出当前相似度排名。")
        print("  如需验证历史胜率，去掉 --skip-backtest 后重新运行。")
    else:
        if backtest_scope == "topk":
            backtest_codes = stock_df["代码"].tolist()
            print(f"  回测范围: TopK {len(backtest_codes)} 只")
        else:
            backtest_codes = candidate_codes
            print(f"  回测范围: cache/hist 股票池候选 {len(backtest_codes)} 只")
        trades_df = compute_similarity_backtest(
            template_vectors,
            backtest_codes,
            hold_days_list=hold_days_list,
            similarity_threshold=similarity_threshold,
            lookback=lookback,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        summary = summarize_ml_by_hold_days(trades_df) if not trades_df.empty else pd.DataFrame()
        if not summary.empty:
            print(summary.to_string(index=False))
        else:
            print("  [!] 回测无交易信号")

    results["backtest_trades"] = trades_df
    results["backtest_summary"] = summary

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, f"pattern_match_{template_code}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    generate_similarity_report(
        detail_df,
        stock_df,
        template_info=_template_info(templates),
        backtest_trades=trades_df,
        backtest_summary=summary,
        output_file=report_path,
    )
    results["report_path"] = report_path
    print(f"\n报告已保存: {report_path}")
    return results


def train_model_from_date_ranges(
    stock_ranges: list[dict],
    lookback: int = DEFAULT_LOOKBACK,
    forward_horizon: int = 5,
    target_pct: float = 5.0,
    use_pca: bool = False,
    validation_split: float = 0.2,
    model_dir: str = "高胜率pkl",
    supplement_negatives: bool = True,
) -> tuple[MLPatternModel, dict]:
    """多股票+各自时间段 → 提取形态 → 训练ML模型 → 生成.pkl

    Args:
        stock_ranges: [{"code": "600288", "date_start": "2026-06-20", "date_end": "2026-07-08"}, ...]
        lookback: 窗口天数，默认20
        forward_horizon: 预测未来N天，默认5
        target_pct: 目标涨幅%，默认5.0
        use_pca: 是否使用PCA降维
        validation_split: 验证集比例
        model_dir: 模型输出目录，默认"高胜率pkl"
        supplement_negatives: 是否从其他股票补充负样本

    Returns:
        (model, stats_dict)
    """
    template_codes = []
    all_template_windows = []

    print("=" * 60)
    print(f"Step 1/3: 提取 {len(stock_ranges)} 只模板股票的指定时间段形态")
    print("=" * 60)

    for item in stock_ranges:
        code = normalize_code(item["code"])
        date_start = item["date_start"]
        date_end = item["date_end"]
        template_codes.append(code)

        templates = extract_template_windows(
            [code], lookback=lookback, date_range=(date_start, date_end)
        )
        all_template_windows.extend(templates)
        print(f"  {code} ({date_start} ~ {date_end}): 提取 {len(templates)} 个窗口")

    if not all_template_windows:
        raise RuntimeError("未能从任何指定时间段提取到有效窗口，请检查日期范围和缓存数据")

    template_vectors = np.array([t["vector"] for t in all_template_windows], dtype=np.float64)
    print(f"  合计: {len(all_template_windows)} 个模板窗口，向量维度: {template_vectors.shape[1]}")

    print(f"\n{'=' * 60}")
    print(f"Step 2/3: 构建训练集 & 训练 ML 模型")
    print(f"{'=' * 60}")

    t0 = time.time()

    # 正样本：模板股票在指定时间段内的窗口
    X_pos = template_vectors
    y_pos = np.ones(len(X_pos), dtype=np.int32)

    # 负样本：同一批模板股票在指定时间段之外的窗口 + 其他股票的窗口
    X_neg_list, y_neg_list = [], []
    if supplement_negatives:
        # 从模板股票自身取负样本（指定时间段外的窗口）
        for item in stock_ranges:
            code = normalize_code(item["code"])
            date_start = pd.Timestamp(item["date_start"])
            date_end = pd.Timestamp(item["date_end"])
            df = extract_indicator_matrix(code, min_rows=80)
            if df.empty:
                continue
            for t in range(lookback - 1, len(df)):
                d = df.iloc[t]["日期"]
                if date_start <= d <= date_end:
                    continue  # 跳过指定时间段（已作为正样本）
                rec = _window_to_record(code, df, t, lookback, source="neg_self")
                if rec is not None:
                    X_neg_list.append(rec["vector"])
                    y_neg_list.append(0)

        # 从其他股票补充负样本
        others = [c for c in list_cached_codes() if c not in set(template_codes)][:300]
        print(f"  从 {len(others)} 只其他股票补充负样本...")
        for code in others:
            df = extract_indicator_matrix(code, min_rows=80)
            if df.empty:
                continue
            # 每只股票随机取最多5个窗口作为负样本
            indices = list(range(lookback - 1, len(df)))
            if len(indices) > 5:
                indices = sorted(np.random.choice(indices, 5, replace=False))
            for t in indices:
                rec = _window_to_record(code, df, t, lookback, source="neg_other")
                if rec is not None:
                    X_neg_list.append(rec["vector"])
                    y_neg_list.append(0)

    if X_neg_list:
        X = np.vstack([X_pos, np.array(X_neg_list, dtype=np.float64)])
        y = np.concatenate([y_pos, np.array(y_neg_list, dtype=np.int32)])
    else:
        X, y = X_pos, y_pos

    # 平衡正负样本
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_neg > n_pos * 3:
        # 降采样负样本到正样本的3倍
        neg_idx = np.where(y == 0)[0]
        keep_neg = np.random.choice(neg_idx, n_pos * 3, replace=False)
        pos_idx = np.where(y == 1)[0]
        keep = np.sort(np.concatenate([pos_idx, keep_neg]))
        X, y = X[keep], y[keep]

    print(f"  训练集: {len(X)} 样本 (正:{int(np.sum(y==1))} 负:{int(np.sum(y==0))})")
    print(f"  正样本比例: {np.mean(y):.1%}")

    if len(X) < 20:
        raise RuntimeError(f"训练样本不足：{len(X)}，请增加模板股票或扩大日期范围")

    model = MLPatternModel(
        lookback=lookback,
        feature_cols=list(ML_INDICATOR_COLUMNS),
        use_pca=use_pca,
        n_components=min(50, max(2, X.shape[1] // 2)),
    )
    stats = model.fit(X, y, validation_split=validation_split)
    model.template_codes = template_codes
    model.forward_horizon = forward_horizon
    model.target_pct = target_pct
    model.train_time = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    # 保存模板日期范围信息
    model.template_ranges = [
        {"code": item["code"], "date_start": item["date_start"], "date_end": item["date_end"]}
        for item in stock_ranges
    ]

    stats.update({
        "template_codes": template_codes,
        "template_ranges": model.template_ranges,
        "n_template_windows": len(all_template_windows),
        "lookback": lookback,
        "forward_horizon": forward_horizon,
        "target_pct": target_pct,
        "train_time_seconds": round(time.time() - t0, 1),
    })

    print(f"\n{'=' * 60}")
    print(f"Step 3/3: 保存模型")
    print(f"{'=' * 60}")

    os.makedirs(model_dir, exist_ok=True)
    safe_codes = "_".join(template_codes[:4])
    if len(template_codes) > 4:
        safe_codes += f"_plus{len(template_codes) - 4}"
    target_str = str(target_pct).replace(".", "p")
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    model_name = f"multi_range_{safe_codes}_lb{lookback}_h{forward_horizon}_t{target_str}_{ts}.pkl"
    model_path = os.path.join(model_dir, model_name)

    model.save(model_path)
    stats["model_path"] = model_path
    print(f"  模型已保存: {model_path}")

    if "validation" in stats:
        v = stats["validation"]
        print(f"  验证集: Acc={v['accuracy']:.3f} Prec={v['precision']:.3f} Recall={v['recall']:.3f} F1={v['f1']:.3f} AUC={v['auc_roc']:.3f}")

    return model, stats


def run_ml_pipeline(
    template_codes: list[str],
    candidate_codes: list[str] | None = None,
    lookback: int = DEFAULT_LOOKBACK,
    forward_horizon: int = 5,
    target_pct: float = 5.0,
    similarity_threshold: float = 0.60,
    hold_days_list: list[int] | None = None,
    top_k: int = 50,
    use_pca: bool = False,
    template_mode: str = "auto",
) -> dict:
    if hold_days_list is None:
        hold_days_list = [1, 3, 5, 10]
    model, stats = train_model(template_codes, lookback, forward_horizon, target_pct, use_pca)
    similarity_df = find_similar_stocks(template_codes, candidate_codes, lookback, similarity_threshold, top_k, template_mode=template_mode)
    backtest_codes = similarity_df["代码"].tolist() if not similarity_df.empty else (candidate_codes or list_cached_codes()[:100])
    trades = compute_ml_backtest(model, backtest_codes, hold_days_list=hold_days_list)
    summary = summarize_ml_by_hold_days(trades) if not trades.empty else pd.DataFrame()
    return {"model": model, "stats": stats, "similarity_df": similarity_df, "backtest_trades": trades, "backtest_summary": summary}
