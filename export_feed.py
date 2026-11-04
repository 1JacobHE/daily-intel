# -*- coding: utf-8 -*-
"""
export_feed.py — Agent 出口

为什么需要：
  用户主要在手机上看，但总有「不方便开网页、想让 Agent 直接读」的时候。
  把当日数据导成结构化文本，Agent 就能直接消费：
    data/feed/latest.md   当日摘要（人/Agent 都能读的 Markdown）
    data/feed/llms.txt    站点说明书 + 数据文件索引（LLM 入口约定）
    data/feed/feed.xml    RSS 2.0（可被任意阅读器订阅）
    data/feed/events.md   当日事件清单（纯列表，token 最省）

借鉴 AIHOT 的多出口设计（RSS / API / MCP / llms.txt / Agent Markdown）。
"""
import html
import json
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FEED_DIR = os.path.join(DATA_DIR, "feed")
CST = timezone(timedelta(hours=8))
SITE = "https://daily-intel-dashboard-27810.app.workbuddy.host/"

IMP_CN = {"bull": "利好", "bear": "利空", "neutral": "中性"}
TREND_CN = {"up": "上升", "down": "回落", "flat": "持平"}


def load(name):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _norm_title(t, n=44):
    return (t or "").replace("\n", " ").strip()[:n]


