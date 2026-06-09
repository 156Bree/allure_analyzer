"""loader：扫描 data/test-cases/*.json 全部记录 → TestCaseRecord 列表。

职责（不含 owner/case_key/component 业务判定，那些在 owner.py / classify.py）：
- O(N) 遍历，丢弃 steps/attachments 等大字段，控内存。
- 字段缺失全程 .get 容错；单文件解析失败不中断，结尾汇总告警。
- (host, history_id) 唯一性自检：重复时保留 time.stop 最新者并告警。
- 填充 host_display（device.display_map），其余业务字段留待 enrich 阶段。
"""
import glob
import json
import os


def _labels_map(d):
    """labels 是 [{name,value}, ...]，转成 name -> [values]。"""
    out = {}
    for l in d.get("labels", []) or []:
        n = l.get("name")
        v = l.get("value")
        if n is None:
            continue
        out.setdefault(n, []).append(v)
    return out


def _first(lm, name, default=""):
    vs = lm.get(name)
    return vs[0] if vs else default


def _collect_tags(d, lm):
    """合并 labels.tag 与 extra.tags，去重保序。"""
    tags = list(lm.get("tag", []) or [])
    extra = d.get("extra", {}) or {}
    et = extra.get("tags", []) or []
    if isinstance(et, list):
        for t in et:
            tags.append(t)
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _status_message(d):
    """尽量取失败信息（passed 记录通常没有）。"""
    msg = d.get("statusMessage") or d.get("statusTrace")
    if not msg:
        sd = d.get("statusDetails") or {}
        if isinstance(sd, dict):
            msg = sd.get("message") or sd.get("trace") or ""
    return (msg or "").strip()


def _build_record(d, display_map, passed_values):
    from .models import TestCaseRecord
    lm = _labels_map(d)
    host = _first(lm, "host")
    status = d.get("status", "") or ""
    rec = TestCaseRecord(
        uid=d.get("uid", "") or "",
        name=d.get("name", "") or "",
        full_name=d.get("fullName", "") or "",
        history_id=d.get("historyId", "") or "",
        status=status,
        is_pass=(status in passed_values),
        host=host,
        host_display=display_map.get(host, host),
        tags=_collect_tags(d, lm),
        severity=_first(lm, "severity"),
        feature=_first(lm, "feature"),
        suite=_first(lm, "suite"),
        sub_suite=_first(lm, "subSuite"),
        parent_suite=_first(lm, "parentSuite"),
        package=_first(lm, "package"),
        duration_ms=int(((d.get("time") or {}).get("duration")) or 0),
        retries_count=int(d.get("retriesCount") or 0),
        flaky=bool(d.get("flaky")),
        status_message=_status_message(d),
        hidden=bool(d.get("hidden")),
    )
    # 解析阶段先把 links 暂存到 rec._links（供 classify 抽 case_key/jira），用属性挂载避免污染 dataclass
    rec_links = []
    for ln in d.get("links", []) or []:
        rec_links.append({"name": ln.get("name", "") or "", "url": ln.get("url", "") or ""})
    setattr(rec, "_links", rec_links)
    # story label 也可能含 jira（如 https://jira.../LIP-690），一并暂存供 classify 兜底
    setattr(rec, "_story_labels", list(lm.get("story", []) or []))
    return rec


def _stop_time(d):
    return ((d.get("time") or {}).get("stop")) or 0


def load_records(report_dir, config):
    """返回 (records, stats)。report_dir 为报告根目录（含 data/test-cases）。"""
    tc_dir = os.path.join(report_dir, "data", "test-cases")
    files = sorted(glob.glob(os.path.join(tc_dir, "*.json")))
    display_map = (config.get("device", {}) or {}).get("display_map", {}) or {}
    passed_values = set((config.get("status", {}) or {}).get("passed_values", ["passed"]))

    stats = {
        "files_total": len(files),
        "parsed": 0,
        "parse_failed": 0,
        "parse_failed_files": [],
        "dup_keys": 0,
        "dup_dropped": 0,
        "hidden": 0,
        "visible": 0,
    }
    if not files:
        print("[loader] 警告：%s 下没有任何 test-case json。" % tc_dir)
        return [], stats

    # (host, history_id) -> (rec, stop_time)
    by_key = {}
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
        except Exception as e:  # noqa: BLE001
            stats["parse_failed"] += 1
            stats["parse_failed_files"].append("%s (%s)" % (os.path.basename(f), e))
            continue
        rec = _build_record(d, display_map, passed_values)
        stats["parsed"] += 1
        if rec.hidden:
            stats["hidden"] += 1
        else:
            stats["visible"] += 1

        key = (rec.host, rec.history_id)
        stop = _stop_time(d)
        if key in by_key:
            stats["dup_keys"] += 1
            stats["dup_dropped"] += 1
            prev_rec, prev_stop = by_key[key]
            if stop >= prev_stop:
                by_key[key] = (rec, stop)  # 保留更晚结束的
        else:
            by_key[key] = (rec, stop)

    records = [r for (r, _s) in by_key.values()]

    # 结尾汇总告警
    if stats["parse_failed"]:
        print("[loader] 警告：%d 个文件解析失败：%s" % (
            stats["parse_failed"], "; ".join(stats["parse_failed_files"][:10])))
    if stats["dup_keys"]:
        print("[loader] 警告：发现 %d 处 (host, historyId) 重复，已保留最新结束记录并去重 %d 条。" % (
            stats["dup_keys"], stats["dup_dropped"]))
    print("[loader] 解析文件 %d / 成功 %d / 失败 %d；去重后记录 %d 条（hidden=%d, visible=%d）。" % (
        stats["files_total"], stats["parsed"], stats["parse_failed"],
        len(records), stats["hidden"], stats["visible"]))
    stats["records_after_dedup"] = len(records)
    return records, stats
