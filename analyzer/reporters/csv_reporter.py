"""csv_reporter：把分析结果导出为多个 CSV 文件（utf-8-sig，Excel 友好）。"""
import csv
import os


def _pct(x):
    return "%.2f%%" % (x * 100)


def _write(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def write(analysis, reconcile_result, out_dir):
    csv_dir = os.path.join(out_dir, "csv")
    os.makedirs(csv_dir, exist_ok=True)
    written = []

    def emit(name, header, rows):
        p = os.path.join(csv_dir, name)
        _write(p, header, rows)
        written.append(p)

    # 总览
    ov = analysis["overview"]
    emit("overview.csv", ["grain", "total", "pass", "fail", "pass_rate"], [
        ["scenario", ov["scenario"]["total"], ov["scenario"]["pass"],
         ov["scenario"]["fail"], _pct(ov["scenario"]["pass_rate"])],
        ["case", ov["case"]["total"], ov["case"]["pass"],
         ov["case"]["fail"], _pct(ov["case"]["pass_rate"])],
    ])

    # Case Result（case×host）
    emit("case_result.csv",
         ["case_key", "jira_url", "owners", "components", "host", "host_display",
          "verdict", "n_pass", "n_total"],
         [[r["case_key"], r["jira_url"], "|".join(r["owners"]), "|".join(r["components"]),
           r["host"], r["host_display"], r["verdict"], r["n_pass"], r["n_total"]]
          for r in analysis["case_host_rows"]])

    # Case / Step 三视角汇总
    for grain, key in (("case", "case_summary"), ("step", "scenario_summary")):
        for dim in ("owner", "component", "device"):
            emit("%s_summary_%s.csv" % (grain, dim),
                 [dim, "pass", "fail", "total", "pass_rate"],
                 [[r["name"], r["pass"], r["fail"], r["total"], _pct(r["pass_rate"])]
                  for r in analysis[key][dim]])

    # host × owner 矩阵
    mx = analysis["matrix"]
    header = ["host\\owner"] + mx["owners"]
    rows = []
    for h in mx["hosts"]:
        row = [h]
        for o in mx["owners"]:
            c = mx["cells"].get("%s||%s" % (h, o))
            row.append("%d/%d" % (c["pass"], c["total"]) if c else "")
        rows.append(row)
    emit("matrix_host_owner.csv", header, rows)

    # 失败明细
    emit("failures.csv",
         ["case_key", "host", "scenario", "status", "severity", "status_message"],
         [[r["case_key"], r["host"], r["scenario"], r["status"], r["severity"],
           (r["status_message"] or "").replace("\n", " ")[:500]]
          for r in analysis["failures"]])

    # TopN
    emit("top_duration.csv", ["case_key", "host", "scenario", "duration_ms"],
         [[r["case_key"], r["host"], r["scenario"], r["duration_ms"]]
          for r in analysis["top_duration"]])
    emit("top_retries.csv", ["case_key", "host", "scenario", "retries_count"],
         [[r["case_key"], r["host"], r["scenario"], r["retries_count"]]
          for r in analysis["top_retries"]])

    # 跨机不一致
    emit("inconsistent_cases.csv", ["case_key", "jira_url", "host_verdicts"],
         [[r["case_key"], r["jira_url"],
           "; ".join("%s=%s" % (h, v) for h, v in r["hosts"].items())]
          for r in analysis["inconsistent"]])

    # UNLINKED & key_source
    emit("unlinked.csv", ["scenario", "host", "suite"],
         [[r["scenario"], r["host"], ""] for r in analysis["unlinked"]])
    emit("key_source_dist.csv", ["key_source", "count"],
         [[k, v] for k, v in analysis["key_source_dist"].items()])

    # 对账
    rr = reconcile_result
    emit("reconcile.csv", ["metric", "value"], [
        ["records_total", rr["records_total"]],
        ["visible_records", rr["visible_records"]],
        ["hidden_records", rr["hidden_records"]],
        ["summary_json_total", rr["summary_total"]],
        ["match", rr["match"]],
        ["note", rr["note"]],
    ])

    print("[csv] 已写出 %d 个 CSV 到 %s" % (len(written), csv_dir))
    return written
