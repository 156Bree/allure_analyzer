"""数据模型：TestCaseRecord 表示一条 scenario 执行记录（= 一个 test-cases/*.json 文件）。

口径要点：
- 数据单元 = data/test-cases/*.json 全部记录，(host, history_id) 作唯一键。
- scenario 唯一键 = history_id（name 仅作展示）。
- case 唯一键 = 归一化后的 case_key（LIP-<n> 或 UNLINKED）。
- 对外状态只分 Pass / Fail：is_pass = status in passed_values；其余(含 broken)计 Fail。
"""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class TestCaseRecord:
    uid: str = ""
    name: str = ""                 # scenario 展示名
    full_name: str = ""
    history_id: str = ""           # scenario 唯一键

    status: str = ""               # 原始状态 passed/failed/broken/...
    is_pass: bool = False          # 二元口径：是否 passed

    host: str = ""                 # 机器维度键（host label）
    host_display: str = ""         # 机器美化显示名（缺映射=host 原值）

    owners: List[str] = field(default_factory=list)   # 0/1/多 owner
    components: List[str] = field(default_factory=list)  # 单一归属：来自 parentSuite 映射，0 或 1 个

    tags: List[str] = field(default_factory=list)
    severity: str = ""
    feature: str = ""
    suite: str = ""
    sub_suite: str = ""
    parent_suite: str = ""         # parentSuite label，component 来源
    package: str = ""

    duration_ms: int = 0
    retries_count: int = 0
    flaky: bool = False

    case_key: str = ""             # "LIP-690" / "UNLINKED"
    case_key_source: str = ""      # suite / subSuite / links.url / none

    status_message: str = ""       # 失败信息（供未来 fail 原因分析）
    log_links: List[Dict[str, str]] = field(default_factory=list)  # Allure attachment/log 轻量链接
    log_preview: str = ""          # 关联 log 前几行预览
    hidden: bool = False           # Allure hidden 标记（visible 子集对账用）

    jira_url: str = ""             # case 对应 Jira 链接（UNLINKED 时为空）

    # ---- 派生便捷属性 ----
    @property
    def status_label(self):
        """对外两态：Pass / Fail。"""
        return "Pass" if self.is_pass else "Fail"

    @property
    def owners_display(self):
        return self.owners if self.owners else []
