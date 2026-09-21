"""从本地30分钟缓存学习“低涨幅股票随后盘中触及涨停”的过滤规则。

严格按时间切分训练/验证；分别在10:00和10:30截取当时可见数据，标签只
查看检查点之后是否首次触及涨停，且强制检查点涨幅不超过3%。
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MINUTE_DIR = ROOT / "cache" / "minute"
OUTPUT_FILE = ROOT / "output" / "intraday_learned_strategy.json"
CHECKPOINTS = ["10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30"]


def _extract_samples(path: Path) -> list[dict]:
    try:
        df = pd.read_csv(path)
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        for col in ["开盘", "最高", "最低", "收盘", "成交量"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["datetime", "开盘", "最高", "最低", "收盘", "成交量"])
        df = df[(df[["开盘", "最高", "最低", "收盘"]] > 0).all(axis=1)].sort_values("datetime")
    except Exception:
        return []
    if df.empty:
        return []

    days = [(date, group.reset_index(drop=True)) for date, group in df.groupby(df["datetime"].dt.date)]
    samples = []
    prior_checkpoint_volumes: dict[int, list[float]] = {i: [] for i in range(1, len(CHECKPOINTS) + 1)}
    previous_close = None
    for date, day in days:
        for checkpoint_size, checkpoint_name in enumerate(CHECKPOINTS, 1):
            if previous_close and len(day) > checkpoint_size:
                checkpoint = day.iloc[:checkpoint_size]
                future = day.iloc[checkpoint_size:]
                limit_price = previous_close * 1.095  # 兼容涨停价按分取整
                already_hit = float(checkpoint["最高"].max()) >= limit_price
                history = prior_checkpoint_volumes[checkpoint_size]
                expected_volume = pd.Series(history[-5:]).median() if history else math.nan
                cumulative_volume = float(checkpoint["成交量"].sum())
                if not already_hit and expected_volume and pd.notna(expected_volume) and expected_volume > 0:
                    high, low = float(checkpoint["最高"].max()), float(checkpoint["最低"].min())
                    close, open_price = float(checkpoint.iloc[-1]["收盘"]), float(checkpoint.iloc[0]["开盘"])
                    samples.append({
                        "date": str(date), "checkpoint": checkpoint_name,
                        "pct": (close / previous_close - 1) * 100,
                        "volumeRatio": cumulative_volume / expected_volume,
                        "dayPosition": (close - low) / (high - low) * 100 if high > low else 50.0,
                        "amplitude": (high / low - 1) * 100 if low > 0 else 99.0,
                        "openingGap": (open_price / previous_close - 1) * 100,
                        "bodyPct": (close / open_price - 1) * 100,
                        "target": int(not future.empty and float(future["最高"].max()) >= limit_price),
                    })
            if len(day) >= checkpoint_size:
                prior_checkpoint_volumes[checkpoint_size].append(float(day.iloc[:checkpoint_size]["成交量"].sum()))
        if len(day):
            previous_close = float(day.iloc[-1]["收盘"])
    return samples


def _matches(df: pd.DataFrame, cfg: dict) -> pd.Series:
    return (
        (df["pct"] >= cfg["minPct"])
        & (df["pct"] <= cfg["maxPct"])
        & (df["volumeRatio"] >= cfg["minVolumeRatio"])
        & (df["dayPosition"] >= cfg["minDayPosition"])
        & (df["amplitude"] <= cfg["maxAmplitude"])
        & (df["openingGap"] >= cfg["minOpeningGap"])
        & (df["bodyPct"] >= cfg["minBodyPct"])
    )


def _metrics(df: pd.DataFrame, cfg: dict) -> dict:
    mask = _matches(df, cfg)
    selected = df[mask]
    total_positive = int(df["target"].sum())
    hits = int(selected["target"].sum()) if len(selected) else 0
    precision = hits / len(selected) if len(selected) else 0.0
    baseline = total_positive / len(df) if len(df) else 0.0
    return {
        "samples": int(len(df)), "positive": total_positive, "selected": int(len(selected)), "hits": hits,
        "precision": round(precision * 100, 2),
        "recall": round((hits / total_positive * 100) if total_positive else 0, 2),
        "baseline": round(baseline * 100, 2),
        "lift": round(precision / baseline, 2) if baseline else 0,
    }


def _fit_one_checkpoint(df: pd.DataFrame, checkpoint: str, split_date: str) -> dict:
    scoped = df[df["checkpoint"] == checkpoint]
    train, valid = scoped[scoped["date"] <= split_date], scoped[scoped["date"] > split_date]
    best_cfg, best_value = None, -1.0
    for values in itertools.product(
        [-2.0, -1.0, 0.0, 0.5, 1.0], [1.5, 2.0, 3.0],
        [1.0, 1.2, 1.5, 2.0], [50.0, 65.0, 75.0, 85.0],
        [2.5, 4.0, 6.0], [-2.0, -1.0, 0.0, 1.0], [0.0, 0.5, 1.0],
    ):
        cfg = dict(zip([
            "minPct", "maxPct", "minVolumeRatio", "minDayPosition",
            "maxAmplitude", "minOpeningGap", "minBodyPct",
        ], values))
        metric = _metrics(train, cfg)
        if metric["selected"] < 30:
            continue
        value = metric["precision"] * .75 + metric["recall"] * .25
        if value > best_value:
            best_cfg, best_value = cfg, value
    if best_cfg is None:
        raise RuntimeError(f"{checkpoint}没有找到满足最小样本数的低涨幅策略")
    train_metrics = _metrics(train, best_cfg)
    validation_metrics = _metrics(valid, best_cfg)
    # 验证集只负责决定是否允许上线，不参与阈值搜索。
    approved = bool(
        validation_metrics["selected"] >= 10
        and validation_metrics["hits"] >= 1
        and validation_metrics["lift"] >= 1.5
    )
    return {
        "thresholds": best_cfg,
        "train": train_metrics,
        "validation": validation_metrics,
        "approved": approved,
        "status": "实验启用" if approved else "验证未通过",
    }


def research(max_stocks: int = 0) -> dict:
    files = sorted(MINUTE_DIR.glob("*_30m.csv"))
    if max_stocks > 0:
        files = files[:max_stocks]
    rows = []
    for no, path in enumerate(files, 1):
        rows.extend(_extract_samples(path))
        if no % 300 == 0:
            print(f"  已分析 {no}/{len(files)} 个30分钟缓存，样本 {len(rows)}")
    df = pd.DataFrame(rows)
    if df.empty or df["target"].sum() < 10:
        raise RuntimeError("有效涨停样本不足，无法生成策略")
    dates = sorted(df["date"].unique())
    split_date = dates[max(1, int(len(dates) * .7)) - 1]
    models = {checkpoint: _fit_one_checkpoint(df, checkpoint, split_date) for checkpoint in CHECKPOINTS}
    result = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "barFrequency": "30m", "target": "检查点涨幅不超过3%，之后盘中首次触及主板涨停",
        "models": models, "trainEndDate": split_date,
        "data": {
            "files": len(files), "dates": len(dates), "start": dates[0], "end": dates[-1],
            "source": "本地BaoStock 30分钟缓存（旧版）", "sectorHistoryIncluded": False,
        },
        "warning": "规则来自有限历史样本；验证表现不代表未来收益，且未模拟成交、封单、滑点及T+1。",
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    temp = OUTPUT_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUTPUT_FILE)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="从30分钟缓存研究涨停前形态并生成盘中过滤规则")
    parser.add_argument("--max-stocks", type=int, default=0, help="0=全部，仅调试时限制股票数")
    args = parser.parse_args()
    result = research(args.max_stocks)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
