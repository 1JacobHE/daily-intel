# -*- coding: utf-8 -*-
"""
event_cluster.py — 事件聚簇层

解决的问题（原项目实测）：
  60 条快讯里，7 条美联储快讯其实是同一次官员密集讲话被 7 家媒体各报一遍，
  占了 12% 版面，还会在排序里因为「关键词命中多」拿到最高分。
  本质是「按文章聚合」，缺了「按事件聚合」这一步。

方法借鉴 AIHOT（KKKKhazix/AIHOT）的事件归组：
  1. 召回：近两周窗口内按标题相似度找候选
  2. 判定：LLM 判四种关系 —— 本项目改为规则判定（无 LLM 依赖）
       SAME_OCCURRENCE  同一次发生（多家媒体报道同一件事）→ 合并为一条
       SAME_STORY       同一主体的后续进展（美联储不同官员讲话）→ 归组但各自保留
       ROUNDUP          汇总类（早报/晚报/隔夜要闻）→ 不参与合并，单独标注
       UNRELATED        无关
  3. 热度按事件算，不按文章算：48 小时内每个独立来源只算一次，24 小时减半
     —— 一家媒体发十篇也只算一次，排在前面的才是真的有很多人在说

诚实标注：判定环节是规则实现（字符串相似度 + 实体重叠），非 LLM 语义判断，
因此在 provenance 中标记为 derived，且会在结果里保留「判定依据」以便复核。
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# 相似度阈值
SAME_OCCURRENCE_T = 0.52     # 高于此值 → 判定为同一次发生，合并
SAME_STORY_T = 0.30          # 高于此值且有同主体 → 同一事件的后续，归组不合并

# 汇总类特征
ROUNDUP_KW = ["早报", "晚报", "午评", "收盘", "隔夜", "一览", "汇总", "盘点", "梳理",
              "要闻回顾", "今日必读", "你需要知道", "财经日历", "周报", "快讯汇总"]

# 实体提取：机构 / 公司 / 官方主体
# 早期版本词典过窄，导致「亚马逊据悉…」与「亚马逊…」、「博通据悉筹措…」与
# 「博通筹措…」这类同主体条目共享实体数识别为 0，漏合并。
# 现在三层策略：预设机构词典 + 通用中文主体模式 + 英文专名。
ENT_DICT = [
    # 官方 / 国际组织
    "美联储", "FOMC", "欧央行", "欧洲央行", "日本央行", "中国人民银行", "央行",
    "国家统计局", "统计局", "财政部", "发改委", "证监会", "工信部", "商务部",
    "住建部", "国资委", "海关总署", "国务院", "特朗普", "白宫", "北约", "欧盟",
    "达拉斯联储", "纽约联储", "旧金山联储", "克利夫兰联储",
    # 科技 / 芯片
    "英伟达", "NVIDIA", "AMD", "英特尔", "微软", "谷歌", "苹果", "特斯拉", "Meta",
    "OpenAI", "Anthropic", "台积电", "三星", "美光", "华为", "小米", "高通", "博通",
    "软银", "亚马逊", "甲骨文", "IBM", "索尼", "任天堂",
    # 金融 / 能源 / 消费
    "嘉能可", "埃尼集团", "摩根士丹利", "高盛", "摩根大通", "花旗", "富国银行",
    "丰业银行", "城堡证券", "贝莱德", "耐克", "可口可乐", "波音",
    # 中概 / A股
    "比亚迪", "小鹏", "理想", "蔚来", "宁德时代", "隆基", "中芯国际", "寒武纪",
    "贵州茅台", "招商银行", "平安",
]
ENT_RE_LIST = re.compile("|".join(re.escape(x) for x in
                                  sorted(ENT_DICT, key=len, reverse=True)))
# 通用中文主体 + 英文专名（连续大写开头词，如 WTI / AT&T / DAX）
ENT_RE_GENERIC = re.compile(
    r"([一-龥]{2,6}(?:集团|银行|证券|基金|科技|电子|能源|股份|控股|汽车|医药|"
    r"半导体|地产|证券|保险|重工|航空|通信|网络|生物|材料|电力|煤业|矿业))")
ENT_RE_EN = re.compile(r"\b([A-Z][A-Za-z&]{1,12})\b")

# 主题词：用于判定「是否同一话题」
TOPIC_KW = {
    # 不要把「利率」「基点」放进美联储主题 —— 它们是通用词，
    # 会把「日本2年期国债收益率下跌2.5个基点」这类全球债市新闻吸进来
    "美联储利率": ["美联储", "联储", "加息", "降息", "FOMC", "联邦基金", "鲍威尔"],
    # 注意：不要放笼统的「回购」——公司股份回购（腾讯/名创优品回购）会被误归为美债
    "美债": ["美债", "美国财政部", "逆回购", "长期国债", "国债拍卖", "美债收益率"],
    "全球债市": ["国债收益率", "债券收益率", "收益率曲线", "债市", "国债", "基点"],
    "中东": ["伊朗", "以色列", "胡塞", "也门", "伊拉克", "加沙", "中东", "沙特"],
    "俄乌": ["俄罗斯", "乌克兰", "普京", "基辅", "北约", "加里宁格勒"],
    "关税贸易": ["关税", "贸易", "制裁", "出口管制", "反倾销"],
    "AI芯片": ["芯片", "半导体", "英伟达", "算力", "GPU", "光刻", "存储"],
    "大模型": ["大模型", "AI", "人工智能", "OpenAI", "DeepSeek", "智能体"],
    "房地产": ["楼市", "房地产", "房价", "购房", "房贷", "地产"],
    "新能源车": ["新能源车", "电动车", "汽车", "交付", "销量"],
    "医药": ["医药", "创新药", "集采", "临床试验", "疫苗"],
    "股指行情": ["沪指", "恒生指数", "纳指", "道指", "标普", "KOSPI", "日经", "三大指数"],
}

_STOP = set("的了在是与和及对将为以于其该这那有等被把从到会能够就也都还很更最"
            "称表示显示据消息报道今日今天昨日月日年公司方面人士")


def _norm(s):
    """归一化：去标点空格、去数字、去停用词"""
    s = re.sub(r"[^\u4e00-\u9fa5A-Za-z]", "", s or "")
    return s


def _ngrams(s, n=3):
    s = _norm(s)
    if len(s) <= n:
        return {s} if s else set()
    return set(s[i:i + n] for i in range(len(s) - n + 1))


def similarity(a, b):
    """标题相似度：3-gram Jaccard，混合短串包含关系"""
    A, B = _ngrams(a), _ngrams(b)
    if not A or not B:
        return 0.0
    j = len(A & B) / len(A | B)
    # 短标题被长标题包含时，Jaccard 会被稀释，补一个包含度
    na, nb = _norm(a), _norm(b)
    contain = 0.0
    if na and nb and (na in nb or nb in na):
        contain = min(len(na), len(nb)) / max(len(na), len(nb))
    return max(j, contain)


# 英文大写词黑名单：这些是通用缩写，不构成「同一主体」证据
EN_STOP = {"The", "And", "For", "With", "US", "UK", "EU", "CPI", "PPI", "GDP",
           "PMI", "IPO", "ETF", "CEO", "CFO", "M2", "WTI", "OPEC", "FOMC"}


def entities(text):
    """提取文本中的主体实体（三层策略）"""
    text = text or ""
    out = set(ENT_RE_LIST.findall(text))
    out |= set(ENT_RE_GENERIC.findall(text))
    for w in ENT_RE_EN.findall(text):
        if len(w) >= 3 and w not in EN_STOP and w.isupper() is False:
            out.add(w)
    return out


def topic_of(text):
    """返回命中的主题标签集合"""
    return {t for t, kws in TOPIC_KW.items() if any(k in (text or "") for k in kws)}


def is_roundup(title):
    return any(k in (title or "") for k in ROUNDUP_KW)


def _parse_time(t):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime((t or "").strip(), fmt)
            if fmt.startswith("%m"):
                dt = dt.replace(year=datetime.now(CST).year)
            return dt.replace(tzinfo=CST)
        except Exception:
            continue
    return None


# ============================================================
#  判定关系
# ============================================================
def judge(a, b):
    """
    判定两条快讯的关系，返回 (relation, sim, reason)
    """
    ta, tb = a.get("title", ""), b.get("title", "")
    if is_roundup(ta) or is_roundup(tb):
        return "ROUNDUP", 0.0, "含汇总类特征词"

    sim = similarity(ta, tb)
    ea, eb = entities(ta + " " + (a.get("body") or "")[:60]), entities(tb + " " + (b.get("body") or "")[:60])
    shared_ent = ea & eb
    shared_topic = topic_of(ta) & topic_of(tb)

    # 同一次发生：高度相似，或同主题 + 共享实体 + 中等相似
    if sim >= SAME_OCCURRENCE_T:
        return "SAME_OCCURRENCE", sim, f"标题相似度 {sim:.2f} ≥ {SAME_OCCURRENCE_T}"
    if sim >= 0.34 and shared_ent and shared_topic:
        return "SAME_OCCURRENCE", sim, (
            f"共享实体 {'/'.join(list(shared_ent)[:2])} + 同主题 "
            f"{'/'.join(list(shared_topic)[:2])}，相似度 {sim:.2f}")
    # 两个以上相同的具体实体 + 同主题 —— 即使措辞差异大也基本可判定为同一件事
    # （例：「知情人士：博通着手筹集600亿美元，为Anthropic采购芯片提供资金」
    #   与「博通据悉筹措600亿美元 为Anthropic芯片项目提供资金」，相似度仅 0.2 出头）
    if len(shared_ent) >= 2 and shared_topic and sim >= 0.18:
        return "SAME_OCCURRENCE", sim, (
            f"共享 {len(shared_ent)} 个实体（{'/'.join(list(shared_ent)[:3])}）"
            f"且同主题，判定为同一事件（相似度 {sim:.2f}）")

    # 同一故事的后续进展：同主题 + 共享实体，但表达差异较大
    if shared_ent and shared_topic and sim >= SAME_STORY_T:
        return "SAME_STORY", sim, (
            f"同一主体（{'/'.join(list(shared_ent)[:2])}）的后续进展，相似度 {sim:.2f}")
    if len(shared_topic) >= 2 and sim >= 0.22:
        return "SAME_STORY", sim, f"同属主题 {'/'.join(list(shared_topic)[:2])}，相似度 {sim:.2f}"

    return "UNRELATED", sim, ""


# ============================================================
#  事件 ID（跨天稳定，供时间线使用）
# ============================================================
def make_eid(items):
    """
    生成跨天稳定的标识，返回 (eid, ekey, kind)。

    kind 区分两种线，供时间线分别展示：
      topic_line —— 有明确主体（美联储 / 博通 / 中东…），ekey = 实体+主题，
                    用于追踪「同一主体的一连串动静」
      event_line —— 无主体，ekey = 标题指纹，只追踪「本事件本身」

    早期实现里无实体的事件一律用「#主题」做 key，导致
    「AI 硬件端走弱」「日本投 1400 亿建数据中心」「港股 AI 股暴跌 48%」
    这三件毫无关系的事被串成同一条时间线 —— 它们只是都带「AI」字样。
    """
    best = items[0]
    ents = sorted(entities(best.get("title", "") + best.get("body", "")[:40]))
    tops = sorted(topic_of(best.get("title", "")))
    if ents:
        key = "|".join(ents[:2]) + ("#" + tops[0] if tops else "")
        kind = "topic_line"
    else:
        key = _norm(best.get("title", ""))[:16]
        kind = "event_line"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:10], key, kind


# ============================================================
#  热度（按事件算，不按文章算）
# ============================================================
def heat_of(items, now=None):
    """
    48 小时内每个独立来源只算一次，24 小时内算 1.0，超过算 0.5。
    返回 (热度值, 独立来源数, 独立来源列表)
    """
    now = now or datetime.now(CST)
    by_src = {}
    for it in items:
        t = _parse_time(it.get("time"))
        if not t:
            w = 0.6        # 时间缺失给一个保守权重
        else:
            age_h = (now - t).total_seconds() / 3600.0
            if age_h > 48:
                continue
            w = 1.0 if age_h <= 24 else 0.5
        s = it.get("src", "未知")
        by_src[s] = max(by_src.get(s, 0.0), w)
    return round(sum(by_src.values()), 2), len(by_src), sorted(by_src.keys())


def freshness_of(items, now=None):
    """
    返回 (fresh6h, rising_internal)
    fresh6h ：组内最近 6 小时有条目 → 该事件今天有更新
    rising_internal：最近 6 小时的条目数 > 之前 42 小时平均速率 × 1.5

    注意：这两个都不是「新事件」的判定 —— 同一天抓取的数据里所有条目都是「今天」的，
    用它判 isNew 会让每条都标新，毫无区分度（早期实现就踩了这个坑）。
    真正的 isNew / isRising 必须与上一次运行的事件快照对比，见 mark_changes()。
    """
    now = now or datetime.now(CST)
    recent, older = 0, 0
    for it in items:
        t = _parse_time(it.get("time"))
        if not t:
            continue
        age_h = (now - t).total_seconds() / 3600.0
        if age_h <= 6:
            recent += 1
        elif age_h <= 48:
            older += 1
    fresh6h = recent > 0
    baseline = (older / 7.0) if older else 0
    rising_internal = recent > 0 and recent > max(baseline * 1.5, 0.99)
    return fresh6h, rising_internal


# ============================================================
#  主题分组（解决「7 条美联储快讯散落各处」）
#  这些不是同一次发生，不能合并（各是独立信息），
#  但按主题聚在一起展示，用户一眼能看出「今天美联储有一堆动静」。
# ============================================================
TOPIC_PRIORITY = ["美联储利率", "美债", "全球债市", "关税贸易", "中东", "俄乌",
                  "AI芯片", "大模型", "房地产", "新能源车", "医药", "股指行情"]
TOPIC_LABEL = {
    "美联储利率": "美联储动向", "美债": "美债与财政", "全球债市": "全球债市",
    "关税贸易": "关税与制裁",
    "中东": "中东局势", "俄乌": "俄乌局势", "AI芯片": "AI 芯片与算力",
    "大模型": "大模型与 AI 应用", "房地产": "地产与楼市", "新能源车": "新能源车",
    "医药": "医药与生物", "股指行情": "全球股指行情",
}


def primary_topic(title, body=""):
    """
    主题判定只看标题。
    早期实现会在标题无主题词时回退看正文，结果「海南离岛免税购物金额超1亿元」
    因为正文提到 AI 被归进「大模型」块。宁可少归组，也不把不相干内容塞进话题块。
    """
    tops = topic_of(title or "")
    for t in TOPIC_PRIORITY:
        if t in tops:
            return t
    return None


def group_topics(events, min_size=3):
    """
    把同主题的多个独立事件归到一个话题块。返回话题列表（按总热度降序）。
    min_size：至少这么多条才成块，否则散着显示。
    """
    buckets = {}
    for e in events:
        t = primary_topic(e.get("title", ""), e.get("body", ""))
        if t:
            buckets.setdefault(t, []).append(e)
    out = []
    for t, es in buckets.items():
        if len(es) < min_size:
            continue
        es.sort(key=lambda x: -x["rank_score"])
        out.append({
            "topic": t,
            "label": TOPIC_LABEL.get(t, t),
            "count": len(es),
            "sources": sorted({s for e in es for s in e["sources"]}),
            "heat": round(sum(e["heat"] for e in es), 2),
            "eids": [e["eid"] for e in es],
            "lead": es[0]["title"],
            "events": es,
        })
    out.sort(key=lambda x: -x["heat"])
    return out


# ============================================================
#  跨快照对比（真正的 isNew / isRising）
# ============================================================
SNAP_DIR = os.path.join(DATA_DIR, "event_snapshots")


def save_snapshot(events, now=None):
    """把本次事件快照落盘，供下次运行对比 + 事件时间线使用"""
    now = now or datetime.now(CST)
    os.makedirs(SNAP_DIR, exist_ok=True)
    p = os.path.join(SNAP_DIR, now.strftime("%Y-%m-%d-%H") + ".json")
    payload = {
        "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
        "events": [{
            "eid": e["eid"], "ekey": e.get("ekey"), "kind": e.get("kind"),
            "title": e["title"],
            "heat": e["heat"], "source_count": e["source_count"],
            "rank_score": e["rank_score"],
            "topic": primary_topic(e["title"], e.get("body", "")),
            "time": e.get("time", ""),
        } for e in events],
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return p


def load_prev_snapshot(now=None, min_gap_h=2.0):
    """找最近一次、且至少 min_gap_h 小时前的快照作为对比基准"""
    now = now or datetime.now(CST)
    if not os.path.isdir(SNAP_DIR):
        return None
    cands = []
    for fn in os.listdir(SNAP_DIR):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{2})\.json$", fn)
        if not m:
            continue
        try:
            t = datetime.strptime(m.group(1) + " " + m.group(2),
                                  "%Y-%m-%d %H").replace(tzinfo=CST)
        except Exception:
            continue
        if (now - t).total_seconds() / 3600.0 >= min_gap_h:
            cands.append((t, os.path.join(SNAP_DIR, fn)))
    if not cands:
        return None
    cands.sort(reverse=True)
    try:
        with open(cands[0][1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def mark_changes(events, prev):
    """与上一次快照对比，标注 isNew（新出现）与 isRising（热度显著上升）"""
    pm = {x["eid"]: x for x in (prev or {}).get("events", [])}
    for e in events:
        e["heat_delta"] = 0.0
        if not prev:
            # 首次运行无对比基准 —— 不制造虚假标记
            e["isNew"] = False
            e["isRising"] = False
            continue
        p = pm.get(e["eid"])
        if p is None:
            e["isNew"] = True
            e["isRising"] = False
        else:
            e["isNew"] = False
            old = p.get("heat", 0) or 0
            e["heat_delta"] = round(e["heat"] - old, 2)
            e["isRising"] = e["heat"] > max(old * 1.3, old + 0.5)
    return events


# ============================================================
#  聚簇主流程
# ============================================================
def cluster(items, now=None):
    """
    输入已评分的快讯列表（按 final_score 降序），返回 (events, stat)
    events 按热度降序排列。
    """
    now = now or datetime.now(CST)
    items = list(items)
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    relations = {}       # (i,j) -> (relation, sim, reason)
    story_links = []     # SAME_STORY 关系，用于归组不合并

    for i in range(n):
        if is_roundup(items[i].get("title", "")):
            continue
        for j in range(i + 1, n):
            if is_roundup(items[j].get("title", "")):
                continue
            rel, sim, reason = judge(items[i], items[j])
            if rel == "SAME_OCCURRENCE":
                relations[(i, j)] = (rel, sim, reason)
                union(i, j)
            elif rel == "SAME_STORY":
                story_links.append((i, j, sim, reason))

    # 归并成组
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    events = []
    for root, idxs in groups.items():
        members = [items[i] for i in idxs]
        members.sort(key=lambda x: -x.get("final_score", 0))
        merged = len(members) > 1
        eid, ekey, ekind = make_eid(members)
        heat, src_n, srcs = heat_of(members, now)
        fresh6h, rising_internal = freshness_of(members, now)
        head = members[0]

        # 组内合并的判定依据（供复核）
        reasons = []
        for i in idxs:
            for j in idxs:
                if i < j and (i, j) in relations:
                    reasons.append(relations[(i, j)][2])
        # 同一 story 的其他条目（不合并，但提示有关联）
        related = []
        for i, j, sim, reason in story_links:
            if i in idxs and j not in idxs:
                related.append({"title": items[j].get("title", ""), "sim": round(sim, 2),
                                "reason": reason})
            elif j in idxs and i not in idxs:
                related.append({"title": items[i].get("title", ""), "sim": round(sim, 2),
                                "reason": reason})

        events.append({
            "eid": eid,
            "ekey": ekey,
            "kind": ekind,          # topic_line（主体线）/ event_line（单事件线）
            "title": head.get("title", ""),
            "body": head.get("body", ""),
            "dim": head.get("dim"),
            "dimName": head.get("dimName"),
            "impact": head.get("impact"),
            "sectors": head.get("sectors") or [],
            "ctypeName": head.get("ctypeName"),
            "tier": head.get("tier"),
            "score": head.get("final_score"),
            "heat": heat,
            "source_count": src_n,
            "sources": srcs,
            "isNew": False,          # 由 mark_changes() 与上一快照对比后填入
            "isRising": False,
            "heat_delta": 0.0,
            "fresh6h": fresh6h,
            "risingHeat": rising_internal,
            "topic": primary_topic(head.get("title", ""), head.get("body", "")),
            "topicLabel": TOPIC_LABEL.get(
                primary_topic(head.get("title", ""), head.get("body", "")) or "", ""),
            "merged": merged,
            "member_count": len(members),
            "members": [{
                "title": m.get("title", ""),
                "src": m.get("src", ""),
                "time": m.get("time", ""),
                "body": m.get("body", ""),
                "score": m.get("final_score"),
            } for m in members],
            "merge_reasons": reasons[:4],
            "related": related[:3],
            "time": head.get("time", ""),
        })

    # 排序：热度优先，其次分数；被合并（多来源）的加权，体现「很多人在说」
    for e in events:
        # 排序：热度（多家媒体在说）优先，单篇质量次之，上升/新出现加权
        e["rank_score"] = round(e["heat"] * 15 + (e["score"] or 0) * 0.4
                                + (8 if e["isRising"] else 0)
                                + (5 if e["isNew"] else 0)
                                + (6 if e["source_count"] > 1 else 0), 1)
    events.sort(key=lambda x: -x["rank_score"])

    stat = {
        "input_articles": n,
        "events": len(events),
        "merged_away": n - len(events),
        "redundancy": round(n / len(events), 2) if events else 0,
        "multi_source_events": sum(1 for e in events if e["source_count"] > 1),
        "roundup_articles": sum(1 for it in items if is_roundup(it.get("title", ""))),
        "story_links": len(story_links),
        "method": "rule_based",       # 非 LLM 语义判定，如实标注
    }
    return events, stat


def build(auto_news_path=None, save=True, log=True):
    """
    完整聚簇流程：读取 auto_news.json → 聚簇 → 对比上一快照 → 主题分组 → 落盘。
    返回 (payload, stat)
    """
    p = auto_news_path or os.path.join(DATA_DIR, "auto_news.json")
    if not os.path.exists(p):
        return None, {"error": "auto_news.json 不存在"}
    with open(p, encoding="utf-8") as f:
        d = json.load(f)

    events, stat = cluster(d["news"])
    prev = load_prev_snapshot()
    mark_changes(events, prev)
    topics = group_topics(events)

    stat["topic_blocks"] = len(topics)
    stat["compared_with"] = (prev or {}).get("ts")
    stat["new_events"] = sum(1 for e in events if e["isNew"])
    stat["rising_events"] = sum(1 for e in events if e["isRising"])

    payload = {
        "date": d.get("date"),
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "events": events,
        "topics": topics,
        "stat": stat,
        "provenance": {
            "method": "rule_based_clustering",
            "status": "derived",
            "detail": ("事件合并与主题归组由标题相似度 + 实体重叠规则判定，"
                       "非 LLM 语义判断；热度按独立来源数计算（48h 内每源一次，24h 减半）"),
        },
    }
    if save:
        with open(os.path.join(DATA_DIR, "events.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        save_snapshot(events)
        # 按日期归档，供看板切换历史日期时使用
        if payload.get("date"):
            hist_dir = os.path.join(DATA_DIR, "event_history")
            os.makedirs(hist_dir, exist_ok=True)
            with open(os.path.join(hist_dir, f"{payload['date']}.json"),
                      "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    if log:
        print(f"  输入 {stat['input_articles']} 条 → {stat['events']} 个事件"
              f"（合并 {stat['merged_away']} 条，冗余系数 {stat['redundancy']}×）")
        print(f"  主题块 {stat['topic_blocks']} 个 | 新事件 {stat['new_events']} | "
              f"上升 {stat['rising_events']} | 对比基准 {stat['compared_with'] or '无'}")
    return payload, stat


def main():
    import sys
    payload, stat = build(save=True, log=True)
    if payload is None:
        print("请先运行 news_fetcher.py")
        return 1
    print()
    print("话题块（同主题多条独立事件）:")
    for t in payload["topics"]:
        print(f"  【{t['label']}】{t['count']} 条 · 来源 {len(t['sources'])} 家 · "
              f"总热度 {t['heat']}")
        for e in t["events"][:3]:
            print(f"       · {e['title'][:46]}")
    print()
    print("事件热度 Top 12：")
    for e in payload["events"][:12]:
        flag = "🆕" if e["isNew"] else ("🔥" if e["isRising"] else "  ")
        multi = f" ×{e['source_count']}源" if e["source_count"] > 1 else ""
        print(f"  {flag} 热度{e['heat']:4.1f}{multi}  {e['title'][:44]}")
        for m in e["members"][1:3]:
            print(f"           └ {m['src']}: {m['title'][:40]}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
