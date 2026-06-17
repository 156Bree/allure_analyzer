#!/usr/bin/env python3
"""serve.py —— 本地（仅 localhost）趋势/报告统一服务。

默认启动「全站统一入口」：服务 trend_data/ 根目录，/ 自动跳到 trend_out/trend.html。
从趋势页进入任意 daily_out/<date>/report.html 时，日报与趋势页共享同一个
/api/analysis，因此 AI 分析、人工编辑、删除、吸收都在同一端口下可用。

纯标准库（http.server + json + urllib），零额外依赖，仅绑定 127.0.0.1。

用法：
    python3 serve.py                              # 统一入口：trend_data/ + trend_out/trend.html
    python3 serve.py --date 2026-06-09            # 兼容：只服务 trend_data/daily_out/2026-06-09
    python3 serve.py --dir /path/to/report_dir    # 兼容：显式指定报告目录
可选：--port 8765  --config config.yaml

提供的接口（与 templates/report.html.j2 约定一致）：
    GET  /                 -> trend_out/trend.html（默认）或 report.html（--date/--dir）
    GET  /api/analysis     -> 返回整份 store.json：{fp: entry}
    POST /api/analysis     -> body {action:'save'|'delete', fp, ...}
                             save  : 置 source=manual / locked=true，返回 {ok, entry}
                             delete: 删除该 fp，返回 {ok}
    POST /api/absorb       -> body {fp}：把该条人工修正幂等写入
                             skill 的 references/learned-corrections.md，返回 {ok}

安全：仅本机访问；fp 必须为 40 位 sha1 十六进制；只写 store.json 与 learned 文件；
静态文件复用 SimpleHTTPRequestHandler 的目录限制（防路径穿越）。
"""
import argparse
import json
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from analyzer.config import load_config            # noqa: E402
from analyzer.ai import store as store_mod          # noqa: E402

_FP_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SAVE_FIELDS = ("case_key", "host", "scenario", "status_message",
                "conclusion", "cause", "suggestion", "evidence")


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------
def _resolve_serve_root(args):
    """返回 (静态根目录, 首页路径, 模式说明)。"""
    if args.dir:
        d = os.path.abspath(args.dir)
        if not os.path.isdir(d):
            sys.exit("[serve][error] 目录不存在：%s" % d)
        return d, "/report.html", "单日报告目录"

    daily_root = os.path.join(HERE, "trend_data", "daily_out")
    if args.date:
        d = os.path.join(daily_root, args.date)
        if not os.path.isdir(d):
            sys.exit("[serve][error] 未找到该日期报告目录：%s" % d)
        return d, "/report.html", "单日报告日期 %s" % args.date

    trend_root = os.path.join(HERE, "trend_data")
    trend_home = os.path.join(trend_root, "trend_out", "trend.html")
    if not os.path.isfile(trend_home):
        sys.exit("[serve][error] 未找到 %s，请先用 run_daily.py 生成趋势；"
                 "若只想打开单日报告，请使用 --date 或 --dir。" % trend_home)
    return trend_root, "/trend_out/trend.html", "趋势 + 全部日报统一入口"


def _resolve_store_path(ai_cfg):
    rel = ((ai_cfg.get("cache") or {}).get("store_path")
           or "trend_data/ai_analysis/store.json")
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(HERE, rel))


def _resolve_learned_path(ai_cfg):
    skill_cfg = ai_cfg.get("skill") or {}
    skill_path = skill_cfg.get("path", "")
    learned_rel = skill_cfg.get("learned_file", "references/learned-corrections.md")
    if not skill_path:
        return ""
    skill_dir = skill_path if os.path.isabs(skill_path) else \
        os.path.normpath(os.path.join(HERE, skill_path))
    return os.path.join(skill_dir, learned_rel)


# ---------------------------------------------------------------------------
# learned-corrections.md 两层幂等写入
# ---------------------------------------------------------------------------
def _resolve_api_key(ai_cfg):
    api_key = str(ai_cfg.get("api_key") or "").strip()
    if api_key:
        return api_key
    api_key_env = ai_cfg.get("api_key_env", "OPENAI_API_KEY")
    return os.environ.get(api_key_env or "OPENAI_API_KEY", "")


