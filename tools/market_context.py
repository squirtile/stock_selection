# -*- coding: utf-8 -*-
"""
市场环境评估
============
读取 sector_heat.json + money_flow.json，生成每个行业/概念的板块热度标签。

输出: output/market_context.json

标签规则:
  🔥 热门: 近一周涨停数≥3天 且 资金净流入
  🌡️ 温和: 近一周登场≥1天 或 资金有进有出
  ❄️ 冷门: 近一周未登场 或 资金持续流出

大盘趋势:
  📈 强势: 上证在MA20上方 + 主力净流入
  📊 震荡: 上证在MA20附近 ±2%
  📉 弱势: 上证在MA20下方 + 主力净流出

用法:
  python tools/market_context.py --json
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# 行业→概念映射（粗粒度，用于把行业标签映射到概念板块中查热度）
# 如果 sector_heat.json 里没有该行业的直接数据，用这个概念去查
INDUSTRY_TO_CONCEPT_MAP = {
    "半导体": "芯片概念",
    "元器件": "消费电子概念",
    "软件服务": "人工智能",
    "通信设备": "5G",
    "IT设备": "信创",
    "互联网": "数字经济",
    "化学制药": "创新药",
    "生物制药": "创新药",
    "中成药": "中药",
    "医疗保健": "医疗器械概念",
    "医药商业": "医药电商",
    "化学原料": "氢能源",
    "化工原料": "锂电池概念",
    "农药化肥": "化肥",
    "塑料": "可降解塑料",
    "橡胶": "汽车热管理",
    "化纤": "碳纤维",
    "钢铁": "特钢概念",
    "小金属": "稀土永磁",
    "黄金": "黄金概念",
    "铜": "金属铜",
    "铝": "工业金属",
    "煤炭开采": "煤炭概念",
    "石油开采": "天然气",
    "石油加工": "石油加工贸易",
    "电力": "绿色电力",
    "水力发电": "抽水蓄能",
    "火力发电": "碳中和",
    "新型电力": "储能",
    "供气供热": "天然气",
    "环境保护": "碳中和",
    "污水处理": "污水处理",
    "固废处理": "固废处理",
    "建筑工程": "新型城镇化",
    "装修装饰": "装配式建筑",
    "房地产": "物业管理",
    "水泥": "水泥概念",
    "玻璃": "光伏概念",
    "陶瓷": "建筑材料",
    "机械基件": "机器人概念",
    "专用机械": "工业母机",
    "通用机械": "高端装备",
    "电气设备": "充电桩",
    "电网设备": "智能电网",
    "仪器仪表": "传感器",
    "运输设备": "飞行汽车(eVTOL)",
    "汽车整车": "新能源汽车",
    "汽车配件": "汽车零部件",
    "汽车服务": "汽车服务及其他",
    "家用电器": "智能家居",
    "家居用品": "智能家居",
    "食品": "预制菜",
    "饲料": "猪肉",
    "农业综合": "乡村振兴",
    "种植业": "农业种植",
    "渔业": "水产养殖",
    "服饰": "网红经济",
    "纺织": "人民币贬值受益",
    "造纸": "造纸",
    "广告包装": "文化传媒概念",
    "文教休闲": "体育产业",
    "影视音像": "短剧游戏",
    "出版业": "知识产权保护",
    "旅游服务": "旅游概念",
    "酒店餐饮": "预制菜",
    "超市连锁": "新零售",
    "百货": "免税店",
    "水运": "航运概念",
    "空运": "机场航运",
    "港口": "自由贸易港",
    "铁路": "高铁",
    "路桥": "公路铁路运输",
    "多元金融": "互联网金融",
    "证券": "证券",
    "保险": "保险",
    "银行": "银行",
    "日用化工": "化妆品",
    "轻工机械": "工业母机",
    "综合类": "国企改革",
}


def load_json(filename: str) -> dict:
    path = OUTPUT_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_context() -> dict:
    """构建市场环境上下文"""
    # 读取现有数据
    sector_data = load_json("sector_heat.json")
    money_data = load_json("money_flow.json")

    # ── 大盘评估 ──
    market = {"trend": "neutral", "label": "📊 震荡", "score": 0}
    mkt = money_data.get("mkt", {})
    if mkt:
        net = mkt.get("net_amount", 0)
        sh_pct = mkt.get("pct_change_sh", 0)
        # 综合判断：主力净额 + 涨跌幅
        if sh_pct > 0.3 and net > 0:
            market = {"trend": "bullish", "label": "📈 强势", "score": 1}
        elif sh_pct < -0.5 and net < -100:
            market = {"trend": "bearish", "label": "📉 弱势", "score": -1}
        else:
            market = {"trend": "neutral", "label": "📊 震荡", "score": 0}

    # ── 板块热度映射 ──
    # 用"一周汇总"里的板块名作热度查表
    summary = sector_data.get("summary", [])
    sector_heat: dict[str, dict] = {}
    for item in summary:
        name = item.get("name", "")
        if name:
            sector_heat[name] = {
                "appear_days": item.get("count", 0),
                "avg_rank": item.get("avg_rank", 99),
                "avg_up_nums": item.get("avg_up_nums", 0),
                "avg_pct_chg": item.get("avg_pct_chg", 0),
                "heat_score": item.get("heat_score", 0),
            }

    # ── 资金流向（概念板块维度） ──
    concept_flow: dict[str, dict] = {}
    cnt_list = money_data.get("cnt", [])
    for item in cnt_list:
        name = item.get("name", "")
        if name:
            concept_flow[name] = {
                "pct_change": item.get("pct_change", 0),
                "net_buy": item.get("net_buy_amount", 0),
                "net_sell": item.get("net_sell_amount", 0),
                "net_amount": item.get("net_amount", 0),
                "lead_stock": item.get("lead_stock", ""),
            }

    # ── 行业资金流向 ──
    industry_flow: dict[str, dict] = {}
    ind_list = money_data.get("ind", [])
    for item in ind_list:
        name = item.get("industry", "")
        if name:
            industry_flow[name] = {
                "pct_change": item.get("pct_change", 0),
                "net_buy": item.get("net_buy_amount", 0),
                "net_sell": item.get("net_sell_amount", 0),
                "net_amount": item.get("net_amount", 0),
                "lead_stock": item.get("lead_stock", ""),
            }

    # ── 为每个行业/概念打标签 ──
    sector_labels: dict[str, dict] = {}

    def classify(heat: dict | None, flow: dict | None) -> dict:
        """根据热度+资金流向分类"""
        # 热度（一周内出现天数判断）
        hot = (heat.get("appear_days", 0) >= 3) if heat else False
        warm = (heat.get("appear_days", 0) >= 1) if heat else False

        # 资金方向
        net = flow.get("net_amount", 0) if flow else 0
        inflow = net > 0
        outflow = net < 0

        if hot and inflow:
            return {"label": "🔥 热门", "score": 2}
        elif hot and not inflow:
            return {"label": "🔥 热门(分歧)", "score": 1}
        elif warm and inflow:
            return {"label": "🌡️ 温和", "score": 1}
        elif warm and outflow:
            return {"label": "🌡️ 温和(流出)", "score": 0}
        elif not hot and not warm and inflow:
            return {"label": "🌡️ 新进", "score": 0}
        else:
            return {"label": "❄️ 冷门", "score": -1}

    # 按概念板块名标记
    for concept_name, heat in sector_heat.items():
        flow = concept_flow.get(concept_name, {})
        sector_labels[concept_name] = classify(heat, flow)

    # 补充概念板块中未出现但行业存在的（通过资金流向判断）
    for ind_name, flow in industry_flow.items():
        if ind_name not in sector_labels:
            # 尝试通过映射找对应概念
            concept_name = INDUSTRY_TO_CONCEPT_MAP.get(ind_name)
            if concept_name and concept_name in sector_labels:
                sector_labels[ind_name] = sector_labels[concept_name].copy()
                sector_labels[ind_name]["matched_via"] = concept_name
            else:
                # 单凭资金流向判断
                net = flow.get("net_amount", 0)
                label = "🌡️ 温和" if net > 0 else "❄️ 冷门"
                score = 1 if net > 0 else -1
                sector_labels[ind_name] = {"label": label, "score": score}

    # ── 汇总输出 ──
    trade_date = money_data.get("trade_date", datetime.now().strftime("%Y%m%d"))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": trade_date,
        "market": market,
        "sectors": sector_labels,
        "concept_flow": concept_flow,
        "industry_flow": industry_flow,
    }


def export_json():
    """导出 market_context.json"""
    context = build_context()
    output_path = OUTPUT_DIR / "market_context.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2, default=str)

    # 输出摘要（去掉表情符号，Windows GBK 终端不兼容）
    label_no_emoji = context['market']['label'].replace("📈", "").replace("📉", "").replace("📊", "").strip()
    print(f"[OK] 市场环境评估完成")
    print(f"   大盘: {label_no_emoji}")
    labels = context["sectors"]
    hot = sum(1 for v in labels.values() if "热门" in v["label"])
    warm = sum(1 for v in labels.values() if "温和" in v["label"])
    cold = sum(1 for v in labels.values() if "冷门" in v["label"])
    print(f"   板块: 热门{hot} 温和{warm} 冷门{cold}")
    print(f"   -> {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="市场环境评估")
    parser.add_argument("--json", action="store_true", help="导出 JSON")
    args = parser.parse_args()

    if args.json:
        export_json()
    else:
        export_json()
