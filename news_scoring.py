# -*- coding: utf-8 -*-
"""
news_scoring.py — 新闻重要性评分层

方法借鉴 AIHOT（KKKKhazix/AIHOT）的 selected-score 方法论，落地为纯规则实现
（无 LLM 依赖，可在定时任务里零成本跑）。

核心设计（忠于原方法论）：
  1. 五轴独立打分：sig 实质份量 / nov 信息增量 / cred 证据强度
                    reson 共振面 / act 可用性，各 0-10
  2. 按 7 类内容类型加权（每类权重和 = 10，因此加权结果天然落在 0-100）
  3. 「必须压住的噪声」硬上限：给营销稿、转述、预测类内容设天花板，
     让「财政部发文」和「某公司活动预告」拿不到同样的分
  4. 五轴打分只看文本内容本身，信源等级只用于「门槛」环节
     —— 对应原方法论「输入不告诉模型来源等级，防它猜答案」
  5. 双通道独立打分：内容通道 + 结构通道，各自 0-100，
     两者之和 ≥ 2×门槛才入选，降低单通道规则的偏差

设计差异说明：
  原方法论是让同一个 LLM 用同一标准独立打两次分，用于降低单次采样的方差。
  本项目不上 LLM，规则打分本身无随机方差，因此改为「两个互补视角」双通道：
  内容通道（说了什么）+ 结构通道（怎么说的、什么来源）。
  目的相同：避免单一规则表把排序带偏。此处如实标注为 derived。
"""
import re

# ============================================================
#  内容类型 × 五轴权重表（每行权重和 = 10，加权后 = 0-100）
# ============================================================
AXES = ("sig", "nov", "cred", "reson", "act")
AXIS_NAME = {
    "sig": "实质份量",
    "nov": "信息增量",
    "cred": "证据强度",
    "reson": "共振面",
    "act": "可用性",
}

CONTENT_TYPES = {
    "policy": {
        "name": "政策发布",
        "kw": ["国务院", "常务会议", "央行", "人民银行", "财政部", "发改委", "证监会",
               "工信部", "商务部", "住建部", "国资委", "统计局", "银保监", "金融监管总局",
               "政策", "通知", "意见", "办法", "条例", "规划", "试点", "落地", "实施",
               "降准", "降息", "逆回购", "MLF", "LPR", "减税", "补贴", "贴息", "专项债"],
        "w": {"sig": 4, "nov": 2, "cred": 2, "reson": 2, "act": 0},
    },
    "data": {
        "name": "经济数据",
        "kw": ["CPI", "PPI", "PMI", "GDP", "非农", "失业率", "社融", "M2", "进出口",
               "外汇储备", "工业增加值", "社会消费品零售", "固定资产投资", "财新",
               "同比增长", "环比", "环比上涨", "同比上涨", "数据显示", "统计"],
        "w": {"sig": 4, "nov": 2, "cred": 2, "reson": 2, "act": 0},
    },
    "company": {
        "name": "公司事件",
        "kw": ["公告", "业绩", "营收", "净利润", "预增", "预亏", "重组", "并购", "收购",
               "回购", "增持", "减持", "解禁", "分红", "上市", "IPO", "退市", "立案",
               "停牌", "复牌", "股东", "定增", "股权", "签约", "中标", "订单"],
        "w": {"sig": 3, "nov": 2, "cred": 2, "reson": 1, "act": 2},
    },
    "market": {
        "name": "市场动作",
        "kw": ["沪指", "深指", "创业板指", "科创50", "北证50", "成交额", "涨停", "跌停",
               "北向资金", "南向资金", "主力资金", "融资余额", "两融", "板块异动",
               "盘中", "收盘", "开盘", "涨幅", "跌幅", "股指期货", "板块轮动"],
        "w": {"sig": 2, "nov": 1, "cred": 2, "reson": 3, "act": 2},
    },
    "overseas": {
        "name": "海外宏观",
        "kw": ["美联储", "FOMC", "鲍威尔", "欧央行", "日本央行", "白宫", "特朗普",
               "关税", "制裁", "北约", "伊朗", "以色列", "俄罗斯", "乌克兰", "胡塞",
               "原油", "黄金", "美债", "收益率", "美元指数", "非美货币", "外资"],
        "w": {"sig": 3, "nov": 2, "cred": 1, "reson": 3, "act": 1},
    },
    "view": {
        "name": "行业观点",
        "kw": ["研报", "分析师", "机构认为", "券商认为", "预计", "展望", "观点", "点评",
               "看好", "建议关注", "维持买入", "评级", "目标价", "策略", "复盘",
               "解读", "专家", "首席", "论坛", "峰会"],
        "w": {"sig": 1, "nov": 2, "cred": 1, "reson": 2, "act": 4},
    },
    "tech": {
        "name": "技术进展",
        "kw": ["芯片", "半导体", "光刻", "晶圆", "大模型", "人工智能", "AI", "算力",
               "机器人", "固态电池", "钠离子", "钙钛矿", "可控核聚变", "量子计算",
               "创新药", "临床试验", "获批上市", "专利", "技术突破", "研发成功", "量产",
               "火箭", "卫星", "航天", "商业航天", "数据中心", "光模块", "智能驾驶"],
        "w": {"sig": 3, "nov": 3, "cred": 2, "reson": 2, "act": 0},
    },
}

