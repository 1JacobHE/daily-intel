# -*- coding: utf-8 -*-
"""
weekly_report.py — 周报

单日榜单看不出「谁在持续涨星」——只能看到今天爆发的项目。
周报补的正是这个视角：把本周每一天的归档叠起来，找持续出现的项目与持续发酵的话题。

产出：
  data/weekly/YYYY-Www.json  （周报数据）
  data/weekly/index.json     （周报索引）

两部分：
  1. GitHub 持续性榜单 —— 本周上榜天数 + 星数净增
  2. 要闻主线 —— 本周反复出现的主题（借用 timeline.json 的跨天串联结果）
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
NEWS_HIST = os.path.join(DATA_DIR, "news_history")
OUT_DIR = os.path.join(DATA_DIR, "weekly")
CST = timezone(timedelta(hours=8))


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def iso_week(dt):
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _daily_files(days):
    """近 N 天的日期字符串集合"""
    today = datetime.now(CST).date()
    return {(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)}


def github_persistence(days=7):
    """
    GitHub 持续性榜单：
      上榜天数 —— 本周有几天进入任一榜单（火箭/势能/活跃）
      星数净增 —— 本周首见与最新的星数差
      趋势     —— 排名是否在往上走
    """
    if not os.path.isdir(HIST_DIR):
        return []
    window = _daily_files(days)
    track = {}

    for fn in sorted(os.listdir(HIST_DIR)):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.json$", fn)
        if not m or m.group(1) not in window:
            continue
        date = m.group(1)
        d = load(os.path.join(HIST_DIR, fn))
        if not d:
            continue
        seen_today = set()
        for board, key in (("火箭榜", "rocket"), ("势能榜", "potential"), ("活跃榜", "active")):
            for rank, r in enumerate(d.get(key, []) or [], 1):
                fn_ = r.get("full_name")
                if not fn_ or fn_ in seen_today:
                    continue
                seen_today.add(fn_)
                t = track.setdefault(fn_, {
                    "full_name": fn_, "desc": r.get("desc", ""),
                    "lang": r.get("lang"), "boards": set(), "days": [],
                    "stars": {}, "ranks": [],
                })
                t["boards"].add(board)
                t["days"].append(date)
                t["stars"][date] = r.get("stars", 0)
                t["ranks"].append({"date": date, "board": board, "rank": rank})

    out = []
    for t in track.values():
        ds = sorted(t["stars"])
        first, last = (t["stars"][ds[0]], t["stars"][ds[-1]]) if ds else (0, 0)
        growth = last - first
        # 排名趋势：比较最早与最晚在火箭榜的名次
        rr = [x for x in t["ranks"] if x["board"] == "火箭榜"]
        trend = "flat"
        if len(rr) >= 2:
            ef = min(x["rank"] for x in rr[:len(rr) // 2]) if rr[:len(rr) // 2] else 0
            el = min(x["rank"] for x in rr[len(rr) // 2:]) if rr[len(rr) // 2:] else 0
            if el and ef and el < ef:
                trend = "up"
            elif el and ef and el > ef:
                trend = "down"
        out.append({
            "full_name": t["full_name"], "desc": t["desc"], "lang": t["lang"],
            "days_on_board": len(set(t["days"])),
            "boards": sorted(t["boards"]),
            "first_date": ds[0] if ds else "", "last_date": ds[-1] if ds else "",
            "stars_first": first, "stars_last": last, "stars_growth": growth,
            "trend": trend,
        })

    out.sort(key=lambda x: (-x["days_on_board"], -x["stars_growth"]))
    return out


def news_mainlines(days=7):
    """要闻主线：直接复用 timeline 的跨天串联结果"""
    tl = load(os.path.join(DATA_DIR, "timeline.json"))
    if not tl:
        return []
    window = _daily_files(days)
    out = []
    for e in tl.get("timelines", []):
        pts = [p for p in e.get("series", []) if p["date"] in window]
        if len(pts) < 2:
            continue
        out.append({
            "topicLabel": e.get("topicLabel") or e.get("dim") or "综合",
            "title": e["title"],
            "days": len(pts),
            "kind": e.get("kind"),
            "points": [{"date": p["date"], "title": p["title"],
                        "heat": p["heat"], "sources": p.get("source_count", 0)}
                       for p in pts],
        })
    out.sort(key=lambda x: (-x["days"],))
    return out


def build(days=7, save_out=True, log=True):
    now = datetime.now(CST)
    gh = github_persistence(days)
    ml = news_mainlines(days)

    payload = {
        "week": iso_week(now),
        "date_range": [now.strftime("%Y-%m-%d"),
                       (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")],
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "github_persistent": gh[:30],
        "news_mainlines": ml[:12],
        "stat": {
            "repos_tracked": len(gh),
            "repos_multi_day": sum(1 for x in gh if x["days_on_board"] > 1),
            "mainlines": len(ml),
        },
        "provenance": {
            "method": "aggregate_over_archives",
            "status": "derived",
            "detail": "对近 %d 天归档做叠加统计：GitHub 用「上榜天数+星数净增」，"
                      "要闻主线复用跨天事件串联结果" % days,
        },
    }
    if save_out:
        save(os.path.join(OUT_DIR, f"{payload['week']}.json"), payload)
        # 索引
        idx = load(os.path.join(OUT_DIR, "index.json")) or {"weeks": []}
        weeks = [w for w in idx.get("weeks", []) if w.get("week") != payload["week"]]
        weeks.append({
            "week": payload["week"], "range": payload["date_range"],
            "repos": payload["stat"]["repos_tracked"],
            "mainlines": payload["stat"]["mainlines"],
        })
        weeks.sort(key=lambda x: x["week"])
        save(os.path.join(OUT_DIR, "index.json"),
             {"latest": payload["week"], "weeks": weeks})

    if log:
        print(f"  周报 {payload['week']}（{payload['date_range'][1]} ~ {payload['date_range'][0]}）")
        print(f"  GitHub 持续榜：{payload['stat']['repos_tracked']} 个项目中 "
              f"{payload['stat']['repos_multi_day']} 个多日上榜")
        print(f"  要闻主线：{payload['stat']['mainlines']} 条")
    return payload, {}


def main():
    p, _ = build(log=True)
    print()
    if p["github_persistent"]:
        print("GitHub 持续性榜单（本周多日上榜）:")
        for r in p["github_persistent"][:8]:
            if r["days_on_board"] < 2:
                continue
            arrow = {"up": "↑", "down": "↓", "flat": "→"}[r["trend"]]
            print(f"  {arrow} {r['days_on_board']}天  {r['full_name'][:38]:40s} "
                  f"{r['stars_last']:>7}★  ({r['stars_growth']:+d})")
    if p["news_mainlines"]:
        print()
        print("要闻主线:")
        for m in p["news_mainlines"][:6]:
            print(f"  {m['days']}天 · 【{m['topicLabel']}】{m['title'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