def _g(entry, key):
    return str(entry.get(key, "") or "").strip()


def _first_line(text, limit=160):
    lines = str(text or "").splitlines()
    return (lines[0] if lines else "")[:limit]


def _learned_skeleton():
    return "\n".join([
        "# Learned Corrections (人工修正沉淀)",
        "",
        "> 本文件由“分析龙虾”每日报告网页里的人工修正自动追加。",
        "> 它是 `fix-case-error` skill 的最高优先级上下文：自动分析失败 scenario 时优先读取本文件。",
        "> 文件分两层：通用规则层用于可复用模式，具体案例层用于单个 case/host/scenario 的精确经验。",
        "> 请勿手工破坏下方 `<!-- rule:... -->` / `<!-- entry:... -->` 标记，serve.py 依赖它做幂等更新。",
        "",
        "## 1. 通用规则层（跨 case 可复用）",
        "",
        "<!-- general-rules-start -->",
        "",
        "<!-- general-rules-end -->",
        "",
        "## 2. 具体案例层（单 case 精确经验）",
        "",
        "<!-- case-examples-start -->",
        "",
        "<!-- case-examples-end -->",
        "",
    ])


def _ensure_learned_sections(text):
    if "<!-- general-rules-start -->" in text and "<!-- case-examples-start -->" in text:
        return text
    legacy = ""
    m = re.search(r"<!-- entries-start -->(.*?)<!-- entries-end -->", text or "", re.DOTALL)
    if m:
        legacy = m.group(1).strip()
    out = _learned_skeleton()
    if legacy:
        out = out.replace("<!-- case-examples-end -->", legacy + "\n\n<!-- case-examples-end -->", 1)
    return out


def _choose_learned_layer(ai_cfg, entry):
    """让模型判断写入通用规则层还是具体案例层；失败时保守落到具体案例层。"""
    fallback = {
        "layer": "case_example",
        "title": "%s · %s" % (_g(entry, "case_key") or "(no-case)", _g(entry, "scenario") or "(no-scenario)"),
        "applicability": _g(entry, "cause"),
        "boundary": "仅确认与该 case/host/scenario 失败特征一致时复用。",
    }
    if not bool(ai_cfg.get("enabled")):
        return fallback
    api_key = _resolve_api_key(ai_cfg)
    if not api_key:
        return fallback

    system_prompt = (
        "You maintain a pytest/Allure failure triage skill. Decide whether one human correction "
        "should become a reusable general rule or remain a specific case example. "
        "Return ONLY JSON: {\"layer\":\"general_rule|case_example\",\"title\":\"...\","
        "\"applicability\":\"...\",\"boundary\":\"...\"}. "
        "Choose general_rule only when the correction describes a pattern reusable across multiple cases; "
        "choose case_example when it depends on exact case, host, scenario, or one-off data."
    )
    user_prompt = "\n".join([
        "Human correction to absorb:",
        "case_key: %s" % _g(entry, "case_key"),
        "host: %s" % _g(entry, "host"),
        "scenario: %s" % _g(entry, "scenario"),
        "status_message: %s" % _first_line(_g(entry, "status_message"), 500),
        "conclusion: %s" % _g(entry, "conclusion"),
        "cause: %s" % _g(entry, "cause"),
        "suggestion: %s" % _g(entry, "suggestion"),
        "evidence: %s" % _g(entry, "evidence"),
    ])
    try:
        result = llm_client.chat_json(
            ai_cfg.get("base_url", ""), api_key, ai_cfg.get("model", ""),
            system_prompt, user_prompt,
            timeout=int(ai_cfg.get("timeout", 30) or 30),
            max_retries=int(ai_cfg.get("max_retries", 1) or 0),
            log=lambda msg: sys.stderr.write("%s\n" % msg))
        layer = str(result.get("layer", "") or "").strip()
        if layer not in ("general_rule", "case_example"):
            layer = "case_example"
        return {
            "layer": layer,
            "title": str(result.get("title") or fallback["title"]).strip(),
            "applicability": str(result.get("applicability") or fallback["applicability"]).strip(),
            "boundary": str(result.get("boundary") or fallback["boundary"]).strip(),
        }
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("[serve] skill 层级判定失败，按具体案例写入：%s\n" % e)
        return fallback