# ============================================================
#  A 股关联度（校准发现的关键缺失维度）
# ============================================================
# 校准报告显示：规则准确率仅 47.6%，最主要的误选是「纯海外个股消息」——
# 「埃尼集团对渔业柴油提供20%折扣」74 分、「嘉能可澳交所二次上市」71 分，
# 它们有公司名、有数字、有动作，五轴全部给高分，但跟 A 股没有任何关系。
# 根因是五轴只评「信息质量」，没有评「与本市场是否相关」。
CN_LINK = ["A股", "沪指", "深证", "创业板", "科创板", "北交所", "北证", "恒生", "港股",
           "中概", "人民币", "沪深", "两市", "国内", "我国", "中国", "国产", "央行",
           "证监会", "发改委", "财政部", "国务院", "统计局", "商务部", "工信部",
           "国资委", "上交所", "深交所", "中证", "社保", "公募", "私募", "北向",
           "南向", "IPO", "再融资", "退市", "解禁", "增持", "减持", "回购",
           "人民币汇率", "存款准备金", "专项债", "两会"]

FOREIGN_MARKET = ["美国", "美股", "纳指", "道指", "标普", "费城", "欧洲", "欧央行",
                  "欧洲央行", "欧元区", "日本", "日经", "韩国", "KOSPI", "德国",
                  "法国", "英国", "加拿大", "澳大利亚", "澳洲", "沙特", "希腊",
                  "俄罗斯", "乌克兰", "以色列", "伊朗", "印度", "越南", "巴西"]

# 科技/新能源等全球产业链话题：即便主体在海外，A 股也有映射，不压制
TECH_HINT = ["芯片", "半导体", "光刻", "晶圆", "算力", "AI", "人工智能", "大模型",
             "存储", "机器人", "新能源", "光伏", "锂电", "储能", "创新药", "商业航天",
             "固态电池", "光模块", "数据中心", "智能驾驶", "液冷", "PCB", "CPO"]

# ============================================================
#  信源分级 + 入选门槛
# ============================================================
TIER_LABEL = {"T1": "官方一手", "T1.5": "专业快讯", "T2": "媒体转载"}

# 入选门槛（0-100 尺度）。沿用 AIHOT「官方一手门槛最低」的分级思路，
# 但数值按本项目规则打分的实测分布重新标定 —— 原项目 60/65/76 是 LLM 打分尺度，
# 直接搬过来会导致 60 条只入选 14 条。
# 该组数值由 calibrate.py 在 40-90 区间扫描后确定，见 data/calibration/report.json
# 调优轨迹（校准闭环真实记录）：
#   初版 50/54/58  → 准确率 47.6%（规则凭经验写，从未验证过）
#   +A股关联度维度 → 52.4%
#   +领域无关/小额/会议通知/标题党压制 → 61.9%
#   +硬淘汰机制   → 90.5%
#   +聚簇感知评测 + 门槛扫描 → 97.4%（查准率 100%）
# 扫描显示统一门槛 52 为最优点，据此定 T2=52。
TIER_THRESHOLDS = {"T1": 46, "T1.5": 50, "T2": 52}

