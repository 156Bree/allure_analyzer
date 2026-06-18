"""skill_context.py —— 读取 fix-case-error skill 内容，拼成 LLM 的 system prompt。

约定：
- ``SKILL.md`` 作为主领域知识与“AI 自动分析输出规范(§5)”。
- ``references/learned-corrections.md`` 是最高优先级人工经验，但不会全量塞入每次请求：
  通用规则层全量携带（最多 20 条），具体案例层按当前失败检索 Top N。
- ``references/learned-index.json`` 是 learned-corrections 的轻量索引，自动重建。
- 其余 ``references/*.md`` 作为补充。
缺失文件全部跳过；整体缺失时回落到一段最简内置指令，保证不阻断。
"""
import datetime
import glob
import json
import os
import re


MAX_GENERAL_RULES = 20
MAX_CASE_EXAMPLES = 50
RELEVANT_CASE_TOP_N = 5
_INDEX_VERSION = 1

_FALLBACK = (
    "You are a senior test-failure triage assistant for pytest/Allure failures. "
    "Classify each failure, preferring False Positive / implement script error / "
    "test infrastructure error when the signature points to timing, polling, weak "
    "preconditions, readiness gaps, or wrapper handling rather than a stable product defect."
)

# 输出契约（即使 SKILL.md 缺失也强制注入，确保严格 JSON + 字数约束）
OUTPUT_CONTRACT = (
    "\n\n# OUTPUT CONTRACT (MUST FOLLOW)\n"
    "Return ONLY a single JSON object, no markdown, no code fence, no extra text:\n"
    '{"conclusion": "...", "cause": "...", "suggestion": "...", "evidence": "..."}\n'
    "- conclusion: 结论，≤20个汉字，给出 False Positive / implement script error / "
    "test infrastructure error / 疑似产品缺陷 的明确判定。\n"
    "- cause: 原因，≤80个汉字，简述最可能根因。\n"
    "- suggestion: 建议，≤80个汉字，给出最小可行修复方向。\n"
    "- evidence: 分析依据，≤160个汉字，只写可验证依据，例如关键断言、报错/log片段、"
    "匹配到的人工经验或排除信号；不要输出隐藏推理过程。\n"
    "四个字段必须存在且非空，用简短中文，不要输出其它字段。"
)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def resolve_skill_dir(skill_path, base_dir):
    """把（可能相对的）skill 路径解析为绝对路径。base_dir 为本工具目录。"""
    if not skill_path:
        return ""
    if os.path.isabs(skill_path):
        return skill_path
    return os.path.normpath(os.path.join(base_dir, skill_path))


def _section(text, start, end):
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def _marked_blocks(text, marker):
    pattern = r"<!-- %s:fp=([^>]+) -->(.*?)<!-- /%s:fp=\1 -->" % (marker, marker)
    out = []
    for m in re.finditer(pattern, text or "", re.DOTALL):
        fp = m.group(1).strip()
        block = m.group(0).strip()
        body = m.group(2).strip()
        title = ""
        for line in body.splitlines():
            if line.startswith("##"):
                title = line.lstrip("#").strip()
                break
        out.append({"fp": fp, "text": block, "body": body, "title": title})
    return out


