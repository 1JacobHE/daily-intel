# -*- coding: utf-8 -*-
"""
GitHub 涨星雷达 —— 抓取当前 GitHub 上增长最快的项目
数据源：GitHub 官方 Search API（无需 token，未认证限速 10 req/min）

策略说明：
  GitHub 已不再对外提供「单日 star 增量」接口，trending 页面也无官方 API。
  本脚本用三个可量化的维度逼近「增长最快」：
    1. 火箭榜  —— 近 FRESH_DAYS 天内新建、且已拿到高星的项目（爆发式增长）
    2. 势能榜  —— 近 QUARTER_DAYS 天内新建、星数最高的项目（持续高增长）
    3. 活跃榜  —— 高星项目中最近仍在高频推送代码的（热度未退）
  每次运行会保存快照，第二次运行起可计算「真实星数增量」。
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
SNAP_DIR = os.path.join(DATA_DIR, "snapshots")
HIST_DIR = os.path.join(DATA_DIR, "history")
os.makedirs(SNAP_DIR, exist_ok=True)
os.makedirs(HIST_DIR, exist_ok=True)

API = "https://api.github.com/search/repositories"
UA = {"Accept": "application/vnd.github+json",
      "User-Agent": "star-radar/1.0",
      "X-GitHub-Api-Version": "2022-11-28"}

# 认证：CI（GitHub Actions）里注入 GITHUB_TOKEN 后，Search API 限额从
# 10 req/min 提升到 30 req/min，可基本消除 403 部分失败（10-06/09/11/21 各踩过一次）
TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
if TOKEN:
    UA["Authorization"] = f"Bearer {TOKEN}"

FRESH_DAYS = 10       # 火箭榜窗口
QUARTER_DAYS = 180    # 势能榜窗口
CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 数据溯源
# 借鉴 HKUDS/Vibe-Trading 的 _provenance 设计：每个数字都要能说清「从哪来」，
# 并显式标注口径、回退与失败，避免「默认值静默替换真实值」这类隐蔽问题。
def make_prov():
    return {
        "source": "api.github.com/search/repositories",
        "source_type": "official_api",
        "auth": "token (GITHUB_TOKEN)" if TOKEN else "anonymous",
        "rate_limit": "30 req/min (token)" if TOKEN else "10 req/min (unauthenticated)",
        "fetched_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {},
        "warnings": [],
    }


def prov_mark(prov, key, status, detail=""):
    """记录某个指标的可信度：observed(实测) / derived(推算) / failed(缺失)"""
    prov["metrics"][key] = {"status": status, "detail": detail}


def today_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def days_ago(n):
    return (datetime.now(CST) - timedelta(days=n)).strftime("%Y-%m-%d")


def api_search(query, per_page=30, sort="stars"):
    """调用 GitHub Search API。返回 (items, ok)。失败时 ok=False，绝不静默返回空列表。

    403/429 限流时不盲目重试：优先按 X-RateLimit-Reset 或 Retry-After 精确等待，
    等待上限 90s；无法解析等待头则退化为递增退避。
    """
    params = urllib.parse.urlencode({
        "q": query, "sort": sort, "order": "desc", "per_page": per_page,
    })
    url = f"{API}?{params}"
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data.get("items", []), True
        except urllib.error.HTTPError as e:      # noqa: PERF203
            last_err = e
            if e.code in (403, 429):
                wait = _rate_wait(e)
                print(f"  [RATE] {e.code} 限流，等待 {wait}s 后重试（第 {attempt + 1} 次）",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            time.sleep(2 + attempt * 2)
        except Exception as e:                  # noqa: BLE001
            last_err = e
            time.sleep(3 + attempt * 3)
    print(f"  [ERROR] 请求失败 {query}: {last_err}", file=sys.stderr)
    return [], False


def _rate_wait(err):
    """从限流响应头推算应等待的秒数，上限 90s"""
    try:
        reset = err.headers.get("X-RateLimit-Reset")
        if reset:
            wait = int(reset) - int(time.time()) + 2
            if 0 < wait <= 90:
                return wait
        ra = err.headers.get("Retry-After")
        if ra and str(ra).isdigit() and 0 < int(ra) <= 90:
            return int(ra) + 2
    except Exception:                           # noqa: BLE001
        pass
    return 20


def slim(item):
    """裁剪仓库字段，只留看板需要的"""
    lang = item.get("language") or "Other"
    return {
        "full_name": item["full_name"],
        "url": item["html_url"],
        "desc": (item.get("description") or "").strip(),
        "stars": item.get("stargazers_count", 0),
        "forks": item.get("forks_count", 0),
        "lang": lang,
        "created": (item.get("created_at") or "")[:10],
        "pushed": (item.get("pushed_at") or "")[:10],
        "topics": (item.get("topics") or [])[:6],
        "owner": item["owner"]["login"],
        "avatar": item["owner"]["avatar_url"],
        "age_days": None,
    }


def enrich_age(repos):
    now = datetime.now(timezone.utc)
    for r in repos:
        try:
            c = datetime.strptime(r["created"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            r["age_days"] = max(1, (now - c).days)
            r["stars_per_day"] = round(r["stars"] / r["age_days"], 1)
        except Exception:                       # noqa: BLE001
            r["stars_per_day"] = 0
    return repos


def dedupe(seq):
    seen, out = set(), []
    for r in seq:
        if r["full_name"] in seen:
            continue
        seen.add(r["full_name"])
        out.append(r)
    return out


def load_prev_snapshot(exclude_date=None):
    """读最近一次快照，用于计算星数增量

    exclude_date: 排除该日期的快照（通常是今天）。当天重跑时必须排除今天
    已写出的快照，否则会「拿今天跟今天自己比」→ 增量恒为 0。
    典型的翻车场景：GitHub 首轮抓取失败写出空快照，随后重试成功。
    """
    if not os.path.isdir(SNAP_DIR):
        return None, None
    files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    if exclude_date:
        files = [f for f in files if f[:-5] < exclude_date]
    if not files:
        return None, None
    path = os.path.join(SNAP_DIR, files[-1])
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), files[-1][:-5]
    except Exception:                           # noqa: BLE001
        return None, None


def collect():
    prov = make_prov()
    print("[1/3] 抓取 GitHub 数据 …")
    fresh_q = f"created:>{days_ago(FRESH_DAYS)} stars:>80 fork:false"
    quarter_q = f"created:>{days_ago(QUARTER_DAYS)} stars:>800 fork:false"
    active_q = f"pushed:>{days_ago(3)} stars:>5000 fork:false"

    fresh_raw, ok1 = api_search(fresh_q, 40)
    time.sleep(2)
    quarter_raw, ok2 = api_search(quarter_q, 40)
    time.sleep(2)
    active_raw, ok3 = api_search(active_q, 20)

    prov_mark(prov, "rocket", "observed" if ok1 else "failed",
              f"{fresh_q} -> {len(fresh_raw)} 条")
    prov_mark(prov, "potential", "observed" if ok2 else "failed",
              f"{quarter_q} -> {len(quarter_raw)} 条")
    prov_mark(prov, "active", "observed" if ok3 else "failed",
              f"{active_q} -> {len(active_raw)} 条")

    # 三个查询全部失败 -> 保留上一次结果，不要用空数据覆盖好数据
    if not (ok1 or ok2 or ok3):
        print("  [ABORT] 三次查询全部失败，保留上一次数据文件", file=sys.stderr)
        return None

    fresh = enrich_age([slim(i) for i in fresh_raw])
    quarter = enrich_age([slim(i) for i in quarter_raw])
    active = enrich_age([slim(i) for i in active_raw])

    all_repos = dedupe(quarter + fresh)

    # 计算与上次快照的增量（排除今天，避免重跑时与自己比对）
    prev, prev_date = load_prev_snapshot(exclude_date=today_str())
    deltas = {}
    if prev:
        stale = []
        pm = {r["full_name"]: r["stars"] for r in prev.get("repos", [])}
        for r in all_repos:
            if r["full_name"] in pm:
                d = r["stars"] - pm[r["full_name"]]
                if d > 0:
                    deltas[r["full_name"]] = d
                elif d < 0:
                    stale.append(r["full_name"])   # 星数减少，通常是被删星或数据抖动
        if stale:
            prov["warnings"].append(
                f"{len(stale)} 个仓库星数较上次减少（可能被删星或上游抖动），这些仓库不计入增量榜")
        prov_mark(prov, "star_delta", "observed",
                  f"对比快照 {prev_date}，{len(deltas)} 个项目有正向增量")
    else:
        prov_mark(prov, "star_delta", "unavailable", "首次运行，无历史快照可比对")
        prov["warnings"].append("首次运行：暂无真实星数增量，需至少运行两次采集脚本")

    # 火箭榜速率本质是「平均吸星速率」，不是「当日增量」——必须讲清楚
    prov_mark(prov, "stars_per_day", "derived",
              "stars ÷ 存活天数，为平均速率而非真实单日增量")
    # 星数快照存在上游缓存延迟
    prov_mark(prov, "star_count", "observed",
              "GitHub Search API 返回的星数，可能有分钟级缓存延迟")

    ranked_by_delta = sorted(
        [r for r in all_repos if r["full_name"] in deltas],
        key=lambda r: -deltas[r["full_name"]],
    )

    snap = {
        "date": today_str(),
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "fresh_days": FRESH_DAYS,
        "repos": all_repos,
        "deltas": deltas,
        "prev_date": prev_date,
        "provenance": prov,
    }
    out = os.path.join(SNAP_DIR, f"{today_str()}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    print(f"      -> {out}  ({len(all_repos)} 个仓库, 增量可比 {len(deltas)} 个)")

    result = {
        "generated_at": snap["generated_at"],
        "date": snap["date"],
        "prev_date": prev_date,
        "fresh_days": FRESH_DAYS,
        "provenance": prov,
        "deltas": deltas,
        "rocket": sorted(fresh, key=lambda r: -r["stars_per_day"])[:20],
        "potential": sorted(quarter, key=lambda r: -r["stars"])[:20],
        "active": sorted(active, key=lambda r: -r["stars"])[:12],
        "movers": [dict(r, delta=deltas[r["full_name"]]) for r in ranked_by_delta[:20]],
    }
    with open(os.path.join(DATA_DIR, "github.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- 按日期归档，供看板切换历史 ----
    # 看板读取 data/history/YYYY-MM-DD.json，索引在 data/history/index.json
    hist = dict(result)
    hist["annotations"] = _load_annotations_payload(result)
    hist_path = os.path.join(HIST_DIR, f"{snap['date']}.json")
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    rebuild_history_index()
    print(f"      -> history/{snap['date']}.json")

    # ---- 生成中文解读表 ----
    try:
        from project_notes import build_annotations
        ann = build_annotations(result["rocket"] + result["potential"] + result["active"])
        with open(os.path.join(DATA_DIR, "annotations.json"), "w", encoding="utf-8") as f:
            json.dump(ann, f, ensure_ascii=False, indent=2)
        covered = sum(0 if v.get("auto") else 1 for v in ann.values())
        print(f"      -> annotations.json  ({covered}/{len(ann)} 个有精写解读，"
              f"其余按赛道规则兜底)")
    except Exception as e:                      # noqa: BLE001
        print(f"  [warn] 解读表生成失败: {e}", file=sys.stderr)

    return result


def _load_annotations_payload(result):
    """把解读表内联进历史归档，这样看历史日期也能显示人话解读"""
    try:
        from project_notes import build_annotations
        return build_annotations(result["rocket"] + result["potential"] + result["active"])
    except Exception:                           # noqa: BLE001
        return {}


def rebuild_history_index():
    """扫描 data/history/ 生成索引，含每日概览，供日期选择器使用"""
    if not os.path.isdir(HIST_DIR):
        return
    days = []
    for fn in sorted(os.listdir(HIST_DIR), reverse=True):
        if not fn.endswith(".json") or fn == "index.json":
            continue
        path = os.path.join(HIST_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                       # noqa: BLE001
            continue
        days.append({
            "date": d.get("date", fn[:-5]),
            "generated_at": d.get("generated_at", ""),
            "rocket_count": len(d.get("rocket", [])),
            "delta_count": len(d.get("deltas", {})),
            "top_repo": (d.get("rocket") or [{}])[0].get("full_name", ""),
        })
    days.sort(key=lambda x: x["date"], reverse=True)

    index = {
        "updated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(days),
        "latest": days[0]["date"] if days else "",
        "days": days,
    }
    with open(os.path.join(HIST_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"      -> history/index.json  ({len(days)} 天)")


if __name__ == "__main__":
    res = collect()
    print(f"\n生成时间: {res['generated_at']}")
    print(f"火箭榜(Top20, {FRESH_DAYS}天内):")
    for i, r in enumerate(res["rocket"][:20], 1):
        print(f"  {i:2d}. +{r['stars_per_day']:>7}/天  {r['full_name']:<45} "
              f"{r['stars']:>6}★  [{r['lang']}]")
