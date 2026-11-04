# -*- coding: utf-8 -*-
"""
归档脚本 —— 把当前工作数据按日期存入历史目录，供看板日期切换使用

用法：
    python archive.py            # 归档今天
    python archive.py 2026-09-30 # 归档指定日期

看板读取：
    data/history/YYYY-MM-DD.json       —— GitHub 榜单单日归档
    data/news_history/YYYY-MM-DD.json  —— A股要闻单日归档
    data/history/index.json            —— 日期索引（由 github_star_radar.py 重建）
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
NEWS_HIST_DIR = os.path.join(DATA_DIR, "news_history")
CST = timezone(timedelta(hours=8))


def load(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:                      # noqa: BLE001
        print(f"  [warn] 读取失败 {path}: {e}")
        return None


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def archive(date=None):
    date = date or datetime.now(CST).strftime("%Y-%m-%d")
    print(f"归档日期：{date}")

    gh = load(os.path.join(DATA_DIR, "github.json"))
    if gh:
        if gh.get("date") != date:
            print(f"  [warn] github.json 日期为 {gh.get('date')}，与目标 {date} 不一致")
        # 内联中文解读，这样看历史日期也能显示人话说明
        if not gh.get("annotations"):
            notes = load(os.path.join(DATA_DIR, "annotations.json"))
            if notes:
                gh["annotations"] = notes
            else:
                try:
                    from project_notes import build_annotations
                    gh["annotations"] = build_annotations(
                        gh.get("rocket", []) + gh.get("potential", []) + gh.get("active", []))
                except Exception as e:          # noqa: BLE001
                    print(f"  [warn] 解读表内联失败: {e}")
        save(os.path.join(HIST_DIR, f"{date}.json"), gh)
        print(f"  -> history/{date}.json  (榜单 {len(gh.get('rocket', []))} 条, "
              f"解读 {len(gh.get('annotations', {}))} 条)")
    else:
        print("  [skip] 未找到 github.json")

    mk = load(os.path.join(DATA_DIR, "market_news.json"))
    if mk:
        if mk.get("date") != date:
            print(f"  [warn] market_news.json 日期为 {mk.get('date')}，与目标 {date} 不一致")
        save(os.path.join(NEWS_HIST_DIR, f"{date}.json"), mk)
        print(f"  -> news_history/{date}.json  (要闻 {len(mk.get('news', []))} 条)")
    else:
        print("  [skip] 未找到 market_news.json")

    # 重建索引
    try:
        from github_star_radar import rebuild_history_index
        rebuild_history_index()
    except Exception as e:                      # noqa: BLE001
        print(f"  [warn] 索引重建失败: {e}")


if __name__ == "__main__":
    archive(sys.argv[1] if len(sys.argv) > 1 else None)