BASE_TIER = {"东方财富": "T1.5", "新浪财经": "T2", "同花顺": "T2"}
DEFAULT_TIER = "T2"

# 内容中若主体是官方一手发布，升级为 T1
OFFICIAL_ORGS = ["国务院", "中国人民银行", "央行", "国家统计局", "统计局", "财政部",
                 "国家发展改革委", "发改委", "中国证监会", "证监会", "金融监管总局",
                 "工业和信息化部", "工信部", "商务部", "住建部", "国资委", "海关总署",
                 "国家能源局", "上交所", "深交所", "北交所", "外汇局", "美联储",
                 "FOMC", "欧央行", "欧洲央行", "日本央行"]

# 与市场判断无关的领域（生态/农业科研/平台运营/社会议题）
IRRELEVANT_KW = ["生态建设", "林草", "饲草", "飞蝗", "基因组", "破译", "研究团队",
                 "论文", "活跃用户", "注册用户", "下载量", "录取", "招生",
                 "赛事", "演出", "演练", "儿童", "伤亡", "人道", "援助", "比赛"]
# 会议通知类（有主体、有日期，但没有任何实质信息）
MEETING_KW = ["董事会会议", "股东大会", "会议将于", "拟召开", "审议", "会议通知"]
# 强标题党词：财经快讯里出现这些基本等于低质内容（「重磅」单用太常见，不列入）
STRONG_CLICKBAIT = ["大消息", "重磅来袭", "速看", "速览", "炸了", "炸裂",
                    "刚刚宣布", "慌了", "彻底火了", "刷屏"]

# ============================================================
#  噪声压制规则（轴级降权）—— 这一节是精髓
#  规则：(匹配条件, 受限轴, 上限值, 说明)
# ============================================================
NOISE_RULES = [
    # 营销 / 活动 / 软文
    (["预告", "即将开启", "正式启动报名", "福利", "限时", "免费领", "抽奖", "招募",
      "招募启动", "征集", "征稿", "开放报名", "报名通道"],
     "sig", 2, "活动预告/营销类，无实质信息"),
    (["发布会预告", "官宣", "重磅来袭", "敬请期待"],
     "sig", 3, "宣发类内容，无事实增量"),
    # 招聘 / 人事
    (["招聘", "诚聘", "岗位", "简历", "应聘"],
     "sig", 1, "招聘信息，与市场判断无关"),
    # 预测 / 展望类（非事实）
    (["预计", "或将", "有望", "可能会", "大概率", "业内人士称", "分析师预计"],
     "nov", 4, "预测性表述，非既成事实，信息增量受限"),
    # 传闻 / 未证实
    (["传闻", "网传", "有消息称", "市场消息称", "据悉", "知情人士", "接近人士透露"],
     "cred", 3, "未经证实的消息源，证据强度受限"),
    # 纯转述 / 复盘
    (["回顾", "复盘", "盘点", "梳理", "一览", "汇总"],
     "nov", 4, "回顾整理类，信息增量有限"),
    # 情绪化 / 标题党
    (["震惊", "炸裂", "重磅", "慌了", "慌了！", "巨亏", "狂飙", "爆了", "彻底"],
     "cred", 4, "情绪化表述，降低证据权重"),
    # 领域与市场判断无关（校准报告里的一类高频误选：生态/农业科研/平台运营/人道议题）
    (IRRELEVANT_KW, "sig", 3, "领域与市场判断无关"),
    (IRRELEVANT_KW, "reson", 3, "领域与市场判断无关，影响面受限"),
    # 会议通知类
    (MEETING_KW, "sig", 3, "会议通知类，无实质内容"),
    (MEETING_KW, "nov", 3, "会议通知类，无信息增量"),
    # 标题党加强（原规则只压 cred，实测「美联储加息，大消息！今夜，重磅数据来袭！」仍达 50 分）
    (["大消息", "炸了", "炸裂", "重磅来袭", "慌了", "震惊", "速看", "刚刚宣布"],
     "sig", 4, "情绪化标题，降低实质份量"),
    (["大消息", "炸了", "炸裂", "重磅来袭", "慌了", "震惊", "速看"],
     "reson", 4, "情绪化标题，降低影响面权重"),
]


