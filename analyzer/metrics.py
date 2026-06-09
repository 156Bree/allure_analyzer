"""metrics.py：把富化后的 records 聚合成一个可直接内嵌 HTML 的分析结果 dict。

口径（**Case 视图统一按 (case, host) 行计数**）：
- scenario 级 = 全部记录（本报告 1199）；scenario 三视角(owner/component/device) 也按记录计数。
- case 级二元判定 unit = (case, host)：
    该 case 在该机器上跑的所有 scenario 全 passed 才记 Pass，否则 Fail。
    一条 case 在 N 台机器上跑就贡献 N 条计数行（owner/component 多归属时按行的多归属累加）。
- overview.case 也基于 (case, host) 行：total = 行数，pass = verdict==Pass 行数。
- component 来自 parentSuite 映射，**单一归属**（component 求和 == 总行数；未映射 → (no-component)）；
  owner 仍可能 0 或 1 个（不臆造）。
- 每个汇总单元附带下钻 filter，供 HTML 超链接点击后过滤明细。
"""
import collections


def _rate(passed, total):
    return round(passed / total, 4) if total else 0.0


def _counts(passed, total):
    return {"pass": passed, "fail": total - passed, "total": total,
            "pass_rate": _rate(passed, total)}


def build_analysis(records, config, report_meta):
    no_owner = (config.get("owner", {}) or {}).get("no_owner_label", "(no-owner)")
    no_comp = (config.get("component", {}) or {}).get("no_component_label", "(no-component)")
    unlinked = (config.get("case_key", {}) or {}).get("unlinked_label", "UNLINKED")
    top_n = int(config.get("top_n", 10))

    # ---------- 扁平 scenario 行（供 Step 视图 + Case 展开） ----------
    scenario_rows = []
    for i, r in enumerate(records):
        scenario_rows.append({
            "idx": i,
            "scenario": r.name,
            "case_key": r.case_key,
            "jira_url": r.jira_url,
            "owners": r.owners or [],
            "components": r.components or [],
            "host": r.host,
            "host_display": r.host_display,
            "status": r.status,
            "status_label": r.status_label,
            "is_pass": r.is_pass,
            "duration_ms": r.duration_ms,
            "retries_count": r.retries_count,
            "severity": r.severity,
            "status_message": r.status_message,
        })

    # ---------- case 索引 ----------
    by_case = collections.defaultdict(list)
    for r in records:
        by_case[r.case_key].append(r)

    case_global = {}     # case_key -> bool(全局 PASS)
    case_owners = {}     # case_key -> [owners]
    case_comps = {}      # case_key -> [components]
    case_jira = {}
    for ck, rs in by_case.items():
        case_global[ck] = all(x.is_pass for x in rs)
        ow = []
        for x in rs:
            for o in x.owners:
                if o not in ow:
                    ow.append(o)
        case_owners[ck] = ow
        cps = []
        for x in rs:
            for c in x.components:
                if c not in cps:
                    cps.append(c)
        case_comps[ck] = cps
        case_jira[ck] = next((x.jira_url for x in rs if x.jira_url), "")

    real_cases = [ck for ck in by_case if ck != unlinked]

    # ---------- Case Result 行 = (case, host) ----------
    case_host_rows = []
    chr_index = collections.defaultdict(list)  # (case,host) -> [scenario idx]
    for row in scenario_rows:
        chr_index[(row["case_key"], row["host"])].append(row["idx"])
    for (ck, host), idxs in chr_index.items():
        rs = [records[i] for i in idxs]
        npass = sum(1 for x in rs if x.is_pass)
        total = len(rs)
        verdict = "Pass" if npass == total else "Fail"
        case_host_rows.append({
            "case_key": ck,
            "jira_url": case_jira.get(ck, ""),
            "owners": case_owners.get(ck, []),
            "components": case_comps.get(ck, []),
            "host": host,
            "host_display": records[idxs[0]].host_display,
            "verdict": verdict,
            "n_pass": npass,
            "n_total": total,
            "scenario_idx": sorted(idxs),
        })
    case_host_rows.sort(key=lambda x: (x["case_key"], x["host"]))

    # ---------- 总览 ----------
    s_total = len(records)
    s_pass = sum(1 for r in records if r.is_pass)
    # case 视图按 (case, host) 行计数（与三视角口径一致）
    ch_rows_real = [row for row in case_host_rows if row["case_key"] != unlinked]
    c_total = len(ch_rows_real)
    c_pass = sum(1 for row in ch_rows_real if row["verdict"] == "Pass")
    # 同时保留唯一 case 数量，供页面/markdown 信息展示
    unique_cases = len(real_cases)
    unique_cases_pass = sum(1 for ck in real_cases if case_global[ck])
    overview = {
        "scenario": _counts(s_pass, s_total),
        "case": _counts(c_pass, c_total),
        "unique_case": _counts(unique_cases_pass, unique_cases),
        "status_breakdown": dict(collections.Counter(r.status for r in records)),
    }

    # ---------- 汇总：通用构造器 ----------
    def case_summary_by_row(keyfunc, none_label):
        """case 级（行口径）：keyfunc(row) -> [bucket...]；按 (case,host) 行计数。
        一个 case 在 N 台机器上跑就贡献 N 行；component 单一归属，owner 0/1 个。
        """
        buckets = collections.defaultdict(lambda: [0, 0])  # bucket -> [pass,total]
        for row in ch_rows_real:
            ks = keyfunc(row) or [none_label]
            for k in ks:
                buckets[k][1] += 1
                if row["verdict"] == "Pass":
                    buckets[k][0] += 1
        rows = []
        for k in sorted(buckets):
            p, t = buckets[k]
            rows.append({"name": k, **_counts(p, t)})
        return rows

    def case_summary_by_host():
        """Device 视角天然就是 (case,host) 行口径。"""
        buckets = collections.defaultdict(lambda: [0, 0])
        for row in ch_rows_real:
            buckets[row["host_display"]][1] += 1
            if row["verdict"] == "Pass":
                buckets[row["host_display"]][0] += 1
        return [{"name": k, **_counts(*buckets[k])} for k in sorted(buckets)]

    def scenario_summary_by(keyfunc, none_label):
        buckets = collections.defaultdict(lambda: [0, 0])
        for r in records:
            ks = keyfunc(r) or [none_label]
            for k in ks:
                buckets[k][1] += 1
                if r.is_pass:
                    buckets[k][0] += 1
        return [{"name": k, **_counts(*buckets[k])} for k in sorted(buckets)]

    case_summary = {
        "owner": case_summary_by_row(lambda row: row["owners"], no_owner),
        "component": case_summary_by_row(lambda row: row["components"], no_comp),
        "device": case_summary_by_host(),
    }
    scenario_summary = {
        "owner": scenario_summary_by(lambda r: r.owners, no_owner),
        "component": scenario_summary_by(lambda r: r.components, no_comp),
        "device": scenario_summary_by(lambda r: [r.host_display], "(no-host)"),
    }

    # ---------- host × owner 矩阵（scenario 级 pass/total） ----------
    matrix = collections.defaultdict(lambda: [0, 0])
    owners_axis, hosts_axis = set(), set()
    for r in records:
        hosts_axis.add(r.host_display)
        ows = r.owners or [no_owner]
        for o in ows:
            owners_axis.add(o)
            matrix[(r.host_display, o)][1] += 1
            if r.is_pass:
                matrix[(r.host_display, o)][0] += 1
    matrix_out = {
        "hosts": sorted(hosts_axis),
        "owners": sorted(owners_axis),
        "cells": {"%s||%s" % (h, o): _counts(*matrix[(h, o)])
                  for (h, o) in matrix},
    }

    # ---------- TopN ----------
    top_retries = sorted(
        [s for s in scenario_rows if s["retries_count"] > 0],
        key=lambda x: -x["retries_count"])[:top_n]
    top_duration = sorted(scenario_rows, key=lambda x: -x["duration_ms"])[:top_n]

    # ---------- 失败明细 ----------
    failures = [s for s in scenario_rows if not s["is_pass"]]
    failures.sort(key=lambda x: (x["case_key"], x["host"]))

    # ---------- 跨机不一致 case ----------
    inconsistent = []
    by_case_host_verdict = collections.defaultdict(dict)
    for row in case_host_rows:
        by_case_host_verdict[row["case_key"]][row["host"]] = row["verdict"]
    for ck, hv in by_case_host_verdict.items():
        if len(set(hv.values())) > 1:
            inconsistent.append({"case_key": ck,
                                 "hosts": hv,
                                 "jira_url": case_jira.get(ck, "")})
    inconsistent.sort(key=lambda x: -len(x["hosts"]))

    # ---------- UNLINKED & key_source ----------
    unlinked_rows = [s for s in scenario_rows if s["case_key"] == unlinked]
    key_source_dist = dict(collections.Counter(r.case_key_source for r in records))

    return {
        "meta": report_meta,
        "overview": overview,
        "scenario_rows": scenario_rows,
        "case_host_rows": case_host_rows,
        "case_summary": case_summary,
        "scenario_summary": scenario_summary,
        "matrix": matrix_out,
        "top_retries": top_retries,
        "top_duration": top_duration,
        "failures": failures,
        "inconsistent": inconsistent,
        "unlinked": unlinked_rows,
        "key_source_dist": key_source_dist,
        "labels": {"no_owner": no_owner, "no_component": no_comp, "unlinked": unlinked},
        "thresholds": config.get("thresholds", {}),
        "counts": {"cases": c_total, "unique_cases": unique_cases,
                   "scenarios": s_total,
                   "case_host_rows": len(case_host_rows),
                   "inconsistent_cases": len(inconsistent)},
    }
