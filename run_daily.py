#!/usr/bin/env python3
"""run_daily.py：每日一键脚本（定位 → analyze → snapshot → trend）。

特性
----
1) 智能定位：自动识别 reports_inbox/ 下的日期目录、嵌套层级、压缩包；同日多候选会阻塞并列出。
2) 增量识别：默认跳过"已分析过且报告未变更"的日期（比对 snapshots/<date>.json 里的 source_fingerprint）。
   加 --force 时强制全部重跑。
3) 汇报卡：跑完打印一段"今日值班汇报"摘要 + 落盘 trend_data/trend_out/daily_briefing.md。
   加 --no-briefing 关闭。

使用方式
--------
1) 收件根模式（推荐）：
    python3 run_daily.py --inbox /path/to/reports_inbox

2) 单日模式（目录或压缩包都可以）：
    python3 run_daily.py --date-dir /path/to/reports_inbox/2026-06-09
    python3 run_daily.py --date-dir /path/to/reports_inbox/2026-06-09.zip

3) 显式指定报告根：
    python3 run_daily.py --report-root /path/to/.../allure-report --date 2026-06-09

支持的压缩包格式：.zip / .tar / .tar.gz / .tgz / .tar.bz2 / .tbz2
"""
import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from analyzer.locator import (  # noqa: E402
    resolve_targets, normalize_date, is_archive,
)
from analyzer import snapshot as snapshot_mod  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="分析龙虾 · 每日一键（analyze + snapshot + trend）")
    p.add_argument("--inbox", default="", help="收件根目录（自动扫日期子目录与日期压缩包）")
    p.add_argument("--date-dir", default="", help="单个日期目录或日期压缩包")
    p.add_argument("--report-root", default="", help="显式指定 allure 报告根（覆盖自动定位）")
    p.add_argument("--date", default="", help="显式日期 YYYY-MM-DD（仅 --report-root 模式）")
    p.add_argument("--snapshot-dir", default=os.path.join(HERE, "trend_data", "snapshots"))
    p.add_argument("--analysis-out", default=os.path.join(HERE, "trend_data", "daily_out"))
    p.add_argument("--trend-out", default=os.path.join(HERE, "trend_data", "trend_out"))
    p.add_argument("--unpack-cache",
                   default=os.path.join(HERE, "trend_data", "_unpack_cache"),
                   help="压缩包解压缓存目录，默认 trend_data/_unpack_cache")
    p.add_argument("--no-unpack", action="store_true",
                   help="禁用自动解压（仅按已有目录形态识别报告）")
    p.add_argument("--force", action="store_true",
                   help="强制重跑所有日期（默认会跳过已分析过且报告未变更的日期）")
    p.add_argument("--no-briefing", action="store_true",
                   help="跑完后不打印汇报卡也不落盘 daily_briefing.md")
    p.add_argument("--formats", default="html,csv,md")
    p.add_argument("--skip-trend", action="store_true")
    p.add_argument("--skip-analyze", action="store_true")
    p.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    return p.parse_args()


# ---------------------------------------------------------------------------
# 增量识别：算"原始来源"的指纹
# ---------------------------------------------------------------------------

def _archive_path_from_source(source):
    """从 resolve_targets 返回 item 的 source 字段提取 archive 路径；不是 archive 来源返回空。"""
    if not source:
        return ""
    if source.startswith("archive:"):
        return source[len("archive:"):]
    return ""


def _compute_source_fingerprint_for_target(item):
    """根据 resolve_targets 返回的单个 target 决定指纹来源。

    - 顶层日期压缩包 source="archive:<path>" → 用压缩包指纹（最稳定，也包含解压目录的稳定性）
    - 日期目录 source="dir"：扫该日期目录里**所有**压缩包 + 报告根目录，串起来算（任何一个变了都重跑）
    """
    arch = _archive_path_from_source(item.get("source", ""))
    if arch:
        return snapshot_mod.compute_archive_fingerprint(arch)

    # dir 来源：把日期目录里能找到的所有压缩包指纹 + 报告根目录指纹拼起来
    parts = []
    date_dir = item.get("date_dir", "")
    if date_dir and os.path.isdir(date_dir):
        # 浅扫日期目录里的压缩包（最多 2 层）
        try:
            for root, _, files in os.walk(date_dir):
                # 限制深度
                rel = os.path.relpath(root, date_dir)
                if rel.count(os.sep) >= 2:
                    continue
                for fn in sorted(files):
                    if is_archive(os.path.join(root, fn)):
                        fp = snapshot_mod.compute_archive_fingerprint(os.path.join(root, fn))
                        if fp:
                            parts.append(fp)
        except OSError:
            pass
    report_root = item.get("report_root", "")
    if report_root:
        fp = snapshot_mod.compute_dir_fingerprint(report_root)
        if fp:
            parts.append(fp)
    return "+".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# 子任务调用
