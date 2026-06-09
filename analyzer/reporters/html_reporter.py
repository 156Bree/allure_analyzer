"""html_reporter：生成单文件自包含交互式 HTML 仪表盘。

实现方式：读取 templates/report.html.j2 作为 HTML 外壳（静态、与数据无关），
把 analysis / reconcile 结果以 JSON 内嵌替换占位符。无需 jinja2（纯占位符替换），
缺模板文件时回落到内置最简外壳。
"""
import json
import os

_PLACEHOLDERS = ("__ANALYSIS_JSON__", "__RECONCILE_JSON__",
                 "__REPORT_NAME__", "__ORIGINAL_REPORT__")

_FALLBACK_SHELL = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>__REPORT_NAME__</title></head><body>
<h1>Allure 分析结果（降级模式）</h1>
<p>未找到 HTML 模板，仅内嵌原始 JSON 数据。</p>
<pre id="d"></pre>
<script id="analysis-data" type="application/json">__ANALYSIS_JSON__</script>
<script>document.getElementById('d').textContent=document.getElementById('analysis-data').textContent;</script>
<!-- __RECONCILE_JSON__ __ORIGINAL_REPORT__ --></body></html>"""


def _template_path():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # analyzer/
    return os.path.join(os.path.dirname(here), "templates", "report.html.j2")


def write(analysis, reconcile_result, out_dir):
    tpl_path = _template_path()
    if os.path.isfile(tpl_path):
        with open(tpl_path, "r", encoding="utf-8") as f:
            shell = f.read()
    else:
        print("[html] 未找到模板 %s，使用内置降级外壳。" % tpl_path)
        shell = _FALLBACK_SHELL

    meta = dict(analysis.get("meta", {}))
    analysis_json = json.dumps(analysis, ensure_ascii=False)
    reconcile_json = json.dumps(reconcile_result, ensure_ascii=False)

    # 先替换 JSON（其中可能含 __XXX__ 文本的概率极低，但仍按固定顺序、整体替换一次）
    html = shell.replace("__ANALYSIS_JSON__", analysis_json)
    html = html.replace("__RECONCILE_JSON__", reconcile_json)
    html = html.replace("__REPORT_NAME__", meta.get("report_name", "Allure Report"))
    html = html.replace("__ORIGINAL_REPORT__", meta.get("original_report", "") or "#")

    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("[html] 已写出 %s" % path)
    return path