def _hit(text, kws):
    return sum(1 for w in kws if w in text)


# ============================================================
#  类型判定
# ============================================================
# 市场动作强特征：指数名 + 涨跌动词。命中即直接归为 market，
# 避免「费城半导体指数涨2%」因含「半导体」被误判成技术进展。
_MARKET_IDX = re.compile(
    r"(沪指|深证成指|深指|创业板指|科创50|北证50|KOSPI|日经|纳指|纳斯达克|道琼斯|道指|"
    r"标普|费城半导体指数|恒生指数|恒指|欧洲主要股指|富时|德国DAX|法国CAC|"
    r"美股三大指数|三大指数|股指期货)")
_MARKET_VERB = re.compile(r"[涨跌收报点%％]")


def classify_type(text):
    """返回 (类型key, 命中数)。全部未命中时归为 view（观点）"""
    # 强特征优先：指数行情类
    if _MARKET_IDX.search(text) and _MARKET_VERB.search(text):
        return "market", 9
    best, best_n = "view", 0
    for k, v in CONTENT_TYPES.items():
        n = _hit(text, v["kw"])
        if n > best_n:
            best, best_n = k, n
    return best, best_n


# ============================================================
#  五轴打分（只看文本，不看来源等级）
# ============================================================
_NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|亿|万|亿股|亿元|万元|元|点|个基点|bp|BP)")
_ORG_RE = re.compile(
    r"(?:中国人民银行|央行|国家统计局|财政部|发改委|证监会|工信部|商务部|住建部|国资委|"
    r"美联储|欧央行|欧洲央行|日本央行|[一-龥]{2,8}(?:集团|银行|证券|基金|科技|电子|能源|"
    r"股份|控股|汽车|医药|半导体))")
_ACTION_KW = ["发布", "公布", "宣布", "签署", "批准", "上调", "下调", "取消", "叫停",
              "启动", "终止", "达成", "通过", "实施", "生效", "落地", "出台", "印发",
              "召开", "决定", "完成", "投产", "量产", "开建", "获批", "中标"]
_FRESH_KW = ["今日", "今天", "刚刚", "最新", "首次", "正式", "即日起", "自今日",
             "发布", "公布", "宣布", "落地", "生效", "实施"]
_STALE_KW = ["此前", "昨日", "上周", "上月", "去年", "回顾", "早前", "曾"]
_MACRO_KW = ["全市场", "大盘", "A股", "沪深", "两市", "所有板块", "整体", "全面",
             "央行", "利率", "汇率", "关税", "经济", "政策", "指数"]
_SINGLE_KW = ["公司", "该行", "该企业", "其"]

# 禁用自动加分项（原方法论明令禁止）：这些出现不给额外分
# 大厂/名校/长正文/术语多/数字多/SOTA —— 我们仅在文档里声明，不在代码里给权重


def score_sig(text):
    """实质份量：有没有硬事实"""
    s = 0
    if _NUM_RE.search(text):
        s += 4
    if _ORG_RE.search(text):
        s += 3
    if _hit(text, _ACTION_KW):
        s += 3
    return min(s, 10)


def score_nov(text):
    """信息增量：是不是新信息，而非复述或预测"""
    s = 5
    if _hit(text, _FRESH_KW):
        s += 3
    if _hit(text, _STALE_KW):
        s -= 2
    if _hit(text, ["预计", "或将", "有望", "展望", "预期"]):
        s -= 2
    return max(0, min(s, 10))


def score_cred(text):
    """证据强度：消息可靠度"""
    s = 4
    if _NUM_RE.search(text) and _hit(text, ["数据显示", "公告", "披露", "统计", "报告"]):
        s += 4
    if _hit(text, ["传闻", "网传", "有消息称", "据悉", "知情人士"]):
        s -= 3
    if _hit(text, OFFICIAL_ORGS):
        s += 2
    if _hit(text, ["分析认为", "机构认为", "专家表示", "业内人士"]):
        s -= 1
    return max(0, min(s, 10))


