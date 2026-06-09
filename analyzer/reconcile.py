"""reconcile.py：把 visible 子集与 widgets/summary.json 对账，给出提示徽标信息。

口径：数据单元用全部记录(1199)；Allure 页面默认只展示 visible(hidden=false) 子集，
summary.json 的 statistic.total 即 visible 数(本报告 411)。两者差异属正常（合并报告里
被去重/隐藏的历史记录），此处仅做一致性提示，不影响分析口径。
"""
import json
import os


def reconcile(records, report_dir, load_stats):
    summary_path = os.path.join(report_dir, "widgets", "summary.json")
    visible_records = sum(1 for r in records if not r.hidden)
    result = {
        "records_total": len(records),
        "visible_records": visible_records,
        "hidden_records": len(records) - visible_records,
        "summary_json_found": False,
        "summary_total": None,
        "summary_statistic": None,
        "match": None,
        "note": "",
    }
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        stat = data.get("statistic", {}) or {}
        result["summary_json_found"] = True
        result["summary_total"] = stat.get("total")
        result["summary_statistic"] = stat
        result["match"] = (stat.get("total") == visible_records)
    except Exception as e:  # noqa: BLE001
        result["note"] = "未读到 summary.json(%s)，跳过对账。" % e
        return result

    if result["match"]:
        result["note"] = ("visible 记录 %d 与 summary.json total %d 一致；"
                          "另有 hidden 记录 %d，分析口径采用全部 %d 条。" % (
                              visible_records, result["summary_total"],
                              result["hidden_records"], len(records)))
    else:
        result["note"] = ("注意：visible 记录 %d 与 summary.json total %s 不一致，请核查。" % (
            visible_records, result["summary_total"]))
    return result
