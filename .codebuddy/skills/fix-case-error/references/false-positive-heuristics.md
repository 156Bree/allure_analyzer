## False Positive Heuristics for Case Failures

Use this checklist when a case failure needs a fast and practical classification.

### Knowledge boundary

- Original scope: simple assertion mismatch, polling/timing mistakes, app-exit verification gaps, weak preconditions, cleanup/file-lock pollution.
- Added scope from the `LIP-1712 / Scenario 09 / YogaS7Ultra` analysis: empty issue lists after successful API calls, Windows privacy/system-setting precondition mistakes, stale scan data, and confusion between adjacent setting layers.
- Added scope from the `LIP-2297 / T14sAMD-3106 / Get-AppUsage` analysis: wrapper-level empty `stdout` / `NoneType.strip()` failures, valid-data branch versus invalid-validation branch comparison, service/DB/mock-data readiness checks, and device-isolated repair gates.
- Fusion rule: added scopes extend the original False Positive heuristics. They do not override the original product-defect escalation boundary. Apply the most specific matching rule first, then verify against the shared escalation boundary.

### Strong signals for implement script error

- Assertion is only a simple mismatch, such as `assert 0 == 4` or `assert 0 == 1`
- API outer response is successful, but inner status is still `running`
- API outer response and inner `errorCode` are successful, but returned `issues` / `scanData` is unexpectedly empty
- Expected code or issue appears later in logs after additional polling or a later sibling scenario
- App close command is sent, but there is no proof that all target apps really exited
- OS privacy or capability setting change is sent, but the script does not verify the authoritative post-change value
- Device-level and app-level settings are inferred from the same helper result or mixed in logs
- Test-tool invocation logs show command and elapsed time, but no raw output line
- Failure happens at `console_result.stdout.strip()` or equivalent wrapper parsing before final product payload exists
- Valid data-query branches fail while invalid parameter-validation branches pass
- Service restart, DB deletion/recreation, mock data insertion, or payload file generation is followed only by fixed `sleep()` without readiness verification
- Teardown reports file lock / cleanup failure
- Test logic depends on fixed `sleep()` duration
- Precondition checks only verify file existence, not actual active target replacement, readable DB/cache, payload JSON, or active system state

### Additional checklist for Windows privacy / system-setting cases

1. Identify the exact expected setting layer, e.g. `Camera access` versus `Let apps access your camera`.
2. Verify each layer independently through an authoritative source before scan starts.
3. Clean or rule out stale DB/cache/previous scan results when the expected output is an issue list.
4. Trigger or observe scan completion after the setting change.
5. Query final issues only after the scan reaches a terminal state.
6. Assert expected `issueDomain` / `issueDefinitionId`, not only `len(issues)`.
7. Compare sibling scenarios on the same device and the same scenario on other devices.

### Additional checklist for empty stdout / API wrapper failures

1. Confirm whether the failure happened before a stable final product payload was returned.
2. Capture command line, working directory, payload file path, payload JSON, `stdout`, `stderr`, `returncode`, elapsed time, and raw response.
3. Compare failing valid-data branches with passing invalid-input branches.
4. Verify service/plugin readiness after restart instead of relying only on fixed sleep.
5. Verify DB/cache/mock data exists, is readable, and matches the branch under test.
6. If retry is needed, keep default common-wrapper behavior unchanged and enable retry only from the affected call site.
7. For device-specific failures, gate the fix by host, case key, API, plugin, and branch so other devices/scenarios keep original behavior.

### Suggested default wording

- **结论**: 该报错优先判定为 False Positive，倾向 implement script error / test infrastructure error。
- **理由**: 当前失败更像断言时机、轮询逻辑、App 关闭后未验证其已真正退出、系统设置前置状态未被权威验证、状态源混淆、DB/cache/mock 数据未就绪，或 API wrapper 空输出处理缺失导致的脚本误判，而非直接证明产品功能缺陷。
- **建议**: 先修复测试实现逻辑，包括终态轮询、App 退出校验、前置校验、系统设置状态源分离、raw stdout/stderr/returncode 打印、cleanup 重试、设备隔离式重试，再复测确认是否仍为真实产品问题。

### When not to use this shortcut

Do not force this classification if evidence already shows:

- terminal-state polling or explicit readiness verification is correct
- app-exit verification is complete and confirms the relevant apps are really closed
- precondition validation is complete
- for system-setting cases, every expected setting layer is verified by an authoritative state source
- DB/cache/stale scan contamination is ruled out
- API wrapper captures `stdout`, `stderr`, `returncode`, command context, and payload before parsing
- branch-specific and device-specific isolation has been checked
- returned final payload is stable and clearly contradicts product expectation
- the same defect reproduces after script-side fixes

In those cases, classify as likely product defect instead.
