"""analyzer.ai —— AI 失败分析子包（纯标准库，缺失/失败全程降级不阻断）。

模块组成：
- ``store``：指纹缓存读写（``trend_data/ai_analysis/store.json``），locked/manual 语义。
- ``skill_context``：读取 fix-case-error skill 的 ``SKILL.md`` + ``references/*.md`` 拼 system prompt。
- ``llm_client``：OpenAI 兼容 ``/chat/completions``（urllib），超时/重试/JSON 解析容错。
- ``analyzer``：编排——对 failures 比对缓存，仅新增/变化未锁定项调 LLM，回填 ai_map。

对外主入口：``analyzer.ai.run_ai_analysis``。
"""
from .analyzer import run_ai_analysis  # noqa: F401
from . import store, skill_context, llm_client  # noqa: F401

__all__ = ["run_ai_analysis", "store", "skill_context", "llm_client"]
