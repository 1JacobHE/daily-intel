# -*- coding: utf-8 -*-
"""
项目中文解读表 —— 为 GitHub 榜单里的项目补上一句人话
被 build_annotations() 读取后写入 data/annotations.json，看板据此渲染。

字段：
  name  : 「一句话」简洁说明这个项目是干嘛的
  tag   : 赛道分类
  note  : （可选）给用户的额外提醒，比如「跟你相关」「有风险」
"""

# key = full_name
PROJECT_NOTES = {
    # ---------------- 火箭榜 ----------------
    "KKKKhazix/AIHOT": {
        "name": "自动找热点、自动写日报的网站框架，把信源换成你自己的就是个人行业情报站",
        "tag": "信息聚合",
        "note": "跟你正在做的这个工具是同一类思路，可以直接参考它的信源配置",
    },
    "feder-cr/dots": {
        "name": "自带浏览器的 AI Agent，能绕开反爬正常上网抓东西",
        "tag": "AI Agent",
    },
    "jev-chat/jev-chat-jarvis": {
        "name": "手机上的聊天助手：在 QQ/飞书里读懂对方消息，给出候选回复，一键填入，发不发你决定",
        "tag": "AI Agent",
        "note": "9 天冲到 7000+ 星，是本轮增长最猛的项目",
    },
    "wy51ai/floorplan-3d": {
        "name": "把户型平面图转成 3D 模型",
        "tag": "3D/可视化",
    },
    "firelex/jeff": {
        "name": "基于 Qwen3.5 和 Gemma 4 微调的零样本分类模型",
        "tag": "模型微调",
    },
    "yetone/magpie": {
        "name": "一个菜单栏工具，统一管理各家 AI 模型：让 Codex 跑 DeepSeek、Claude Code 跑 Kimi",
        "tag": "开发工具",
    },
    "dzhng/jevgrep": {
        "name": "用自然语言描述功能来搜代码的 CLI 工具，给编程 Agent 用的",
        "tag": "开发工具",
    },
    "Contrastive-LM/CLM": {
        "name": "对比学习语言模型（暂无官方简介）",
        "tag": "模型研究",
    },
    "Niko1221/Strata": {
        "name": "让 125B 超大模型跑在 8GB 显卡上：一键安装，本地起 OpenAI/Anthropic 兼容接口",
        "tag": "本地推理",
        "note": "显存不够跑大模型的痛点方案，消费级硬件就能用",
    },
    "mexicat/pdoom-video": {
        "name": "用代码渲染出来的音乐视频",
        "tag": "创意/AI生成",
    },
    "yihui-dev/awesome-opus5-5-videos": {
        "name": "Claude 生成的爆款视频合集，附带提示词",
        "tag": "资源合集",
    },
    "tobi/disktree": {
        "name": "用矩形树图直观找出磁盘里什么最占空间，方便清理",
        "tag": "系统工具",
    },
    "feitangyuan/onetake": {
        "name": "一镜到底的动效视频生成：每个节拍从上一拍生长出来，不切镜头",
        "tag": "创意/AI生成",
    },
    "kaankiziltug/logo-design-skill": {
        "name": "给 AI Agent 用的 Logo 设计技能包，含设计原则、SVG 技法、1400+ 案例库",
        "tag": "Agent Skill",
    },
    "unreallabsai/unreal-agent": {
        "name": "异步优先的 Agent 运行框架",
        "tag": "AI Agent",
    },
    "shihabal3amri/DiPlay": {
        "name": "让安卓车机用上 CarPlay 的独立接收器",
        "tag": "车载/系统",
    },
    "JohnHeibel/PDoomVideo": {
        "name": "AI 音乐视频的源码（mexicat 那个项目的同款）",
        "tag": "创意/AI生成",
    },
    "deepopen-com/deepopen": {
        "name": "非自回归的 System 1 决策引擎，专做结构化类型决策，主打快",
        "tag": "模型架构",
    },
    "supermemoryai/company-brain": {
        "name": "团队知识大脑：Slack 里的 AI 队友，记住团队说过的所有事并帮你干活",
        "tag": "企业应用",
    },
    "852wa/JIZURA": {
        "name": "从歌词自动生成文字 PV 的浏览器应用",
        "tag": "创意/AI生成",
    },
    "dgreenheck/tidewater": {
        "name": "用 Claude 生成的 3D 海滨小镇",
        "tag": "创意/AI生成",
    },
    "riba2534/claude-opus-5-5-demo": {
        "name": "Claude 新版本能力演示",
        "tag": "创意/AI生成",
    },
    "nokia-applied-research/AnyJev": {
        "name": "把任意 LLM 改造成 Jev 风格的决策模型，支持类型化决策与真实推理",
        "tag": "模型研究",
    },
    "ollaya-dev/ollaya": {
        "name": "本地运行开源决策模型，一键拉取和部署",
        "tag": "本地推理",
    },
    "freestylefly/WeChatBridge": {
        "name": "把微信聊天记录转发给 AI Agent 和 Obsidian 的 macOS 原生工具",
        "tag": "效率工具",
    },
    "OnlistTeam/ai-manager": {
        "name": "管理各类 AI 编程工具的桌面应用",
        "tag": "开发工具",
    },
    "kryvora-network/kryvora-node": {
        "name": "Kryvora 网络的参考客户端与验证节点",
        "tag": "区块链",
    },
    "mikehasa/golive-skill": {
        "name": "让 Agent 做的产品直接上线：托管、数据库、域名、邮件一站式",
        "tag": "Agent Skill",
    },
    "dzhng/jevgrep ": {
        "name": "同 jevgrep",
        "tag": "开发工具",
    },

    # ---------------- 10-01 新增 ----------------
    "rehan-remade/universal-modder": {
        "name": "让 Claude 给任意游戏做 Mod：配套技能、工具和 fal MCP 服务",
        "tag": "AI Agent",
    },
    "nanaism/yomiyasu": {
        "name": "日文 AI 写作润色技能：把生硬的机翻日语改写成自然的人话",
        "tag": "Agent Skill",
    },
    "OpSafari/hypoarena": {
        "name": "科研假设发现工作台：把假设和证据连成图谱，辅助科学推理",
        "tag": "科研工具",
    },
    "Louis-CFM/coucou": {
        "name": "住在刘海（macOS）或屏幕顶端（Windows）的小桌宠伙伴",
        "tag": "桌面应用",
    },
    "echris6/motion-video-kit": {
        "name": "做商业级 AI 辅助视频的 Claude 技能包",
        "tag": "Agent Skill",
    },
    "eternity4719/HowToLiveBetter": {
        "name": "高性价比人生指南：长寿防病、急救、省钱理财、法律红线、失业工伤、医保社保、婚育育儿、创业合规、出国技能，每条标明成本收益与证据等级",
        "tag": "生活指南",
        "note": "你正在办跨省医保备案，里面医保社保那一节可能用得上",
    },
    "BigPizzaV3/CodexPlusPlus": {
        "name": "Codex 命令行工具的增强版，让它更好用",
        "tag": "开发工具",
    },
    "TheAlgorithms/Python": {
        "name": "用 Python 实现的各种算法大全，学算法/刷题常备",
        "tag": "学习资源",
        "note": "经典老项目，30 万星级别的基础设施",
    },

    # ---------------- 势能榜 ----------------
    "deepseek-ai/deepseek-harness": {
        "name": "DeepSeek 官方 Agent 框架，主打「一切皆插件」，半年拿到 24 万星",
        "tag": "AI Agent",
        "note": "本榜增长最快的项目，生态地位类似 Claude Code 的插件体系",
    },
    "DietrichGebert/ponytail": {
        "name": "让 AI 像最懒的资深工程师那样思考——最好的代码是你从没写过的代码",
        "tag": "Agent Skill",
        "note": "理念是让 AI 少写代码、多复用，反向优化 token 消耗",
    },
    "JuliusBrussee/caveman": {
        "name": "让编程 Agent 用「原始人说话」的方式省掉 65% token 的代理工具",
        "tag": "开发工具",
    },
    "nexu-io/open-design": {
        "name": "开源的 Claude Design 替代品，本地优先的设计桌面应用",
        "tag": "设计工具",
    },
    "odysseus-dev/odysseus": {
        "name": "可自托管的 AI 工作台",
        "tag": "自托管",
    },
    "tt-a1i/archify": {
        "name": "画架构图/流程图/时序图/数据流图的 Agent 技能，输出带动效的 HTML",
        "tag": "Agent Skill",
    },
    "career-ops-hq/career-ops": {
        "name": "开源 AI 求职助手：扫招聘网站、按 1-5 分给岗位打分、定制简历、跟踪投递",
        "tag": "求职工具",
        "note": "你正在看机会的话，这个可以直接拿来用",
    },
    "MemPalace/mempalace": {
        "name": "开源 AI 记忆系统，主打各种 benchmark 跑分最高，且免费",
        "tag": "AI 记忆",
    },
    "ayghri/i-have-adhd": {
        "name": "治 AI「话太多」的技能：让它别把答案埋在废话里，直接给结论",
        "tag": "Agent Skill",
    },
    "debpalash/VoiceStudio": {
        "name": "全本地运行的开源 ElevenLabs 替代品：声音克隆、配音、转录、有声书",
        "tag": "语音/AI",
    },
    "Yuan1z0825/nature-skills": {
        "name": "写 Nature 论文用的学术表达和科研绘图技能包",
        "tag": "Agent Skill",
    },
    "bilawalsidhu/gods-eye-view": {
        "name": "浏览器里的间谍卫星模拟器，游玩用的是真实开源地理数据",
        "tag": "地理可视化",
    },
    "cathrynlavery/diagram-design": {
        "name": "偏杂志排版风格的图表设计技能，输出纯 HTML+SVG，不用 Mermaid",
        "tag": "Agent Skill",
    },
    "alibaba/open-code-review": {
        "name": "阿里开源的代码审查工具：确定性流水线 + LLM，能精确到行级评论",
        "tag": "开发工具",
        "note": "阿里生产环境验证过，工程可靠性有背书",
    },
    "zhaoxuya520/reverse-skill": {
        "name": "逆向工程/授权渗透测试的技能路由器包，按需加载工具链",
        "tag": "安全研究",
        "note": "安全类工具，注意只在授权范围内使用",
    },
    "JustVugg/colibri": {
        "name": "纯 C 写的推理引擎，无依赖，把专家权重从磁盘流式加载，让普通机器也能跑超大 MoE 模型",
        "tag": "本地推理",
    },
    "esengine/DeepSeek-Reasonix": {
        "name": "面向复杂软件工程任务的可靠编程 Agent",
        "tag": "AI Agent",
    },
    "freestylefly/awesome-gpt-image-2": {
        "name": "GPT Image 2/2.5 的提示词案例库，530+ 案例 + 20+ 工业级模板",
        "tag": "资源合集",
    },
    "alchaincyf/nuwa-skill": {
        "name": "蒸馏任何人的思维方式：心智模型、决策启发式、表达 DNA",
        "tag": "Agent Skill",
    },
    "virgiliojr94/book-to-skill": {
        "name": "把技术书 PDF 转成可随时查阅的 Claude 技能",
        "tag": "Agent Skill",
    },
    "Graphify-Labs/graphify": {
        "name": "把代码库连同文档、SQL、配置、PDF 一起变成可查询的知识图谱",
        "tag": "代码理解",
    },
    "esengine/DeepSeek-Reasonix ": {
        "name": "同 DeepSeek-Reasonix",
        "tag": "AI Agent",
    },
    "freestylefly/awesome-gpt-image-2 ": {
        "name": "同 awesome-gpt-image-2",
        "tag": "资源合集",
    },

    # ---------------- 活跃榜 ----------------
    "public-apis/public-apis": {
        "name": "免费 API 大合集，做项目找数据源先看这个",
        "tag": "资源合集",
        "note": "48 万星，程序员必备清单",
    },
    "freeCodeCamp/freeCodeCamp": {
        "name": "免费学编程的课程与代码库",
        "tag": "学习资源",
    },
    "openclaw/openclaw": {
        "name": "跨平台通用 AI 助手，主打「真能干活」",
        "tag": "AI Agent",
    },
    "nilbuild/developer-roadmap": {
        "name": "开发者成长路线图，各技术方向该学什么一目了然",
        "tag": "学习资源",
    },
    "vinta/awesome-python": {
        "name": "Python 工具大全：想做 X，该用哪个库",
        "tag": "资源合集",
    },
    "awesome-selfhosted/awesome-selfhosted": {
        "name": "可自托管的开源网络服务清单",
        "tag": "资源合集",
    },
    "practical-tutorials/project-based-learning": {
        "name": "通过做项目来学编程的教程合集",
        "tag": "学习资源",
    },
    "mattpocock/skills": {
        "name": "一线工程师的真实 Agent 技能库",
        "tag": "Agent Skill",
    },
    "affaan-m/ECC": {
        "name": "Agent 运行框架的性能优化系统：技能、直觉、记忆、安全",
        "tag": "AI Agent",
    },
    "react/react": {
        "name": "React 前端框架源码",
        "tag": "前端框架",
    },
    "torvalds/linux": {
        "name": "Linux 内核源码",
        "tag": "操作系统",
    },
    "NousResearch/hermes-agent": {
        "name": "随你一起成长的 Agent",
        "tag": "AI Agent",
    },
}


