# -*- coding: utf-8 -*-
"""
purge_cdn.py — 推送到 GitHub 后刷新 jsDelivr 缓存

为什么需要：jsDelivr 对 branch（@main）引用默认缓存 12 小时，
不主动清缓存的话，早上 08:00 生成的新数据可能要等到中午才生效。
purge.jsdelivr.net 是官方提供的按文件清理接口，几秒内生效。

用法：
  python tools/purge_cdn.py <owner> <repo>
环境变量：
  GITHUB_TOKEN（可选，仅用于提高 purge 接口的配额）
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 页面每次打开都会读的「热点文件」，必须清
HOT = [
    "data/history/index.json",
    "data/github.json",
    "data/market_news.json",
    "data/events.json",
    "data/annotations.json",
    "data/timeline.json",
    "data/weekly/index.json",
    "data/calibration/report.json",
    "data/feed/latest.md",
    "data/feed/events.md",
    "data/feed/llms.txt",
    "data/feed/feed.xml",
]


def purge(owner, repo, path, token=""):
    url = f"https://purge.jsdelivr.net/gh/{owner}/{repo}@main/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "intel-purge/1.0"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8", "replace")
        ok = '"status":"finished"' in body.replace(" ", "") or r.status == 200
        return ok
    except Exception as e:                      # noqa: BLE001
        print(f"  [warn] purge 失败 {path}: {type(e).__name__} {e}")
        return False


def main():
    if len(sys.argv) < 3:
        print("用法: python tools/purge_cdn.py <owner> <repo>")
        return 1
    owner, repo = sys.argv[1], sys.argv[2]
    token = os.environ.get("GITHUB_TOKEN", "").strip()

    today = datetime.now(CST).strftime("%Y-%m-%d")
    paths = list(HOT) + [
        f"data/history/{today}.json",
        f"data/news_history/{today}.json",
        f"data/event_history/{today}.json",
    ]

    okn = 0
    for p in paths:
        if purge(owner, repo, p, token):
            okn += 1
            print(f"  purged {p}")
        else:
            print(f"  SKIP   {p}")
    print(f"\n[purge] {okn}/{len(paths)} 成功（失败不影响数据正确性，最多延迟缓存刷新）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