def _remove_fp_blocks(text, fp):
    patterns = [
        r"\n?<!-- rule:fp=%s -->.*?<!-- /rule:fp=%s -->\n?" % (re.escape(fp), re.escape(fp)),
        r"\n?<!-- entry:fp=%s -->.*?<!-- /entry:fp=%s -->\n?" % (re.escape(fp), re.escape(fp)),
    ]
    for p in patterns:
        text = re.sub(p, "\n", text, flags=re.DOTALL)
    return text


def _insert_before(text, marker, block):
    return text.replace(marker, block.rstrip() + "\n\n" + marker, 1)


def _build_general_rule_block(fp, entry, decision):
    return "\n".join([
        "<!-- rule:fp=%s -->" % fp,
        "## 通用规则：%s" % (decision.get("title") or _g(entry, "conclusion") or fp[:8]),
        "",
        "- **适用特征**: %s" % (decision.get("applicability") or _g(entry, "cause")),
        "- **判断依据**: %s" % (_g(entry, "evidence") or _first_line(_g(entry, "status_message"))),
        "- **推荐结论**: %s" % _g(entry, "conclusion"),
        "- **原因模板**: %s" % _g(entry, "cause"),
        "- **建议模板**: %s" % _g(entry, "suggestion"),
        "- **适用边界**: %s" % (decision.get("boundary") or "仅在失败特征匹配时复用。"),
        "- **来源案例**: %s · %s · %s" % (_g(entry, "case_key"), _g(entry, "host"), _g(entry, "scenario")),
        "- **来源**: manual · 吸收时间 %s" % (entry.get("updated_at") or store_mod.now_iso()),
        "<!-- /rule:fp=%s -->" % fp,
    ])


def _build_case_example_block(fp, entry):
    scenario = _g(entry, "scenario")
    return "\n".join([
        "<!-- entry:fp=%s -->" % fp,
        "## %s · %s · %s" % (_g(entry, "case_key") or "(no-case)",
                             _g(entry, "host") or "(no-host)",
                             (scenario or "(no-scenario)")[:60]),
        "",
        "- **Case**: %s" % _g(entry, "case_key"),
        "- **Host**: %s" % _g(entry, "host"),
        "- **Scenario**: %s" % scenario,
        "- **Status message (摘要)**: %s" % _first_line(_g(entry, "status_message")),
        "- **结论**: %s" % _g(entry, "conclusion"),
        "- **原因**: %s" % _g(entry, "cause"),
        "- **建议**: %s" % _g(entry, "suggestion"),
        "- **分析依据**: %s" % (_g(entry, "evidence") or _first_line(_g(entry, "status_message"))),
        "- **来源**: manual · 吸收时间 %s" % (entry.get("updated_at") or store_mod.now_iso()),
        "<!-- /entry:fp=%s -->" % fp,
    ])