def build_annotations(repos):
    """给仓库列表注入中文解读，未收录的做兜底推断"""
    out = {}
    for r in repos:
        fn = r["full_name"].strip()
        info = PROJECT_NOTES.get(r["full_name"]) or PROJECT_NOTES.get(fn)
        if info:
            out[r["full_name"]] = info
            continue
        # 兜底：用 tag 规则猜赛道，避免看板出现空白
        out[r["full_name"]] = {
            "name": (r.get("desc") or "").strip() or "（官方未提供简介）",
            "tag": guess_tag(r),
            "auto": True,
        }
    return out


def guess_tag(r):
    blob = ((r.get("desc") or "") + " " + " ".join(r.get("topics") or [])).lower()
    rules = [
        (("agent", "harness", "skill"), "AI Agent"),
        (("llm", "model", "inference", "quantiz"), "模型/推理"),
        (("cli", "ide", "editor", "debug", "lint"), "开发工具"),
        (("dataset", "awesome", "roadmap", "book", "tutorial", "curriculum"), "资源合集"),
        (("voice", "image", "video", "diffus", "music", "art"), "创意/AI生成"),
        (("security", "pentest", "exploit", "reverse"), "安全研究"),
        (("trading", "stock", "quant", "finance"), "金融科技"),
    ]
    for keys, tag in rules:
        if any(k in blob for k in keys):
            return tag
    return "其他"
