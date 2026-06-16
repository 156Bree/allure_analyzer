## False Positive Heuristics for Case Failures

Use this checklist when a case failure needs a fast and practical classification.

### Strong signals for implement script error

- Assertion is only a simple mismatch, such as `assert 0 == 4`
- API outer response is successful, but inner status is still `running`
- Expected code appears later in logs after additional polling
- App close command is sent, but there is no proof that all target apps really exited
- Teardown reports file lock / cleanup failure
- Test logic depends on fixed `sleep()` duration
- Precondition checks only verify file existence, not actual active target replacement

### Suggested default wording

- **结论**: 该报错优先判定为 False Positive，倾向 implement script error。
- **理由**: 当前失败更像断言时机、轮询逻辑、App 关闭后未验证其已真正退出，或前置校验不足导致的脚本误判，而非直接证明产品功能缺陷。
- **建议**: 先修复测试实现逻辑，包括终态轮询、App 退出校验、前置校验、原始响应打印和 cleanup 重试，再复测确认是否仍为真实产品问题。

### When not to use this shortcut

Do not force this classification if evidence already shows:

- terminal-state polling is correct
- app-exit verification is complete and confirms the relevant apps are really closed
- precondition validation is complete
- returned final payload is stable and clearly contradicts product expectation
- the same defect reproduces after script-side fixes

In those cases, classify as likely product defect instead.
