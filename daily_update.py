# -*- coding: utf-8 -*-
"""
daily_update.py — 每日一键全自动更新（供定时任务调用）

流程（8 步）：
  1. 抓 GitHub 涨星数据                    (github_star_radar.py)
  2. 抓财经快讯 + 五轴评分 + 噪声压制      (news_fetcher.py → news_scoring.py)
  3. 合并到 market_news.json               —— 自动快讯 + 人工深度调研（若有）
  4. 归档到历史目录                        (archive.py)
  5. 事件聚簇：按事件而非文章聚合          (event_cluster.py)
  6. 重建跨天事件时间线                    (timeline.py)
  7. 生成周报                              (weekly_report.py)
  8. 导出 Agent 出口（md/llms.txt/RSS）    (export_feed.py)

设计原则：
  - 任一环节失败不影响其他环节（GitHub 挂了仍然更新新闻，反之亦然）
  - fail-closed：抓取全失败则保留旧文件，绝不用空数据覆盖
  - 可重复执行（幂等），同一天多次运行会覆盖当日数据
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
CST = timezone(timedelta(hours=8))

PY = sys.executable


def log(msg):
    print(msg, flush=True)


def run_script(name):
    """跑一个子脚本，返回 (ok, stdout)"""
    path = os.path.join(HERE, name)
    try:
        r = subprocess.run([PY, path], cwd=HERE, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300)
        if r.stdout:
            for line in r.stdout.strip().splitlines():
                log("    " + line)
        if r.returncode != 0:
            if r.stderr:
                log("    [stderr] " + r.stderr.strip()[:400])
            return False, r.stdout
        return True, r.stdout
    except Exception as e:
        log(f"    [EXC] {name}: {type(e).__name__} {e}")
        return False, ""


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


# ============================================================
#  自动快讯 -> market_news.news schema 映射
# ============================================================
IMP_MAP = {"bull": "利好", "bear": "利空", "neutral": "中性"}
TAG_MAP = {
    "military": "地缘",
    "economic": "宏观",
    "tech": "科技",
    "risk": "资金",
}


def to_news_item(a):
    """把一条自动快讯转成看板需要的 news 结构"""
    imp = a.get("impact", "neutral")
    sectors = a.get("sectors") or []
    src = a.get("src", "")
    t = a.get("time", "")
    return {
        "dim": a.get("dim", "risk"),
        "dimName": a.get("dimName", ""),
        "tag": TAG_MAP.get(a.get("dim"), "快讯"),
        "impact": imp,
        "confidence": "medium",
        "evidence": "auto",
        "title": a.get("title", ""),
        "body": a.get("body") or a.get("title", ""),
        # 自动快讯的 why 由规则生成，明确标注为推断
        "why": _auto_why(a),
        "sectors": sectors,
        "source": f"{src} {t}".strip(),
        "auto": True,
    }


def _auto_why(a):
    """为自动快讯生成一句「为什么重要」——规则推断，非人工判断"""
    imp = a.get("impact", "neutral")
    dim = a.get("dimName", "")
    sectors = a.get("sectors") or []
    head = {
        "bull": "偏正面，",
        "bear": "偏负面，",
        "neutral": "中性，",
    }.get(imp, "")
    if sectors:
        return f"{head}属{dim}维度，可能影响 {'、'.join(sectors)} 板块。（自动归类，仅供参考）"
    return f"{head}属{dim}维度，暂无明确受益板块映射。（自动归类，仅供参考）"


AUTO_SRC_HINT = ("东方财富", "新浪财经", "同花顺")


def _is_auto_item(n):
    """
    判断一条 news 是否为「自动抓取」产物（而非人工调研）。
    用于保证重复运行的幂等性：定时任务每天跑，不能把自动快讯越滚越多。
    判定依据（任一命中即为自动）：
      1. 显式标记 auto=True
      2. evidence == "auto"
      3. why 中含自动归类话术
      4. source 以媒体名开头（人工条目的 source 是描述性文字，非媒体名开头）
    """
    if n.get("auto") is True:
        return True
    if n.get("evidence") == "auto":
        return True
    if "自动归类" in (n.get("why") or ""):
        return True
    src = (n.get("source") or "").strip()
    if src and any(src.startswith(h) for h in AUTO_SRC_HINT):
        return True
    return False


def _auto_only(auto_items, auto, today, wd, prov_extra=None):
    """纯自动模式：无人工深度研判时的输出结构"""
    bull = sum(1 for n in auto_items if n["impact"] == "bull")
    bear = sum(1 for n in auto_items if n["impact"] == "bear")
    prov_auto = (auto or {}).get("provenance") or {}
    metrics = {
        "news_facts": {
            "status": "observed",
            "detail": f"接口实测可得 {len(auto_items)} 条；来源 "
                      + "/".join(prov_auto.get("sources_ok", [])),
        },
        "classification": {
            "status": "derived",
            "detail": "四维归类、利好利空、受益板块均由关键词规则推断，非人工审核",
        },
        "impact_judgement": {
            "status": "derived",
            "detail": "本页为自动汇总，不含人工深度研判与多空评分结论",
        },
    }
    if prov_extra:
        metrics["merge_note"] = {"status": "observed", "detail": prov_extra.get("note", "")}
    return {
        "date": today,
        "weekday": f"{wd} · 自动抓取模式",
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "marketClosed": datetime.now(CST).weekday() >= 5,
        "news": auto_items,
        "auto_news_count": len(auto_items),
        "manual_news_count": 0,
        "provenance": {
            "source": prov_auto.get("source", "公开财经快讯接口"),
            "source_type": prov_auto.get("source_type", "public_news_api"),
            "fetched_at": prov_auto.get("fetched_at", ""),
            "auth": "none",
            "metrics": metrics,
            "warnings": [
                "本页数据由脚本自动抓取与规则分类生成，未经人工审核，仅供信息聚合参考",
                "自动模式下不含「决策仪表盘」与「风险与机会」深度分析",
                f"当前情绪统计：利好 {bull} / 利空 {bear} / 中性 {len(auto_items)-bull-bear}"
                "（规则判定偏乐观，请结合原文判断）",
            ],
        },
    }


def merge_market_news(auto, manual):
    """
    合并自动快讯与人工调研。
    - manual 存在深度内容（conclusion / riskOpportunity）时，人工内容优先
    - 新闻条目：人工的置顶（更经筛选），自动的补齐数量
    """
    now = datetime.now(CST)
    today = now.strftime("%Y-%m-%d")
    wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]

    auto_items = [to_news_item(a) for a in (auto.get("news") or [])] if auto else []

    if manual and manual.get("date") == today:
        # 人工当日调研：人工条目在前，自动快讯补充
        base = dict(manual)
        all_news = manual.get("news") or []
        # 幂等关键：剔除「上一轮自动写入的」条目，只保留真人工内容。
        # 否则定时任务每天运行会把自动快讯误当人工内容，越滚越多。
        man_news = [n for n in all_news if not _is_auto_item(n)]

        # 若一条真人工内容都没有（说明本日只有自动数据），退回纯自动模式
        if not man_news:
            return _auto_only(auto_items, auto, today, wd, prov_extra={
                "note": "上一轮为自动数据，本轮未检测到人工调研内容，继续以自动模式呈现",
            })

        seen = set(n.get("title", "")[:16] for n in man_news)
        extra = [n for n in auto_items if n["title"][:16] not in seen]
        base["news"] = man_news + extra
        base["auto_news_count"] = len(extra)
        base["manual_news_count"] = len(man_news)
        # 溯源：合并双方
        prov = dict(base.get("provenance") or {})
        met = dict(prov.get("metrics") or {})
        met["auto_news"] = {
            "status": "observed",
            "detail": f"自动抓取 {len(auto_items)} 条快讯"
                      + (f"，来源 {'/'.join(auto['provenance'].get('sources_ok', []))}"
                         if auto and auto.get("provenance") else ""),
        }
        met["manual_review"] = {
            "status": "observed",
            "detail": f"人工深度调研 {len(man_news)} 条（含结论与风险机会）",
        }
        prov["metrics"] = met
        base["provenance"] = prov
        return base

    # 无人工调研（或无当日人工调研）：纯自动版
    return _auto_only(auto_items, auto, today, wd)


def main():
    started = datetime.now(CST)
    log("=" * 60)
    log(f"  每日自动更新 · {started.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    results = {}

    log("\n[1/8] 抓取 GitHub 涨星数据 ...")
    results["github"] = run_script("github_star_radar.py")

    log("\n[2/8] 抓取财经快讯（含五轴评分与噪声压制）...")
    results["news"] = run_script("news_fetcher.py")

    log("\n[3/8] 合并 A股要闻 ...")
    auto = load(os.path.join(DATA_DIR, "auto_news.json"))
    manual = load(os.path.join(DATA_DIR, "market_news.json"))
    if auto is None and manual is None:
        log("    [ABORT] 自动与人工数据都不可用，保留原文件")
    else:
        merged = merge_market_news(auto, manual)
        save(os.path.join(DATA_DIR, "market_news.json"), merged)
        log(f"    -> market_news.json "
            f"({len(merged.get('news', []))} 条；"
            f"人工 {merged.get('manual_news_count', 0)} + 自动 {merged.get('auto_news_count', len(merged.get('news', [])))}）")
        results["merge"] = (True, "")

    log("\n[4/8] 归档到历史目录 ...")
    results["archive"] = run_script("archive.py")

    log("\n[5/8] 事件聚簇（按事件而非文章聚合）...")
    results["cluster"] = run_script("event_cluster.py")

    log("\n[6/8] 重建跨天事件时间线 ...")
    results["timeline"] = run_script("timeline.py")

    log("\n[7/8] 生成周报 ...")
    results["weekly"] = run_script("weekly_report.py")

    log("\n[8/8] 导出 Agent 出口（Markdown / llms.txt / RSS）...")
    results["feed"] = run_script("export_feed.py")

    log("\n" + "=" * 60)
    ok = sum(1 for v in results.values() if v[0])
    log(f"  完成：{ok}/{len(results)} 个环节成功")
    for k, v in results.items():
        log(f"    {'OK  ' if v[0] else 'FAIL'} {k}")
    log("=" * 60)

    # 允许部分降级：GitHub 挂了仍应更新新闻，反之亦然；但多数环节失败即视为异常
    return 0 if ok >= 4 else 1


if __name__ == "__main__":
    sys.exit(main())
