# -*- coding: utf-8 -*-
"""
verify_daily.py — 当日数据「真成功」三判据校验（供 CI / 手动排查使用）

背景（项目 MEMORY.md 故障手册）：
  脚本自报 8/8 成功、exit 0 并不可信。历史上多次出现 GitHub 环节「部分失败」——
  3 个查询维度挂掉 1~3 个，仓库数从 80 掉到 40 甚至 0，但 delta_count 仍非 0，
  旧判据完全看不出来。因此必须以数据文件的实际形状判断。

三判据（全绿才算真成功）：
  ① data/history/index.json 的 latest == 今天（CST）
  ② data/snapshots/<今天>.json 的 repos 数量 >= MIN_REPOS
  ③ provenance.metrics.{rocket,potential,active}.status 全为 observed

退出码：0 = 全绿；2 = 有判据不过（CI 据此触发重跑）
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
MIN_REPOS = 60          # 往常 80，<60 即认定为部分失败


def jload(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    today = datetime.now(CST).strftime("%Y-%m-%d")
    ok = True
    lines = []

    # ① index.latest
    idx = jload(os.path.join(DATA, "history", "index.json")) or {}
    latest = idx.get("latest", "")
    c1 = latest == today
    ok &= c1
    lines.append(f"{'PASS' if c1 else 'FAIL'}  ① index.latest = {latest or '(空)'}  (期望 {today})")

    # ② 快照仓库数
    snap = jload(os.path.join(DATA, "snapshots", f"{today}.json")) or {}
    repos = snap.get("repos") or {}
    n = len(repos)
    c2 = n >= MIN_REPOS
    ok &= c2
    lines.append(f"{'PASS' if c2 else 'FAIL'}  ② snapshot.repos = {n}  (期望 >= {MIN_REPOS})")

    # ③ 三维度状态
    metrics = (snap.get("provenance") or {}).get("metrics") or {}
    want = ["rocket", "potential", "active"]
    bad = []
    for k in want:
        m = metrics.get(k)
        st = m.get("status") if isinstance(m, dict) else m
        if st != "observed":
            bad.append(f"{k}={st or 'missing'}")
    c3 = not bad
    ok &= c3
    lines.append(f"{'PASS' if c3 else 'FAIL'}  ③ metrics 状态 {'；'.join(bad) if bad else 'rocket/potential/active 全 observed'}")

    # 附加信息（不计入成败，只用于日志）
    mn = jload(os.path.join(DATA, "market_news.json")) or {}
    news_n = len(mn.get("news") or [])
    lines.append(f"INFO  快讯 {news_n} 条 / auto={mn.get('auto_news_count')} manual={mn.get('manual_news_count')}")

    print("\n".join(lines))
    if not ok:
        print("\n[VERIFY] 判据未全绿 —— 需要重跑 GitHub 环节")
        return 2
    print("\n[VERIFY] 三判据全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
