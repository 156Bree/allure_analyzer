"""snapshot.py：从 build_analysis 的完整结果中抽取一份"紧凑快照"，落盘供趋势分析使用。

设计原则
--------
- 快照文件名 = `<YYYY-MM-DD>.json`，按日期作为唯一主键；同日重跑会覆盖。
- 体量目标：单文件几 KB ~ 几十 KB，与原始 allure 报告解耦；原始大报告可随后归档/删除。
- 字段覆盖用户勾选的全部维度：整体通过率(scenario+case+unique_case)、owner/component/device 通过率、
  报告体量(case 数/机器数/scenario 数)、case 状态流转所需的"case_key → verdict"映射。
- case 流转维度：保留每个 unique case 的全局判定（pass=该 case 所有记录全 passed），
  趋势侧用前后两天对比即可算出"新增 / 修复 / 回归"，不需要每日完整 case 明细。
- 增量识别：可选写入 source_fingerprint 字段（来自归档文件指纹或报告目录指纹），
  上层（run_daily.py）据此判断"今天的报告与已分析过的是否一致"，决定跳过还是重跑。
"""
import hashlib
import json
import os


SNAPSHOT_VERSION = 2  # v2: 增加 source_fingerprint 字段


def compute_archive_fingerprint(archive_path):
    """压缩包的指纹：abspath + size + mtime。复用 locator 的同款规则但独立实现避免循环依赖。"""
    if not os.path.isfile(archive_path):
        return ""
    st = os.stat(archive_path)
    raw = "archive|%s|%d|%d" % (os.path.abspath(archive_path), st.st_size, int(st.st_mtime))
    return "ar:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def compute_dir_fingerprint(report_root):
    """报告目录指纹：data/test-cases/ 下的文件数 + 总字节数 + max(mtime)。

    设计目标：足够便宜（O(N) listdir），又对内容变更敏感（任何 json 增删/改都会改变指纹）。
    """
    if not os.path.isdir(report_root):
        return ""
    tc = os.path.join(report_root, "data", "test-cases")
    if not os.path.isdir(tc):
        # 兜底：只看 data/ 下所有文件
        tc = os.path.join(report_root, "data")
        if not os.path.isdir(tc):
            return ""
    n_files = 0
    total_size = 0
    max_mtime = 0
    try:
        for name in os.listdir(tc):
            p = os.path.join(tc, name)
            if not os.path.isfile(p):
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            n_files += 1
            total_size += st.st_size
            if st.st_mtime > max_mtime:
                max_mtime = st.st_mtime
    except OSError:
        return ""
    raw = "dir|%s|%d|%d|%d" % (os.path.abspath(tc), n_files, total_size, int(max_mtime))
    return "dr:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def compute_source_fingerprint(report_root, archive_path=""):
    """计算"数据源指纹"。优先用压缩包指纹（更稳定），否则用报告目录指纹。"""
    if archive_path:
        fp = compute_archive_fingerprint(archive_path)
        if fp:
            return fp
    return compute_dir_fingerprint(report_root)


def _summary_to_pairs(rows):
    """把 [{name,pass,fail,total,pass_rate}, ...] 压成 {name: [pass, total]} 节省体积。"""
    return {row["name"]: [int(row["pass"]), int(row["total"])] for row in rows}