def _tokens(text):
    text = str(text or "")
    raw = re.findall(r"LIP-\d+|[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
    stop = {"AssertionError", "where", "with", "true", "false", "None", "INFO", "ERROR"}
    out = []
    seen = set()
    for t in raw:
        k = t.lower()
        if t in stop or len(k) < 2 or k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out[:80]


def _parse_learned(text):
    rules = _marked_blocks(text, "rule")[:MAX_GENERAL_RULES]
    cases = _marked_blocks(text, "entry")[:MAX_CASE_EXAMPLES]
    entries = []
    for layer, blocks in (("general_rule", rules), ("case_example", cases)):
        for b in blocks:
            body = b["body"]
            entries.append({
                "fp": b["fp"],
                "layer": layer,
                "title": b["title"],
                "case_keys": sorted(set(re.findall(r"LIP-\d+", body, re.I))),
                "keywords": _tokens(body),
                "text": b["text"],
            })
    return {"rules": rules, "cases": cases, "entries": entries}


def _index_path(learned_abs):
    return os.path.join(os.path.dirname(learned_abs), "learned-index.json")


def refresh_learned_index(learned_abs):
    """从 learned-corrections.md 重建轻量索引。失败不抛出，返回索引 dict。"""
    text = _read(learned_abs)
    parsed = _parse_learned(text)
    obj = {
        "version": _INDEX_VERSION,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": os.path.basename(learned_abs),
        "limits": {
            "general_rule": MAX_GENERAL_RULES,
            "case_example": MAX_CASE_EXAMPLES,
            "relevant_case_top_n": RELEVANT_CASE_TOP_N,
        },
        "counts": {
            "general_rule": len(parsed["rules"]),
            "case_example": len(parsed["cases"]),
        },
        "entries": [
            {k: e[k] for k in ("fp", "layer", "title", "case_keys", "keywords")}
            for e in parsed["entries"]
        ],
    }
    try:
        with open(_index_path(learned_abs), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass
    return obj


def _score_case_example(entry, failure):
    hay = "\n".join([
        str(failure.get("case_key", "") or ""),
        str(failure.get("scenario", "") or ""),
        str(failure.get("status_message", "") or ""),
        str(failure.get("host", "") or ""),
    ])
    hay_l = hay.lower()
    score = 0
    ck = str(failure.get("case_key", "") or "")
    if ck and ck in entry.get("case_keys", []):
        score += 20
    for kw in entry.get("keywords", []):
        if kw and kw.lower() in hay_l:
            score += 2 if kw.upper().startswith("LIP-") else 1
    return score


def _learned_prompt(learned_abs, failure=None):
    text = _read(learned_abs)
    if not text.strip():
        return ""
    parsed = _parse_learned(text)
    refresh_learned_index(learned_abs)

    chunks = []
    if parsed["rules"]:
        chunks.append("# HIGHEST-PRIORITY HUMAN CORRECTIONS · GENERAL RULES (always apply)\n" +
                      "\n\n".join(b["text"] for b in parsed["rules"]))

    selected = []
    if failure:
        scored = []
        for e in parsed["entries"]:
            if e.get("layer") != "case_example":
                continue
            score = _score_case_example(e, failure)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1].get("title", "")))
        selected = [e for _, e in scored[:RELEVANT_CASE_TOP_N]]
    if selected:
        chunks.append("# RELEVANT HUMAN CASE EXAMPLES (retrieved top %d)\n" % len(selected) +
                      "\n\n".join(e["text"] for e in selected))
    return "\n\n---\n\n".join(chunks)


def build_system_prompt(skill_dir, learned_file_rel="references/learned-corrections.md", failure=None):
    """读取 skill 内容拼 system prompt。返回字符串（必含 OUTPUT CONTRACT）。

    learned-corrections 策略：通用规则层全量携带（最多 20 条），具体案例层仅按当前
    failure 的 case_key / status_message / 关键词检索 Top N，避免一年后 prompt 过大。
    """
    parts = []
    learned_abs = ""
    if skill_dir and os.path.isdir(skill_dir):
        # 1) learned-corrections 最高优先，但按层级/相关性裁剪
        learned_abs = os.path.join(skill_dir, learned_file_rel)
        learned = _learned_prompt(learned_abs, failure=failure)
        if learned.strip():
            parts.append(learned)
        # 2) SKILL.md 主体
        skill_md = _read(os.path.join(skill_dir, "SKILL.md"))
        if skill_md.strip():
            parts.append("# SKILL: fix-case-error\n" + skill_md)
        # 3) 其它 references
        ref_glob = os.path.join(skill_dir, "references", "*.md")
        for ref in sorted(glob.glob(ref_glob)):
            if os.path.normpath(ref) == os.path.normpath(learned_abs):
                continue
            txt = _read(ref)
            if txt.strip():
                parts.append("# REFERENCE: %s\n%s" % (os.path.basename(ref), txt))

    if not parts:
        parts.append(_FALLBACK)

    return "\n\n---\n\n".join(parts) + OUTPUT_CONTRACT


def build_user_prompt(failure):
    """把单条失败 scenario 拼成 user prompt。failure 为 scenario_row dict。"""
    lines = [
        "Analyze ONE failed test scenario and return the JSON described in the OUTPUT CONTRACT.",
        "For evidence, quote or summarize only observable facts from status_message/logs and matched rules; do not reveal chain-of-thought.",
        "",
        "case_key: %s" % failure.get("case_key", ""),
        "host: %s" % failure.get("host", ""),
        "scenario: %s" % failure.get("scenario", ""),
        "status: %s" % failure.get("status", ""),
        "status_message:",
        str(failure.get("status_message", "") or "(empty)"),
    ]
    return "\n".join(lines)
