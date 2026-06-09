"""classify.py：case key 抽取 + 归一化、component（parentSuite 映射）、jira 链接，以及 case 二元判定工具。

case key 口径（已确认）：
- 按可配置优先级 order（默认 suite → subSuite → links.url）依次尝试，命中即停。
- 用 regex 提取数字，归一化为 LIP-<n>，记录 key_source。
- 全部抽不到 → UNLINKED。

component 口径（已确认，单一归属）：
- 来源字段 = `parentSuite` label（每条记录恰好 1 个）。
- 通过 `component.parent_suite_map` 配置映射到对外 component 名；
  未在映射表内的 parentSuite → (no-component)。
- record.components 仍以 list 表示（0 或 1 个元素），方便下游兼容。

case 二元判定（最严格，已确认"保持现状"）：
- 某 case 在某维度(如某台机器)下，其全部 scenario 记录都 passed 才算 PASS，
  任一非 passed 即 FAIL。只看该维度实际跑的记录子集。
"""
import re


class Classifier:
    def __init__(self, config):
        ck = config.get("case_key", {}) or {}
        self.order = ck.get("order", ["suite", "subSuite", "links.url"])
        self.regex = re.compile(ck.get("regex", r"[Ll][Ii][Pp][-_ ]?(\d+)"))
        self.prefix = ck.get("normalized_prefix", "LIP-")
        self.unlinked = ck.get("unlinked_label", "UNLINKED")

        self.jira_base = (config.get("jira", {}) or {}).get(
            "browse_base", "https://jira.tc.lenovo.com/browse/")

        comp = config.get("component", {}) or {}
        # 新规则：单一 component，来自 parentSuite 映射
        self.parent_suite_map = comp.get("parent_suite_map", {}) or {}
        self.no_component = comp.get("no_component_label", "(no-component)")

    # ---- case key ----
    def _candidates(self, source, rec):
        """返回某来源下用于匹配的候选字符串列表。"""
        if source == "suite":
            return [rec.suite]
        if source == "subSuite":
            return [rec.sub_suite]
        if source == "parentSuite":
            return [getattr(rec, "parent_suite", "")]
        if source == "fullName":
            return [rec.full_name]
        if source == "links.url":
            out = []
            for ln in getattr(rec, "_links", []) or []:
                out.append(ln.get("url", "")); out.append(ln.get("name", ""))
            # story label 也常带 jira 链接，作为 links.url 的补充
            out.extend(getattr(rec, "_story_labels", []) or [])
            return out
        return []

    def extract_case_key(self, rec):
        """返回 (case_key, key_source)。"""
        for source in self.order:
            for s in self._candidates(source, rec):
                if not s:
                    continue
                m = self.regex.search(s)
                if m:
                    return self.prefix + m.group(1), source
        return self.unlinked, "none"

    def jira_url_of(self, case_key):
        if not case_key or case_key == self.unlinked:
            return ""
        return self.jira_base + case_key

    # ---- component（单一归属：parentSuite -> 对外名） ----
    def extract_components(self, rec):
        ps = getattr(rec, "parent_suite", "") or ""
        name = self.parent_suite_map.get(ps, "")
        return [name] if name else []

    # ---- 富化一条记录 ----
    def enrich(self, rec):
        ck, src = self.extract_case_key(rec)
        rec.case_key = ck
        rec.case_key_source = src
        rec.jira_url = self.jira_url_of(ck)
        rec.components = self.extract_components(rec)
        return rec


def case_verdict_pass(records):
    """case 二元判定：给定一组 scenario 记录，全部 passed 才返回 True。"""
    if not records:
        return False
    return all(r.is_pass for r in records)
