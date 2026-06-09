"""配置加载：优先读外部 config.yaml（需 PyYAML），缺失则回落到内置默认值。

内置默认值与 config.yaml 完全等价，保证“没装 PyYAML 也能跑”。
"""
import os

# ----------------------------------------------------------------------------
# 内置默认配置（与同目录 config.yaml 保持一致）
# ----------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "case_key": {
        "order": ["suite", "subSuite", "links.url"],
        "regex": r"[Ll][Ii][Pp][-_ ]?(\d+)",
        "normalized_prefix": "LIP-",
        "unlinked_label": "UNLINKED",
    },
    "jira": {
        "browse_base": "https://jira.tc.lenovo.com/browse/",
    },
    "owner": {
        "whitelist": ["Steven", "Marcus", "Qingting", "Judy"],
        "whitelist_only": True,
        "blacklist": [],
        "no_owner_label": "(no-owner)",
        "name_rule": {
            "require_first_upper": True,
            "alpha_only": True,
            "min_len": 3,
            "max_len": 12,
        },
    },
    "component": {
        "source": "parentSuite",
        "parent_suite_map": {
            "tests.test_hw_insight": "UDC plugin HW Insight",
            "tests.test_app_insight": "UDC Plugin -APP Insight",
        },
        "no_component_label": "(no-component)",
    },
    "device": {
        "model_regex": r"(_|[0-9])",
        "display_map": {},
    },
    "status": {
        "passed_values": ["passed"],
        "fail_values": ["failed", "broken", "unknown", "skipped"],
    },
    "thresholds": {
        "pass_rate_good": 0.90,
        "pass_rate_warn": 0.70,
    },
    "top_n": 10,
}


def _deep_merge(base, override):
    """用 override 递归覆盖 base（dict 深合并，其余直接替换）。"""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(config_path=None):
    """加载配置。

    config_path 指定且存在且 PyYAML 可用时读取并与默认值深合并；
    否则返回内置默认（并在无法读取时打印提示，不中断）。
    """
    if not config_path:
        return dict(DEFAULT_CONFIG)
    if not os.path.isfile(config_path):
        print("[config] 未找到 %s，使用内置默认配置。" % config_path)
        return dict(DEFAULT_CONFIG)
    try:
        import yaml  # type: ignore
    except ImportError:
        print("[config] 未安装 PyYAML，无法读取 %s，使用内置默认配置。"
              "（pip install PyYAML 可启用外部配置）" % config_path)
        return dict(DEFAULT_CONFIG)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        return _deep_merge(DEFAULT_CONFIG, user_cfg)
    except Exception as e:  # noqa: BLE001
        print("[config] 读取 %s 失败(%s)，使用内置默认配置。" % (config_path, e))
        return dict(DEFAULT_CONFIG)