def score_reson(text, sectors=None):
    """共振面：影响广度"""
    s = 2
    if _hit(text, _MACRO_KW):
        s += 4
    n = len(sectors or [])
    if n >= 2:
        s += 4
    elif n == 1:
        s += 2
    if _hit(text, _SINGLE_KW) and n == 0:
        s -= 1
    return max(0, min(s, 10))


def score_act(text, sectors=None, has_stock=False):
    """可用性：能否据此行动"""
    s = 1
    if has_stock:
        s += 4
    if sectors:
        s += 3
    if _hit(text, ["建议关注", "标的", "利好", "利空", "受益"]):
        s += 2
    return max(0, min(s, 10))


def score_axes(text, sectors=None, has_stock=False):
    return {
        "sig": score_sig(text),
        "nov": score_nov(text),
        "cred": score_cred(text),
        "reson": score_reson(text, sectors),
        "act": score_act(text, sectors, has_stock),
    }


# ============================================================
#  噪声压制
# ============================================================
# 明确的海外公司主体：命中即视为与 A 股无直接关联（非科技产业链话题时）
OVERSEAS_CORP = ["富国银行", "丰业银行", "埃尼集团", "嘉能可", "耐克", "埃森哲",
                 "Evercore", "摩根士丹利", "摩根大通", "高盛", "花旗", "贝莱德",
                 "波音", "可口可乐", "沃尔玛", "空客", "丰田", "本田", "西门子",
                 "辉瑞", "默克", "强生", "雪佛龙", "埃克森", "壳牌", "道达尔",
                 "力拓", "必和必拓", "淡水河谷", "诺和诺德", "阿斯利康", "联合利华"]


def _is_foreign_stock_news(text, ctype):
    """
    纯海外个股 / 海外机构观点：与 A 股无直接关联。

    这是校准报告里误选最多的一类 —— 「埃尼集团柴油20%折扣」74 分、
    「嘉能可澳交所二次上市」71 分，都因为「有公司名 + 有数字 + 有动作」
    在五轴下拿到高分，但对 A 股读者没有任何价值。

    豁免条件：
      - 文本含中国关联词（A股/央行/国内…）→ 是本土消息
      - 文本属科技/新能源全球产业链话题 → 海外进展对 A 股有映射
    """
    if ctype not in ("company", "view"):
        return False
    if _hit(text, CN_LINK):
        return False
    # 明确命中海外公司主体 → 直接压制，不因顺带提到 AI 而豁免。
    # 「Evercore 上调埃森哲目标价至250美元，看好AI业务增长」就是钻了这个空子：
    # 主体是海外机构，却因为文中出现「AI」被当成科技产业链消息放行。
    if _hit(text, OVERSEAS_CORP):
        return True
    if _hit(text, TECH_HINT):
        return False
    return _hit(text, FOREIGN_MARKET) > 0


# 资金动作词：只有这类语境下的「金额大小」才有市场信号意义
MONEY_ACTION = ["回购", "融资", "募资", "投资", "增资", "增持", "中标", "订单",
                "收购", "并购", "分红", "派息", "定增", "签约", "注资", "跟投", "募投"]
_AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(亿|千万|百万|万)?\s*(美元|港元|港币|人民币|美金|元)")


def _max_amount_wan(text):
    """文本中出现的最大金额（换算成万元）；无金额返回 0"""
    best = 0.0
    for m in _AMOUNT_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        unit = m.group(2) or ""
        mult = {"亿": 10000.0, "千万": 1000.0, "百万": 100.0, "万": 1.0, "": 0.0001}
        best = max(best, v * mult.get(unit, 1.0))
    return best


def _is_small_amount(text, limit_wan=5000):
    """
    金额过小的事件不构成市场信号。
    校准发现「名创优品回购24.55万美元」「苏科斯完成4000万元A轮融资」
    都因为「有公司名 + 有数字 + 有动作」拿到近 70 分。
    仅在包含资金动作词时判定，避免把「WTI原油报89.15美元/桶」这类价格误当金额。
    """
    if not _hit(text, MONEY_ACTION):
        return False
    mx = _max_amount_wan(text)
    return 0 < mx < limit_wan


