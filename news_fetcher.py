# -*- coding: utf-8 -*-
"""
news_fetcher.py — 财经快讯自动抓取 + 四维分类 + 情绪/板块标注

数据源（多源冗余，任一可用即可）：
  1. 东方财富快讯  np-listapi.eastmoney.com   —— 主力源，字段最干净
  2. 新浪财经滚动  feed.mix.sina.com.cn
  3. 同花顺快讯    news.10jqka.com.cn

设计原则（沿用 Vibe-Trading 的可溯源思想）：
  - 每条新闻记录来源 source + 抓取时间
  - 分类结果标记为 derived（规则推断），非事实陈述
  - 全部源失败时返回 None，由调用方保留上一次数据（fail-closed）
"""
import json
import os
import re
import ssl
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get(url, timeout=12):
    """带 UA 的 GET，返回文本；失败抛异常由调用方处理"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", "replace")


# ============================================================
#  四维分类关键词表
# ============================================================
DIMS = {
    "military": {
        "name": "军事地缘",
        "kw": ["军事", "军队", "美军", "俄军", "乌军", "以军", "哈马斯", "伊朗", "以色列",
               "导弹", "无人机", "袭击", "空袭", "战争", "停火", "谈判", "冲突", "军演",
               "国防", "航母", "核", "制裁", "地缘", "边境", "部署", "部队", "武器",
               "特朗普", "北约", "欧盟", "外交", "大使", "撤军", "驻军", "打击"],
    },
    "economic": {
        "name": "宏观经济/政策",
        "kw": ["央行", "货币政策", "降息", "加息", "降准", "逆回购", "MLF", "LPR", "利率",
               "GDP", "CPI", "PPI", "PMI", "通胀", "通缩", "经济", "财政", "减税", "国债",
               "国务院", "发改委", "财政部", "统计局", "证监会", "政策", "国务院常务",
               "楼市", "房地产", "房价", "购房", "贷款", "贴息", "消费", "就业", "失业率",
               "外贸", "进出口", "关税", "汇率", "人民币", "美元指数", "美联储", "非农",
               "PCE", "国债收益率", "预算", "赤字", "两会", "规划"],
    },
    "tech": {
        "name": "AI 与科技",
        "kw": ["AI", "人工智能", "大模型", "算力", "芯片", "半导体", "光刻", "晶圆", "GPU",
               "英伟达", "NVIDIA", "AMD", "英特尔", "台积电", "三星", "美光", "存储",
               "机器人", "自动驾驶", "智能驾驶", "华为", "昇腾", "鸿蒙", "DeepSeek", "OpenAI",
               "微软", "谷歌", "Meta", "特斯拉", "苹果", "量子", "5G", "6G", "数据中心",
               "云计算", "开源", "算法", "软件", "互联网", "科技", "卫星", "航天", "商业航天"],
    },
    "risk": {
        "name": "市场资金面",
        "kw": ["成交额", "成交量", "涨停", "跌停", "北向", "南向", "主力", "游资", "融资",
               "两融", "ETF", "基金", "板块", "个股", "指数", "沪指", "深指", "创业板",
               "科创板", "增持", "减持", "回购", "解禁", "IPO", "新股", "退市", "立案",
               "ST", "违约", "爆雷", "市值", "估值", "券商", "调整", "反弹", "下跌", "上涨"],
    },
}

# 四维配额：单维上限 40%（防某一维淹没版面），单维保底 15%（保证四维都出现）
MAX_PER_DIM_RATIO = 0.40
MIN_PER_DIM_RATIO = 0.15

# 利好 / 利空 情绪词
BULL_KW = ["上涨", "走高", "大涨", "涨停", "创新高", "增长", "回升", "复苏", "扩张", "改善",
           "超预期", "利好", "提振", "宽松", "降息", "降准", "减税", "支持", "补贴", "回暖",
           "突破", "签约", "中标", "获批", "合作", "上调", "增持", "回购", "盈利", "扭亏",
           "转正", "新高", "涨停潮", "流入", "净买入", "反弹", "攀升", "劲增", "爆发"]
BEAR_KW = ["下跌", "走低", "大跌", "跌停", "创新低", "下滑", "萎缩", "放缓", "恶化", "不及预期",
           "利空", "承压", "收紧", "加息", "抛售", "清仓", "退市", "立案", "处罚", "违规",
           "违约", "爆雷", "亏损", "下调", "减持", "解禁", "流出", "净卖出", "回落", "跳水",
           "暴跌", "重挫", "风险", "警示", "调查", "诉讼", "索赔", "裁员", "破产"]

# 板块识别（新闻 -> 受益板块）
SECTOR_MAP = {
    "半导体/AI芯片": ["芯片", "半导体", "光刻", "晶圆", "GPU", "英伟达", "算力", "存储",
                  "美光", "台积电", "中芯", "国产替代"],
    "AI应用/软件": ["AI", "人工智能", "大模型", "DeepSeek", "OpenAI", "算法", "软件",
                 "SaaS", "机器人", "智能体"],
    "算力/数据中心": ["算力", "数据中心", "IDC", "服务器", "云计算", "液冷", "光模块"],
    "军工/国防": ["军工", "国防", "导弹", "无人机", "航母", "军费", "兵器", "航空发动机"],
    "黄金/贵金属": ["黄金", "金价", "避险", "白银", "贵金属"],
    "石油/能源": ["石油", "原油", "油价", "天然气", "柴油", "OPEC", "能源"],
    "航运/物流": ["航运", "海运", "港口", "运价", "红海", "苏伊士", "物流"],
    "地产/基建": ["地产", "房地产", "楼市", "房价", "基建", "水泥", "钢铁", "购房", "保障房"],
    "消费/白酒": ["消费", "白酒", "食品", "零售", "免税", "旅游", "餐饮"],
    "医药/生物": ["医药", "生物", "疫苗", "创新药", "医疗器械", "集采"],
    "券商/大金融": ["券商", "证券", "保险", "银行", "金融"],
    "新能源/锂电": ["新能源", "锂电", "光伏", "储能", "风电", "电池", "宁德"],
    "汽车/智能驾驶": ["汽车", "智能驾驶", "自动驾驶", "新能源车", "特斯拉", "整车"],
    "农业/种业": ["农业", "种业", "粮食", "猪价", "饲料"],
    "电力/公用": ["电力", "电网", "核电", "水电", "电价", "火电"],
}


def classify_dim(text):
    """按关键词命中数选维度，返回 (dim_key, score)"""
    best, best_n = "risk", 0
    for k, v in DIMS.items():
        n = sum(1 for w in v["kw"] if w in text)
        if n > best_n:
            best, best_n = k, n
    return best, best_n


def judge_impact(text):
    """情绪判定：利好 / 利空 / 中性，返回 (impact_key, hit_bull, hit_bear)"""
    b = sum(1 for w in BULL_KW if w in text)
    s = sum(1 for w in BEAR_KW if w in text)
    if b > s:
        return "bull", b, s
    if s > b:
        return "bear", b, s
    return "neutral", b, s


def match_sectors(text, limit=3):
    """命中板块，按命中词数排序"""
    hits = []
    for name, kws in SECTOR_MAP.items():
        n = sum(1 for w in kws if w in text)
        if n:
            hits.append((name, n))
    hits.sort(key=lambda x: -x[1])
    return [h[0] for h in hits[:limit]]


# ============================================================
#  抓取源
# ============================================================
def fetch_eastmoney(page_size=80):
    """东方财富快讯 — 主力源"""
    url = ("https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
           f"?client=web&biz=web_724&fastColumn=102&sortEnd=&pageSize={page_size}&req_trace=1")
    d = json.loads(_get(url))
    out = []
    for it in d.get("data", {}).get("fastNewsList", []):
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        # summary 常以【标题】开头，去掉避免重复
        body = summary
        if title and body.startswith("【" + title + "】"):
            body = body[len(title) + 2:].strip()
        if not title and summary.startswith("【"):
            m = re.match(r"【(.+?)】(.*)", summary)
            if m:
                title, body = m.group(1), m.group(2).strip()
        if not title:
            continue
        out.append({
            "title": title,
            "body": body or summary,
            "time": it.get("showTime", ""),
            "stocks": it.get("stockList") or [],
            "src": "东方财富",
            "id": it.get("code", ""),
        })
    return out


def fetch_sina(page_size=50):
    """新浪财经滚动"""
    url = ("https://feed.mix.sina.com.cn/api/roll/get"
           f"?pageid=155&lid=1686&num={page_size}&page=1")
    d = json.loads(_get(url))
    out = []
    for it in d.get("result", {}).get("data", []):
        title = (it.get("title") or "").strip()
        if not title:
            continue
        ts = it.get("ctime")
        try:
            t = datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            t = ""
        out.append({
            "title": title,
            "body": (it.get("intro") or "").strip(),
            "time": t,
            "stocks": [],
            "src": "新浪财经",
            "id": str(it.get("oid", "")),
        })
    return out


def fetch_10jqka(page_size=50):
    """同花顺快讯"""
    url = ("https://news.10jqka.com.cn/tapp/news/push/stock/"
           f"?page=1&tag=&track=website&pagesize={page_size}")
    d = json.loads(_get(url))
    out = []
    for it in d.get("data", {}).get("list", []):
        title = (it.get("title") or "").strip()
        if not title:
            continue
        ts = it.get("ctime") or it.get("rtime")
        try:
            t = datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            t = ""
        out.append({
            "title": title,
            "body": (it.get("digest") or "").strip(),
            "time": t,
            "stocks": [],
            "src": "同花顺",
            "id": str(it.get("seq", "")),
        })
    return out


SOURCES = [
    ("东方财富", fetch_eastmoney),
    ("新浪财经", fetch_sina),
    ("同花顺", fetch_10jqka),
]


# ============================================================
#  主流程
# ============================================================
def collect_news(per_source=80, max_items=60, log=True):
    """
    抓取 + 去重 + 分类，返回 (items, provenance_dict)
    items: 按重要性排序的新闻列表；全部源失败时返回 (None, prov)
    """
    raw, ok_src, fail_src = [], [], []
    for name, fn in SOURCES:
        try:
            items = fn(per_source)
            if items:
                raw.extend(items)
                ok_src.append(f"{name}({len(items)})")
                if log:
                    print(f"  [OK]   {name}: {len(items)} 条", file=sys.stderr)
            else:
                fail_src.append(name + "(空)")
        except Exception as e:
            fail_src.append(f"{name}({type(e).__name__})")
            if log:
                print(f"  [FAIL] {name}: {type(e).__name__} {str(e)[:60]}", file=sys.stderr)

    prov = {
        "source": "东方财富快讯 / 新浪财经 / 同花顺快讯（公开接口）",
        "source_type": "public_news_api",
        "fetched_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "auth": "none",
        "sources_ok": ok_src,
        "sources_fail": fail_src,
    }

    if not raw:
        return None, prov

    # 去重：标题前 18 字做指纹
    seen, uniq = set(), []
    for it in raw:
        fp = re.sub(r"\s+", "", it["title"])[:18]
        if fp in seen:
            continue
        seen.add(fp)
        uniq.append(it)

    # 四维分类 + 情绪 + 板块（看板展示用）
    for it in uniq:
        text = it["title"] + " " + it["body"]
        dim, dim_score = classify_dim(text)
        impact, nb, ns = judge_impact(text)
        it["dim"] = dim
        it["dimName"] = DIMS[dim]["name"]
        it["dim_score"] = dim_score
        it["impact"] = impact
        it["sectors"] = match_sectors(text)
        it["has_stock"] = 1 if it.get("stocks") else 0

    # 重要性评分：五轴加权 + 噪声压制 + 双通道门槛（news_scoring 模块）
    # 取代早先「关键词命中数 × 3」的简易排序 —— 那种算法下，
    # 同一件事被多家媒体各报一遍反而分更高，是反向激励。
    try:
        from news_scoring import score_all as _score_all
        uniq, score_stat = _score_all(uniq)
        prov["scoring"] = score_stat
    except Exception as e:
        print(f"  [warn] 评分层不可用，回退简易打分: {e}", file=sys.stderr)
        for it in uniq:
            it["score"] = (it["dim_score"] * 3 + it["has_stock"] * 4
                           + (2 if it["impact"] != "neutral" else 0))
            it["final_score"] = it["score"]
            it["passed"] = True
        uniq.sort(key=lambda x: -x["final_score"])
        prov["scoring"] = {"fallback": True}

    uniq.sort(key=lambda x: -x.get("final_score", 0))

    # 硬淘汰的条目直接出局，不进入候选池
    # （否则「埃尼集团柴油折扣」这类被判定的噪声仍会出现在看板和事件列表里）
    pool = [x for x in uniq if not x.get("hard_drops")]
    if not pool:
        pool = uniq

    # 选取：每维上限 40% 防单一维度淹没，同时每维保底 15% 条
    # 保证「四维全覆盖」不会因为某一维分数普遍偏低而被清空
    cap = max(5, int(max_items * MAX_PER_DIM_RATIO))
    floor = max(4, int(max_items * MIN_PER_DIM_RATIO))
    picked, per_dim = [], {k: 0 for k in DIMS}
    picked_ids = set()
    for it in pool:
        if len(picked) >= max_items:
            break
        if per_dim[it["dim"]] >= cap:
            continue
        per_dim[it["dim"]] += 1
        picked.append(it)
        picked_ids.add(id(it))
    # 保底补齐
    for k in DIMS:
        if per_dim[k] >= floor:
            continue
        need = floor - per_dim[k]
        added = 0
        for it in pool:
            if added >= need or len(picked) >= max_items:
                break
            if it["dim"] == k and id(it) not in picked_ids:
                it["backfill"] = True     # 标记为「保底入选」，看板可显示
                picked.append(it)
                picked_ids.add(id(it))
                per_dim[k] += 1
                added += 1

    prov["total_fetched"] = len(raw)
    prov["after_dedupe"] = len(uniq)
    prov["picked"] = len(picked)
    prov["passed_threshold"] = sum(1 for x in uniq if x.get("passed"))
    prov["dim_dist"] = {DIMS[k]["name"]: v for k, v in per_dim.items() if v}

    return picked, prov


def main():
    items, prov = collect_news(log=True)
    if items is None:
        print("[ABORT] 全部新闻源失败，保留上一次数据", file=sys.stderr)
        return 1
    out = {"date": datetime.now(CST).strftime("%Y-%m-%d"), "news": items, "provenance": prov}
    path = os.path.join(DATA_DIR, "auto_news.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"-> auto_news.json ({len(items)} 条)")
    print(f"   维度分布: {prov['dim_dist']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