def build_latest_md(date, events, gh, mk):
    L = []
    L.append(f"# 今日情报汇总 · {date}")
    L.append("")
    gen = (events or {}).get("generated_at") or datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    L.append(f"> 数据日期 **{date}** · 生成于 {gen} · "
             f"在线看板：{SITE}")
    if mk and mk.get("marketClosed"):
        L.append(">")
        L.append(f"> 🏖 A股今日休市（{mk.get('weekday','')}）")
    L.append("")

    # ---- 一、GitHub ----
    if gh:
        L.append("## 一、GitHub 涨星雷达")
        L.append("")
        rocket = (gh.get("rocket") or [])[:5]
        if rocket:
            L.append("**火箭榜（平均吸星速率）**")
            L.append("")
            for i, r in enumerate(rocket, 1):
                rate = r.get("stars_per_day")
                rate_s = f"{rate:.0f}" if isinstance(rate, (int, float)) else "—"
                ann = ((gh.get("annotations") or {}).get(r.get("full_name")) or {})
                note = ann.get("name") or (r.get("desc") or "")[:40]
                delta = ((gh.get("deltas") or {}).get(r.get("full_name")))
                d_s = f" · 较上次 {delta:+d}★" if isinstance(delta, int) else ""
                L.append(f"{i}. **{r.get('full_name')}** — {note}")
                L.append(f"   {r.get('stars',0)}★ · +{rate_s}★/天 · {r.get('lang') or '—'}{d_s}")
            L.append("")
        L.append(f"（完整榜单见在线看板，共 "
                 f"{sum(len(gh.get(k) or []) for k in ('rocket','potential','active'))} 条）")
        L.append("")

    # ---- 二、事件 ----
    if events:
        evs = (events.get("events") or [])[:10]
        L.append("## 二、今日事件热度 Top 10")
        L.append("")
        L.append(f"*共抓取 {events['stat']['input_articles']} 条快讯，"
                 f"聚成 {events['stat']['events']} 个事件"
                 f"（同一件事的多条报道已合并）*")
        L.append("")
        cur_topic = None
        for e in evs:
            t = e.get("topicLabel")
            if t and t != cur_topic:
                cur_topic = t
                L.append(f"### 【{t}】")
                L.append("")
            flags = []
            if e.get("isNew"):
                flags.append("🆕新")
            if e.get("isRising"):
                flags.append("🔥上升")
            if e.get("source_count", 0) > 1:
                flags.append(f"{e['source_count']}家媒体报道")
            flag_s = (" · " + " · ".join(flags)) if flags else ""
            L.append(f"- **{_norm_title(e.get('title'), 50)}**"
                     f"（热度 {e.get('heat')}｜{e.get('tier')}{flag_s}）")
            if e.get("sectors"):
                L.append(f"  - 关联板块：{'、'.join(e['sectors'])}")
            for m in (e.get("members") or [])[1:3]:
                L.append(f"  - 另见 {m.get('src')}：{_norm_title(m.get('title'), 40)}")
        L.append("")

    # ---- 三、A股要闻 ----
    if mk:
        L.append("## 三、A股四维要闻")
        L.append("")
        c = mk.get("conclusion")
        if c:
            L.append(f"**基调**：{c.get('stance','—')}（多空评分 {c.get('score','—')}）")
            L.append("")
            L.append(f"{c.get('oneLine','')}")
            L.append("")
        news = mk.get("news") or []
        manual = [n for n in news if not n.get("auto")]
        auto = [n for n in news if n.get("auto")]
        if manual:
            L.append(f"### 人工深度研判（{len(manual)} 条）")
            L.append("")
            for n in manual:
                L.append(f"- **[{n.get('dimName')}] {_norm_title(n.get('title'), 48)}**"
                         f"（{IMP_CN.get(n.get('impact'), '')}）")
                if n.get("why"):
                    L.append(f"  - 为什么重要：{n['why']}")
                if n.get("sectors"):
                    L.append(f"  - 板块：{'、'.join(n['sectors'])}")
            L.append("")
        if auto:
            L.append(f"### 自动抓取快讯（{len(auto)} 条，按四维分组）")
            L.append("")
            from collections import defaultdict
            g = defaultdict(list)
            for n in auto:
                g[n.get("dimName") or "其他"].append(n)
            for dim, ns in g.items():
                L.append(f"**{dim}**（{len(ns)}）")
                L.append("")
                for n in ns[:8]:
                    L.append(f"- {_norm_title(n.get('title'), 50)}"
                             f"（{IMP_CN.get(n.get('impact'), '')}）")
                if len(ns) > 8:
                    L.append(f"- …另有 {len(ns)-8} 条")
                L.append("")
        ro = mk.get("riskOpportunity")
        if ro:
            L.append("### 风险与机会")
            L.append("")
            if ro.get("headline"):
                L.append(f"*{ro['headline']}*")
                L.append("")
            for kind, label in (("risks", "风险"), ("opportunities", "机会")):
                for it in (ro.get(kind) or [])[:4]:
                    lv = {"high": "高", "medium": "中", "low": "低"}.get(it.get("level"), "")
                    L.append(f"- **[{label}·{lv}] {it.get('title')}**")
                    if it.get("detail"):
                        L.append(f"  - {it['detail']}")
                    if it.get("action"):
                        L.append(f"  - 应对：{it['action']}")
            L.append("")

    # ---- 四、时间线 ----
    tl = load("timeline.json")
    if tl and tl.get("timelines"):
        multi = [e for e in tl["timelines"] if e.get("days", 1) > 1][:5]
        if multi:
            L.append("## 四、跨天事件追踪")
            L.append("")
            for e in multi:
                L.append(f"- **【{e.get('topicLabel') or e.get('dim') or '综合'}】"
                         f"{_norm_title(e.get('title'), 44)}**"
                         f"（{e['days']} 天 · {TREND_CN.get(e.get('trend'), '')}）")
                for p in e.get("series", []):
                    L.append(f"  - {p['date']}：{_norm_title(p.get('title'), 42)}")
            L.append("")

    L.append("---")
    L.append("")
    L.append("**数据来源与局限**：GitHub 数据来自官方 Search API（未认证，有频率限制）；"
             "财经快讯来自东方财富/新浪/同花顺公开接口，"
             "四维归类、情绪判定、事件合并、热度均为规则推断（derived），未经人工审核。"
             "A股深度研判（决策结论与风险机会）为人工调研内容。"
             "本页仅供信息聚合参考，不构成投资建议。")
    return "\n".join(L)


def build_events_md(date, events):
    """纯事件清单，token 最省，适合直接喂给 Agent"""
    L = [f"# {date} 事件清单", ""]
    if not events:
        return "\n".join(L)
    for i, e in enumerate(events.get("events") or [], 1):
        flags = []
        if e.get("isNew"):
            flags.append("新")
        if e.get("isRising"):
            flags.append("升")
        if e.get("source_count", 0) > 1:
            flags.append(f"{e['source_count']}源")
        f = f" [{'/'.join(flags)}]" if flags else ""
        L.append(f"{i}. {e.get('title')}  ({e.get('topicLabel') or e.get('dimName') or '—'}"
                 f"｜{e.get('impact')}｜热度{e.get('heat')}){f}")
    return "\n".join(L)