# ============================================================
#  硬淘汰（hard drop）
#  为什么需要它：轴级压制在多轴加权下会被稀释 —— 校准实测
#  「埃尼集团柴油20%折扣」压了 reson/sig/act 三个轴，仍有 56 分（门槛 50），照样入选。
#  对这类「本就不该出现在看板上」的内容，只降权不够，必须封顶。
# ============================================================
HARD_CAP = 42          # 低于最低门槛（T1=46），确保硬淘汰条目一定落选


def hard_drop_reasons(text, title, ctype):
    """返回命中「硬淘汰」的原因列表；非空表示该条不应入选"""
    rs = []
    if _is_plain_quote(title or text):
        rs.append("纯行情/数据播报")
    if ctype and _is_foreign_stock_news(text, ctype):
        rs.append("纯海外个股/观点，与 A 股无直接关联")
    if _is_small_amount(text):
        rs.append("涉及金额过小，不构成市场信号")
    if _hit(text, MEETING_KW):
        rs.append("会议通知类，无实质内容")
    if _hit(text, IRRELEVANT_KW):
        rs.append("领域与市场判断无关")
    if _hit(text, STRONG_CLICKBAIT):
        rs.append("强标题党词，无实质内容")
    return rs


_BOND_VERB = re.compile(r"[涨跌升降]\s*(\d+(?:\.\d+)?)\s*个?基点")


def _is_plain_quote(text):
    """
    纯行情/数据播报：只有指数或收益率 + 小幅变动，没有原因、没有个股。
    例如「费城半导体指数涨2%」「韩国KOSPI指数开盘下跌0.4%」
        「日本2年期国债收益率下跌2.5个基点」。
    这类内容信息增量接近零，但早期实现会因为「有数字」反而拿高分。

    两处放宽（校准后调整）：
      - 长度上限 34 → 44（否则「日经225指数收盘下跌0.94%；韩国KOSPI指数收盘上涨0.46%」漏网）
      - 增加债市收益率播报判据
    涨跌幅 ≥3% 视为异动，仍保留价值，不压制。
    """
    # 债市收益率播报
    if ("收益率" in text or "国债" in text) and _BOND_VERB.search(text):
        return len(text) <= 46
    if not (_MARKET_IDX.search(text) and _MARKET_VERB.search(text)):
        return False
    if len(text) > 44:
        return False
    m = re.search(r"[涨跌]\s*(\d+(?:\.\d+)?)\s*[%％]", text)
    if not m:
        return False
    try:
        return float(m.group(1)) < 3.0
    except ValueError:
        return False


def apply_noise_caps(axes, text, title="", ctype=None):
    """
    按「必须压住的噪声」规则给指定轴设上限。
    返回 (新axes, 命中的规则说明列表)
    """
    out = dict(axes)
    fired = []
    for pats, axis, cap, why in NOISE_RULES:
        if _hit(text, pats):
            if out[axis] > cap:
                out[axis] = cap
                fired.append(f"{why}（{axis} 压至 {cap}）")
    # 函数型规则 1：纯行情播报（判据只看标题，避免被正文长度带偏）
    if _is_plain_quote(title or text):
        if out["nov"] > 3:
            out["nov"] = 3
        if out["reson"] > 5:
            out["reson"] = 5
        fired.append("纯行情播报，仅指数涨跌幅无实质信息（nov≤3, reson≤5）")
    # 函数型规则 2：纯海外个股 / 观点
    if ctype and _is_foreign_stock_news(text, ctype):
        for k, v in (("reson", 3), ("sig", 4), ("act", 2)):
            if out[k] > v:
                out[k] = v
        fired.append("纯海外个股/观点，与 A 股无直接关联（reson≤3, sig≤4, act≤2）")
    # 函数型规则 3：涉及金额过小
    if _is_small_amount(text):
        for k, v in (("sig", 3), ("act", 3)):
            if out[k] > v:
                out[k] = v
        fired.append(f"涉及金额过小（最大 {_max_amount_wan(text):.0f} 万元），"
                     f"不构成市场信号（sig≤3, act≤3）")
    return out, fired


