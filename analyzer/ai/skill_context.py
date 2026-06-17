"""skill_context.py —— 读取 fix-case-error skill 内容，拼成 LLM 的 system prompt。

约定：
- ``SKILL.md`` 作为主领域知识与“AI 自动分析输出规范(§5)”。
- ``references/learned-corrections.md`` 为**最高优先级**人工修正沉淀，置于上下文最前。
- 其余 ``references/*.md`` 作为补充。
缺失文件全部跳过；整体缺失时回落到一段最简内置指令，保证不阻断。
"""
import os
import glob


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


def build_system_prompt(skill_dir, learned_file_rel="references/learned-corrections.md"):
    """读取 skill 内容拼 system prompt。返回字符串（必含 OUTPUT CONTRACT）。"""
    parts = []
    learned_abs = ""
    if skill_dir and os.path.isdir(skill_dir):
        # 1) learned-corrections 最高优先
        learned_abs = os.path.join(skill_dir, learned_file_rel)
        learned = _read(learned_abs)
        if learned.strip():
            parts.append("# HIGHEST-PRIORITY HUMAN CORRECTIONS "
                         "(reuse matching judgment first)\n" + learned)
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