def build_llms_txt(date):
    return f"""# 今日情报汇总看板

> GitHub 涨星雷达 + A股四维要闻。每日自动更新。

在线看板: {SITE}
数据日期: {date}
生成时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M')}

## 这是什么
一个聚合两类信息的看板：
1. GitHub 涨星雷达 —— 用「火箭榜（星数÷存活天数）/ 势能榜（半年内总星）/ 活跃榜（近3天推送）」三维度逼近"涨星最快"，并用每日快照计算真实增量
2. A股四维要闻 —— 军事地缘 / 宏观经济政策 / AI与科技 / 市场资金面，标注利好利空与受益板块

## 数据入口（供 Agent 读取）
- {SITE}data/feed/latest.md      当日完整摘要（推荐，含事件聚簇与要闻）
- {SITE}data/feed/events.md      当日事件清单（最省 token）
- {SITE}data/feed/feed.xml       RSS 订阅
- {SITE}data/events.json         当日聚簇后的事件（含热度、来源数、成员报道）
- {SITE}data/github.json         当日 GitHub 榜单（含中文解读与增量）
- {SITE}data/market_news.json    当日 A股要闻
- {SITE}data/timeline.json       跨天事件时间线
- {SITE}data/weekly/index.json   周报索引
- {SITE}data/calibration/report.json  筛选规则校准报告（准确率/查准/查全 + 错例）

## 口径说明
- 热度按「事件」算而非按文章算：48 小时内每个独立来源只算一次，24 小时减半
- 重要性评分为五轴加权（实质份量/信息增量/证据强度/共振面/可用性）+ 噪声压制
- 四维归类、情绪判定、事件合并、热度均为规则推断（derived），未经人工审核
- A股深度研判（决策结论、风险机会）为人工调研内容，自动化流程不改写
- 本看板仅供信息聚合参考，不构成投资建议
"""


def build_rss(date, events, mk):
    now = datetime.now(CST)
    items = []
    for e in (events or {}).get("events", [])[:20]:
        title = html.escape(e.get("title", ""))
        desc_bits = [f"热度 {e.get('heat')} · {e.get('source_count')} 家来源",
                     f"类型 {e.get('ctypeName') or '—'}"]
        if e.get("sectors"):
            desc_bits.append("板块 " + "、".join(e["sectors"]))
        if e.get("members") and len(e["members"]) > 1:
            desc_bits.append("另见：" + "；".join(
                f"{m.get('src')} {m.get('title','')[:30]}" for m in e["members"][1:3]))
        desc = html.escape(" | ".join(desc_bits))
        guid = f"{SITE}#event-{e.get('eid','')}"
        items.append(
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{html.escape(SITE)}</link>\n"
            f"    <description>{desc}</description>\n"
            f"    <guid isPermaLink=\"false\">{html.escape(guid)}</guid>\n"
            f"    <pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S +0800')}</pubDate>\n"
            f"  </item>")
    # A股要闻也进 feed
    for n in (mk or {}).get("news", [])[:15]:
        if n.get("auto"):
            continue
        items.append(
            f"  <item>\n"
            f"    <title>{html.escape('[' + (n.get('dimName') or '') + '] ' + n.get('title',''))}</title>\n"
            f"    <link>{html.escape(SITE)}</link>\n"
            f"    <description>{html.escape((n.get('why') or n.get('body') or '')[:200])}</description>\n"
            f"    <guid isPermaLink=\"false\">{html.escape(SITE + '#news-' + str(abs(hash(n.get('title',''))) % 10**8))}</guid>\n"
            f"    <pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S +0800')}</pubDate>\n"
            f"  </item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0">\n<channel>\n'
            f'  <title>今日情报汇总看板 · {date}</title>\n'
            f'  <link>{html.escape(SITE)}</link>\n'
            '  <description>GitHub 涨星雷达 + A股四维要闻，每日自动更新</description>\n'
            '  <language>zh-cn</language>\n'
            f'  <lastBuildDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0800")}</lastBuildDate>\n'
            + "\n".join(items) + "\n</channel>\n</rss>\n")


def build(save_out=True, log=True):
    events = load("events.json")
    gh = load("github.json")
    mk = load("market_news.json")
    date = (gh or {}).get("date") or (mk or {}).get("date") or \
        datetime.now(CST).strftime("%Y-%m-%d")

    files = {
        "latest.md": build_latest_md(date, events, gh, mk),
        "events.md": build_events_md(date, events),
        "llms.txt": build_llms_txt(date),
        "feed.xml": build_rss(date, events, mk),
    }
    if save_out:
        for name, text in files.items():
            save(os.path.join(FEED_DIR, name), text)
    if log:
        for name, text in files.items():
            print(f"  -> feed/{name}  ({len(text)} 字符)")
    return files


def main():
    build(log=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