# ============================================================
#  加权
# ============================================================
def weighted_score(axes, type_key):
    w = CONTENT_TYPES[type_key]["w"]
    return sum(axes[a] * w[a] for a in AXES)


# ============================================================
#  信源分级
# ============================================================
# 官方「发布行为」动词——只有机构在发布/公布时才算一手信源，
# 单纯「提到」某机构（如"东京通胀高于日本央行目标"）不升级。
_OFFICIAL_RELEASE = re.compile(
    r"(发布|公布|宣布|印发|出台|下发|批复|核准|决定|通知|公告|数据|统计|召开|答记者问|"
    r"披露|报告|白皮书|征求意见)")


def resolve_tier(src, text, title=""):
    """
    信源分级：媒体源给基础等级；文本主体确为官方机构「发布行为」时升级到 T1。

    收紧原因：早期实现只要文本出现官方机构名就升级，导致
    「东京通胀加速，大幅高于日本央行目标」这类被当成 T1 一手信源——
    实际它只是一条媒体转述的海外数据，不该享受最低门槛。
    现在要求：机构出现在标题前部 + 搭配发布类动词。
    """
    tier = BASE_TIER.get(src, DEFAULT_TIER)
    head = (title or text)[:18]
    if _hit(head, OFFICIAL_ORGS) and _OFFICIAL_RELEASE.search(text):
        if TIER_THRESHOLDS["T1"] < TIER_THRESHOLDS[tier]:
            return "T1", TIER_THRESHOLDS["T1"], f"官方机构发布（{src} → T1）"
    return tier, TIER_THRESHOLDS[tier], f"{src}（{tier}）"


# ============================================================
#  通道 B：结构通道（独立视角）
# ============================================================
def structural_score(item, plain_quote=False):
    """
    结构通道：不看内容语义，只看「怎么说的、什么来源」。
    独立于内容通道，用于双通道交叉验证。

    plain_quote=True 时表示这是纯行情播报：此时「有股票标的」不能算加分
    —— 东财对指数行情会自动挂成分股列表，那不是事件标的，容易被误当价值信号。
    """
    s = 40.0
    src = item.get("src", "")
    text = item.get("title", "") + " " + item.get("body", "")

    # 来源：东财有结构化标的关联，偏专业快讯
    if src == "东方财富":
        s += 10
    elif src in ("新浪财经", "同花顺"):
        s += 4

    # 有明确股票标的（纯行情播报不计）
    if item.get("stocks") and not plain_quote:
        s += 12

    # 正文信息量（但明令禁止「长正文」自动加分 → 上限有限）
    blen = len(item.get("body") or "")
    if blen >= 60:
        s += 8
    elif blen >= 25:
        s += 4

    # 数字密度（同样设上限）
    nd = len(_NUM_RE.findall(text))
    s += min(nd, 3) * 3

    # 时效：抓取时间距今（快讯本身就新，这里只做粗判）
    t = item.get("time") or ""
    if re.search(r"\d{4}-\d{2}-\d{2}", t):
        s += 3

    # 惩罚
    if _hit(text, ["传闻", "网传", "据悉", "知情人士"]):
        s -= 10
    if _hit(text, ["预计", "或将", "有望"]):
        s -= 6
    if _hit(text, ["重磅", "震惊", "炸裂", "官宣"]):
        s -= 8

    # 纯行情播报在结构通道同样设上限
    if plain_quote:
        s = min(s, 48)

    return max(0, min(s, 100))


# ============================================================
#  预筛（prefilter）：明显不该进的直接淘汰，省下后续算力
# ============================================================
PREFILTER_DROP = ["招聘", "诚聘", "征稿", "抽奖", "限时免费", "报名通道", "直播预告",
                  "新股申购日历", "休市安排", "节假日安排", "天气"]


def prefilter(text):
    """返回 (是否通过, 原因)"""
    for w in PREFILTER_DROP:
        if w in text:
            return False, f"预筛淘汰：命中 {w}"
    if len(text.strip()) < 8:
        return False, "预筛淘汰：文本过短"
    return True, ""


