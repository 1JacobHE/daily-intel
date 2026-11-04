#!/usr/bin/env bash
# ci_update.sh — GitHub Actions 内的「抓取 + 自愈重试」包装
#
# 为什么需要重试：GitHub Search API 未认证时限流 10 req/min，
# 三个查询维度里挂掉一个就会导致仓库数腰斩（80→40），但脚本仍 exit 0。
# 历史踩坑记录见项目 MEMORY.md「运行期故障手册」。
# 带 token 后限额提到 30 req/min，配合这里的退避重试，可基本无人值守。
set -uo pipefail
cd "$(dirname "$0")/.."

echo "===== [1/3] 首轮抓取 ====="
python daily_update.py || echo "[warn] daily_update 返回非 0，继续做数据校验"

echo "===== [2/3] 三判据校验 ====="
if python tools/verify_daily.py; then
  echo "[ok] 首轮即通过，无需补跑"
  exit 0
fi

echo "===== [3/3] 进入自愈重试 ====="
for i in 1 2 3; do
  echo "--- 补跑第 $i 次（先等 75s 让限流窗口滚动）---"
  sleep 75
  python github_star_radar.py || true
  python archive.py           || true
  python event_cluster.py     || true
  python timeline.py          || true
  python weekly_report.py     || true
  python export_feed.py       || true

  if python tools/verify_daily.py; then
    echo "[ok] 补跑第 $i 次通过"
    exit 0
  fi
done

echo "[FAIL] 三次补跑后仍未通过三判据"
exit 1