# ---------------------------------------------------------------------------

def run_analyze(report_root, date_str, fingerprint, args):
    daily_out = os.path.join(os.path.abspath(args.analysis_out), date_str)
    os.makedirs(daily_out, exist_ok=True)
    cmd = [
        sys.executable, os.path.join(HERE, "analyze.py"),
        "--report", report_root,
        "--output", daily_out,
        "--config", args.config,
        "--formats", args.formats,
        "--snapshot-dir", os.path.abspath(args.snapshot_dir),
        "--snapshot-date", date_str,
        "--source-fingerprint", fingerprint or "",
        "--report-name", "Allure Report (%s)" % date_str,
    ]
    print("\n>>> [%s] analyze: %s" % (date_str, report_root))
    rc = subprocess.call(cmd)
    if rc != 0:
        print("[run_daily][error] analyze.py 退出码 %d，跳过 %s" % (rc, date_str))
        return False
    return True


def run_trend(args):
    cmd = [
        sys.executable, os.path.join(HERE, "trend.py"),
        "--snapshots", os.path.abspath(args.snapshot_dir),
        "--output", os.path.abspath(args.trend_out),
        "--formats", "html,csv,md",
        "--daily-out", os.path.abspath(args.analysis_out),
    ]
    print("\n>>> trend:")
    rc = subprocess.call(cmd)
    if rc != 0:
        print("[run_daily][error] trend.py 退出码 %d" % rc)
        return False
    return True


def _log(msg):
    print(msg)


# ---------------------------------------------------------------------------
# 汇报卡
# ---------------------------------------------------------------------------

def _rate_safe(d):
    if not isinstance(d, dict):
        return None
    t = int(d.get("total") or 0)
    if t == 0:
        return None
    if "pass_rate" in d and d.get("pass_rate") is not None:
        try:
            return float(d["pass_rate"])
        except (TypeError, ValueError):
            pass
    return int(d.get("pass") or 0) / t


def _fmt_pct(r):
    return "-" if r is None else "%.2f%%" % (r * 100)


def _delta(now, prev, unit_pt=False):
    """返回 (字符串, 符号 ∈ {+,-,=})。unit_pt=True 时按百分点，否则按整数。"""
    if now is None or prev is None:
        return ("-", "=")
    diff = now - prev
    if abs(diff) < 1e-9:
        return ("±0", "=")
    sign = "▲" if diff > 0 else "▼"
    if unit_pt:
        return ("%s %.2fpt" % (sign, abs(diff) * 100), "+" if diff > 0 else "-")
    if isinstance(diff, float) and not diff.is_integer():
        return ("%s %.2f" % (sign, abs(diff)), "+" if diff > 0 else "-")
    return ("%s %d" % (sign, int(abs(diff))), "+" if diff > 0 else "-")


def _diff_devices(prev_snap, cur_snap):
    """返回 (新增 device list, 下线 device list)。"""
    pp = set((prev_snap.get("case_summary") or {}).get("device", {}).keys()) if prev_snap else set()
    cc = set((cur_snap.get("case_summary") or {}).get("device", {}).keys())
    return sorted(cc - pp), sorted(pp - cc)


def _diff_verdicts(prev_snap, cur_snap):
    """返回 (regressed_keys, fixed_keys, new_pass_keys, new_fail_keys, dropped_keys)。"""
    p = (prev_snap or {}).get("case_verdicts", {}) or {}
    c = (cur_snap or {}).get("case_verdicts", {}) or {}
    pk = set(p.keys()); ck = set(c.keys())
    new_keys = ck - pk
    gone_keys = pk - ck
    common = ck & pk
    return (
        sorted(k for k in common if p[k] == "Pass" and c[k] == "Fail"),  # regressed
        sorted(k for k in common if p[k] == "Fail" and c[k] == "Pass"),  # fixed
        sorted(k for k in new_keys if c[k] == "Pass"),                   # new_pass
        sorted(k for k in new_keys if c[k] == "Fail"),                   # new_fail
        sorted(gone_keys),                                                # dropped
    )


