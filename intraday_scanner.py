#!/usr/bin/env python3
"""盘中实时候选评分：公开行情源多源校验，结果供网页/API 使用。

仅用于研究排序，不产生交易指令。东方财富负责全市场候选池；腾讯、新浪只
校验入选股票的报价。同花顺 iFinD 实时行情需授权，因此不绕过授权抓取。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import signal
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from strategies.chanlun import detect_all_buy_points, detect_all_sell_points

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CACHE = OUTPUT / "intraday_candidates.json"
TAIL_CACHE = OUTPUT / "intraday_tail_candidates.json"
LEARNED_STRATEGY_FILE = OUTPUT / "intraday_learned_strategy.json"
SECTOR_VALIDATION_FILE = OUTPUT / "intraday_sector_validation.json"
HISTORICAL_SECTOR_MODEL_FILE = OUTPUT / "intraday_sector_historical_model.json"
SNAPSHOT_ROOT = ROOT / "cache" / "intraday_snapshots"
HIST_ROOT = ROOT / "cache" / "hist"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-selection/1.0)"}
EASTMONEY_URLS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2delay.eastmoney.com/api/qt/clist/get",
)
EASTMONEY_TOKEN = "bd1d9ddb04089700cf9c27f6f7426281"
EASTMONEY_MARKET_URL = "https://push2ex.eastmoney.com/getTopicZDFenBu"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_QUOTE_LIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
CHANLUN_SCAN_LIMIT = 12
INTRADAY_MIN_SCORE = 50
SCAN_DEADLINE_SECONDS = 180


class _ScanDeadlineExceeded(BaseException):
    """整轮扫描超过硬截止时间；继承 BaseException，避免被数据源降级分支吞掉。"""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_number(value: Any) -> float | None:
    """解析可缺失行情字段；缺失不能伪装成资金净流入 0。"""
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_prefix(code: str) -> str:
    return "sh" if str(code).startswith(("600", "601", "603", "605")) else "sz"


def _is_trading_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return clock_time(9, 30) <= current <= clock_time(11, 30) or clock_time(13, 0) <= current <= clock_time(15, 0)


def _public_get(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 8) -> requests.Response:
    """公开行情直连优先；直连不可用时回退系统代理。"""
    session = requests.Session()
    try:
        session.trust_env = False
        return session.get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException:
        return requests.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        session.close()


def _eastmoney_json(params: dict[str, Any]) -> dict[str, Any]:
    """请求东方财富行情，强制直连以避开本地代理的间歇性故障。"""
    errors = []
    headers = {**HEADERS, "Referer": "https://quote.eastmoney.com/"}
    for url in EASTMONEY_URLS:
        try:
            response = _public_get(url, params=params, headers=headers, timeout=8)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url.split('/')[2]}:{type(exc).__name__}")
    raise RuntimeError("；".join(errors))


def fetch_eastmoney() -> list[dict[str, Any]]:
    """按量比倒序获取沪深主板；量比低于1.5后停止继续翻页。"""
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f10", "ut": EASTMONEY_TOKEN,
        "fs": "m:1+t:2,m:0+t:6",
        "fields": "f2,f3,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f20,f62,f100,f184",
    }
    items = []
    # 正常盘中通常数页即可覆盖全部量比>=1.5股票；20页为访问量保护上限。
    for page in range(1, 21):
        params["pn"] = page
        rows = (_eastmoney_json(params).get("data") or {}).get("diff") or []
        if not rows:
            break
        items.extend(rows)
        ratios = [_number(row.get("f10")) for row in rows]
        if ratios and min(ratios) < 1.5:
            break
    result = []
    for raw in items:
        code, name = str(raw.get("f12", "")).zfill(6), str(raw.get("f14", ""))
        price, prev = _number(raw.get("f2")), _number(raw.get("f18"))
        is_main_board = code.startswith(("600", "601", "603", "605", "000", "001", "002", "003"))
        volume_ratio = _number(raw.get("f10"))
        if not is_main_board or not name or "ST" in name.upper() or price <= 0 or prev <= 0 or volume_ratio < 1.5:
            continue
        stock = {
            "code": code, "name": name, "price": price, "pct": _number(raw.get("f3")),
            "volume": _number(raw.get("f5")), "amount": _number(raw.get("f6")),
            "amplitude": _number(raw.get("f7")), "turnover": _number(raw.get("f8")),
            "volumeRatio": volume_ratio, "high": _number(raw.get("f15")),
            "low": _number(raw.get("f16")), "open": _number(raw.get("f17")), "prevClose": prev,
            "marketCap": _number(raw.get("f20")) / 100_000_000,
            "industry": str(raw.get("f100") or "").strip("- "), "source": "东方财富",
        }
        main_net_inflow = _optional_number(raw.get("f62"))
        main_net_ratio = _optional_number(raw.get("f184"))
        if main_net_inflow is not None and main_net_ratio is not None:
            stock["mainNetInflow"] = main_net_inflow
            stock["mainNetRatio"] = main_net_ratio
        result.append(stock)
    return result


def fetch_eastmoney_main_money(codes: list[str], batch_size: int = 50) -> dict[str, dict[str, float]]:
    """批量补充个股主力净额/占比，供腾讯主行情降级路径使用。"""
    unique_codes = list(dict.fromkeys(str(code).zfill(6) for code in codes if str(code).strip()))
    result: dict[str, dict[str, float]] = {}
    for start in range(0, len(unique_codes), batch_size):
        batch = unique_codes[start:start + batch_size]
        secids = ",".join(("1." if code.startswith("6") else "0.") + code for code in batch)
        response = _public_get(
            EASTMONEY_QUOTE_LIST_URL,
            params={
                "fltt": 2, "secids": secids, "fields": "f12,f62,f184",
                "ut": EASTMONEY_TOKEN,
            },
            headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}, timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("diff") if isinstance(data, dict) else []
        if not isinstance(rows, list):
            rows = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            code = str(raw.get("f12") or "").zfill(6)
            amount = _optional_number(raw.get("f62"))
            ratio = _optional_number(raw.get("f184"))
            if code and amount is not None and ratio is not None:
                result[code] = {"mainNetInflow": amount, "mainNetRatio": ratio}
    return result


def fetch_tencent_market(batch_size: int = 80) -> list[dict[str, Any]]:
    """东方财富个股列表不可用时，用本地股票池批量读取腾讯实时行情。"""
    codes = sorted(
        path.name.removesuffix("_bs.csv")
        for path in HIST_ROOT.glob("*_bs.csv")
        if path.name[:6].isdigit()
        and path.name[:6].startswith(("600", "601", "603", "605", "000", "001", "002", "003"))
    )
    result: list[dict[str, Any]] = []
    headers = {**HEADERS, "Referer": "https://gu.qq.com/"}
    for start in range(0, len(codes), batch_size):
        batch = codes[start:start + batch_size]
        symbols = ",".join(_market_prefix(code) + code for code in batch)
        response = _public_get("https://qt.gtimg.cn/q=" + symbols, headers=headers, timeout=6)
        response.raise_for_status()
        text = response.content.decode("gbk", errors="ignore")
        for line in text.split(";"):
            if '="' not in line:
                continue
            fields = line.split('="', 1)[1].strip().strip('"').split("~")
            if len(fields) <= 49:
                continue
            code, name = str(fields[2]).zfill(6), str(fields[1]).strip()
            price, prev = _number(fields[3]), _number(fields[4])
            volume_ratio = _number(fields[49])
            if not name or "ST" in name.upper() or price <= 0 or prev <= 0 or volume_ratio < 1.5:
                continue
            high, low = _number(fields[33]), _number(fields[34])
            result.append({
                "code": code, "name": name, "price": price, "pct": _number(fields[32]),
                "volume": _number(fields[36]), "amount": _number(fields[37]) * 10_000,
                "amplitude": _number(fields[43]), "turnover": _number(fields[38]),
                "volumeRatio": volume_ratio, "high": high, "low": low,
                "open": _number(fields[5]), "prevClose": prev,
                "marketCap": _number(fields[44]), "industry": "", "source": "腾讯",
            })
    if not result:
        raise RuntimeError("腾讯行情未返回符合条件的主板股票")
    try:
        money_flow = fetch_eastmoney_main_money([stock["code"] for stock in result])
        for stock in result:
            if stock["code"] in money_flow:
                stock.update(money_flow[stock["code"]])
                stock["mainMoneySource"] = "东方财富"
    except (requests.RequestException, ValueError, RuntimeError):
        # 主行情可用时不能因资金辅助字段失败而中止整轮扫描。
        pass
    return result


def _fetch_eastmoney_sector_type(kind: str) -> list[dict[str, Any]]:
    """获取东方财富行业或概念板块实时快照。"""
    if kind not in {"industry", "concept"}:
        raise ValueError(f"不支持的板块类型：{kind}")
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "ut": EASTMONEY_TOKEN,
        "fs": "m:90+t:2+f:!50" if kind == "industry" else "m:90+t:3+f:!50",
        "fields": "f2,f3,f6,f8,f12,f14,f62,f104,f105,f106,f128,f136,f184",
    }
    rows = []
    # 行业用于逐股关联，需要完整翻页；概念目前只保存强势前100，避免高频访问过多。
    max_pages = 6 if kind == "industry" else 1
    for page in range(1, max_pages + 1):
        params["pn"] = page
        data = _eastmoney_json(params).get("data") or {}
        batch = data.get("diff") or []
        rows.extend(batch)
        if len(batch) < 100 or len(rows) >= int(data.get("total") or 0):
            break
    sectors = []
    for raw in rows:
        name = str(raw.get("f14") or "").strip()
        if not name:
            continue
        up, down, flat = int(_number(raw.get("f104"))), int(_number(raw.get("f105"))), int(_number(raw.get("f106")))
        breadth_base = up + down + flat
        sectors.append({
            "type": kind, "code": str(raw.get("f12") or ""), "name": name,
            "pct": _number(raw.get("f3")), "amount": _number(raw.get("f6")),
            "turnover": _number(raw.get("f8")), "mainNetInflow": _number(raw.get("f62")),
            "mainNetRatio": _number(raw.get("f184")), "up": up, "down": down, "flat": flat,
            "breadth": round(up / breadth_base * 100, 1) if breadth_base else 0.0,
            "leader": str(raw.get("f128") or "").strip("- "),
            "leaderPct": _number(raw.get("f136")),
        })
    return sectors


def fetch_eastmoney_sectors() -> dict[str, list[dict[str, Any]]]:
    """一次扫描只请求两次板块列表，不逐股抓取板块页面。"""
    return {
        "industry": _fetch_eastmoney_sector_type("industry"),
        "concept": _fetch_eastmoney_sector_type("concept"),
    }


def fetch_eastmoney_market_context() -> dict[str, Any]:
    """从东方财富涨跌分布接口获取全A市场广度，避免为此遍历全部股票。"""
    response = _public_get(
        EASTMONEY_MARKET_URL,
        params={"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt"},
        headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}, timeout=8,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    distribution = data.get("fenbu") or []
    buckets = {int(key): int(value) for row in distribution for key, value in row.items()}
    if not buckets:
        raise RuntimeError("东方财富涨跌分布为空")
    up = sum(count for level, count in buckets.items() if level > 0)
    down = sum(count for level, count in buckets.items() if level < 0)
    flat = buckets.get(0, 0)
    total = up + down + flat
    halfway, cumulative, median_bucket = total / 2, 0, 0
    for level, count in sorted(buckets.items()):
        cumulative += count
        if cumulative >= halfway:
            median_bucket = level
            break
    return {
        "scope": "全A股", "tradeDate": str(data.get("qdate") or ""),
        "total": total, "up": up, "down": down, "flat": flat,
        "upRatio": round(up / total * 100, 1) if total else 0.0,
        "medianPct": float(median_bucket),
        "nearLimitUp": sum(count for level, count in buckets.items() if level >= 8),
        "riseAtLeast10": sum(count for level, count in buckets.items() if level >= 10),
        "limitUp": buckets.get(10, 0),
        "distribution": buckets,
    }


def _market_context(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    pcts = [s["pct"] for s in stocks]
    total = len(pcts)
    up = sum(v > 0 for v in pcts)
    down = sum(v < 0 for v in pcts)
    return {
        "total": total, "up": up, "down": down, "flat": total - up - down,
        "upRatio": round(up / total * 100, 1) if total else 0.0,
        "medianPct": round(statistics.median(pcts), 2) if pcts else 0.0,
        "nearLimitUp": sum(v >= 8 for v in pcts),
        "limitUp": sum(v >= 9.5 for v in pcts),
    }


def _read_previous_snapshot(now: datetime) -> dict[str, Any] | None:
    """读取4至15分钟前的同源快照，用于计算板块短时加速。"""
    folder = SNAPSHOT_ROOT / now.strftime("%Y-%m-%d")
    if not folder.exists():
        return None
    for path in sorted(folder.glob("*.json.gz"), reverse=True):
        try:
            hhmm = path.stem.split(".")[0]
            snapshot_time = datetime.strptime(f"{now:%Y-%m-%d} {hhmm}", "%Y-%m-%d %H%M")
            age = (now - snapshot_time).total_seconds()
            if age < 240:
                continue
            if age > 900:
                break
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None


def _add_sector_acceleration(sectors: dict[str, list[dict[str, Any]]], previous: dict[str, Any] | None) -> None:
    old_groups = (previous or {}).get("sectors", {})
    for kind, rows in sectors.items():
        old = {s.get("code"): s for s in old_groups.get(kind, [])}
        for sector in rows:
            prior = old.get(sector["code"])
            sector["pctAcceleration"] = round(sector["pct"] - _number(prior.get("pct")), 2) if prior else None


def _sector_score(sector: dict[str, Any] | None) -> tuple[int, bool, list[str]]:
    """行业环境加减分；资金流只参与评分，不单独决定是否入选。"""
    if not sector:
        return -20, False, ["缺少实时行业归属"]
    delta, reasons = 0, []
    pct, breadth = sector["pct"], sector["breadth"]
    if pct >= 1.5:
        delta += 8; reasons.append(f"行业强势 {pct:+.2f}%")
    elif pct >= .3:
        delta += 5; reasons.append(f"行业上涨 {pct:+.2f}%")
    elif pct < -.5:
        delta -= 10; reasons.append(f"行业偏弱 {pct:+.2f}%")
    if breadth >= 65:
        delta += 7; reasons.append(f"行业上涨家数 {breadth:.0f}%")
    elif breadth >= 55:
        delta += 4; reasons.append(f"行业广度 {breadth:.0f}%")
    elif breadth < 45:
        delta -= 8; reasons.append(f"行业广度不足 {breadth:.0f}%")
    if sector["mainNetRatio"] >= 3:
        delta += 6; reasons.append(f"行业主力净流入比 {sector['mainNetRatio']:+.1f}%")
    elif sector["mainNetRatio"] > 0:
        delta += 3; reasons.append("行业主力净流入")
    elif sector["mainNetRatio"] <= -5:
        delta -= 5; reasons.append("行业资金明显流出")
    if sector["leaderPct"] >= 8:
        delta += 5; reasons.append(f"行业领涨股 {sector['leaderPct']:+.1f}%")
    acceleration = sector.get("pctAcceleration")
    if acceleration is not None and acceleration >= .3:
        delta += 5; reasons.append(f"行业约5分钟加速 {acceleration:+.2f}%")
    elif acceleration is not None and acceleration <= -.3:
        delta -= 5; reasons.append(f"行业约5分钟回落 {acceleration:+.2f}%")
    # 前置条件强调板块不是普跌，并且至少出现涨幅、广度、资金或龙头之一。
    strength_confirmed = pct >= .3 or breadth >= 55 or sector["mainNetRatio"] > 0 or sector["leaderPct"] >= 5
    eligible = pct >= -.5 and breadth >= 45 and strength_confirmed
    return delta, eligible, reasons


def _snapshot_stock(stock: dict[str, Any]) -> dict[str, Any]:
    """保留可用于未来无前视回测的字段，避免每分钟快照无谓膨胀。"""
    keys = (
        "code", "name", "price", "pct", "volume", "amount", "amplitude", "turnover",
        "volumeRatio", "high", "low", "open", "prevClose", "industry", "dayPosition",
        "mainNetInflow", "mainNetRatio", "mainMoneyUpdatedAt", "mainMoneyTrend",
        "learnedMatch", "bigYangPullbackMatch", "sectorEligible", "chanlunBuySignals", "chanlunSellSignals",
    )
    return {key: stock.get(key) for key in keys}


def _main_money_trend(history: list[dict[str, Any]]) -> str:
    if not history:
        return "暂无数据"
    current = _number(history[-1].get("mainNetInflow"))
    if len(history) == 1:
        return "净流入" if current > 0 else ("净流出" if current < 0 else "资金持平")
    previous = _number(history[-2].get("mainNetInflow"))
    if previous <= 0 < current:
        return "由流出转流入"
    if previous >= 0 > current:
        return "由流入转流出"
    if current > 0:
        return "持续流入" if current >= previous else "流入减弱"
    if current < 0:
        return "持续流出" if current <= previous else "流出减弱"
    return "资金持平"


def _record_main_money_flow(
    target: dict[str, Any], live: dict[str, Any] | None, now: datetime,
    prior_history: list[dict[str, Any]] | None = None,
) -> None:
    """把个股当日累计主力净额追加为时间序列；源缺失时保留最后有效点。"""
    history = [dict(point) for point in (prior_history if prior_history is not None else target.get("mainMoneyFlowHistory") or [])]
    amount = _optional_number((live or {}).get("mainNetInflow"))
    ratio = _optional_number((live or {}).get("mainNetRatio"))
    if amount is None or ratio is None:
        target["mainMoneyFlowHistory"] = history
        target["mainMoneyStale"] = bool(history or target.get("mainMoneyUpdatedAt"))
        return
    point = {
        "time": now.strftime("%H:%M"), "mainNetInflow": amount, "mainNetRatio": ratio,
        "price": _number((live or {}).get("price")), "pct": _number((live or {}).get("pct")),
    }
    if history and history[-1].get("time") == point["time"]:
        history[-1] = point
    else:
        history.append(point)
    history = history[-240:]
    target["mainNetInflow"] = amount
    target["mainNetRatio"] = ratio
    target["mainMoneyUpdatedAt"] = now.strftime("%Y-%m-%d %H:%M:%S")
    target["mainMoneyFlowHistory"] = history
    target["mainMoneyTrend"] = _main_money_trend(history)
    target["mainMoneyStale"] = False


def _mark_main_money_stale(payload: dict[str, Any]) -> None:
    """整轮行情失败时，将缓存中的个股资金明确标成旧数据。"""
    for stock in payload.get("stocks") or []:
        if stock.get("mainNetInflow") is not None or stock.get("mainMoneyFlowHistory"):
            stock["mainMoneyStale"] = True


def _save_snapshot(
    now: datetime,
    stocks: list[dict[str, Any]],
    sectors: dict[str, list[dict[str, Any]]],
    market: dict[str, Any],
    checkpoint: str,
) -> str:
    """按分钟保存免费网页行情，供后续训练个股+板块模型。"""
    folder = SNAPSHOT_ROOT / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now:%H%M}.json.gz"
    temp = folder / f".{now:%H%M}.json.gz.tmp"
    payload = {
        "schemaVersion": 2, "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "东方财富免费网页行情", "quoteValidationSources": ["腾讯", "新浪"],
        "checkpoint": checkpoint, "market": market, "sectors": sectors,
        "stocks": [_snapshot_stock(s) for s in stocks],
    }
    with gzip.open(temp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    temp.replace(path)
    return str(path.relative_to(ROOT))


def _score(stock: dict[str, Any]) -> tuple[int, list[str]]:
    """稳健的盘中研究评分：趋势、量能、位置、流动性和过热风险。"""
    # 基础行情最多约 67 分，给板块与历史策略效果预留空间，避免基础项直接堆满 100。
    score, reasons = 20.0, []
    pct, vr, turnover = stock["pct"], stock["volumeRatio"], stock["turnover"]
    high, low, price = stock["high"], stock["low"], stock["price"]
    if 1.5 <= pct <= 7:
        score += 15; reasons.append("涨幅处于强势区间")
    elif 0 < pct < 1.5:
        score += 6; reasons.append("小幅走强")
    elif pct > 7:
        score += 3; reasons.append("涨幅过高，谨慎追涨")
        score -= min(12, (pct - 7) * 2)
    else:
        score -= min(12, abs(pct) * 1.5)
    if vr >= 2:
        score += 12; reasons.append(f"量比 {vr:.1f}")
    elif vr >= 1.2:
        score += 6; reasons.append(f"量比 {vr:.1f}")
    if 2 <= turnover <= 15:
        score += 7; reasons.append("换手活跃")
    elif turnover > 25:
        score -= 6; reasons.append("换手过高")
    if high > low:
        location = (price - low) / (high - low)
        stock["dayPosition"] = round(location * 100, 1)
        if location >= .75:
            score += 8; reasons.append("接近日内高位")
        elif location <= .25:
            score -= 5
    if stock["amount"] >= 100_000_000:
        score += 5; reasons.append("成交额充足")
    return max(0, min(100, round(score))), reasons


def _intraday_strategy_labels(stock: dict[str, Any]) -> list[str]:
    """把盘中候选统一映射为可做历史评价的策略标签。"""
    labels: list[str] = []
    if stock.get("learnedMatch"):
        labels.append("低涨幅后续触板")
    if stock.get("bigYangPullbackMatch"):
        labels.append("大阳回调不破10日线")
    if stock.get("longShadowMatch"):
        labels.append("长上下影线")
    labels.extend(
        str(signal.get("name") or signal.get("type"))
        for signal in (stock.get("chanlunBuySignals") or [])
        if signal.get("name") or signal.get("type")
    )
    return list(dict.fromkeys(labels))


def _load_intraday_strategy_history(now: datetime) -> dict[str, Any]:
    """用首次入选价到当日收盘价的收益，评价各盘中策略。"""
    rows_seen = 0
    all_returns: list[float] = []
    stats: dict[str, dict[str, Any]] = {}
    for path in sorted(CACHE.parent.glob("intraday_hits_????-??-??.json")):
        if path.stem.removeprefix("intraday_hits_") >= now.strftime("%Y-%m-%d"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        trade_date = str(payload.get("tradeDate") or path.stem.removeprefix("intraday_hits_"))
        for stock in payload.get("stocks", []):
            labels = _intraday_strategy_labels(stock)
            if not labels:
                continue
            selected_price = _number(stock.get("selectedPrice"))
            # 历史文件在收盘前持续刷新，price 是该交易日最后一次行情；新版同时写 closePrice。
            close_price = _number(stock.get("closePrice") or stock.get("price"))
            if selected_price <= 0 or close_price <= 0:
                continue
            return_pct = (close_price / selected_price - 1) * 100
            rows_seen += 1
            all_returns.append(return_pct)
            for label in labels:
                item = stats.setdefault(label, {"selected": 0, "returns": [], "days": set()})
                item["selected"] += 1
                item["returns"].append(return_pct)
                item["days"].add(trade_date)

    baseline = sum(all_returns) / len(all_returns) if all_returns else 0.0
    prior_strength = 20
    serializable = {}
    for label, item in stats.items():
        selected = item["selected"]
        returns = sorted(item["returns"])
        raw_average = sum(returns) / selected
        adjusted = (sum(returns) + baseline * prior_strength) / (selected + prior_strength)
        middle = selected // 2
        median = returns[middle] if selected % 2 else (returns[middle - 1] + returns[middle]) / 2
        serializable[label] = {
            "selected": selected, "days": len(item["days"]),
            "rawAvgReturn": round(raw_average, 2),
            "adjustedAvgReturn": round(adjusted, 2),
            "medianReturn": round(median, 2),
            "positiveRate": round(sum(value > 0 for value in returns) / selected * 100, 2),
        }
    return {
        "completedRows": rows_seen, "baselineAvgReturn": round(baseline, 2),
        "priorStrength": prior_strength, "strategies": serializable,
    }


def _weighted_intraday_score(
    stock: dict[str, Any],
    history: dict[str, Any],
    *,
    market_weak: bool = False,
) -> int:
    """基础行情 + 板块 + 经样本量收缩的入选后收益，形成最终分。"""
    base_score, _ = _score(stock)
    sector_delta, _, _ = _sector_score(stock.get("sector"))
    sector_score = max(-10, min(14, round(sector_delta * .45)))
    market_score = -8 if market_weak else 0

    baseline = _number(history.get("baselineAvgReturn"), 0.0)
    strategy_points: list[int] = []
    historical_rates = {}
    for label in _intraday_strategy_labels(stock):
        metric = (history.get("strategies") or {}).get(label) or {}
        adjusted = _number(metric.get("adjustedAvgReturn"), baseline)
        # 每高于全体平均收益 1 个百分点约多 4 分；小样本先向全体均值收缩。
        points = max(1, min(10, round(4 + (adjusted - baseline) * 4)))
        strategy_points.append(points)
        historical_rates[label] = {
            "selected": int(metric.get("selected") or 0),
            "rawAvgReturn": _number(metric.get("rawAvgReturn")),
            "adjustedAvgReturn": round(adjusted, 2),
            "medianReturn": _number(metric.get("medianReturn")),
            "positiveRate": _number(metric.get("positiveRate")),
            "points": points,
        }
    strategy_points.sort(reverse=True)
    strategy_score = min(14, (strategy_points[0] if strategy_points else 0) + sum(strategy_points[1:]) // 3)
    confidences = [_number(signal.get("confidence")) for signal in (stock.get("chanlunBuySignals") or [])]
    confidence_score = min(2, round(max(confidences, default=0) / 50))
    sell_penalty = min(12, 4 * len(stock.get("chanlunSellSignals") or []))
    final_score = max(0, min(99, round(base_score + sector_score + market_score + strategy_score + confidence_score - sell_penalty)))
    stock["scoreBreakdown"] = {
        "base": base_score, "sector": sector_score, "market": market_score,
        "strategy": strategy_score, "confidence": confidence_score, "sellPenalty": sell_penalty,
    }
    stock["strategyHistoricalRates"] = historical_rates
    return final_score


def fetch_eastmoney_30m(code: str, limit: int = 240, frequency: int = 30) -> pd.DataFrame:
    """从东方财富免费网页接口读取最新30分钟K线，供盘中缠论识别。"""
    secid = ("1." if str(code).startswith("6") else "0.") + str(code).zfill(6)
    response = _public_get(
        EASTMONEY_KLINE_URL,
        params={
            "secid": secid, "ut": EASTMONEY_TOKEN, "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": frequency, "fqt": 1, "beg": 0, "end": 20500101, "lmt": limit,
        },
        headers={**HEADERS, "Referer": "https://quote.eastmoney.com/"}, timeout=6,
    )
    response.raise_for_status()
    rows = ((response.json().get("data") or {}).get("klines") or [])
    parsed = []
    for row in rows:
        fields = str(row).split(",")
        if len(fields) < 7:
            continue
        parsed.append({
            "datetime": fields[0], "开盘": fields[1], "收盘": fields[2],
            "最高": fields[3], "最低": fields[4], "成交量": fields[5],
            "成交额": fields[6], "代码": str(code).zfill(6),
        })
    return pd.DataFrame(parsed)


def fetch_sina_30m(code: str, limit: int = 240, frequency: int = 30) -> pd.DataFrame:
    """东方财富历史K线域名不可达时，使用新浪免费30分钟K线兜底。"""
    symbol = _market_prefix(code) + str(code).zfill(6)
    response = _public_get(
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/CN_MarketDataService.getKLineData",
        params={"symbol": symbol, "scale": frequency, "ma": "no", "datalen": limit},
        headers=HEADERS, timeout=6,
    )
    response.raise_for_status()
    match = re.search(r"(\[.*\])", response.text, flags=re.S)
    if not match:
        return pd.DataFrame()
    rows = json.loads(match.group(1))
    return pd.DataFrame([
        {
            "datetime": row.get("day"), "开盘": row.get("open"), "收盘": row.get("close"),
            "最高": row.get("high"), "最低": row.get("low"), "成交量": row.get("volume"),
            "成交额": row.get("amount", 0), "代码": str(code).zfill(6),
        }
        for row in rows
    ])


def fetch_realtime_30m(code: str, limit: int = 240, frequency: int = 30) -> tuple[pd.DataFrame, str]:
    """按东方财富→新浪顺序获取分钟K线。"""
    try:
        bars = fetch_eastmoney_30m(code, limit, frequency)
        if not bars.empty:
            return bars, "东方财富"
    except Exception:
        pass
    bars = fetch_sina_30m(code, limit, frequency)
    return bars, "新浪"


def _chanlun_for_stock(stock: dict[str, Any]) -> dict[str, Any]:
    """识别最新30分钟缠论买卖点；单股失败不会影响整轮扫描。"""
    result = {"buy": [], "sell": [], "error": "", "source": ""}
    try:
        for frequency in (30, 60):
            bars, source = fetch_realtime_30m(stock["code"], frequency=frequency)
            result["source"] = source if not result["source"] else result["source"] + "/" + source
            if len(bars) < 80:
                continue
            _, buys = detect_all_buy_points(bars)
            _, sells = detect_all_sell_points(bars)
            result["buy"].extend([
                {"type": p.type, "name": f"{frequency}分钟缠论{p.type[0]}买", "confidence": round(float(p.confidence) * 100, 1), "reason": p.reason}
                for p in buys if p.type != "1B"
            ])
            result["sell"].extend([
                {"type": p.type, "name": f"{frequency}分钟缠论{p.type[0]}卖", "confidence": round(float(p.confidence) * 100, 1), "reason": p.reason}
                for p in sells
            ])
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def _apply_chanlun(stocks: list[dict[str, Any]]) -> int:
    """对最有潜力的少量股票并发做缠论分析，控制免费接口访问频率。"""
    eligible = [
        s for s in stocks
        if -3 <= s["pct"] <= 7 and s["high"] < s["prevClose"] * 1.095
        and s["amount"] >= 30_000_000 and s.get("dayPosition", 0) >= 55
    ]
    eligible.sort(key=lambda s: (bool(s.get("learnedMatch")), s["score"], s["amount"]), reverse=True)
    targets = eligible[:CHANLUN_SCAN_LIMIT]
    if not targets:
        return 0
    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        futures = {pool.submit(_chanlun_for_stock, stock): stock for stock in targets}
        for future in as_completed(futures):
            stock = futures[future]
            analysis = future.result()
            stock["chanlunBuySignals"] = analysis["buy"]
            stock["chanlunSellSignals"] = analysis["sell"]
            stock["chanlunError"] = analysis["error"]
            stock["chanlunDataSource"] = analysis["source"]
            for signal in analysis["buy"]:
                # 对“低涨幅后续拉升”目标，二买兼顾位置与确认度，优先级最高。
                bonus = {"2B": 25, "3B": 15}.get(signal["type"], 8)
                sector = stock.get("sector") or {}
                if signal["type"] == "2B" and _number(sector.get("mainNetRatio")) > 0:
                    bonus += 10
                    stock["reasons"].insert(0, "二买叠加行业资金流入")
                stock["score"] = min(100, stock["score"] + bonus)
                stock["reasons"].insert(0, f"{signal['name']}（置信度{signal['confidence']:.0f}%）")
            for signal in analysis["sell"]:
                penalty = {"1S": 15, "2S": 20, "3S": 25}.get(signal["type"], 15)
                stock["score"] = max(0, stock["score"] - penalty)
                stock["reasons"].append(f"风险：{signal['name']}（置信度{signal['confidence']:.0f}%）")
    return len(targets)


def _daily_big_yang_match(stock: dict[str, Any]) -> bool:
    """用本地日K缓存复核“3-5日前大阳回调不破10日线”。"""
    try:
        path = HIST_ROOT / f"{stock['code']}_bs.csv"
        if not path.exists():
            return False
        df = pd.read_csv(path)
        rename = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume", "涨跌幅": "pct"}
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        need = {"date", "open", "close", "high", "low", "volume", "pct"}
        if not need.issubset(df.columns):
            return False
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for col in need - {"date"}: df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=list(need)).sort_values("date").tail(180).reset_index(drop=True)
        if len(df) < 30: return False
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma10"] = df["close"].rolling(10).mean()
        df["avgvol20"] = df["volume"].shift(1).rolling(20).mean()
        pos = len(df) - 1
        latest = df.iloc[pos]
        # 当前实时价替换缓存最后一根收盘，避免盘中继续使用昨天收盘判断。
        current_price = _number(stock.get("price"), _number(latest["close"]))
        current_pct = _number(stock.get("pct"), _number(latest["pct"]))
        for start in range(max(0, pos - 5), pos - 2):
            row = df.iloc[start]
            if row["pct"] < 8 or row["volume"] < row["avgvol20"] * 1.5 or row["close"] <= row["ma5"] or row["close"] <= row["ma10"]:
                continue
            pullback = df.iloc[start + 1:pos + 1]
            if pullback.empty or pullback["low"].lt(pullback["ma10"] * .98).any(): continue
            if pullback["volume"].mean() > row["volume"] * .70: continue
            if current_price < row["close"] * .88 or current_price < latest["ma10"] * .98 or current_pct >= 9.5: continue
            return True
    except Exception:
        return False
    return False


def _apply_daily_big_yang(stocks: list[dict[str, Any]]) -> int:
    targets = sorted(
        [s for s in stocks if -3 <= s["pct"] < 9.5 and s["amount"] >= 30_000_000],
        key=lambda s: (s["score"], s["amount"]), reverse=True,
    )[:40]
    hits = 0
    for stock in targets:
        stock["bigYangPullbackMatch"] = _daily_big_yang_match(stock)
        if stock["bigYangPullbackMatch"]:
            hits += 1
            stock["score"] = min(100, stock["score"] + 18)
            stock["reasons"].insert(0, "大阳回调不破10日线")
    return len(targets)


def _daily_long_shadow_match(stock: dict[str, Any]) -> bool:
    """复用日线长上下影线规则，并把当前实时行情作为今日K线。"""
    try:
        path = HIST_ROOT / f"{stock['code']}_bs.csv"
        if not path.exists(): return False
        df = pd.read_csv(path)
        df = df.rename(columns={"日期":"date", "开盘":"open", "收盘":"close", "最高":"high", "最低":"low", "成交量":"volume"})
        cols = {"date", "open", "close", "high", "low", "volume"}
        if not cols.issubset(df.columns): return False
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for col in cols - {"date"}: df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=list(cols)).sort_values("date").tail(120)
        today = pd.Timestamp(datetime.now().date())
        live = {"date": today, "open": _number(stock.get("open")), "close": _number(stock.get("price")),
                "high": _number(stock.get("high")), "low": _number(stock.get("low")), "volume": _number(stock.get("volume"))}
        if live["open"] > 0 and live["close"] > 0 and live["high"] >= live["low"] > 0:
            df = df[df["date"].dt.normalize() != today]
            df = pd.concat([df, pd.DataFrame([live])], ignore_index=True)
        if len(df) < 3: return False
        flags = []
        for i in range(2, len(df)):
            base_low, base_vol = float(df.iloc[i-2]["low"]), float(df.iloc[i-2]["volume"])
            upper = lower = False; min_volatility = float("inf")
            for j in (i-1, i):
                row = df.iloc[j]; k_len = float(row["high"] - row["low"])
                if k_len <= 0: continue
                min_volatility = min(min_volatility, k_len / ((row["high"] + row["low"]) / 2) * 100)
                if base_vol > 0 and row["volume"] > base_vol * 1.5: continue
                upper_shadow = row["high"] - max(row["open"], row["close"])
                lower_shadow = min(row["open"], row["close"]) - row["low"]
                if upper_shadow >= .5*k_len and abs(row["low"]-row["open"]) < .4*k_len: upper = True
                elif lower_shadow >= .5*k_len and abs(row["high"]-row["close"]) < .4*k_len: lower = True
            flags.append(upper and lower and min_volatility > 2.5 and min(float(df.iloc[i-1]["low"]), float(df.iloc[i]["low"])) < base_low)
        return bool(flags[-1])
    except Exception:
        return False


def _apply_daily_long_shadow(stocks: list[dict[str, Any]]) -> int:
    targets = sorted([s for s in stocks if -3 <= s["pct"] < 9.5 and s["amount"] >= 30_000_000], key=lambda s: (s["score"], s["amount"]), reverse=True)[:40]
    for stock in targets:
        stock["longShadowMatch"] = _daily_long_shadow_match(stock)
        if stock["longShadowMatch"]:
            stock["score"] = min(100, stock["score"] + 10)
            stock["reasons"].insert(0, "长上下影线")
    return len(targets)


def _retain_tail_hits(now: datetime, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """尾盘窗口内保留已经入选的股票，避免14:40后短暂命中后消失。"""
    try:
        saved = json.loads(TAIL_CACHE.read_text(encoding="utf-8"))
        rows = {str(x.get("code")): x for x in saved.get("stocks", []) if x.get("code") and saved.get("tradeDate") == now.strftime("%Y-%m-%d")}
    except (OSError, json.JSONDecodeError):
        rows = {}
    for row in rows.values(): row["currentMatch"] = False
    for stock in selected:
        old = rows.get(stock["code"], {})
        stock["firstHitTime"] = old.get("firstHitTime") or now.strftime("%H:%M:%S")
        stock["selectedPct"] = old.get("selectedPct", stock.get("pct"))
        stock["selectedPrice"] = old.get("selectedPrice", stock.get("price"))
        stock["lastHitTime"] = now.strftime("%H:%M:%S")
        stock["currentMatch"] = True
        if now.time() >= clock_time(14, 55):
            stock["closePct"] = stock.get("pct")
            stock["closePrice"] = stock.get("price")
        rows[stock["code"]] = stock
    retained = sorted(rows.values(), key=lambda x: (bool(x.get("currentMatch")), int(x.get("score") or 0), x.get("lastHitTime", "")), reverse=True)
    payload = {"success": True, "tailReady": True, "tradeDate": now.strftime("%Y-%m-%d"), "time": now.strftime("%Y-%m-%d %H:%M:%S"), "stocks": retained}
    TAIL_CACHE.parent.mkdir(exist_ok=True)
    temp = TAIL_CACHE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(TAIL_CACHE)
    dated = TAIL_CACHE.parent / f"intraday_tail_{now:%Y-%m-%d}.json"
    dated.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return retained


def _retain_daily_hits(
    now: datetime,
    selected: list[dict[str, Any]],
    market_stocks: list[dict[str, Any]],
    strategy_history: dict[str, Any] | None = None,
    market_weak: bool = False,
) -> list[dict[str, Any]]:
    """当日命中过的股票持续保留，避免下一轮条件变化后从页面消失。"""
    path = CACHE.parent / f"intraday_hits_{now:%Y-%m-%d}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        old_rows = saved.get("stocks", []) if saved.get("tradeDate") == now.strftime("%Y-%m-%d") else []
    except (OSError, json.JSONDecodeError):
        old_rows = []

    rows = {str(row.get("code", "")): row for row in old_rows if row.get("code")}
    live_map = {stock["code"]: stock for stock in market_stocks}
    current_codes = {stock["code"] for stock in selected}
    quote_keys = (
        "price", "pct", "volume", "amount", "amplitude", "turnover", "volumeRatio",
        "high", "low", "open", "prevClose", "marketCap", "industry", "sector",
        "sectorEligible", "dayPosition",
    )
    for code, row in rows.items():
        row["currentMatch"] = False
        live = live_map.get(code)
        if live:
            prior_history = row.get("mainMoneyFlowHistory") or []
            for key in quote_keys:
                if key in live:
                    row[key] = live[key]
            _record_main_money_flow(row, live, now, prior_history)
            # 选中时的涨幅保留不变；收盘前最后一轮行情作为收盘涨幅。
            if row.get("selectedPct") is None:
                row["selectedPct"] = row.get("pct")
            if row.get("selectedPrice") is None:
                row["selectedPrice"] = row.get("price")
            if now.time() >= clock_time(14, 55):
                row["closePct"] = live.get("pct")
                row["closePrice"] = live.get("price")

    hit_time = now.strftime("%H:%M:%S")
    for stock in selected:
        code = stock["code"]
        prior = rows.get(code, {})
        live_money = {
            "mainNetInflow": stock.get("mainNetInflow"), "mainNetRatio": stock.get("mainNetRatio"),
            "price": stock.get("price"), "pct": stock.get("pct"),
        }
        if _optional_number(live_money["mainNetInflow"]) is None or _optional_number(live_money["mainNetRatio"]) is None:
            stock.pop("mainNetInflow", None)
            stock.pop("mainNetRatio", None)
        _record_main_money_flow(stock, live_money, now, prior.get("mainMoneyFlowHistory") or [])
        for key in ("mainNetInflow", "mainNetRatio", "mainMoneyUpdatedAt", "mainMoneyTrend"):
            if key not in stock and key in prior:
                stock[key] = prior[key]
        stock["firstHitTime"] = prior.get("firstHitTime") or hit_time
        stock["selectedPct"] = prior.get("selectedPct", stock.get("pct"))
        stock["selectedPrice"] = prior.get("selectedPrice", stock.get("price"))
        stock["lastHitTime"] = hit_time
        stock["hitScans"] = int(prior.get("hitScans") or 0) + 1
        stock["currentMatch"] = True
        if now.time() >= clock_time(14, 55):
            stock["closePct"] = stock.get("pct")
            stock["closePrice"] = stock.get("price")
        rows[code] = stock

    # 兼容旧缓存：历史上曾写入过一买信号，现统一从盘中展示记录中移除。
    for row in rows.values():
        row["chanlunBuySignals"] = [x for x in (row.get("chanlunBuySignals") or []) if x.get("type") != "1B"]
        row["briefReasons"] = [x for x in (row.get("briefReasons") or []) if "一买" not in str(x)]
        row["reasons"] = [x for x in (row.get("reasons") or []) if "一买" not in str(x)]
        if strategy_history is not None:
            row["score"] = _weighted_intraday_score(row, strategy_history, market_weak=market_weak)

    retained = sorted(
        rows.values(),
        key=lambda row: (bool(row.get("currentMatch")), int(row.get("score") or 0), row.get("lastHitTime", "")),
        reverse=True,
    )
    payload = {
        "tradeDate": now.strftime("%Y-%m-%d"), "updatedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": retained,
    }
    path.parent.mkdir(exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    # JSON 继续作为接口缓存；SQLite 作为可查询的长期盘中历史库，扫描失败不影响实时展示。
    try:
        from backtest.intraday_history_store import save_intraday_hits
        save_intraday_hits(ROOT, now.strftime("%Y-%m-%d"), retained, payload["updatedAt"])
    except Exception:
        pass
    return retained


def _load_learned_strategy() -> dict[str, Any] | None:
    try:
        data = json.loads(LEARNED_STRATEGY_FILE.read_text(encoding="utf-8"))
        return data if data.get("models") else None
    except (OSError, json.JSONDecodeError):
        return None


def _load_sector_validation() -> dict[str, Any]:
    try:
        return json.loads(SECTOR_VALIDATION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"reviewDays": 0, "minimumReviewDays": 20, "status": "样本积累中"}


def _load_historical_sector_model() -> dict[str, Any]:
    try:
        return json.loads(HISTORICAL_SECTOR_MODEL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _with_retained_main_money(stocks: list[dict[str, Any]], now: datetime) -> tuple[list[dict[str, Any]], int]:
    """给已入选但跌出当前高量比池的股票补资金字段，不让其趋势中断。"""
    path = CACHE.parent / f"intraday_hits_{now:%Y-%m-%d}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        old_rows = payload.get("stocks", []) if payload.get("tradeDate") == now.strftime("%Y-%m-%d") else []
    except (OSError, json.JSONDecodeError):
        old_rows = []
    rows = list(stocks)
    stock_map = {str(stock.get("code") or ""): stock for stock in stocks}
    missing_codes = []
    for old in old_rows:
        code = str(old.get("code") or "")
        current = stock_map.get(code)
        if code and (current is None or current.get("mainNetInflow") is None or current.get("mainNetRatio") is None):
            missing_codes.append(code)
    if not missing_codes:
        return rows, 0
    for code in missing_codes:
        if code not in stock_map:
            supplement = {"code": code}
            rows.append(supplement)
            stock_map[code] = supplement
    try:
        flows = fetch_eastmoney_main_money(missing_codes)
    except (requests.RequestException, ValueError, RuntimeError):
        return rows, 0
    for code, flow in flows.items():
        current = stock_map.get(code)
        if current is not None:
            current.update(flow)
        else:
            rows.append({"code": code, **flow, "mainMoneySource": "东方财富"})
    return rows, len(flows)


def _learned_match(stock: dict[str, Any], model: dict[str, Any]) -> bool:
    cfg = model["thresholds"]
    opening_gap = (stock["open"] / stock["prevClose"] - 1) * 100 if stock["prevClose"] else -99
    body_pct = (stock["price"] / stock["open"] - 1) * 100 if stock["open"] else -99
    return bool(
        cfg["minPct"] <= stock["pct"] <= cfg["maxPct"]
        and stock["volumeRatio"] >= cfg["minVolumeRatio"]
        and stock.get("dayPosition", 0) >= cfg["minDayPosition"]
        and stock["amplitude"] <= cfg["maxAmplitude"]
        and opening_gap >= cfg["minOpeningGap"]
        and body_pct >= cfg["minBodyPct"]
        and stock["high"] < stock["prevClose"] * 1.095
    )


def _active_learned_model(strategy: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
    """只在对应30分钟K线已结束后启用，避免盘中偷看未完成K线。"""
    if not strategy:
        return "", None
    now = datetime.now().time()
    if now >= clock_time(15, 0):
        return "", None
    schedule = [
        (clock_time(14, 30), "14:30"), (clock_time(14, 0), "14:00"),
        (clock_time(13, 30), "13:30"), (clock_time(11, 30), "11:30"),
        (clock_time(11, 0), "11:00"), (clock_time(10, 30), "10:30"),
        (clock_time(10, 0), "10:00"),
    ]
    checkpoint = next((name for start, name in schedule if now >= start), "")
    if not checkpoint:
        return "", None
    model = strategy.get("models", {}).get(checkpoint)
    if not model or not model.get("approved", False):
        return checkpoint, None
    return checkpoint, model


def _parse_tencent(codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}
    symbols = ",".join(_market_prefix(c) + c for c in codes)
    try:
        text = _public_get("https://qt.gtimg.cn/q=" + symbols, headers=HEADERS, timeout=6).content.decode("gbk", errors="ignore")
        result = {}
        for line in text.split(";"):
            if '="' not in line:
                continue
            symbol, values = line.split('="', 1)
            parts = values.strip('"').split("~")
            if len(parts) > 3 and symbol.startswith("v_"):
                result[symbol[-6:]] = _number(parts[3])
        return result
    except requests.RequestException:
        return {}


def _parse_sina(codes: list[str]) -> dict[str, float]:
    if not codes:
        return {}
    symbols = ",".join(_market_prefix(c) + c for c in codes)
    try:
        text = _public_get("https://hq.sinajs.cn/list=" + symbols, headers=HEADERS, timeout=6).content.decode("gbk", errors="ignore")
        result = {}
        for line in text.split(";"):
            if '="' not in line:
                continue
            symbol, values = line.split('="', 1)
            fields = values.strip('"').split(",")
            if len(fields) > 3:
                result[symbol[-6:]] = _number(fields[3])
        return result
    except requests.RequestException:
        return {}


def scan_intraday(limit: int = 50) -> dict[str, Any]:
    now = datetime.now()
    # 交易时段外只返回最后一份缓存，避免手工刷新或常驻进程用盘后行情覆盖当日结果。
    if not _is_trading_session(now):
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            cached["servedFromCache"] = True
            return cached
        except (OSError, json.JSONDecodeError):
            return {
                "success": False, "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "error": "当前不在盘中交易时段，且暂无可用盘中缓存", "stocks": [],
            }
    strategy_history = _load_intraday_strategy_history(now)
    primary_error = ""
    try:
        stocks = fetch_eastmoney()
        source_status = {
            "个股行情": "东方财富",
            "东方财富个股": "成功", "东方财富板块": "待获取", "东方财富市场": "待获取", "腾讯": "待校验",
            "新浪": "待校验", "同花顺": "未接入（免费公开接口不稳定）",
        }
    except Exception as exc:
        try:
            primary_error = f"东方财富行情获取失败：{exc}"
            stocks = fetch_tencent_market()
            source_status = {
                "个股行情": "腾讯降级",
                "东方财富个股": f"失败：{type(exc).__name__}", "东方财富板块": "待获取", "东方财富市场": "待获取",
                "腾讯": "个股主行情", "新浪": "待校验", "同花顺": "未接入（免费公开接口不稳定）",
            }
        except Exception as fallback_exc:
            error = f"{primary_error}；腾讯降级行情失败：{fallback_exc}"
            try:
                cached = json.loads(CACHE.read_text(encoding="utf-8"))
                if cached.get("success"):
                    cached["servedFromCache"] = True
                    cached["stale"] = True
                    cached["sourceError"] = error
                    _mark_main_money_stale(cached)
                    return cached
            except (OSError, json.JSONDecodeError):
                pass
            return {"success": False, "time": now.strftime("%Y-%m-%d %H:%M:%S"), "error": error, "stocks": []}
    try:
        sectors = fetch_eastmoney_sectors()
        sector_data_ok = bool(sectors["industry"])
        source_status["东方财富板块"] = "成功" if sector_data_ok else "无数据"
    except Exception as exc:
        sectors = {"industry": [], "concept": []}
        sector_data_ok = False
        source_status["东方财富板块"] = f"失败：{type(exc).__name__}"
    try:
        market = fetch_eastmoney_market_context()
        market_data_ok = True
        source_status["东方财富市场"] = "成功"
    except Exception as exc:
        market = _market_context(stocks)
        market["scope"] = "高量比候选（降级，不用于放行）"
        market_data_ok = False
        source_status["东方财富市场"] = f"失败：{type(exc).__name__}"

    learned_strategy = _load_learned_strategy()
    active_checkpoint, active_model = _active_learned_model(learned_strategy)
    learned_active = active_model is not None
    previous_snapshot = _read_previous_snapshot(now)
    _add_sector_acceleration(sectors, previous_snapshot)
    # 全市场情绪只做提醒，不作为硬风控拦截。弱市阶段继续留给策略做降权处理。
    market_current = not market.get("tradeDate") or market["tradeDate"] == now.strftime("%Y%m%d")
    market_weak = market_data_ok and market_current and market.get("upRatio", 0) < 25
    market_eligible = market_data_ok and market_current
    industry_map = {row["name"]: row for row in sectors["industry"]}
    for stock in stocks:
        stock["score"], stock["reasons"] = _score(stock)
        stock["chanlunBuySignals"], stock["chanlunSellSignals"] = [], []
        stock["bigYangPullbackMatch"] = False
        stock["learnedMatch"] = bool(active_model and _learned_match(stock, active_model))
        if stock["learnedMatch"]:
            stock["score"] = min(100, stock["score"] + 15)
            stock["reasons"].insert(0, "命中本地涨停前形态")
        sector = industry_map.get(stock.get("industry", ""))
        sector_delta, sector_eligible, sector_reasons = _sector_score(sector)
        stock["sectorEligible"] = bool(sector_data_ok and sector_eligible)
        stock["score"] = max(0, min(100, stock["score"] + sector_delta))
        stock["reasons"].extend(sector_reasons)
        stock["sector"] = sector or {}
        if market_weak:
            stock["score"] = max(0, stock["score"] - 15)
            stock["reasons"].append(f"全A上涨家数仅 {market['upRatio']:.0f}%")
    daily_big_yang_scanned = _apply_daily_big_yang(stocks)
    daily_long_shadow_scanned = _apply_daily_long_shadow(stocks)
    chanlun_scanned = _apply_chanlun(stocks)
    # 所有形态识别完成后统一重算最终分。前面的固定加分只用于确定昂贵分钟K分析的
    # 优先顺序，不再直接成为页面分数，因此不会再出现大面积封顶 100。
    for stock in stocks:
        stock["score"] = _weighted_intraday_score(stock, strategy_history, market_weak=market_weak)
    # 当前产品目标是“历史验证过的低涨幅后续触板候选”。没有可用模型时宁可
    # 返回空列表，也不退回到追涨型通用评分，避免混淆两种完全不同的策略。
    stock_pattern_matches = [s for s in stocks if s["learnedMatch"]] if learned_active else []
    chanlun_matches = [s for s in stocks if s.get("chanlunBuySignals")]
    big_yang_matches = [s for s in stocks if s.get("bigYangPullbackMatch")]
    # 历史样本外结果不支持把行业强弱设为硬门槛：验证期唯一触板样本来自弱行业。
    # 行业接口可用时补充板块信息；临时不可用时继续保留个股策略命中并按缺失行业降权。
    combined_matches = {s["code"]: s for s in stock_pattern_matches}
    combined_matches.update({s["code"]: s for s in chanlun_matches})
    combined_matches.update({s["code"]: s for s in big_yang_matches})
    sector_candidates = list(combined_matches.values())
    # 低于50分不进入本轮正式候选，但历史命中仍由 _retain_daily_hits 保留，便于复盘。
    candidates = [s for s in sector_candidates if int(s.get("score") or 0) >= INTRADAY_MIN_SCORE]
    score_filtered = len(sector_candidates) - len(candidates)
    selected = sorted(candidates, key=lambda x: (x["score"], x["amount"]), reverse=True)[:limit]
    for stock in selected:
        brief = [signal["name"] for signal in stock.get("chanlunBuySignals", [])]
        if stock.get("learnedMatch"):
            brief.append("低涨幅后续触板")
        if stock.get("bigYangPullbackMatch"):
            brief.append("大阳回调不破10日线")
        if not sector_data_ok:
            brief.append("行业数据降级")
        sector = stock.get("sector") or {}
        if _number(sector.get("mainNetRatio")) > 0:
            brief.append(f"行业资金+{_number(sector.get('mainNetRatio')):.1f}%")
        brief.append(f"量比{stock['volumeRatio']:.1f}")
        stock["briefReasons"] = brief[:4]
    # 空结果也必须说明原因。盘中“没有候选”是策略风控的正常结果，不应让页面
    # 看起来像脚本没有运行或行情接口失效。
    no_candidate_reasons: list[str] = []
    next_observation = ""
    if not selected:
        if not market_current:
            no_candidate_reasons.append("当前不是有效交易日行情，已停止输出候选。")
        if not sector_data_ok:
            no_candidate_reasons.append("东方财富行业板块数据本轮不可用，已按缺失行业降权继续扫描。")
        if not learned_active:
            if not active_checkpoint:
                no_candidate_reasons.append("当前处于开盘初始阶段，尚未到达已验证的观察检查点。")
                next_observation = "10:30～11:00"
            else:
                no_candidate_reasons.append(
                    f"当前处于 {active_checkpoint} 检查点；该时点的旧版个股规则未通过历史验证，暂不输出正式候选。"
                )
                if now.time() < clock_time(10, 30):
                    next_observation = "10:30～11:00"
        if market_weak:
            no_candidate_reasons.append(
                f"全A上涨家数仅 {market['upRatio']:.1f}%（情绪冰点）；当前仅作风险提示并进行降权。"
            )
        if learned_active and not stock_pattern_matches:
            no_candidate_reasons.append("已到有效观察窗口，但没有股票同时满足低涨幅、量比、高开、日内位置及未触板等个股形态。")
        if chanlun_scanned and not chanlun_matches:
            no_candidate_reasons.append(f"已对优先级最高的 {chanlun_scanned} 只股票分析30/60分钟K线，本轮未形成缠论二买或三买。")
        if learned_active and stock_pattern_matches and not sector_candidates and sector_data_ok and market_eligible:
            no_candidate_reasons.append("个股形态虽有命中，但缺少可用的行业板块归属，暂不输出候选。")
        if sector_candidates and not candidates:
            no_candidate_reasons.append(f"命中形态的股票评分均低于{INTRADAY_MIN_SCORE}分，本轮未输出正式候选。")
    codes = [s["code"] for s in selected]
    tx, sina = _parse_tencent(codes), _parse_sina(codes)
    source_status["腾讯"] = "成功" if tx else ("无需校验" if not codes else "不可用")
    source_status["新浪"] = "成功" if sina else ("无需校验" if not codes else "不可用")
    for stock in selected:
        checks = {"东方财富": stock["price"]}
        if tx.get(stock["code"]): checks["腾讯"] = tx[stock["code"]]
        if sina.get(stock["code"]): checks["新浪"] = sina[stock["code"]]
        stock["quoteChecks"] = checks
        stock["verified"] = len(checks) >= 2 and max(checks.values()) - min(checks.values()) <= max(.03, stock["price"] * .003)
    # 午间及11:30之后的页面刷新也必须保留当天早些时候命中的股票。
    # _is_trading_session 用于是否实际扫描行情，这里只要仍是当日盘中即可维护累计记录。
    day_market_window = market_current and now.weekday() < 5 and clock_time(9, 30) <= now.time() <= clock_time(15, 30)
    if day_market_window:
        retention_stocks, retained_money_updated = _with_retained_main_money(stocks, now)
        source_status["东方财富个股资金"] = f"成功补充{retained_money_updated}只" if retained_money_updated else "随个股行情更新"
        daily_hits = _retain_daily_hits(now, selected, retention_stocks, strategy_history, market_weak)
    else:
        daily_hits = selected
    display_stocks = daily_hits[:limit]
    snapshot_path, snapshot_error = "", ""
    if _is_trading_session(now) and market_current:
        try:
            snapshot_path = _save_snapshot(now, stocks, sectors, market, active_checkpoint)
        except Exception as exc:
            snapshot_error = f"快照保存失败：{exc}"
    else:
        snapshot_error = "非交易时段或非当前交易日，不保存快照"
    result = {
        "success": True, "time": now.strftime("%Y-%m-%d %H:%M:%S"), "sources": source_status,
        "total": len(stocks), "stockPatternMatched": len(stock_pattern_matches),
        "dailyBigYangScanned": daily_big_yang_scanned, "dailyBigYangMatched": len(big_yang_matches),
        "dailyLongShadowScanned": daily_long_shadow_scanned,
        "chanlunScanned": chanlun_scanned, "chanlunMatched": len(chanlun_matches),
        "matched": len(selected), "dayMatched": len(daily_hits),
        "sectorFiltered": len(stock_pattern_matches) - len(candidates),
        "scoreThreshold": INTRADAY_MIN_SCORE, "scoreFiltered": score_filtered,
        "weakSectorCandidates": sum(not s["sectorEligible"] for s in candidates),
        "learnedStrategyActive": learned_active, "activeCheckpoint": active_checkpoint,
        "learnedStrategy": active_model or {},
        "strategyProvenance": {
            "historyVersion": "legacy-individual-stock-v1", "historySource": "本地BaoStock 30分钟缓存",
            "individualModelSectorHistoryIncluded": False,
            "sectorHistoricalResearch": "已用主板历史K线推演，验证未改善，因此仅用于实时评分",
            "sectorOverlay": "东方财富盘中行业快照",
            "chanlun": "东方财富最新30/60分钟K线；二买/三买独立入选，卖点参与风险降分",
        },
        "sectorFilterActive": sector_data_ok, "marketCurrent": market_current,
        "marketEligible": market_eligible, "market": market,
        "noCandidateReasons": no_candidate_reasons, "nextObservation": next_observation,
        "sectorValidation": _load_sector_validation(),
        "historicalSectorResearch": _load_historical_sector_model(),
        "intradayStrategyHistory": strategy_history,
        "topIndustries": sorted(sectors["industry"], key=lambda x: (x["pct"], x["breadth"]), reverse=True)[:10],
        "topConcepts": sorted(sectors["concept"], key=lambda x: (x["pct"], x["breadth"]), reverse=True)[:10],
        "snapshot": snapshot_path, "snapshotError": snapshot_error, "stocks": display_stocks,
        "quotes": {str(s.get("code")): {"price": s.get("price"), "pct": s.get("pct")} for s in stocks if s.get("code")},
        "disclaimer": "盘中缠论使用东方财富最新30/60分钟K线，二买/三买可独立进入候选，卖点用于风险降分。免费网页行情可能延迟或中断，仅供研究排序。",
    }
    # 14:40后单独生成尾盘候选缓存，页面通过子标签读取，不干扰盘中实时列表。
    tail_ready = _is_trading_session(now) and now.time() >= clock_time(14, 40) and market_current
    if tail_ready:
        tail_selected = []
        for stock in stocks:
            strategies = []
            second_buys = [x for x in stock.get("chanlunBuySignals", []) if x.get("type") == "2B"]
            strategies.extend(x["name"] for x in second_buys)
            if stock.get("longShadowMatch"): strategies.append("长上下影线")
            if stock.get("bigYangPullbackMatch"): strategies.append("主升-大阳回调不破10日线")
            if strategies and stock.get("sector"):
                item = dict(stock)
                item["tailStrategies"] = strategies
                item["briefReasons"] = strategies[:3]
                tail_selected.append(item)
        tail_selected.sort(key=lambda x: (x["score"], x["amount"]), reverse=True)
        retained_tail = _retain_tail_hits(now, tail_selected[:limit])
        result["tailReady"] = True
        result["tailMatched"] = len(tail_selected)
        result["tailStocks"] = retained_tail[:limit]
    else:
        result["tailReady"] = False
        result["tailMatched"] = 0
        result["tailStocks"] = []
    OUTPUT.mkdir(exist_ok=True)
    temp = CACHE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CACHE)
    return result


def _run_scan_with_deadline(limit: int, timeout_seconds: float = SCAN_DEADLINE_SECONDS) -> dict[str, Any]:
    """为整轮扫描设置硬截止时间，防止底层网络连接长期占住循环进程。"""
    def expire(_signum, _frame):
        raise _ScanDeadlineExceeded()

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, timeout_seconds))
    try:
        return scan_intraday(limit)
    except _ScanDeadlineExceeded:
        attempted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = {"success": False, "stocks": []}
        cached["servedFromCache"] = bool(cached.get("success"))
        cached["stale"] = True
        cached["scanTimedOut"] = True
        cached["scanAttemptTime"] = attempted_at
        cached["sourceError"] = f"本轮扫描超过 {timeout_seconds:g} 秒，已终止并保留上次结果"
        _mark_main_money_stale(cached)
        return cached
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0 or previous_timer[1] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def main() -> None:
    parser = argparse.ArgumentParser(description="盘中实时股票评分（仅研究排序）")
    parser.add_argument("--limit", type=int, default=50, help="展示候选数量，默认50")
    parser.add_argument("--loop", action="store_true", help="循环获取实时行情")
    parser.add_argument("--interval", type=int, default=60, help="循环间隔秒数，默认60")
    args = parser.parse_args()
    while True:
        result = _run_scan_with_deadline(args.limit)
        log_time = result.get("scanAttemptTime") or result.get("time")
        status = result.get("sourceError") if result.get("scanTimedOut") else ("成功" if result.get("success") else result.get("error"))
        print(f"{log_time}：{status}，候选 {len(result.get('stocks', []))} 只")
        if not args.loop:
            break
        time.sleep(max(10, args.interval))


if __name__ == "__main__":
    main()
