"""owner.py：从一条记录的 tags 识别 owner。

口径（已与用户确认）：
- owner 信息写在 tag 里（如 Qingting / Marcus）。
- 默认 whitelist_only=True：只认白名单内的名字为 owner —— 绝不臆造 owner，
  识别不到就归 (no-owner)。
- whitelist_only=False 时启用启发式：排除功能词/设备型号(含数字或下划线)/黑名单后，
  满足人名规则(首字母大写、纯字母、长度阈值) 的 tag 也算 owner。
- 可 0 / 1 / 多个 owner。
"""
import re


class OwnerResolver:
    def __init__(self, config):
        oc = config.get("owner", {}) or {}
        self.whitelist = set(oc.get("whitelist", []) or [])
        self.whitelist_only = bool(oc.get("whitelist_only", True))
        self.blacklist = set(oc.get("blacklist", []) or [])
        self.no_owner_label = oc.get("no_owner_label", "(no-owner)")

        rule = oc.get("name_rule", {}) or {}
        self.require_first_upper = bool(rule.get("require_first_upper", True))
        self.alpha_only = bool(rule.get("alpha_only", True))
        self.min_len = int(rule.get("min_len", 3))
        self.max_len = int(rule.get("max_len", 12))

        comp = config.get("component", {}) or {}
        self.functional_tags = set(comp.get("functional_tags", []) or [])
        dev = config.get("device", {}) or {}
        self.model_regex = re.compile(dev.get("model_regex", r"(_|[0-9])"))

    def _looks_like_name(self, t):
        if not t or len(t) < self.min_len or len(t) > self.max_len:
            return False
        if self.require_first_upper and not t[:1].isupper():
            return False
        if self.alpha_only and not t.isalpha():
            return False
        return True

    def resolve(self, tags):
        """返回该记录的 owner 列表（去重保序，可能为空）。"""
        owners, seen = [], set()
        for t in tags or []:
            if t in self.whitelist:
                if t not in seen:
                    seen.add(t); owners.append(t)
        if self.whitelist_only:
            return owners
        # 启发式补充（非白名单模式）
        for t in tags or []:
            if t in seen or t in self.blacklist or t in self.functional_tags:
                continue
            if self.model_regex.search(t):   # 含数字/下划线 → 视为设备型号，非人名
                continue
            if self._looks_like_name(t):
                seen.add(t); owners.append(t)
        return owners
