# Learned Corrections (人工修正沉淀)

> 本文件由“分析龙虾”每日报告网页里的**人工修正**自动追加（通过 `serve.py` 的“吸收进 skill”操作）。
> 它是 `fix-case-error` skill 的**最高优先级上下文**：自动分析失败 scenario 时优先读取本文件。
> 文件分两层：
> - **通用规则层**：适合跨 case / host / scenario 复用的失败判断模式。
> - **具体案例层**：适合单个 case / host / scenario 的精确经验。
>
> 点击网页里的“吸收进 skill”时，`serve.py` 会让大模型判断应写入哪一层。
> 请勿手工破坏下方 `<!-- rule:... -->` / `<!-- entry:... -->` 标记，`serve.py` 依赖它做幂等更新。

## 1. 通用规则层（跨 case 可复用）

<!-- general-rules-start -->


<!-- rule:fp=dd6c09b0454663a025287d990705689603538634 -->
## 通用规则：Check stdout is not empty before calling strip()

- **适用特征**: When executing external commands via subprocess and then parsing stdout, always verify that stdout is not None and not empty before calling string methods that assume a non-None string.
- **判断依据**: AttributeError: 'NoneType' object has no attribute 'strip'
- **推荐结论**: 脚本错误/基础设施错误
- **原因模板**: valid pastDuration分支test tool返回空stdout，wrapper直接strip()导致AttributeError
- **建议模板**: 在wrapper中先判断stdout非空再strip，或对T14sAMD-3106的LIP-2297有效参数分支增加设备隔离诊断与重试
- **适用边界**: This rule applies to any wrapper that processes command output; exceptions may exist if the command is guaranteed to always produce output, but defensive coding is safer.
- **来源案例**: LIP-2297 · T14sAMD-3106 · Scenario 04: pastDuration is 7d
- **来源**: manual · 吸收时间 2026-06-17T15:38:40
<!-- /rule:fp=dd6c09b0454663a025287d990705689603538634 -->

<!-- rule:fp=cbae9c427a91d64f415d7f40e94034960849aead -->
## 通用规则：Poll for asynchronous scan completion instead of using fixed sleep when asserting issue counts

- **适用特征**: All test steps where an action triggers an asynchronous scan, and subsequent assertions depend on the scan's results (e.g., issue count).
- **判断依据**: AssertionError: assert 0 == 3
- **推荐结论**: 优先判定为 False Positive
- **原因模板**: 断言时扫描未终态，实际返回0个issues而预期3个，根因是异步扫描未轮询完成。
- **建议模板**: 将固定sleep改为轮询扫描终态，验证system setting后再查询issues。
- **适用边界**: Only applicable when the system under test performs background scans; not needed for synchronous operations or when the test framework provides a built-in wait for scan events.
- **来源案例**: LIP-1730 · THINKBOOK53306 · Scenario 01: Fix issues Remediate action when Camera all user access settings is disable
- **来源**: manual · 吸收时间 2026-06-17T15:37:55
<!-- /rule:fp=cbae9c427a91d64f415d7f40e94034960849aead -->

<!-- rule:fp=36798c64cf3b23a4ac9d21763f3ab825d261b85a -->
## 通用规则：Poll for scan final state after privacy setting changes and verify both device-level and app-level camera settings separately

- **适用特征**: After modifying Windows camera privacy settings that involve a scanning process and separate device/app controls, tests must poll until the scan reaches a final state and then verify both the device-level and app-level settings.
- **判断依据**: AssertionError: assert 0 == 1
- **推荐结论**: False Positive（测试脚本错误）
- **原因模板**: 设置改变后扫描未完成，且未验证设备级与应用级设置分离。
- **建议模板**: 轮询扫描终态，并分别验证设备级和应用级摄像头设置。
- **适用边界**: Not applicable if the setting change is synchronous and does not have a scanning delay, or if there is no device/app level separation.
- **来源案例**: LIP-1712 · YogaS7Ultra · Scenario 09: disable camera access in windows privacy setting
- **来源**: manual · 吸收时间 2026-06-17T15:37:42
<!-- /rule:fp=36798c64cf3b23a4ac9d21763f3ab825d261b85a -->

<!-- general-rules-end -->

## 2. 具体案例层（单 case 精确经验）

<!-- case-examples-start -->



<!-- entry:fp=7795d7a319edf09ee523b436823dc654ca2457c1 -->
## LIP-2343 · X13G6-002217 · Scenario 04: Scan Device Health with "scanLevel" is 3 and is

- **Case**: LIP-2343
- **Host**: X13G6-002217
- **Scenario**: Scenario 04: Scan Device Health with "scanLevel" is 3 and issueDomain is child level domain
- **Status message (摘要)**: AssertionError: assert 3 == 0
- **结论**: False Positive/implement script error
- **原因**: 断言3==0，扫描可能在非终态时被断言，预期count与实际0不匹配
- **建议**: 改为轮询扫描至终态后再断言，并验证scanLevel和issueDomain参数生效
- **分析依据**: status_message=AssertionError: assert 3 == 0，匹配基线False Positive启发式，无日志证明扫描已完成
- **来源**: manual · 吸收时间 2026-06-18T14:40:12
<!-- /entry:fp=7795d7a319edf09ee523b436823dc654ca2457c1 -->

<!-- entry:fp=29d44366f6becb10d929f38d764ba613c2e2cc6f -->
## LIP-1193 · THINKBOOK53306 · Scenario 04: Get-Usage return within 1 seconds

- **Case**: LIP-1193
- **Host**: THINKBOOK53306
- **Scenario**: Scenario 04: Get-Usage return within 1 seconds
- **Status message (摘要)**: sqlite3.ProgrammingError: Incorrect number of bindings supplied. The current statement uses 3, and there are 0 supplied.
- **结论**: implement script error
- **原因**: SQLite执行时参数绑定错误，语句需要3个参数但提供了0个。
- **建议**: 检查SQL调用代码，确保提供正确的绑定参数。
- **分析依据**: status_message: sqlite3.ProgrammingError: Incorrect number of bindings supplied. The current statement uses 3, and there are 0 supplied.
- **来源**: manual · 吸收时间 2026-06-17T17:37:56
<!-- /entry:fp=29d44366f6becb10d929f38d764ba613c2e2cc6f -->

<!-- case-examples-end -->