def build_snapshot(analysis, date_str, extra_meta=None, source_fingerprint=""):
    """从 analysis(build_analysis 返回值) 抽取快照 dict。

    Args:
        analysis: build_analysis() 的返回 dict。
        date_str: 归一化日期 'YYYY-MM-DD'，作为快照主键。
        extra_meta: 可选 dict，合并进 snapshot.meta（如 source_report_root 等）。
        source_fingerprint: 可选字符串，用于上层增量识别。
    """
    meta_in = analysis.get("meta", {}) or {}
    overview = analysis.get("overview", {}) or {}
    case_summary = analysis.get("case_summary", {}) or {}
    counts = analysis.get("counts", {}) or {}

    # case_key -> verdict（unique case 全局判定）
    # 由 case_host_rows 推导：所有 host 行均 Pass 才算全局 Pass。
    unlinked_label = (analysis.get("labels") or {}).get("unlinked", "UNLINKED")
    by_case = {}
    for row in analysis.get("case_host_rows", []):
        ck = row.get("case_key")
        if not ck or ck == unlinked_label:
            continue
        v = row.get("verdict")
        if ck not in by_case:
            by_case[ck] = True
        if v != "Pass":
            by_case[ck] = False
    case_verdicts = {ck: ("Pass" if ok else "Fail") for ck, ok in by_case.items()}

    # 机器数：device 维度的 bucket 数
    device_rows = case_summary.get("device", []) or []
    n_hosts = len(device_rows)

    snap_meta = {
        "report_name": meta_in.get("report_name", ""),
        "generated_at": meta_in.get("generated_at", ""),
        "source_report_dir": meta_in.get("report_dir", ""),
        "original_report": meta_in.get("original_report", ""),
    }
    if extra_meta:
        snap_meta.update(extra_meta)

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "date": date_str,
        "source_fingerprint": source_fingerprint or "",
        "meta": snap_meta,
        "overview": {
            "scenario": overview.get("scenario", {}),
            "case": overview.get("case", {}),
            "unique_case": overview.get("unique_case", {}),
            "status_breakdown": overview.get("status_breakdown", {}),
        },
        "case_summary": {
            "owner":     _summary_to_pairs(case_summary.get("owner", [])),
            "component": _summary_to_pairs(case_summary.get("component", [])),
            "device":    _summary_to_pairs(case_summary.get("device", [])),
        },
        "counts": {
            "scenarios":         int(counts.get("scenarios", 0)),
            "cases":             int(counts.get("cases", 0)),            # (case,host) 行数
            "unique_cases":      int(counts.get("unique_cases", 0)),
            "case_host_rows":    int(counts.get("case_host_rows", 0)),
            "inconsistent_cases": int(counts.get("inconsistent_cases", 0)),
            "hosts":             int(n_hosts),
        },
        "case_verdicts": case_verdicts,  # {case_key: "Pass"|"Fail"} 用于状态流转对比
        "thresholds": analysis.get("thresholds", {}) or {},
    }
    return snapshot


def write_snapshot(snapshot, snapshots_dir):
    """把快照写到 snapshots_dir/<date>.json，返回完整路径。"""
    os.makedirs(snapshots_dir, exist_ok=True)
    path = os.path.join(snapshots_dir, "%s.json" % snapshot["date"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
    return path


def export(analysis, date_str, snapshots_dir, extra_meta=None, source_fingerprint=""):
    """便捷入口：构建并落盘，返回 (snapshot_dict, path)。"""
    snap = build_snapshot(analysis, date_str, extra_meta=extra_meta,
                          source_fingerprint=source_fingerprint)
    path = write_snapshot(snap, snapshots_dir)
    return snap, path


def read_snapshot_fingerprint(snapshots_dir, date_str):
    """读已有快照里的 source_fingerprint；快照不存在或无该字段返回空串。"""
    path = os.path.join(snapshots_dir, "%s.json" % date_str)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return data.get("source_fingerprint", "") or ""


def load_all(snapshots_dir):
    """读取目录下所有 *.json 快照，按日期升序返回 list of dict。

    会跳过格式不合法或缺 date 字段的文件，并打印 WARN。
    """
    items = []
    if not os.path.isdir(snapshots_dir):
        return items
    for name in sorted(os.listdir(snapshots_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(snapshots_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print("[snapshot][WARN] 无法读取 %s: %s" % (path, e))
            continue
        if not isinstance(data, dict) or "date" not in data:
            print("[snapshot][WARN] 跳过非快照文件：%s" % path)
            continue
        items.append(data)
    items.sort(key=lambda x: x.get("date", ""))
    return items