def _build_briefing(args, analyzed_dates, skipped_items, blocked_items):
    """构造汇报卡：返回 (text_for_console, markdown_for_file)。"""
    snap_dir = os.path.abspath(args.snapshot_dir)
    snaps = snapshot_mod.load_all(snap_dir)
    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    L_md = []  # markdown
    L_md.append("# 🦞 分析龙虾 · 值班汇报")
    L_md.append("")
    L_md.append("- 生成时间：%s" % today)
    L_md.append("- 快照覆盖：%d 天%s" % (
        len(snaps),
        ("（%s ~ %s）" % (snaps[0]["date"], snaps[-1]["date"])) if snaps else "",
    ))
    L_md.append("")

    # 本次执行情况
    L_md.append("## 本次执行")
    L_md.append("")
    if analyzed_dates:
        L_md.append("- ✅ 已分析 %d 天：%s" % (len(analyzed_dates), ", ".join(sorted(analyzed_dates))))
    else:
        L_md.append("- ✅ 已分析：（无新增/变更）")
    if skipped_items:
        ds = ", ".join(sorted(it["date"] for it in skipped_items))
        L_md.append("- ⏭ 跳过 %d 天（已分析且报告未变更）：%s" % (len(skipped_items), ds))
    if blocked_items:
        L_md.append("- 🚫 阻塞 %d 天（需要人工介入）：" % len(blocked_items))
        for it in blocked_items:
            L_md.append("  - **%s**：%s" % (it.get("date", "?"),
                                           (it.get("error") or "").splitlines()[0]))
            for c in it.get("candidates", []):
                L_md.append("    - 候选：`%s`" % c)
    L_md.append("")

    # 趋势变化（只有 ≥ 2 天才有意义）
    if len(snaps) >= 2:
        cur, prev = snaps[-1], snaps[-2]
        ov_c, ov_p = cur.get("overview", {}) or {}, prev.get("overview", {}) or {}
        cn_c, cn_p = cur.get("counts", {}) or {}, prev.get("counts", {}) or {}

        sc_now = _rate_safe(ov_c.get("scenario", {}))
        sc_prev = _rate_safe(ov_p.get("scenario", {}))
        ca_now = _rate_safe(ov_c.get("case", {}))
        ca_prev = _rate_safe(ov_p.get("case", {}))
        uc_now = _rate_safe(ov_c.get("unique_case", {}))
        uc_prev = _rate_safe(ov_p.get("unique_case", {}))

        new_devs, gone_devs = _diff_devices(prev, cur)
        regressed, fixed, new_pass, new_fail, dropped = _diff_verdicts(prev, cur)

        L_md.append("## 最新一天对比（%s vs 前一日 %s）" % (cur["date"], prev["date"]))
        L_md.append("")
        L_md.append("| 指标 | 前一日 | 今日 | 变化 |")
        L_md.append("|---|---|---|---|")
        L_md.append("| scenario 通过率   | %s | %s | %s |" % (
            _fmt_pct(sc_prev), _fmt_pct(sc_now), _delta(sc_now, sc_prev, unit_pt=True)[0]))
        L_md.append("| case 通过率       | %s | %s | %s |" % (
            _fmt_pct(ca_prev), _fmt_pct(ca_now), _delta(ca_now, ca_prev, unit_pt=True)[0]))
        L_md.append("| unique case 通过率 | %s | %s | %s |" % (
            _fmt_pct(uc_prev), _fmt_pct(uc_now), _delta(uc_now, uc_prev, unit_pt=True)[0]))
        L_md.append("| device 数         | %d | %d | %s |" % (
            cn_p.get("hosts", 0), cn_c.get("hosts", 0),
            _delta(cn_c.get("hosts", 0), cn_p.get("hosts", 0))[0]))
        L_md.append("| 跨 device 不一致 case | %d | %d | %s |" % (
            cn_p.get("inconsistent_cases", 0), cn_c.get("inconsistent_cases", 0),
            _delta(cn_c.get("inconsistent_cases", 0), cn_p.get("inconsistent_cases", 0))[0]))
        L_md.append("")

        if new_devs:
            L_md.append("- 🆕 新加入 device：%s" % ", ".join(new_devs))
        if gone_devs:
            L_md.append("- 📴 不再出现 device：%s" % ", ".join(gone_devs))
        if regressed:
            L_md.append("- ⚠ 回归 %d 个 case：%s" % (len(regressed),
                ", ".join(regressed[:10]) + (" 等" if len(regressed) > 10 else "")))
        if fixed:
            L_md.append("- ✅ 修复 %d 个 case：%s" % (len(fixed),
                ", ".join(fixed[:10]) + (" 等" if len(fixed) > 10 else "")))
        if new_fail:
            L_md.append("- 🆕❌ 新增失败 case %d 个：%s" % (len(new_fail),
                ", ".join(new_fail[:10]) + (" 等" if len(new_fail) > 10 else "")))
        if not (new_devs or gone_devs or regressed or fixed or new_fail):
            L_md.append("- 一切如常 🦞")
        L_md.append("")

    # 直达入口
    L_md.append("## 直达入口")
    L_md.append("")
    L_md.append("- 趋势报告：`trend_data/trend_out/trend.html`")
    if snaps:
        latest = snaps[-1]["date"]
        L_md.append("- 最新一天完整报告：`trend_data/daily_out/%s/report.html`" % latest)
    L_md.append("- 快照目录：`trend_data/snapshots/`")
    L_md.append("")

    md_text = "\n".join(L_md)

    # 控制台精简版
    C = []
    C.append("=" * 60)
    C.append("🦞 分析龙虾 · 今日值班汇报")
    C.append("=" * 60)
    if analyzed_dates:
        C.append("✅ 已分析 %d 天：%s" % (len(analyzed_dates), ", ".join(sorted(analyzed_dates))))
    else:
        C.append("✅ 已分析：（无新增/变更）")
    if skipped_items:
        C.append("⏭ 跳过 %d 天（未变更）：%s" % (
            len(skipped_items),
            ", ".join(sorted(it["date"] for it in skipped_items)),
        ))
    if blocked_items:
        C.append("🚫 阻塞 %d 天：%s" % (
            len(blocked_items),
            ", ".join(it.get("date", "?") for it in blocked_items),
        ))
    if len(snaps) >= 2:
        cur, prev = snaps[-1], snaps[-2]
        ov_c, ov_p = cur.get("overview", {}) or {}, prev.get("overview", {}) or {}
        cn_c, cn_p = cur.get("counts", {}) or {}, prev.get("counts", {}) or {}
        sc_now, sc_prev = _rate_safe(ov_c.get("scenario", {})), _rate_safe(ov_p.get("scenario", {}))
        uc_now, uc_prev = _rate_safe(ov_c.get("unique_case", {})), _rate_safe(ov_p.get("unique_case", {}))
        new_devs, gone_devs = _diff_devices(prev, cur)
        regressed, fixed, _, new_fail, _ = _diff_verdicts(prev, cur)
        C.append("")
        C.append("📊 %s vs %s" % (cur["date"], prev["date"]))
        C.append("   • scenario 通过率: %s → %s   %s" % (
            _fmt_pct(sc_prev), _fmt_pct(sc_now), _delta(sc_now, sc_prev, unit_pt=True)[0]))
        C.append("   • unique case 通过率: %s → %s   %s" % (
            _fmt_pct(uc_prev), _fmt_pct(uc_now), _delta(uc_now, uc_prev, unit_pt=True)[0]))
        C.append("   • device 数: %d → %d" % (cn_p.get("hosts", 0), cn_c.get("hosts", 0)))
        C.append("   • 跨 device 不一致: %d → %d" % (
            cn_p.get("inconsistent_cases", 0), cn_c.get("inconsistent_cases", 0)))
        if new_devs:
            C.append("   🆕 新机器: %s" % ", ".join(new_devs))
        if gone_devs:
            C.append("   📴 离线机器: %s" % ", ".join(gone_devs))
        if regressed:
            C.append("   ⚠ 回归 %d: %s" % (len(regressed),
                ", ".join(regressed[:5]) + (" ..." if len(regressed) > 5 else "")))
        if fixed:
            C.append("   ✅ 修复 %d: %s" % (len(fixed),
                ", ".join(fixed[:5]) + (" ..." if len(fixed) > 5 else "")))
        if new_fail:
            C.append("   🆕❌ 新增失败 %d: %s" % (len(new_fail),
                ", ".join(new_fail[:5]) + (" ..." if len(new_fail) > 5 else "")))
    C.append("")
    C.append("📂 直达：")
    C.append("   • 趋势:        " + os.path.join(os.path.abspath(args.trend_out), "trend.html"))
    if snaps:
        C.append("   • 最新日报告:  " + os.path.join(
            os.path.abspath(args.analysis_out), snaps[-1]["date"], "report.html"))
    C.append("=" * 60)
    return "\n".join(C), md_text