def _absorb_entry(learned_path, fp, entry, ai_cfg):
    """把一条人工修正幂等写入 learned 文件；由模型决定通用规则层或具体案例层。"""
    if not learned_path:
        raise RuntimeError("未配置 skill learned 文件路径")

    text = ""
    if os.path.isfile(learned_path):
        with open(learned_path, "r", encoding="utf-8") as f:
            text = f.read()
    text = _ensure_learned_sections(text)
    text = _remove_fp_blocks(text, fp)

    decision = _choose_learned_layer(ai_cfg or {}, entry)
    if decision.get("layer") == "general_rule":
        block = _build_general_rule_block(fp, entry, decision)
        new_text = _insert_before(text, "<!-- general-rules-end -->", block)
    else:
        block = _build_case_example_block(fp, entry)
        new_text = _insert_before(text, "<!-- case-examples-end -->", block)

    d = os.path.dirname(learned_path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(learned_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return decision


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class ReportHandler(SimpleHTTPRequestHandler):
    """静态服务趋势/报告目录 + AI 编辑接口。运行参数由 run() 注入。"""

    # 由 run() 注入
    store_path = ""
    learned_path = ""
    home_path = "/trend_out/trend.html"
    ai_cfg = {}

    # -- 工具 ----------------------------------------------------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, code=400):
        self._send_json({"ok": False, "error": msg}, code)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return None  # 解析失败

    def log_message(self, fmt, *args):  # 降噪：简洁单行日志
        sys.stderr.write("[serve] %s - %s\n" % (self.address_string(), fmt % args))

    def _redirect_home(self):
        self.send_response(302)
        self.send_header("Location", self.home_path)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    # -- GET/HEAD ------------------------------------------------------------
    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._redirect_home()
            return
        return SimpleHTTPRequestHandler.do_HEAD(self)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/analysis":
            try:
                st = store_mod.Store(self.store_path)
                self._send_json(st.data)
            except Exception as e:  # noqa: BLE001
                self._err("读取分析失败：%s" % e, 500)
            return
        if path == "/":
            self._redirect_home()
            return
        return SimpleHTTPRequestHandler.do_GET(self)

    # -- POST ----------------------------------------------------------------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/analysis":
            return self._handle_analysis()
        if path == "/api/absorb":
            return self._handle_absorb()
        self._err("未知接口", 404)

    def _handle_analysis(self):
        body = self._read_body()
        if body is None:
            return self._err("请求体不是合法 JSON")
        action = body.get("action")
        fp = str(body.get("fp", "") or "")
        if not _FP_RE.match(fp):
            return self._err("非法 fp")
        try:
            st = store_mod.Store(self.store_path)
        except Exception as e:  # noqa: BLE001
            return self._err("打开缓存失败：%s" % e, 500)

        if action == "delete":
            st.delete(fp)
            if not st.save(force=True):
                return self._err("写盘失败", 500)
            return self._send_json({"ok": True})

        if action == "save":
            fields = {}
            for k in _SAVE_FIELDS:
                if k in body:
                    fields[k] = str(body.get(k, "") or "").strip()
            entry = st.upsert_manual(fp, fields)
            if not st.save():
                return self._err("写盘失败", 500)
            return self._send_json({"ok": True, "entry": entry})

        return self._err("未知 action：%s" % action)

    def _handle_absorb(self):
        body = self._read_body()
        if body is None:
            return self._err("请求体不是合法 JSON")
        fp = str(body.get("fp", "") or "")
        if not _FP_RE.match(fp):
            return self._err("非法 fp")
        try:
            st = store_mod.Store(self.store_path)
        except Exception as e:  # noqa: BLE001
            return self._err("打开缓存失败：%s" % e, 500)
        entry = st.get(fp)
        if not entry:
            return self._err("该 fp 无分析记录，无法吸收", 404)
        try:
            decision = _absorb_entry(self.learned_path, fp, entry, self.ai_cfg)
        except Exception as e:  # noqa: BLE001
            return self._err("写入 skill 失败：%s" % e, 500)
        return self._send_json({"ok": True, "layer": decision.get("layer", "case_example")})


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="分析龙虾 · 本地趋势/报告统一服务（仅 localhost）")
    p.add_argument("--date", default="", help="兼容模式：只服务 trend_data/daily_out/<date>")
    p.add_argument("--dir", default="", help="兼容模式：显式报告目录（优先于 --date）")
    p.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    p.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    return p.parse_args()


def run():
    args = parse_args()
    serve_root, home_path, mode_desc = _resolve_serve_root(args)
    config = load_config(args.config)
    ai_cfg = (config or {}).get("ai") or {}
    store_path = _resolve_store_path(ai_cfg)
    learned_path = _resolve_learned_path(ai_cfg)

    ReportHandler.store_path = store_path
    ReportHandler.learned_path = learned_path
    ReportHandler.home_path = home_path
    ReportHandler.ai_cfg = ai_cfg
    handler = partial(ReportHandler, directory=serve_root)

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = "http://127.0.0.1:%d/" % args.port
    print("=" * 60)
    print("分析龙虾 · 本地统一服务已启动")
    print("  模式     :", mode_desc)
    print("  静态根   :", serve_root)
    print("  首页     :", home_path)
    print("  store    :", store_path)
    print("  learned  :", learned_path or "(未配置 skill)")
    print("  访问地址 :", url)
    print("  按 Ctrl+C 停止")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] 已停止。")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()
