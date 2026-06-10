#!/usr/bin/env python3
"""trend.py：读取每日快照，聚合 7 天 / 30 天趋势，输出 trend.html / trend.csv / trend.md。

设计思路
--------
- 数据源唯一：`<snapshots-dir>/YYYY-MM-DD.json`，由 analyze.py 的 --snapshot-dir 产出。
- 不依赖原始 allure 报告，原始大报告可归档/删除。
- 输出三种产物，**自包含、单文件**：
    * trend.html  —— Tailwind + Chart.js（CDN），含 7 天 / 30 天 切换、多维度折线。
    * trend.csv   —— overview + counts 长表，方便 Excel 二次处理。
    * trend.md    —— 简明每日表格 + 状态流转摘要。
- case 状态流转：基于 case_verdicts 与前一天对比 → 新增 / 修复 / 回归。

CLI:
    python3 trend.py --snapshots <dir> --output <dir>
"""
import argparse
import csv
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyzer import snapshot as snapshot_mod  # noqa: E402


WINDOWS = [("7d", 7), ("30d", 30)]


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def _slice_window(snapshots, days):
    """按"日历日"切窗口：以最末快照日期为基准，向前数 days-1 天（含基准日共 days 天）。

    语义：
      - 7d 窗口  = [latest - 6天, latest]   只取真实落在该日历日范围内的快照
      - 30d 窗口 = [latest - 29天, latest]
      - 兜底：如果窗口内快照数 < 2 且总快照数 >= 2，扩展到至少包含最近 2 份快照
              （避免数据极稀时窗口里只有 1 个孤点画不出曲线）

    snapshots 必须按 date 升序传入。
    """
    if not snapshots:
        return []
    # 解析最末日期
    latest_str = snapshots[-1].get("date", "")
    try:
        latest = datetime.datetime.strptime(latest_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        # 解析失败，退化为"取最后 days 份"
        return snapshots[-days:] if len(snapshots) > days else snapshots[:]

    cutoff = latest - datetime.timedelta(days=days - 1)
    result = []
    for s in snapshots:
        try:
            d = datetime.datetime.strptime(s.get("date", ""), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if cutoff <= d <= latest:
            result.append(s)

    # 兜底：窗口内 < 2 份且总数 >= 2 时，扩展到最近 2 份
    if len(result) < 2 and len(snapshots) >= 2:
        return snapshots[-2:]
    return result


def _series_overview(snaps):
    """整体通过率 + 体量序列。"""
    out = {
        "dates": [s["date"] for s in snaps],
        "scenario_pass_rate": [],
        "case_pass_rate": [],
        "unique_case_pass_rate": [],
        "scenario_total": [],
        "case_total": [],
        "unique_case_total": [],
        "hosts": [],
        "inconsistent_cases": [],
    }
    for s in snaps:
        ov = s.get("overview", {}) or {}
        cnt = s.get("counts", {}) or {}
        out["scenario_pass_rate"].append(_rate(ov.get("scenario", {})))
        out["case_pass_rate"].append(_rate(ov.get("case", {})))
        out["unique_case_pass_rate"].append(_rate(ov.get("unique_case", {})))
        out["scenario_total"].append(int((ov.get("scenario") or {}).get("total", 0)))
        out["case_total"].append(int((ov.get("case") or {}).get("total", 0)))
        out["unique_case_total"].append(int((ov.get("unique_case") or {}).get("total", 0)))
        out["hosts"].append(int(cnt.get("hosts", 0)))
        out["inconsistent_cases"].append(int(cnt.get("inconsistent_cases", 0)))
    return out


def _rate(d):
    """安全取通过率：优先用 pass_rate；否则用 pass/total 现算。"""
    if not isinstance(d, dict):
        return None
    if "pass_rate" in d and d.get("total"):
        try:
            return round(float(d["pass_rate"]), 4)
        except (TypeError, ValueError):
            pass
    t = int(d.get("total") or 0)
    if t == 0:
        return None
    return round(int(d.get("pass") or 0) / t, 4)


def _series_dim(snaps, dim_key):
    """按维度（owner/component/device）汇总每日各 bucket 的 [pass,total]。

    返回：
      {
        "dates": [...],
        "buckets": ["alice", "bob", ...],         # 出现过的所有 bucket，按字典序
        "pass_rate": {bucket: [rate or None per day]},
        "total":     {bucket: [int per day]},
      }
    """
    dates = [s["date"] for s in snaps]
    bucket_set = set()
    for s in snaps:
        cs = (s.get("case_summary") or {}).get(dim_key) or {}
        bucket_set.update(cs.keys())
    buckets = sorted(bucket_set)
    pr = {b: [] for b in buckets}
    tt = {b: [] for b in buckets}
    for s in snaps:
        cs = (s.get("case_summary") or {}).get(dim_key) or {}
        for b in buckets:
            v = cs.get(b)
            if not v:
                pr[b].append(None)
                tt[b].append(0)
            else:
                p, t = int(v[0]), int(v[1])
                pr[b].append(round(p / t, 4) if t else None)
                tt[b].append(t)
    return {"dates": dates, "buckets": buckets, "pass_rate": pr, "total": tt}


def _series_churn(snaps):
    """case 状态流转：每天相对前一天 新增 / 修复 / 回归 / 仍失败 / 仍通过。

    定义（与前一天的 case_verdicts 对比）：
      - new_pass:  今天首次出现且 Pass        —— 新加入且通过
      - new_fail:  今天首次出现且 Fail        —— 新加入但失败
      - fixed:     昨天 Fail，今天 Pass       —— 修复
      - regressed: 昨天 Pass，今天 Fail       —— 回归
      - dropped:   昨天有，今天没了          —— 当天未跑/被移除
      - still_fail / still_pass: 状态保持
    第一天没有"前一天"，churn 字段全部为 0 或 null。
    """
    out = {"dates": [s["date"] for s in snaps],
           "new_pass": [], "new_fail": [], "fixed": [], "regressed": [],
           "dropped": [], "still_fail": [], "still_pass": []}
    prev = None
    for s in snaps:
        cur = s.get("case_verdicts", {}) or {}
        if prev is None:
            for k in ("new_pass", "new_fail", "fixed", "regressed",
                      "dropped", "still_fail", "still_pass"):
                out[k].append(0)
        else:
            cur_keys = set(cur.keys())
            prev_keys = set(prev.keys())
            new_keys = cur_keys - prev_keys
            gone_keys = prev_keys - cur_keys
            common = cur_keys & prev_keys
            np_ = sum(1 for k in new_keys if cur[k] == "Pass")
            nf_ = sum(1 for k in new_keys if cur[k] == "Fail")
            fx = sum(1 for k in common if prev[k] == "Fail" and cur[k] == "Pass")
            rg = sum(1 for k in common if prev[k] == "Pass" and cur[k] == "Fail")
            sf = sum(1 for k in common if prev[k] == "Fail" and cur[k] == "Fail")
            sp = sum(1 for k in common if prev[k] == "Pass" and cur[k] == "Pass")
            out["new_pass"].append(np_)
            out["new_fail"].append(nf_)
            out["fixed"].append(fx)
            out["regressed"].append(rg)
            out["dropped"].append(len(gone_keys))
            out["still_fail"].append(sf)
            out["still_pass"].append(sp)
        prev = cur
    return out


def _window_summary(snaps):
    """窗口聚合：用于趋势页顶部概览卡。

    返回的字段都是"窗口范围内"的统计，供 6 张概览卡使用：
      - scenario_avg_pass_rate / case_avg_pass_rate / unique_case_avg_pass_rate
      - unique_case_min: {rate, date}      （最低值在哪天）
      - churn_total_fixed / churn_total_regressed
      - latest_inconsistent_cases
      - latest_date / first_date / actual_days
    缺数据时各项为 None / 0。
    """
    if not snaps:
        return {
            "actual_days": 0, "first_date": None, "latest_date": None,
            "scenario_avg_pass_rate": None,
            "case_avg_pass_rate": None,
            "unique_case_avg_pass_rate": None,
            "unique_case_min": None,
            "churn_total_fixed": 0,
            "churn_total_regressed": 0,
            "latest_inconsistent_cases": None,
        }

    def _avg(picks):
        nums = [v for v in picks if v is not None]
        if not nums:
            return None
        return round(sum(nums) / len(nums), 4)

    sc_rates, ca_rates, uc_rates = [], [], []
    uc_min_rate, uc_min_date = None, None
    for s in snaps:
        ov = s.get("overview", {}) or {}
        sc = _rate(ov.get("scenario", {}))
        ca = _rate(ov.get("case", {}))
        uc = _rate(ov.get("unique_case", {}))
        sc_rates.append(sc); ca_rates.append(ca); uc_rates.append(uc)
        if uc is not None and (uc_min_rate is None or uc < uc_min_rate):
            uc_min_rate, uc_min_date = uc, s.get("date")

    churn = _series_churn(snaps)
    last = snaps[-1]
    last_cnt = last.get("counts", {}) or {}
    return {
        "actual_days": len(snaps),
        "first_date": snaps[0].get("date"),
        "latest_date": last.get("date"),
        "scenario_avg_pass_rate": _avg(sc_rates),
        "case_avg_pass_rate": _avg(ca_rates),
        "unique_case_avg_pass_rate": _avg(uc_rates),
        "unique_case_min": (
            None if uc_min_rate is None
            else {"rate": uc_min_rate, "date": uc_min_date}
        ),
        "churn_total_fixed": sum(churn["fixed"]),
        "churn_total_regressed": sum(churn["regressed"]),
        "latest_inconsistent_cases": int(last_cnt.get("inconsistent_cases", 0)),
    }


def aggregate(snapshots):
    """对所有快照做聚合，返回各窗口下的所有维度时间序列。"""
    result = {
        "available_dates": [s["date"] for s in snapshots],
        "windows": {},
        "thresholds": (snapshots[-1].get("thresholds") if snapshots else {}) or {},
    }
    for label, days in WINDOWS:
        snaps = _slice_window(snapshots, days)
        result["windows"][label] = {
            "label": label,
            "days": days,
            "actual_days": len(snaps),
            "overview": _series_overview(snaps),
            "owner": _series_dim(snaps, "owner"),
            "component": _series_dim(snaps, "component"),
            "device": _series_dim(snaps, "device"),
            "churn": _series_churn(snaps),
            "summary": _window_summary(snaps),
        }
    return result


# ---------------------------------------------------------------------------
# 产物：CSV / Markdown / HTML
# ---------------------------------------------------------------------------

def _write_csv(snapshots, out_path):
    """每日一行：date, scenario_*, case_*, unique_case_*, devices, inconsistent, churn_*。"""
    headers = [
        "date",
        "scenario_pass", "scenario_total", "scenario_pass_rate",
        "case_pass", "case_total", "case_pass_rate",
        "unique_case_pass", "unique_case_total", "unique_case_pass_rate",
        "devices", "inconsistent_cases",
        "churn_new_pass", "churn_new_fail", "churn_fixed", "churn_regressed",
        "churn_dropped", "churn_still_fail", "churn_still_pass",
    ]
    churn = _series_churn(snapshots)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for i, s in enumerate(snapshots):
            ov = s.get("overview", {}) or {}
            sc = ov.get("scenario", {}) or {}
            ca = ov.get("case", {}) or {}
            uc = ov.get("unique_case", {}) or {}
            cnt = s.get("counts", {}) or {}
            w.writerow([
                s.get("date", ""),
                sc.get("pass", 0), sc.get("total", 0), _rate(sc) or 0,
                ca.get("pass", 0), ca.get("total", 0), _rate(ca) or 0,
                uc.get("pass", 0), uc.get("total", 0), _rate(uc) or 0,
                cnt.get("hosts", 0), cnt.get("inconsistent_cases", 0),
                churn["new_pass"][i], churn["new_fail"][i],
                churn["fixed"][i], churn["regressed"][i],
                churn["dropped"][i], churn["still_fail"][i], churn["still_pass"][i],
            ])


def _write_markdown(snapshots, agg, out_path):
    lines = []
    lines.append("# 趋势分析（分析龙虾）\n")
    lines.append("- 生成时间：%s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("- 快照覆盖：%d 天（%s ~ %s）\n" % (
        len(snapshots),
        snapshots[0]["date"] if snapshots else "-",
        snapshots[-1]["date"] if snapshots else "-",
    ))
    lines.append("## 每日总览\n")
    lines.append("| 日期 | scenario 通过率 | case 通过率 | unique case 通过率 | device 数 | scenario 总数 | case 总数 | 跨机不一致 |")
    lines.append("|------|----------------|-------------|--------------------|-----------|---------------|-----------|------------|")
    for s in snapshots:
        ov = s.get("overview", {}) or {}
        cnt = s.get("counts", {}) or {}
        def pct(d):
            r = _rate(d)
            return "-" if r is None else "%.2f%%" % (r * 100)
        lines.append("| %s | %s | %s | %s | %d | %d | %d | %d |" % (
            s["date"], pct(ov.get("scenario", {})), pct(ov.get("case", {})),
            pct(ov.get("unique_case", {})),
            cnt.get("hosts", 0), cnt.get("scenarios", 0),
            cnt.get("case_host_rows", 0), cnt.get("inconsistent_cases", 0),
        ))
    lines.append("")
    lines.append("## case 状态流转（相对前一日）\n")
    lines.append("| 日期 | 新增通过 | 新增失败 | 修复 | 回归 | 移除 | 持续失败 | 持续通过 |")
    lines.append("|------|----------|----------|------|------|------|----------|----------|")
    churn = _series_churn(snapshots)
    for i, d in enumerate(churn["dates"]):
        lines.append("| %s | %d | %d | %d | %d | %d | %d | %d |" % (
            d, churn["new_pass"][i], churn["new_fail"][i], churn["fixed"][i],
            churn["regressed"][i], churn["dropped"][i],
            churn["still_fail"][i], churn["still_pass"][i],
        ))
    lines.append("")
    lines.append("> 详细多维度（owner / component / device）曲线请打开 `trend.html`。\n")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


_FALLBACK_TREND_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>趋势分析 · 分析龙虾（降级）</title></head><body>
<h1>趋势分析（降级模式）</h1>
<p>未找到 trend.html.j2 模板，仅内嵌原始聚合 JSON。</p>
<script id="trend-data" type="application/json">__TREND_JSON__</script>
<pre id="d"></pre>
<script>document.getElementById('d').textContent=document.getElementById('trend-data').textContent;</script>
</body></html>"""


def _trend_template_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "templates", "trend.html.j2")


def _write_html(agg, snapshots, out_path, daily_report_rel=""):
    tpl = _trend_template_path()
    if os.path.isfile(tpl):
        with open(tpl, "r", encoding="utf-8") as f:
            shell = f.read()
    else:
        print("[trend][WARN] 未找到模板 %s，使用降级外壳。" % tpl)
        shell = _FALLBACK_TREND_SHELL
    payload = {
        "agg": agg,
        "snapshots_meta": [{
            "date": s["date"],
            "report_name": (s.get("meta") or {}).get("report_name", ""),
            "generated_at": (s.get("meta") or {}).get("generated_at", ""),
        } for s in snapshots],
        "daily_report_rel": daily_report_rel,  # 用于"日期"列超链接，空则不加链接
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    html = shell.replace("__TREND_JSON__", json.dumps(payload, ensure_ascii=False))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="分析龙虾 · 趋势分析")
    p.add_argument("--snapshots", "-s",
                   default=os.path.join(here, "trend_data", "snapshots"),
                   help="快照目录，默认 ./trend_data/snapshots")
    p.add_argument("--output", "-o",
                   default=os.path.join(os.getcwd(), "trend_out"),
                   help="趋势报告输出目录，默认 ./trend_out")
    p.add_argument("--formats", "-f", default="html,csv,md",
                   help="输出格式，逗号分隔：html,csv,md（默认全部）")
    p.add_argument("--daily-out", default="",
                   help="每日详细报告根目录（用于在 HTML 表格中给日期列加超链接）；"
                        "传相对/绝对路径都行，HTML 会自动转为相对 trend.html 的相对路径")
    return p.parse_args()


def main():
    args = parse_args()
    snap_dir = os.path.abspath(args.snapshots)
    out_dir = os.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)

    snapshots = snapshot_mod.load_all(snap_dir)
    if not snapshots:
        print("[trend][error] 快照目录为空：%s" % snap_dir)
        print("  请先运行：python3 analyze.py --report <allure_report> --snapshot-dir %s" % snap_dir)
        sys.exit(1)

    # 计算 daily_out 相对 trend_out 的相对路径
    daily_rel = ""
    if args.daily_out:
        daily_abs = os.path.abspath(args.daily_out)
        try:
            daily_rel = os.path.relpath(daily_abs, out_dir).replace("\\", "/")
        except ValueError:
            daily_rel = daily_abs.replace("\\", "/")

    print("=" * 60)
    print("分析龙虾 · 趋势分析")
    print("  快照目录：%s（共 %d 份）" % (snap_dir, len(snapshots)))
    print("  覆盖日期：%s ~ %s" % (snapshots[0]["date"], snapshots[-1]["date"]))
    print("  输出目录：%s" % out_dir)
    if daily_rel:
        print("  每日报告链接基准（相对 trend.html）：%s" % daily_rel)
    print("=" * 60)

    agg = aggregate(snapshots)
    formats = {x.strip().lower() for x in args.formats.split(",") if x.strip()}
    produced = []
    if "csv" in formats:
        p = os.path.join(out_dir, "trend.csv")
        _write_csv(snapshots, p)
        produced.append("trend.csv")
    if "md" in formats or "markdown" in formats:
        p = os.path.join(out_dir, "trend.md")
        _write_markdown(snapshots, agg, p)
        produced.append("trend.md")
    if "html" in formats:
        p = os.path.join(out_dir, "trend.html")
        _write_html(agg, snapshots, p, daily_report_rel=daily_rel)
        produced.append("trend.html")

    print("完成。产物：%s" % ", ".join(produced))


if __name__ == "__main__":
    main()