def _write_briefing(args, console_text, md_text):
    out_dir = os.path.abspath(args.trend_out)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "daily_briefing.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md_text)
    return path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    cache_root = os.path.abspath(args.unpack_cache)
    auto_unpack = not args.no_unpack
    snap_dir = os.path.abspath(args.snapshot_dir)

    if not (args.inbox or args.date_dir or args.report_root or args.skip_analyze):
        print("[run_daily][error] 必须指定 --inbox / --date-dir / --report-root 之一，"
              "或加 --skip-analyze 仅刷新趋势。")
        sys.exit(2)

    # ---- 解析 targets：每个元素 dict 至少含 date, report_root, source ----
    raw_targets = []   # [item-dict from resolve_targets]
    blocked_items = []  # [item-dict]

    if args.report_root:
        d = (args.date or "").strip()
        if not d:
            for part in reversed(os.path.abspath(args.report_root).replace("\\", "/").split("/")):
                nd = normalize_date(part)
                if nd:
                    d = nd
                    break
        if not d:
            print("[run_daily][error] --report-root 模式下需要 --date YYYY-MM-DD（无法从路径推断）。")
            sys.exit(2)
        raw_targets.append({
            "date": d,
            "report_root": os.path.abspath(args.report_root),
            "date_dir": os.path.abspath(args.report_root),
            "source": "dir",
        })

    elif args.date_dir:
        path = os.path.abspath(args.date_dir)
        items = resolve_targets(path, cache_root, auto_unpack=auto_unpack, log=_log)
        if not items:
            print("[run_daily][error] 无法识别 --date-dir 输入：%s" % path)
            sys.exit(2)
        for it in items:
            if it.get("report_root"):
                raw_targets.append(it)
            else:
                blocked_items.append(it)

    elif args.inbox:
        items = resolve_targets(os.path.abspath(args.inbox), cache_root,
                                auto_unpack=auto_unpack, log=_log)
        if not items:
            print("[run_daily][error] 在 %s 下未找到任何日期目录或日期压缩包" % args.inbox)
            sys.exit(2)
        for it in items:
            if it.get("report_root"):
                raw_targets.append(it)
            else:
                blocked_items.append(it)

    # 报阻塞
    for it in blocked_items:
        print("[run_daily][BLOCKED] 日期 %s（来源 %s）" % (
            it.get("date", "?"), it.get("source", "?")))
        if it.get("candidates"):
            print("  发现多个 Allure 报告候选，请用 --report-root 指定其中之一：")
            for c in it["candidates"]:
                print("    " + c)
        else:
            print("  错误：%s" % it.get("error", "未知"))

    # ---- 增量识别：决定哪些跑、哪些跳过 ----
    targets_to_run = []   # list of (date, report_root, fingerprint)
    skipped_items = []    # list of {date, fingerprint, reason}
    if not args.skip_analyze:
        for it in raw_targets:
            date_str = it["date"]
            report_root = it["report_root"]
            fp_now = _compute_source_fingerprint_for_target(it)
            fp_old = snapshot_mod.read_snapshot_fingerprint(snap_dir, date_str)
            if (not args.force) and fp_now and fp_old and fp_now == fp_old:
                skipped_items.append({"date": date_str, "fingerprint": fp_now, "reason": "unchanged"})
                continue
            targets_to_run.append((date_str, report_root, fp_now))

    # ---- 跑 analyze ----
    analyzed_dates = []
    if not args.skip_analyze:
        if not raw_targets:
            print("[run_daily][error] 没有可处理的日期。")
            sys.exit(2)
        if not targets_to_run:
            print("\n[run_daily] 所有日期都已是最新（%d 天），跳过 analyze。" % len(skipped_items))
        else:
            ok = 0
            for date_str, root, fp in sorted(targets_to_run):
                if run_analyze(root, date_str, fp, args):
                    ok += 1
                    analyzed_dates.append(date_str)
            print("\n[run_daily] analyze 完成：%d/%d（跳过 %d）" % (
                ok, len(targets_to_run), len(skipped_items)))

    # ---- 跑 trend ----
    if not args.skip_trend:
        if not run_trend(args):
            sys.exit(1)

    # ---- 汇报卡 ----
    if not args.no_briefing:
        try:
            console_text, md_text = _build_briefing(args, analyzed_dates, skipped_items, blocked_items)
            print("\n" + console_text)
            briefing_path = _write_briefing(args, console_text, md_text)
            print("\n📝 完整汇报已写出：%s" % briefing_path)
        except Exception as e:
            print("[run_daily][WARN] 生成汇报卡失败：%s" % e)

    print("\n[run_daily] DONE.")
    print("  快照目录: %s" % snap_dir)
    print("  每日详细: %s" % os.path.abspath(args.analysis_out))
    print("  趋势报告: %s" % os.path.abspath(args.trend_out))
    if auto_unpack and os.path.isdir(cache_root):
        print("  解压缓存: %s（保留以供复查；可手动删除）" % cache_root)


if __name__ == "__main__":
    main()
