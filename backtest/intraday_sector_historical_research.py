#!/usr/bin/env python3
"""用本地30分钟历史数据推演10:30个股+行业环境规则。

历史行情允许读取项目现有缓存；实时扫描的数据源仍限定为东方财富、腾讯、
新浪。行业只使用静态分类映射，所有涨跌、广度和标签均由10:30当时可见K线
构造，训练/验证严格按日期切分。
"""
from __future__ import annotations

import itertools
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MINUTE_DIR = ROOT / "cache" / "minute"
OUTPUT_FILE = ROOT / "output" / "intraday_sector_historical_model.json"


def _latest_industry_map() -> tuple[dict[str, str], str]:
    files = sorted((ROOT / "cache").glob("tushare_a_stock_spot_*.csv"))
    if not files:
        raise RuntimeError("没有找到带行业字段的历史股票基础信息")
    path = files[-1]
    df = pd.read_csv(path, dtype={"代码": str})
    mapping = dict(zip(df["代码"].astype(str).str.zfill(6), df["行业"].fillna("未分类").astype(str)))
    return mapping, path.name


def _name_map() -> dict[str, str]:
    path = ROOT / "cache" / "stock_name_map.csv"
    df = pd.read_csv(path, dtype={"代码": str})
    return dict(zip(df["代码"].astype(str).str.zfill(6), df["名称"].fillna("").astype(str)))


def _extract(path: Path, industry: str, name: str) -> list[dict]:
    code = path.name[:6]
    if not code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")) or "ST" in name.upper():
        return []
    try:
        df = pd.read_csv(path)
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        for col in ["开盘", "最高", "最低", "收盘", "成交量", "成交额"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["datetime", "开盘", "最高", "最低", "收盘", "成交量", "成交额"])
        df = df[(df[["开盘", "最高", "最低", "收盘"]] > 0).all(axis=1)]
        df = df.sort_values("datetime")
    except Exception:
        return []
    days = [(date, day.reset_index(drop=True)) for date, day in df.groupby(df["datetime"].dt.date)]
    previous_close, prior_volumes, rows = None, [], []
    for date, day in days:
        if previous_close and len(day) > 2:
            seen, future = day.iloc[:2], day.iloc[2:]
            volume = float(seen["成交量"].sum())
            expected = pd.Series(prior_volumes[-5:]).median() if prior_volumes else math.nan
            high, low = float(seen["最高"].max()), float(seen["最低"].min())
            close, open_price = float(seen.iloc[-1]["收盘"]), float(seen.iloc[0]["开盘"])
            limit_price = previous_close * 1.095
            rows.append({
                "date": str(date), "code": code, "name": name, "industry": industry,
                "pct": (close / previous_close - 1) * 100,
                "volumeRatio": volume / expected if expected and pd.notna(expected) else math.nan,
                "dayPosition": (close - low) / (high - low) * 100 if high > low else 50.0,
                "amplitude": (high / low - 1) * 100 if low else 99.0,
                "openingGap": (open_price / previous_close - 1) * 100,
                "bodyPct": (close / open_price - 1) * 100,
                "amount": float(seen["成交额"].sum()), "alreadyHit": high >= limit_price,
                "target": int(not future.empty and float(future["最高"].max()) >= limit_price),
            })
        if len(day) >= 2:
            prior_volumes.append(float(day.iloc[:2]["成交量"].sum()))
        if len(day):
            previous_close = float(day.iloc[-1]["收盘"])
    return rows


def _add_context(df: pd.DataFrame) -> pd.DataFrame:
    df["isUp"] = (df["pct"] > 0).astype(float)
    grouped = df.groupby(["date", "industry"], as_index=False).agg(
        sectorBreadth=("isUp", "mean"), sectorMeanPct=("pct", "mean"),
        sectorAmount=("amount", "sum"), sectorSize=("code", "count"),
    )
    grouped["sectorBreadth"] *= 100
    grouped = grouped.sort_values(["industry", "date"])
    grouped["priorAmount"] = grouped.groupby("industry")["sectorAmount"].transform(
        lambda values: values.shift(1).rolling(5, min_periods=2).median()
    )
    grouped["sectorAmountRatio"] = grouped["sectorAmount"] / grouped["priorAmount"]
    market = df.groupby("date", as_index=False).agg(marketBreadth=("isUp", "mean"), marketMeanPct=("pct", "mean"))
    market["marketBreadth"] *= 100
    return df.merge(grouped, on=["date", "industry"], how="left").merge(market, on="date", how="left")


def _base_mask(df: pd.DataFrame) -> pd.Series:
    return (
        (~df["alreadyHit"]) & df["volumeRatio"].notna()
        & df["pct"].between(-2, 3) & (df["volumeRatio"] >= 1.5)
        & (df["dayPosition"] >= 85) & (df["amplitude"] <= 4)
        & (df["openingGap"] >= 1) & (df["bodyPct"] >= 0)
    )


def _sector_mask(df: pd.DataFrame, cfg: dict) -> pd.Series:
    return (
        (df["sectorBreadth"] >= cfg["minSectorBreadth"])
        & (df["sectorMeanPct"] >= cfg["minSectorMeanPct"])
        & (df["marketBreadth"] >= cfg["minMarketBreadth"])
    )


