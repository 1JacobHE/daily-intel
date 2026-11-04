# -*- coding: utf-8 -*-
"""
timeline.py — 事件时间线（跨天追踪）

解决的问题：
  单日看板只能看到「今天有什么」，看不出「这件事发展到了哪一步」。
  「美债收益率」「中东局势」「购房贴息」这类都是连续事件，
  跨天追踪比每天罗列一遍有价值得多。

做法（借鉴 AIHOT 的「让读者按时间顺序跟进事件发展」）：
  1. 收集所有历史日期的事件集合
     - data/news_history/YYYY-MM-DD.json  → 现场聚簇
     - data/event_snapshots/YYYY-MM-DD-HH.json → 直接读取
  2. 用 ekey（核心实体 + 主题）做跨天主键，把同一事件的多天记录串起来
  3. 输出每个事件的「首见日期 / 最近出现 / 热度变化 / 每日进展」

产出：data/timeline.json
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA_DIR = os.path.join(HERE, "data")
NEWS_HIST = os.path.join(DATA_DIR, "news_history")
SNAP_DIR = os.path.join(DATA_DIR, "event_snapshots")
CST = timezone(timedelta(hours=8))


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_days():
    """
    返回 [(date, [event,...]), ...]，按日期升序。
    同一天既有归档又有快照时，优先用快照（含 ekey / topic，信息更全）。
    """
    days = {}

    # 1) 每日归档：现场聚簇
    if os.path.isdir(NEWS_HIST):
        from event_cluster import cluster
        for fn in sorted(os.listdir(NEWS_HIST)):
            m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", fn)
            if not m:
                continue
            d = load(os.path.join(NEWS_HIST, fn))
            if not d or not d.get("news"):
                continue
            try:
                events, _ = cluster(d["news"])
            except Exception:
                continue
            days[m.group(1)] = {"events": events, "src": "archive"}

    # 2) 运行快照：覆盖同日归档（ekey 更可靠）
    if os.path.isdir(SNAP_DIR):
        for fn in sorted(os.listdir(SNAP_DIR)):
            m = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{2})\.json$", fn)
            if not m:
                continue
            d = load(os.path.join(SNAP_DIR, fn))
            if not d:
                continue
            date = m.group(1)
            prev = days.get(date)
            if prev and prev["src"] == "snapshot":
                # 同一天多个小时快照：合并事件（按 eid 去重，保留热度高的）
                by_id = {e["eid"]: e for e in prev["events"]}
                for e in d.get("events", []):
                    if e["eid"] not in by_id or (e.get("heat", 0) > by_id[e["eid"]].get("heat", 0)):
                        by_id[e["eid"]] = e
                prev["events"] = list(by_id.values())
            else:
                days[date] = {"events": d.get("events", []), "src": "snapshot",
                              "ts": d.get("ts", "")}

    return sorted(days.items(), key=lambda x: x[0])


def _key(e):
    """跨天主键：优先 ekey（含主体+主题），退化到 eid"""
    return (e.get("ekey") or "").strip() or e.get("eid", "")


def build(min_days=1, save=True, log=True):
    days = collect_days()
    if not days:
        return None, {"error": "无历史数据"}

    tl = {}
    for date, pack in days:
        for e in pack["events"]:
            k = _key(e)
            if not k:
                continue
            node = tl.setdefault(k, {
                "ekey": k,
                "kind": e.get("kind", "event_line"),
                "title": e.get("title", ""),
                "topic": e.get("topic"),
                "topicLabel": e.get("topicLabel"),
                "dim": e.get("dimName"),
                "points": [],
            })
            node["points"].append({
                "date": date,
                "heat": e.get("heat", 0),
                "title": e.get("title", ""),
                "source_count": e.get("source_count", 0),
                "sources": e.get("sources", []),
                "impact": e.get("impact"),
                "sectors": e.get("sectors", []),
                "eid": e.get("eid"),
            })
            # 用最新一次出现更新展示信息
            node["title"] = e.get("title", node["title"])
            if e.get("topic"):
                node["topic"] = e["topic"]
                node["topicLabel"] = e.get("topicLabel")

    # 汇总：只保留出现 >= min_days 天的事件，并按「跨天持续性」排序
    out = []
    for k, node in tl.items():
        pts = sorted(node["points"], key=lambda x: x["date"])
        # 同一天多条合并
        merged = {}
        for p in pts:
            if p["date"] not in merged or p["heat"] > merged[p["date"]]["heat"]:
                merged[p["date"]] = p
        series = [merged[d] for d in sorted(merged)]
        if len(series) < min_days:
            continue
        heats = [p["heat"] for p in series]
        trend = "flat"
        if len(series) >= 2:
            if heats[-1] > heats[0] * 1.2:
                trend = "up"
            elif heats[-1] < heats[0] * 0.8:
                trend = "down"
        out.append({
            "ekey": k,
            "kind": node["kind"],
            "title": node["title"],
            "topic": node["topic"],
            "topicLabel": node["topicLabel"],
            "dim": node["dim"],
            "days": len(series),
            "first_seen": series[0]["date"],
            "last_seen": series[-1]["date"],
            "heat_latest": heats[-1],
            "heat_peak": max(heats),
            "trend": trend,
            "series": series,
        })

    # 主体线优先（跨天追踪价值更高），其次按跨天天数与热度
    out.sort(key=lambda x: (0 if x["kind"] == "topic_line" else 1,
                            -x["days"], -x["heat_peak"]))

    payload = {
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "days_covered": [d for d, _ in days],
        "events_tracked": len(out),
        "multi_day_events": sum(1 for e in out if e["days"] > 1),
        "timelines": out,
        "provenance": {
            "method": "ekey_join_across_days",
            "status": "derived",
            "detail": "以「核心实体+主题」为跨天主键串接同一事件的每日进展；"
                      "天数越多说明该事件被持续关注",
        },
    }
    if save:
        with open(os.path.join(DATA_DIR, "timeline.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    if log:
        print(f"  覆盖 {len(days)} 天：{', '.join(d for d, _ in days)}")
        print(f"  追踪事件 {payload['events_tracked']} 个，"
              f"其中跨天（≥2 天）事件 {payload['multi_day_events']} 个")
    return payload, {}


def main():
    payload, stat = build(log=True)
    if payload is None:
        print("无历史数据，先跑 daily_update.py")
        return 1
    print()
    multi = [e for e in payload["timelines"] if e["days"] > 1]
    if multi:
        print("跨天事件时间线：")
        for e in multi[:8]:
            arrow = {"up": "↑", "down": "↓", "flat": "→"}[e["trend"]]
            print(f"  {arrow} 【{e.get('topicLabel') or e['dim'] or '—'}】"
                  f"{e['title'][:40]}")
            for p in e["series"]:
                print(f"       {p['date']}  热度 {p['heat']:>4}  "
                      f"{p['source_count']} 源  {p['title'][:34]}")
    else:
        print("暂无跨天事件（需要至少两天的数据积累）")
        print("单日事件示例：")
        for e in payload["timelines"][:5]:
            print(f"  · {e['title'][:50]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
