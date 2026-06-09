"""markdown_reporter：生成精炼的 summary.md 摘要（总览 + 三视角 + component + 不一致 + 失败）。"""
import os


def _pct(x):
    return "%.1f%%" % (x * 100)


def _summary_md(title, rows, dim):
    lines = ["#### %s" % title, "", "| %s | Pass | Fail | Total | Pass Rate |" % dim,
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %d | %d | %d | %s |" % (
            r["name"], r["pass"], r["fail"], r["total"], _pct(r["pass_rate"])))
    lines.append("")
    return lines


def write(analysis, reconcile_result, out_dir):
    ov = analysis["overview"]
    L = []
    L.append("# 分析龙虾 · 测试执行分析摘要")
    L.append("")
    m = analysis.get("meta", {})
    L.append("- 报告：**%s**" % m.get("report_name", "Allure Report"))
    L.append("- 生成时间：%s" % m.get("generated_at", ""))
    L.append("- 数据单元：全部 scenario 记录（host × scenario）；对账 %s visible / %s total" % (
        reconcile_result.get("visible_records"), reconcile_result.get("records_total")))
    L.append("")

    L.append("## 总览")
    L.append("")
    L.append("| 粒度 | Total | Pass | Fail | Pass Rate |")
    L.append("|---|---|---|---|---|")
    L.append("| Scenario（每条记录=1 scenario × 1 host） | %d | %d | %d | %s |" % (
        ov["scenario"]["total"], ov["scenario"]["pass"], ov["scenario"]["fail"], _pct(ov["scenario"]["pass_rate"])))
    L.append("| Case（每条记录=1 case × 1 host） | %d | %d | %d | %s |" % (
        ov["case"]["total"], ov["case"]["pass"], ov["case"]["fail"], _pct(ov["case"]["pass_rate"])))
    uc = ov.get("unique_case")
    if uc:
        L.append("| 唯一 Case 数（去重，仅参考） | %d | %d | %d | %s |" % (
            uc["total"], uc["pass"], uc["fail"], _pct(uc["pass_rate"])))
    L.append("")
    L.append("> 状态口径：not_passed = failed + broken，对外仅 Pass / Fail。原始分布：%s" %
             ", ".join("%s=%d" % (k, v) for k, v in ov["status_breakdown"].items()))
    L.append("> 计数口径：**Case 视图按 (case, host) 行计数** —— 同一条 case 在 N 台机器上跑就贡献 N 条记录。")
    L.append("")

    L.append("## Case Result Summary（按 (case, host) 行）")
    L.append("")
    L += _summary_md("按 Owner", analysis["case_summary"]["owner"], "Owner")
    L += _summary_md("按 Component（来自 parentSuite，单一归属）", analysis["case_summary"]["component"], "Component")
    L += _summary_md("按 Device（host）", analysis["case_summary"]["device"], "Device")

    L.append("## Step Result Summary（按 scenario 记录）")
    L.append("")
    L += _summary_md("按 Owner", analysis["scenario_summary"]["owner"], "Owner")
    L += _summary_md("按 Component", analysis["scenario_summary"]["component"], "Component")
    L += _summary_md("按 Device", analysis["scenario_summary"]["device"], "Device")

    if analysis["inconsistent"]:
        L.append("## 跨机结果不一致的 Case（%d）" % len(analysis["inconsistent"]))
        L.append("")
        for r in analysis["inconsistent"]:
            hv = "; ".join("%s=%s" % (h, v) for h, v in r["hosts"].items())
            L.append("- **%s**：%s" % (r["case_key"], hv))
        L.append("")

    if analysis["failures"]:
        L.append("## 失败明细 Top（共 %d 条）" % len(analysis["failures"]))
        L.append("")
        L.append("| Case | Device | Scenario | Status | Message |")
        L.append("|---|---|---|---|---|")
        for r in analysis["failures"][:30]:
            msg = (r["status_message"] or "").replace("\n", " ").replace("|", "/")[:80]
            L.append("| %s | %s | %s | %s | %s |" % (
                r["case_key"], r["host"], r["scenario"][:40], r["status"], msg))
        L.append("")

    path = os.path.join(out_dir, "summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("[markdown] 已写出 %s" % path)
    return path