def _live_overlay_mask(df: pd.DataFrame) -> pd.Series:
    """当前实时版可由历史K线复现的保守部分（不含实时净流入和领涨股）。"""
    strength = (df["sectorMeanPct"] >= .3) | (df["sectorBreadth"] >= 55)
    return (
        (df["sectorMeanPct"] >= -.5) & (df["sectorBreadth"] >= 45)
        & (df["marketBreadth"] >= 25) & strength
    )


def _metrics(df: pd.DataFrame, mask: pd.Series) -> dict:
    selected = df[mask]
    hits = int(selected["target"].sum())
    return {
        "selected": int(len(selected)), "hits": hits,
        "precision": round(hits / len(selected) * 100, 2) if len(selected) else 0.0,
    }


def research() -> dict:
    industry_map, industry_source = _latest_industry_map()
    names = _name_map()
    files = sorted(MINUTE_DIR.glob("*_30m.csv"))
    rows = []
    for no, path in enumerate(files, 1):
        code = path.name[:6]
        rows.extend(_extract(path, industry_map.get(code, "未分类"), names.get(code, "")))
        if no % 400 == 0:
            print(f"  历史板块推演 {no}/{len(files)}，样本 {len(rows)}")
    df = _add_context(pd.DataFrame(rows))
    dates = sorted(df["date"].unique())
    split_date = dates[max(1, int(len(dates) * .7)) - 1]
    train, valid = df[df["date"] <= split_date], df[df["date"] > split_date]
    train_base, valid_base = _base_mask(train), _base_mask(valid)
    train_base_metrics, valid_base_metrics = _metrics(train, train_base), _metrics(valid, valid_base)
    best_cfg, best_value = None, -1.0
    for breadth, sector_pct, market_breadth in itertools.product(
        [35.0, 45.0, 55.0, 65.0], [-0.5, 0.0, 0.3, 0.6], [20.0, 30.0, 40.0, 50.0],
    ):
        cfg = {"minSectorBreadth": breadth, "minSectorMeanPct": sector_pct, "minMarketBreadth": market_breadth}
        metric = _metrics(train, train_base & _sector_mask(train, cfg))
        if metric["selected"] < 10 or metric["hits"] < 1:
            continue
        recall_of_base_hits = metric["hits"] / max(1, train_base_metrics["hits"])
        value = metric["precision"] * .8 + recall_of_base_hits * 20
        if value > best_value:
            best_cfg, best_value = cfg, value
    if best_cfg is None:
        best_cfg = {"minSectorBreadth": 45.0, "minSectorMeanPct": 0.0, "minMarketBreadth": 25.0}
    train_sector = _metrics(train, train_base & _sector_mask(train, best_cfg))
    valid_sector = _metrics(valid, valid_base & _sector_mask(valid, best_cfg))
    train_live = _metrics(train, train_base & _live_overlay_mask(train))
    valid_live = _metrics(valid, valid_base & _live_overlay_mask(valid))
    approved = bool(
        valid_sector["selected"] >= 3 and valid_sector["hits"] >= 1
        and valid_sector["precision"] > valid_base_metrics["precision"]
    )
    result = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checkpoint": "10:30", "thresholds": best_cfg, "approved": approved,
        "status": "历史验证通过" if approved else "仅供明日实验展示",
        "trainEndDate": split_date, "train": {"individualStock": train_base_metrics, "withSector": train_sector},
        "validation": {"individualStock": valid_base_metrics, "withSector": valid_sector},
        "currentLiveOverlay": {
            "thresholds": {"minSectorBreadth": 45.0, "minSectorMeanPct": -0.5, "minMarketBreadth": 25.0,
                           "strength": "行业平均涨幅>=0.3% 或 行业上涨广度>=55%"},
            "train": train_live, "validation": valid_live,
        },
        "candidateHistory": pd.concat([
            train[train_base].assign(dataset="train"), valid[valid_base].assign(dataset="validation")
        ])[['dataset', 'date', 'code', 'name', 'industry', 'pct', 'sectorBreadth', 'sectorMeanPct',
            'marketBreadth', 'sectorAmountRatio', 'target']].round(3).where(pd.notna, None).to_dict('records'),
        "data": {
            "stockBars": "本地30分钟历史缓存（BaoStock旧缓存）", "industryMapping": industry_source,
            "files": len(files), "mainBoardSamples": len(df), "dates": len(dates),
            "sectorFeatures": ["10:30行业上涨广度", "10:30行业成分股平均涨幅", "10:30全市场上涨广度"],
            "sectorFundProxy": "已计算行业同期成交额，但因无法直接映射实时净流入口径，未参与硬阈值",
        },
        "warning": "使用当前行业分类回填历史，可能存在分类迁移；触板不等于可成交或盈利。",
    }
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    temp = OUTPUT_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUTPUT_FILE)
    return result


if __name__ == "__main__":
    result = research()
    base = result["validation"]["individualStock"]
    overlay = result["currentLiveOverlay"]["validation"]
    print(
        f"历史板块推演完成：个股={base['selected']}只/{base['hits']}中({base['precision']}%)，"
        f"板块叠加={overlay['selected']}只/{overlay['hits']}中({overlay['precision']}%)，"
        f"状态={result['status']}"
    )
