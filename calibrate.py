# -*- coding: utf-8 -*-
"""
calibrate.py — 规则校准闭环

为什么需要它：
  news_scoring.py 里的关键词表、五轴打分、门槛数值，都是「凭经验写的」，
  从来没有被验证过准不准。这个脚本用人工标注集把它们测一遍，
  输出准确率 / 查准率 / 查全率，并列出错例 —— 看错例才知道该改哪条规则。

方法借鉴 AIHOT（KKKKhazix/AIHOT）的评测脚本：
  - 标注集分 select / reject / either 三类，either 是「难例」（两可）
    多放难例才有区分度：一眼就能判断的放多了，准确率会虚高
  - 门槛扫描：把门槛从 40 扫到 90，看哪个位置指标最好
  - 分开发集 / 留出集，防止把规则调成「只会做这几道题」

诚实声明：
  这是「规则判定」与「人工标注」的一致性评估，不是绝对准确率 ——
  人工标注本身也有主观性（标注者：本 AI 助手，标准见 gold.jsonl 的 note 字段）。
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA_DIR = os.path.join(HERE, "data")
CAL_DIR = os.path.join(DATA_DIR, "calibration")


def load_gold(path=None):
    p = path or os.path.join(CAL_DIR, "gold.jsonl")
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_samples(path=None):
    p = path or os.path.join(CAL_DIR, "samples.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["samples"]


def _key(t):
    return "".join((t or "").split())[:20]


def prepare(samples):
    """给原始样本补上分类字段（复现 news_fetcher 的处理链）"""
    from news_fetcher import classify_dim, judge_impact, match_sectors, DIMS
    for it in samples:
        text = it.get("title", "") + " " + (it.get("body") or "")
        dim, _ = classify_dim(text)
        impact, _, _ = judge_impact(text)
        it["dim"] = dim
        it["dimName"] = DIMS[dim]["name"]
        it["impact"] = impact
        it["sectors"] = match_sectors(text)
    return samples


def build_units(samples, gold, thr_override=None, use_cluster=True):
    """
    把样本整理成「评测单元」。
    use_cluster=True 时先做事件聚簇：同一件事的多条报道算一个单元
    —— 否则「WTI原油跌4% / 跌3%」这种同事件的两条会被当成两个独立样本，
     其中一条必然被误判为「重复条目误选」，而它在真实流水线里早就被合并了。
    组标签取「最宽松优先」：组内只要有一条值得看，这个事件就值得进看板。
    """
    from news_scoring import score_item

    gold_map = {_key(g["title"]): g for g in gold}
    scored = []
    for it in samples:
        g = gold_map.get(_key(it.get("title")))
        if not g:
            continue
        sc = score_item(it)
        rec = {
            "title": it.get("title", ""), "gold": g, "sc": sc,
            "thr": thr_override if thr_override is not None else sc["threshold"],
        }
        rec["passed"] = (sc["sum_score"] >= 2 * rec["thr"]) and not sc.get("hard_drops")
        scored.append(rec)

    if not use_cluster:
        return [{**r, "titles": [r["title"]], "group_size": 1} for r in scored]

    from event_cluster import cluster
    title_map = {_key(r["title"]): r for r in scored}
    events, _ = cluster([{
        "title": r["title"], "body": "", "src": "", "time": "", "final_score": r["sc"]["final_score"],
    } for r in scored])

    units, used = [], set()
    for e in events:
        ms = []
        for m in e["members"]:
            r = title_map.get(_key(m["title"]))
            if r and id(r) not in used:
                ms.append(r)
                used.add(id(r))
        if not ms:
            continue
        labels = [m["gold"]["label"] for m in ms]
        lab = "select" if "select" in labels else ("either" if "either" in labels else "reject")
        best = max(ms, key=lambda x: x["sc"]["final_score"])
        units.append({**best, "label": lab, "titles": [m["title"] for m in ms],
                      "group_size": len(ms),
                      "group_labels": labels})
    # 兜底：未被聚簇覆盖的（理论上不会发生）
    for r in scored:
        if id(r) not in used:
            units.append({**r, "label": r["gold"]["label"], "titles": [r["title"]],
                          "group_size": 1, "group_labels": [r["gold"]["label"]]})
    return units


def eval_once(samples, gold, thr_override=None, use_cluster=True):
    """
    跑一次评测，返回 (metrics, errors, either_rows)
    thr_override：把所有等级的门槛统一设为该值（用于门槛扫描）
    use_cluster：以「事件」而非「文章」为评测单元
    """
    units = build_units(samples, gold, thr_override, use_cluster)

    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "either_pass": 0, "either_reject": 0}
    errors, either_rows = [], []

    for u in units:
        sc = u["sc"]
        passed = u["passed"]
        label = u["label"]
        row = {
            "title": u["title"], "label": label,
            "score": sc["final_score"], "raw": sc.get("raw_score"),
            "passed": passed, "threshold": u["thr"], "tier": sc["tier"],
            "ctype": sc["ctypeName"], "noise": sc["noise_notes"],
            "hard": sc.get("hard_drops") or [],
            "note": u["gold"].get("note", ""),
            "group_size": u.get("group_size", 1),
            "titles": u.get("titles", [u["title"]]),
        }
        if label == "select":
            if passed:
                counts["tp"] += 1
            else:
                counts["fn"] += 1
                errors.append(dict(row, kind="漏选（该进没进）"))
        elif label == "reject":
            if passed:
                counts["fp"] += 1
                errors.append(dict(row, kind="误选（不该进却进了）"))
            else:
                counts["tn"] += 1
        else:
            if passed:
                counts["either_pass"] += 1
            else:
                counts["either_reject"] += 1
            either_rows.append(row)

    tp, fn, fp, tn = counts["tp"], counts["fn"], counts["fp"], counts["tn"]
    n = tp + fn + fp + tn
    matched = len(units)

    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    report = counts

    metrics = {
        "matched": matched, "n_judged": n, "unit": "event" if use_cluster else "article",
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "accuracy": round(acc, 4), "precision": round(prec, 4),
        "recall": round(rec, 4), "f1": round(f1, 4),
        "either_pass": counts["either_pass"],
        "either_reject": counts["either_reject"],
        "pass_rate": round((tp + fp + counts["either_pass"]) / matched, 3) if matched else 0,
    }
    return metrics, errors, either_rows

    tp = report["tp"]["select"]
    fn = report["fn"]["select"]
    fp = report["fp"]["reject"]
    tn = report["tn"]["reject"]
    n = tp + fn + fp + tn

    acc = (tp + tn) / n if n else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    metrics = {
        "matched": matched, "n_judged": n,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "accuracy": round(acc, 4), "precision": round(prec, 4),
        "recall": round(rec, 4), "f1": round(f1, 4),
        "either_pass": report["either_pass"]["either"],
        "either_reject": report["either_reject"]["either"],
        "pass_rate": round((tp + fp + report["either_pass"]["either"]) / matched, 3)
        if matched else 0,
    }
    return metrics, errors, either_rows


def scan(samples, gold, lo=40, hi=90, step=2):
    """门槛扫描：把门槛统一设为 v（覆盖各等级），看指标如何变化"""
    rows = []
    for v in range(lo, hi + 1, step):
        m, _e, _r = eval_once(samples, gold, thr_override=v)
        rows.append({"threshold": v, "accuracy": m["accuracy"], "precision": m["precision"],
                     "recall": m["recall"], "f1": m["f1"], "pass": m["pass_rate"]})
    best = max(rows, key=lambda x: (x["f1"], x["accuracy"]))
    return rows, best


def split_dev_holdout(samples, gold, ratio=0.7):
    """按 id 排序切分，避免按分数排序造成分布偏移"""
    gold_map = {_key(g["title"]): g for g in gold}
    ok = [s for s in samples if _key(s.get("title")) in gold_map]
    ok.sort(key=lambda x: x.get("id", ""))
    cut = int(len(ok) * ratio)
    return ok[:cut], ok[cut:]


def main():
    gold = load_gold()
    samples = load_samples()
    samples = prepare(samples)

    print("=" * 66)
    print("  规则校准报告 · 新闻筛选规则 vs 人工标注")
    print("=" * 66)
    print(f"  标注集：{len(gold)} 条  "
          f"（select {sum(1 for g in gold if g['label']=='select')} / "
          f"reject {sum(1 for g in gold if g['label']=='reject')} / "
          f"either {sum(1 for g in gold if g['label']=='either')}）")
    print()

    metrics, errors, either_rows = eval_once(samples, gold)
    print("【当前门槛下的表现】")
    print(f"  评测口径：以「事件」为单元（同一件事的多条报道先合并），"
          f"共 {metrics['matched']} 个事件")
    print(f"  可判定事件 {metrics['n_judged']} 个"
          f"（select/reject 二分类，either 不计入）")
    print(f"  准确率 {metrics['accuracy']*100:.1f}%  "
          f"查准率 {metrics['precision']*100:.1f}%  "
          f"查全率 {metrics['recall']*100:.1f}%  "
          f"F1 {metrics['f1']*100:.1f}%")
    print(f"  混淆矩阵  TP {metrics['tp']} / FP {metrics['fp']} / "
          f"TN {metrics['tn']} / FN {metrics['fn']}")
    print(f"  入选率 {metrics['pass_rate']*100:.0f}%"
          f"（含 either 中被判入选 {metrics['either_pass']} 条）")
    print()

    # 分集验证
    dev, hold = split_dev_holdout(samples, gold)
    if dev and hold:
        md, _, _ = eval_once(dev, gold)
        mh, _, _ = eval_once(hold, gold)
        print("【分集验证】（防止规则被调成「只会做这几道题」）")
        print(f"  开发集 {md['n_judged']} 条：准确率 {md['accuracy']*100:.1f}%  "
              f"F1 {md['f1']*100:.1f}%")
        print(f"  留出集 {mh['n_judged']} 条：准确率 {mh['accuracy']*100:.1f}%  "
              f"F1 {mh['f1']*100:.1f}%")
        gap = abs(md["accuracy"] - mh["accuracy"])
        print(f"  两集准确率差 {gap*100:.1f} 个百分点"
              f"{'（差异偏大，规则可能过拟合开发集）' if gap > 0.15 else '（差异正常）'}")
        print()

    # 门槛扫描
    rows, best = scan(samples, gold)
    print("【门槛扫描】（统一门槛 40→90）")
    print("   门槛   准确率  查准率  查全率    F1    入选率")
    for r in rows:
        mark = " ★" if r["threshold"] == best["threshold"] else ""
        print(f"   {r['threshold']:4d}   {r['accuracy']*100:5.1f}%  "
              f"{r['precision']*100:5.1f}%  {r['recall']*100:5.1f}%  "
              f"{r['f1']*100:5.1f}%  {r['pass']*100:5.0f}%{mark}")
    print(f"  最优门槛 {best['threshold']}（按 F1）："
          f"准确率 {best['accuracy']*100:.1f}%，F1 {best['f1']*100:.1f}%")
    print()

    # 错例 —— 最有价值的部分
    print(f"【错例清单】共 {len(errors)} 条，看这些才能知道该改哪条规则")
    for e in sorted(errors, key=lambda x: x["kind"]):
        print(f"  [{e['kind']}] {e['score']:.0f}分/{e['tier']}/{e['ctype']}"
              f"（门槛 {e['threshold']}）")
        print(f"      {e['title'][:52]}")
        print(f"      标注理由：{e['note']}")
        if e.get("hard"):
            print(f"      ⛔ 硬淘汰：{e['hard']}")
        if e["noise"]:
            print(f"      轴级压制：{e['noise']}")
    print()

    # 难例表现
    print(f"【难例（either）表现】{metrics['either_pass'] + metrics['either_reject']} 条"
          f" → 判入选 {metrics['either_pass']} / 判不入选 {metrics['either_reject']}")
    print()

    # 过拟合警示 —— 必须说清楚，否则 100% 会被误读成「规则很准」
    warn = (f"⚠️  过拟合警示：以上规则是在本标注集（{len(gold)} 条）上逐步调优得到的。"
            f"主指标的 {metrics['accuracy']*100:.1f}% 属于「训练集表现」，不代表真实准确率。"
            + (f"留出集（{mh['n_judged']} 个事件）的 {mh['accuracy']*100:.1f}% 更有参考价值。"
               if dev and hold else "")
            + f" 样本量偏小（可判定事件 {metrics['n_judged']} 个），"
              f"建议持续扩充标注集后重新评估。")
    print(warn)

    # 落盘
    out = {
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        "gold_size": len(gold),
        "metrics": metrics,
        "dev": {"accuracy": md["accuracy"], "f1": md["f1"], "n": md["n_judged"]} if dev and hold else None,
        "holdout": {"accuracy": mh["accuracy"], "f1": mh["f1"], "n": mh["n_judged"]} if dev and hold else None,
        "threshold_scan": rows,
        "best_threshold": best["threshold"],
        "errors": errors,
        "holdout_note": ("主指标为训练集表现（规则在本标注集上调优），"
                         "留出集表现更有参考价值"),
        "note": "规则判定与人工标注的一致性评估，非绝对准确率",
    }
    os.makedirs(CAL_DIR, exist_ok=True)
    with open(os.path.join(CAL_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("  报告已写入 data/calibration/report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
