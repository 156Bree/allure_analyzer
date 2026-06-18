"""analyzer.py —— AI 失败分析编排（降级不阻断）。

对 ``analysis["failures"]`` 逐条：
1) 算指纹 fp = sha1(case|host|scenario|status_message)；
2) 命中缓存（人工锁定项必复用；普通缓存项按 cache 开关复用）→ 直接用旧结果；
3) 否则在 enabled 且有 key 时调 LLM 产出结论/原因/建议/分析依据，写入 store；
4) 把结果回填到失败项（``ai`` / ``ai_fp``），并在 analysis 顶层挂 ``ai_map`` / ``ai_meta``。

任何环节出错都只告警、不抛出，确保 analyze.py 主流程不被打断。
不做字数硬截断：store 保存模型原始输出，网页弹窗展示全文。
"""
import os

from . import store as store_mod
from . import skill_context
from . import llm_client


# 写进 scenario_row.ai / ai_map 的精简字段
_VIEW_FIELDS = ("conclusion", "cause", "suggestion", "evidence", "source", "locked", "model", "updated_at")


def _view(entry):
    return {k: entry.get(k) for k in _VIEW_FIELDS if k in entry}


def _resolve_store_path(ai_cfg, base_dir):
    rel = ((ai_cfg.get("cache") or {}).get("store_path")
           or "trend_data/ai_analysis/store.json")
    if os.path.isabs(rel):
        return rel
    return os.path.normpath(os.path.join(base_dir, rel))


def run_ai_analysis(analysis, config, base_dir, log=print):
    """主入口。原地修改 analysis（写 ai_map / ai_meta，并回填 failures 的 ai 字段）。"""
    ai_cfg = (config or {}).get("ai") or {}
    failures = analysis.get("failures") or []

    ai_map = {}
    meta = {
        "enabled": bool(ai_cfg.get("enabled")),
        "model": ai_cfg.get("model", ""),
        "status": "disabled",
        "total_failures": len(failures),
        "analyzed": 0,    # 本次新调 LLM 成功数
        "reused": 0,      # 命中缓存复用数
        "failed": 0,      # LLM 调用失败数
    }
    analysis["ai_map"] = ai_map
    analysis["ai_meta"] = meta

    if not failures:
        meta["status"] = "no_failures" if meta["enabled"] else "disabled"
        return analysis

    # 缓存始终加载（即使未启用 LLM，也复用历史/人工结果用于展示）
    store_path = _resolve_store_path(ai_cfg, base_dir)
    store = store_mod.Store(store_path)
    cache_enabled = bool((ai_cfg.get("cache") or {}).get("enabled", True))

    enabled = bool(ai_cfg.get("enabled"))
    api_key = str(ai_cfg.get("api_key") or "").strip()
    if not api_key:
        api_key_env = ai_cfg.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env or "OPENAI_API_KEY", "")
    can_call_llm = enabled and bool(api_key)

    # 仅在需要调用 LLM 时解析 skill 路径；system prompt 会按当前 failure 检索相关案例。
    skill_dir = ""
    learned_rel = "references/learned-corrections.md"
    if can_call_llm:
        skill_cfg = ai_cfg.get("skill") or {}
        skill_dir = skill_context.resolve_skill_dir(skill_cfg.get("path", ""), base_dir)
        learned_rel = skill_cfg.get("learned_file", learned_rel)

    model = ai_cfg.get("model", "")
    timeout = int(ai_cfg.get("timeout", 30) or 30)
    max_retries = int(ai_cfg.get("max_retries", 1) or 0)
    base_url = ai_cfg.get("base_url", "")

    for f in failures:
        fp = store_mod.fingerprint(
            f.get("case_key"), f.get("host"), f.get("scenario"), f.get("status_message"))
        f["ai_fp"] = fp

        # 1) 复用缓存：人工锁定项必复用；普通项按 cache 开关
        if store.is_locked(fp) or (cache_enabled and store.has(fp)):
            entry = store.get(fp)
            if entry:
                f["ai"] = _view(entry)
                ai_map[fp] = _merge_identity(entry, f)
                meta["reused"] += 1
                continue

        # 2) 不可调用 LLM → 该项保持“未分析”
        if not can_call_llm:
            continue

        # 3) 调 LLM
        try:
            system_prompt = skill_context.build_system_prompt(skill_dir, learned_rel, failure=f)
            user_prompt = skill_context.build_user_prompt(f)
            result = llm_client.chat_json(
                base_url, api_key, model, system_prompt, user_prompt,
                timeout=timeout, max_retries=max_retries, log=log)
            fields = {
                "case_key": f.get("case_key", ""),
                "host": f.get("host", ""),
                "scenario": f.get("scenario", ""),
                "status_message": f.get("status_message", "") or "",
                "conclusion": str(result.get("conclusion", "")).strip(),
                "cause": str(result.get("cause", "")).strip(),
                "suggestion": str(result.get("suggestion", "")).strip(),
                "evidence": str(result.get("evidence", "")).strip(),
            }
            store.upsert_llm(fp, fields, model)
            entry = store.get(fp)
            f["ai"] = _view(entry)
            ai_map[fp] = _merge_identity(entry, f)
            meta["analyzed"] += 1
        except Exception as e:  # noqa: BLE001
            meta["failed"] += 1
            log("[ai] 分析失败 case=%s host=%s scenario=%s：%s" % (
                f.get("case_key"), f.get("host"), f.get("scenario"), e))

    # 落盘缓存（仅在有变化时）
    try:
        store.save()
    except Exception as e:  # noqa: BLE001
        log("[ai] 缓存写盘失败：%s" % e)

    # 汇总状态
    if not enabled:
        meta["status"] = "disabled"
    elif not api_key:
        meta["status"] = "no_key"
    elif meta["failed"] and not (meta["analyzed"] or meta["reused"]):
        meta["status"] = "error"
    elif meta["failed"]:
        meta["status"] = "partial"
    else:
        meta["status"] = "ok"
    return analysis


def _merge_identity(entry, failure):
    """ai_map 条目：在精简视图基础上补 case/host/scenario/status_message 便于 serve 展示。"""
    out = _view(entry)
    out["case_key"] = entry.get("case_key", failure.get("case_key", ""))
    out["host"] = entry.get("host", failure.get("host", ""))
    out["scenario"] = entry.get("scenario", failure.get("scenario", ""))
    out["status_message"] = entry.get("status_message", failure.get("status_message", "") or "")
    return out
