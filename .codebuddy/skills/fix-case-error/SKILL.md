---
name: fix-case-error
description: This skill should be used when users ask to analyze a failed test case, especially pytest or Allure failures with simple assertion mismatches such as `AssertionError: assert 0 == 4`, and need a fast judgment on whether the issue is a False Positive caused by implement script error, polling timing, or test logic mistakes rather than a real product defect.
---

# Fix Case Error

## Overview

Classify common case failures quickly. Prioritize identifying False Positive patterns caused by implement script error, asynchronous polling mistakes, weak precondition checks, stale cache, file lock, or cleanup timing problems.

Use this skill when the goal is not to perform deep product root-cause analysis, but to give a practical triage result and a likely code-fix direction for automated test failures.

## Trigger Patterns

Apply this skill when one or more of the following signals appear:

- `AssertionError: assert 0 == 4`
- `AssertionError: assert <actual> == <expected>` where the failure is only a simple numeric mismatch
- Allure / pytest case failures that look like status polling too early
- Case analysis requests that mention **False Positive**, **implement script error**, **script logic**, **polling**, **wait timing**, **cleanup failure**, or **teardown lock**
- Logs showing API success on the outer layer but unexpected inner result during scan / query status flows

## Default Triage Rule

Treat `AssertionError: assert 0 == 4` and similar simple mismatch assertions as **False Positive candidates first**.

Default to the following interpretation unless stronger evidence proves a real product defect:

1. Consider the issue an **implement script error** first.
2. Check whether the test asserted on an **intermediate state** instead of a **terminal state**.
3. Check whether the script used fixed `sleep()` plus one-shot assertion instead of polling until completion.
4. Check whether preconditions were only partially validated.
5. Check whether cleanup, file replacement, cache, or file-lock behavior polluted the result.

Do **not** directly label the issue as a product defect only because the assertion failed. Escalate to product defect only after terminal-state polling and precondition verification still show the same wrong final behavior.

## Recommended Workflow

### 1. Read the failure signature

Extract these fields first:

- case key
- device / host
- scenario name
- assertion line
- expected value and actual value
- any log lines around API request / API response / scan status / teardown

### 2. Apply the fast judgment

If the signature is a simple mismatch like `assert 0 == 4`, output a short conclusion first:

- probable classification: **False Positive**
- likely bucket: **implement script error**
- first suspicion: **polling / wait / assertion timing / precondition logic**

### 3. Check common script-side causes

Inspect in this order:

- fixed `sleep()` followed by one-time status query
- assertion against a non-terminal `running` state
- missing retry loop for async plugin or scan status
- file copy succeeded but target path / signature / active file not actually validated
- cleanup teardown failed and left files locked
- stale process, stale cache, or reused scan result
- assertion message too weak to expose the real returned payload

### 4. Recommend the code-fix direction

Prefer these repair directions:

- replace `sleep(n)` + one-shot assert with **poll until terminal state**
- assert on **final response** instead of intermediate response
- strengthen precondition validation before scan starts
- attach or print raw response payload on failure
- add retry for file restore / cleanup when Windows file lock exists
- separate script issue from product issue by rerunning after polling fix

## Standard Response Style

When using this skill, keep the answer brief and practical. Prefer the following structure:

- **结论**: 优先判定为 False Positive / implement script error
- **原因**: 断言时机过早、轮询缺失、前置校验不足、cleanup/file lock 干扰等
- **修复方向**: 改轮询、查终态、补前置校验、增强日志

## Repair Patterns

### Pattern A: fixed sleep -> polling

Convert this pattern:

```python
response = start_scan()
time.sleep(5)
status = get_status(scan_id)
assert status["errorCode"] == 4
```

Into this pattern:

```python
deadline = time.time() + 90
last_result = None
while time.time() < deadline:
    last_result = get_status(scan_id)
    if str(last_result.get("status", "")).lower() in {"completed", "failed", "cancelled", "canceled"}:
        break
    time.sleep(3)
assert last_result is not None
assert last_result["errorCode"] == 4, last_result
```

### Pattern B: weak precondition -> explicit validation

Add checks for:

- expected source file exists
- target file actually replaced
- signature / hash / timestamp changed as expected
- plugin scans the intended target path

### Pattern C: cleanup lock -> retry

If teardown shows Windows file lock errors, retry cleanup and make the lock visible in logs instead of silently ignoring it.

## Escalation Boundary

Escalate to product defect only when all of the following are true:

- terminal-state polling is already correct
- preconditions are explicitly verified
- file replacement / target path validation is confirmed
- rerun still produces the same wrong final behavior

## References

Load `references/false-positive-heuristics.md` when a quick classification checklist or wording template is needed.
