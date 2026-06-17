#!/usr/bin/env python3
"""分析龙虾 (Allure Report Analyzer) —— CLI 入口。

用法示例：
    python3 analyze.py --report /path/to/allure_report --output ./out --formats html,csv,excel,md
    python3 analyze.py                       # 默认分析上级目录(若含 data/test-cases)，输出到 ./out

传报告路径即可分析，不绑定某一份报告；口径/白名单/功能词等全在 config.yaml。
"""
import argparse
import datetime
import os
import sys

# 允许从脚本所在目录直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyzer.config import load_config
from analyzer.loader import load_records
from analyzer.owner import OwnerResolver
from analyzer.classify import Classifier
from analyzer.metrics import build_analysis
from analyzer.reconcile import reconcile
from analyzer.reporters import csv_reporter, excel_reporter, html_reporter, markdown_reporter
from analyzer import snapshot as snapshot_mod
from analyzer.locator import normalize_date


def _default_report_dir(script_dir):
    """默认报告目录：脚本上级目录(常见为把工具放进报告子目录的情形)。"""
    parent = os.path.dirname(script_dir)
    if os.path.isdir(os.path.join(parent, "data", "test-cases")):
        return parent
    return os.getcwd()


def parse_args():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="Allure 多机合并报告分析工具（分析龙虾）")
    p.add_argument("--report", "-r", default=_default_report_dir(script_dir),
                   help="Allure 报告根目录（含 data/test-cases），默认自动探测脚本上级目录")
    p.add_argument("--output", "-o", default=os.path.join(os.getcwd(), "out"),
                   help="输出目录，默认 ./out（日常请使用 run_daily.py，会自动按日期分目录）")
    p.add_argument("--config", "-c", default=os.path.join(script_dir, "config.yaml"),
                   help="配置文件路径，默认脚本目录下 config.yaml（缺 PyYAML 时用内置默认）")
    p.add_argument("--formats", "-f", default="html,csv,excel,md",
                   help="输出格式，逗号分隔：html,csv,excel,md（默认全部）")
    p.add_argument("--original-report", default="",
                   help="原始 Allure 报告链接（写入 HTML 顶部 Original Report）")
    p.add_argument("--report-name", default="Allure Report", help="报告显示名")
    p.add_argument("--snapshot-dir", default="",
                   help="趋势分析快照目录；若指定，则在分析完成后导出当日快照（YYYY-MM-DD.json）")
    p.add_argument("--snapshot-date", default="",
                   help="快照日期标识（YYYY-MM-DD），未指定时尝试从 --report 路径中识别，仍无法识别则使用今天")
    p.add_argument("--source-fingerprint", default="",
                   help="（高级）数据源指纹，写入快照供上层增量识别使用；未指定则按 --report 目录现算")
    return p.parse_args()


def main():
    args = parse_args()
    report_dir = os.path.abspath(args.report)
    out_dir = os.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)

    tc = os.path.join(report_dir, "data", "test-cases")
    if not os.path.isdir(tc):
        print("[error] 报告目录无效：%s 下找不到 data/test-cases。请用 --report 指定正确路径。" % report_dir)
        sys.exit(2)

    print("=" * 60)
    print("分析龙虾 · 开始分析")
    print("  报告目录:", report_dir)
    print("  输出目录:", out_dir)
    print("=" * 60)

    config = load_config(args.config)

    # 1) 解析
    records, load_stats = load_records(report_dir, config)
    if not records:
        print("[error] 未解析到任何记录，终止。")
        sys.exit(1)

    # 2) 富化 owner / case_key / component
    ow = OwnerResolver(config)
    cl = Classifier(config)
    for r in records:
        r.owners = ow.resolve(r.tags)
        cl.enrich(r)

    # 3) 对账 + 聚合
    reconcile_result = reconcile(records, report_dir, load_stats)
    meta = {
        "report_name": args.report_name,
        "report_dir": report_dir,
        "original_report": args.original_report,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    analysis = build_analysis(records, config, meta)

    # 3.5) AI 失败分析（降级不阻断）：build_analysis 后、reporter 前回填 ai_map/scenario_rows.ai
    try:
        from analyzer.ai import run_ai_analysis
        run_ai_analysis(analysis, config, os.path.dirname(os.path.abspath(__file__)))
        ai_meta = analysis.get("ai_meta", {})
        if ai_meta.get("enabled"):
            print("[ai] 状态=%s 失败=%d 新分析=%d 复用缓存=%d 失败调用=%d" % (
                ai_meta.get("status"), ai_meta.get("total_failures", 0),
                ai_meta.get("analyzed", 0), ai_meta.get("reused", 0),
                ai_meta.get("failed", 0)))
        else:
            print("[ai] 已禁用（config.ai.enabled=false）或无可分析项，跳过 LLM 调用。")
    except Exception as e:  # noqa: BLE001
        print("[ai][warn] AI 分析模块异常，已降级跳过：%s" % e)
        analysis.setdefault("ai_map", {})
        analysis.setdefault("ai_meta", {"enabled": False, "status": "error"})

    # 4) 输出
    formats = {x.strip().lower() for x in args.formats.split(",") if x.strip()}
    produced = []
    if "csv" in formats:
        csv_reporter.write(analysis, reconcile_result, out_dir)
        produced.append("csv/")
    if "excel" in formats or "xlsx" in formats:
        p = excel_reporter.write(analysis, reconcile_result, out_dir)
        if p:
            produced.append(os.path.basename(p))
    if "html" in formats:
        p = html_reporter.write(analysis, reconcile_result, out_dir)
        produced.append(os.path.basename(p))
    if "md" in formats or "markdown" in formats:
        p = markdown_reporter.write(analysis, reconcile_result, out_dir)
        produced.append(os.path.basename(p))

    # 5) 可选：导出趋势快照
    if args.snapshot_dir:
        # 推断快照日期：显式参数 > 报告路径里的日期目录 > 今天
        snap_date = args.snapshot_date.strip()
        if not snap_date:
            for part in reversed(report_dir.replace("\\", "/").split("/")):
                d = normalize_date(part)
                if d:
                    snap_date = d
                    break
        if not snap_date:
            snap_date = datetime.date.today().strftime("%Y-%m-%d")
        snap_dir = os.path.abspath(args.snapshot_dir)
        fp = (args.source_fingerprint or "").strip()
        if not fp:
            fp = snapshot_mod.compute_source_fingerprint(report_dir)
        _, snap_path = snapshot_mod.export(
            analysis, snap_date, snap_dir,
            extra_meta={"source_report_dir": report_dir},
            source_fingerprint=fp)
        produced.append("snapshot:%s" % os.path.basename(snap_path))
        print("[snapshot] 已写出 %s (date=%s, fp=%s)" % (snap_path, snap_date, fp or "-"))

    print("=" * 60)
    print("完成。输出目录：%s" % out_dir)
    print("  scenarios=%d  cases=%d  case×device行=%d  跨机不一致=%d" % (
        analysis["counts"]["scenarios"], analysis["counts"]["cases"],
        analysis["counts"]["case_host_rows"], analysis["counts"]["inconsistent_cases"]))
    print("  对账：%s" % reconcile_result["note"])
    print("  产物：%s" % ", ".join(produced))
    print("=" * 60)


if __name__ == "__main__":
    main()