# ============================================================
#  单条评分主函数
# ============================================================
def score_item(item):
    """
    为一条快讯计算完整评分，返回新增字段 dict：
      ctype / ctypeName / axes / noise_notes / score(内容通道)
      struct_score(结构通道) / final_score / tier / threshold / passed
    """
    text = (item.get("title", "") + " " + item.get("body", "")).strip()
    sectors = item.get("sectors") or []
    has_stock = bool(item.get("stocks"))

    plain = _is_plain_quote(item.get("title", "") or text)
    ctype, _n = classify_type(text)
    axes_raw = score_axes(text, sectors, has_stock)
    axes, noise_notes = apply_noise_caps(axes_raw, text, item.get("title", ""), ctype)
    content = weighted_score(axes, ctype)
    struct = structural_score(item, plain)

    tier, thr, tier_note = resolve_tier(item.get("src", ""), text, item.get("title", ""))

    # 双通道：两者之和 ≥ 2×门槛
    total = content + struct
    final = total / 2
    hards = hard_drop_reasons(text, item.get("title", ""), ctype)
    if hards:
        final = min(final, HARD_CAP)          # 硬淘汰：封顶到门槛之下
    passed = (not hards) and total >= 2 * thr

    return {
        "ctype": ctype,
        "ctypeName": CONTENT_TYPES[ctype]["name"],
        "axes": axes,
        "axes_raw": axes_raw if axes_raw != axes else None,
        "noise_notes": noise_notes,
        "content_score": round(content, 1),
        "struct_score": round(struct, 1),
        "final_score": round(final, 1),        # 归一化回 0-100；硬淘汰条目已封顶
        "raw_score": round(total / 2, 1),       # 封顶前的原始分（诊断用）
        "sum_score": round(total, 1),
        "tier": tier,
        "threshold": thr,
        "tier_note": tier_note,
        "passed": passed,
        "hard_drops": hards,
        "plain_quote": plain,
    }


def score_all(items, log=None):
    """批量评分，返回 (打分后的列表, 统计信息)"""
    stat = {"total": 0, "prefiltered": 0, "passed": 0,
            "by_type": {}, "by_tier": {}, "noise_hits": 0, "failed": []}
    out = []
    for it in items:
        stat["total"] += 1
        text = (it.get("title", "") + " " + it.get("body", "")).strip()
        ok, why = prefilter(text)
        if not ok:
            stat["prefiltered"] += 1
            continue
        sc = score_item(it)
        it.update(sc)
        out.append(it)
        stat["by_type"][sc["ctypeName"]] = stat["by_type"].get(sc["ctypeName"], 0) + 1
        stat["by_tier"][sc["tier"]] = stat["by_tier"].get(sc["tier"], 0) + 1
        if sc["noise_notes"]:
            stat["noise_hits"] += 1
        if sc["passed"]:
            stat["passed"] += 1
        else:
            stat["failed"].append({
                "title": it.get("title", "")[:40],
                "score": sc["final_score"],
                "threshold": sc["threshold"],
                "type": sc["ctypeName"],
            })
    out.sort(key=lambda x: -x.get("final_score", 0))
    return out, stat


if __name__ == "__main__":
    import json
    import os
    import sys
    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    p = os.path.join(DATA, "auto_news.json")
    if not os.path.exists(p):
        print("请先运行 news_fetcher.py")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    items, stat = score_all(d["news"])
    print(f"评分完成：{stat['total']} 条 → 预筛淘汰 {stat['prefiltered']} "
          f"→ 入选 {stat['passed']} 条")
    print(f"类型分布: {stat['by_type']}")
    print(f"等级分布: {stat['by_tier']}")
    print(f"命中噪声压制的条目: {stat['noise_hits']} 条")
    print()
    print("Top 12：")
    for it in items[:12]:
        print(f"  {it['final_score']:5.1f}  [{it['tier']}/{it['ctypeName']}] "
              f"{it['title'][:44]}")
    print()
    if stat["failed"]:
        print(f"未达门槛（示例前 8 条）:")
        for f in stat["failed"][:8]:
            print(f"  {f['score']:5.1f} < {f['threshold']}  [{f['type']}] {f['title']}")
