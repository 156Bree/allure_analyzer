---
name: fix-case-error
description: This skill should be used when users ask to analyze a failed test case, especially pytest or Allure failures with simple assertion mismatches such as `AssertionError: assert 0 == 4`, `AssertionError: assert 0 == 1`, empty result mismatches, broken cases caused by `NoneType` / empty stdout in test-tool invocation, service restart or DB readiness gaps, and need a fast judgment on whether the issue is a False Positive caused by implement script error, polling timing, weak precondition verification, app-exit verification gaps, stale data, API wrapper robustness gaps, device-specific data-state issues, or test logic mistakes rather than a real product defect.
---

# Fix Case Error

## 1. Module Definition

### 1.1 Purpose

Classify common automated test failures quickly and recommend practical code-fix directions. Prioritize identifying **False Positive / implement script error / test infrastructure error** patterns caused by:

- simple assertion mismatches
- asynchronous polling or fixed-wait mistakes
- weak precondition verification
- missing app-exit verification
- stale cache / stale DB / reused scan result
- DB deletion / recreation readiness gaps after service or plugin restart
- service-control timeout or process-readiness assumptions
- file lock and cleanup timing problems
- confusing adjacent Windows system-setting state sources
- API wrapper robustness gaps, such as empty `stdout` / `NoneType` when invoking a test tool
- device-specific setup or data-state instability that must be isolated from other devices

Use this skill when the goal is practical triage and repair guidance for pytest / Allure failures, not full product internals root-cause analysis.

### 1.2 Classification Principle

Default to **False Positive candidate first** when the failure signature points to test implementation, timing, setup, data state, service/plugin readiness, DB/cache readiness, or wrapper handling rather than a stable final product response.

Do **not** directly label the issue as a product defect only because the case failed. Escalate only after terminal-state polling, precondition verification, app-exit verification, service/plugin readiness verification, stale-state cleanup, wrapper diagnostics, and final-payload stability are all confirmed.

### 1.3 Knowledge Boundary

This module contains four layers of experience:

1. **Historical baseline experience**: generic assertion mismatch, polling, app-exit, precondition, cleanup, file-lock, stale-state, and DB/cache readiness triage.
2. **Previously integrated specialized experience**: `LIP-1712 / Scenario 09 / YogaS7Ultra` camera privacy setting analysis.
3. **Previously integrated specialized experience**: `LIP-2297 / T14sAMD-3106 / Get-AppUsage` empty `stdout` / `NoneType.strip()` analysis.
4. **Newly integrated specialized experience**: `LIP-2195 / X1-CarbG14-3514 / Device Usage Collection / Scenario 10` AppInsights killed/restart and current-hour activity readiness analysis.

The latest experience extends the baseline and the prior specialized rules. It must not override or delete older rules. When multiple rules match, apply the most specific signature rule first, then validate it against the generic escalation boundary.

### 1.4 Required Output Shape When Updating This Skill

When new case experience is added to this module, keep these four core blocks intact:

1. **Module Definition**: purpose, classification principle, knowledge boundary.
2. **Historical Experience Zone**: baseline and already integrated specialized experience.
3. **Newly Integrated Experience Zone**: latest case-specific experience, boundary, branch diagnosis, repair heuristic, isolation rule.
4. **Fusion Application Strategy**: integration map, decision order, conflict priority, repair patterns, escalation boundary.

## 2. Historical Experience Zone

### 2.1 Baseline Fast-Triage Experience

Use the following baseline for common case failures:

- Treat simple mismatches such as `AssertionError: assert 0 == 4`, `assert 0 == 1`, or `len([]) == 1` as False Positive candidates first.
- Check whether the test asserted on an intermediate state instead of a terminal state.
- Replace fixed `sleep()` plus one-shot query with polling until a terminal status or explicit readiness condition.
- Strengthen preconditions beyond file existence: validate target path, active replacement, signature/hash/timestamp, process/session state, DB/cache state, and payload domain.
- Verify that app-close actions really closed all relevant apps, sessions, foreground windows, or processes.
- Treat cleanup failure, file lock, stale process, stale cache, stale DB, and reused scan results as likely script-side pollution until ruled out.
- Treat service restart, plugin restart, DB deletion/recreation, mock data insertion, or payload generation as asynchronous setup unless the script proves readiness.
- Print or attach raw final payloads on failure so the next triage sees returned `stdout`, `stderr`, response JSON, DB/API state, service status, and timing.

### 2.2 Previously Integrated Experience: `LIP-1712 / Scenario 09 / YogaS7Ultra`

Boundary: this experience applies to Windows privacy / system-setting scenarios, especially when expected issues are missing after successful API calls.

Key lessons:

- `issues=[]` after successful outer API calls is still a False Positive candidate if scan timing or setting preconditions are not proven.
- Separate setting layers, e.g. device-level `Camera access` vs app-level `Let apps access your camera`.
- A log proving one setting layer changed does not prove another setting layer changed.
- After setting changes, explicitly trigger or observe scan completion before querying final issues.
- Clean or rule out stale DB/cache/previous scan result before concluding the product missed an issue.

Fusion with baseline:

- It extends **weak precondition** checks into **authoritative Windows setting source** checks.
- It extends **polling** from generic async status to **post-setting-change scan terminal-state verification**.
- It does not relax the product-defect escalation boundary.

### 2.3 Previously Integrated Experience: `LIP-2297 / T14sAMD-3106 / Get-AppUsage`

Boundary: this experience applies when Allure / pytest reports show `LIP-2297` failures on host `T14sAMD-3106`, especially in `Get-AppUsage` valid `pastDuration` scenarios.

Observed failure signature:

- Case result: `Fail, 5/12 passed`.
- Failed scenarios: valid `pastDuration` paths, such as empty, `null`, `1D`, `7d`, `2M`, `2y`, and performance scenario.
- Passed scenarios: invalid parameter validation paths, such as `3651D`, `121M`, `11Y`, and invalid JSON.
- Shared error: `AttributeError: 'NoneType' object has no attribute 'strip'`.
- Shared failing line: API wrapper calls `console_result.stdout.strip()` after `PluginApiTestExe.exe` invocation.
- Logs show `Invoking API` and `Time consumption`, but no `output from test tool` before failure.

Core branch diagnosis:

```text
valid pastDuration
  -> plugin enters AppUsage DB / mock data query path
  -> on T14sAMD-3106, test tool may return empty or None stdout during this path
  -> common wrapper directly calls stdout.strip()
  -> AttributeError masks the real plugin/test-tool state

invalid pastDuration / invalid JSON
  -> plugin enters request validation path
  -> test tool returns normal JSON with errorCode=1
  -> case passes
```

Key lessons:

- The evidence does not prove a stable product logic defect.
- The first suspect is the test invocation wrapper plus device-specific data/readiness state.
- Fixed sleeps after service restart and mock DB insertion are insufficient if the script does not prove the plugin, DB, and test-tool output are ready.
- Empty `stdout` is itself a diagnostic object and must not be converted into an unrelated `AttributeError`.

Wrapper-boundary heuristic:

When a report shows `AttributeError: 'NoneType' object has no attribute 'strip'` at a common API wrapper line such as `console_result.stdout.strip()`:

1. Classify as **broken by test infrastructure or wrapper handling** before product defect.
2. Inspect `returncode`, `stdout`, `stderr`, command line, working directory, payload file path, payload JSON, elapsed time, and retry behavior.
3. Compare passing and failing parameter branches to identify whether only data-query paths fail while validation paths pass.
4. Validate service/plugin readiness and DB/cache/file-lock state before invoking the API.
5. If adding retry or diagnostics, keep it opt-in or narrowly scoped to the affected device/scenario to avoid hiding real failures elsewhere.

Device-isolation requirement:

- target host equals `T14sAMD-3106`
- target case or context equals `LIP-2297`
- target API equals `Get-AppUsage`
- target plugin equals `AppInsightsPlugin`
- target branch equals valid `pastDuration`, e.g. `None`, empty string, `1D`, `7d`, `2M`, or `2y`
- invalid parameter scenarios must keep the original behavior
- non-target devices must keep the original behavior

If a code fix changes common wrappers, default behavior must remain unchanged unless the caller explicitly enables the new handling.

## 3. Newly Integrated Experience Zone

### 3.1 New Case: `LIP-2195 / X1-CarbG14-3514 / Device Usage Collection / Scenario 10`

Boundary: this experience applies when Allure / pytest reports show `LIP-2195` failures on host `X1-CarbG14-3514`, especially `Scenario 10: App insight killed by accidentally` in `tests.test_app_insight.test_lip2195_device_usage_collection.TestLIP2195DeviceUsageCollection`.

Observed failure signature:

- Case result: `Fail, 3/4 passed`.
- Passed scenarios: normal device/user activity collection scenarios such as `Scenario 04: session activity within 1 hour`, `Scenario 05: session activity across 2 hours`, and `Scenario 06: session activity across 2 days`.
- Failed scenario: `Scenario 10: App insight killed by accidentally`.
- Failure form A: `AssertionError: assert False`, where `__is_user_active_at_current_hour(None)` receives `None` from `__get_today_device_activity()` after AppInsights DB deletion and UDC/AppInsights restart.
- Failure form B: `pywintypes.error: (1053, 'ControlService', 'The service did not respond to the start or control request in a timely fashion.')` from `win32serviceutil.StopService()` while stopping `UDCService`.
- Logs show `UDCService` stop/start and deletion of `app-insights-plugin.sqlite3`, then failure with `输入值无效` from `__is_user_active_at_current_hour`; they do not prove that the rebuilt DB has a current-hour activity row.

### 3.2 Core Branch Diagnosis

The important branch split is:

```text
Scenario 04 / 05 / 06 normal collection paths
  -> Windows lock / session activity setup
  -> existing AppInsights DB and collection pipeline remain available
  -> __get_today_device_activity() / __get_today_user_activity() return usable records
  -> __is_user_active_at_current_hour(...) passes

Scenario 10 AppInsights killed / restart path
  -> delete_app_usage_db_file_restart_app_insight_plugin()
  -> stop UDCService and delete app-insights-plugin.sqlite3
  -> start UDCService and wait until AppInsights process is back
  -> fixed sleep(10)
  -> query today's device/user activity immediately
  -> rebuilt DB or current-hour row may not be ready on X1-CarbG14-3514
  -> __get_today_device_activity() returns None
  -> __is_user_active_at_current_hour(None) fails with input invalid
```

Service-control sub-branch:

```text
UDCService stop path
  -> ServiceManager.stop(60)
  -> win32serviceutil.StopService('UDCService')
  -> Windows service control may return 1053 on X1-CarbG14-3514
  -> script raises immediately
  -> no follow-up status polling proves whether service eventually stopped
```

Interpretation:

- The evidence does not yet prove a stable AppInsights product defect.
- The first suspect is script-side readiness validation after DB deletion and service/plugin restart.
- `wait_until_appinsight_process_backon()` only proves process presence, not DB file recreation, DB readability, schema readiness, or current-hour activity data availability.
- `time.sleep(10)` is a weak timing assumption and is device-sensitive.
- `None` activity is a diagnostic state. It must be preserved in assertion messages instead of being collapsed into a generic `assert False`.
- `ControlService 1053` during stop is a service-control boundary issue. It should be handled by explicit final status verification only when the affected scenario opts in.

### 3.3 New Heuristic: DB Deletion + Restart Requires Data-Readiness Polling

When a case deletes AppInsights / UDC plugin DB files or restarts `UDCService` / `AppInsightsPlugin`, do not treat process restart as sufficient readiness.

Before asserting product behavior, verify all relevant readiness layers:

1. `UDCService` final state is expected, such as `STOPPED` before deletion and `RUNNING` after restart.
2. AppInsights process/plugin is back only as a process-level signal, not a data-level signal.
3. Deleted DB file is recreated or the intended storage source is available.
4. DB is readable and not locked.
5. Required tables/schema exist when directly queried.
6. The current branch's expected data exists, such as current-hour `device_activity` and `user_activity` records.
7. The final assertion includes the last observed raw activity payload when readiness times out.

If the only evidence is `__is_user_active_at_current_hour(None)` after `sleep(10)`, classify as **readiness/polling gap first**.

### 3.4 New Heuristic: `ControlService 1053` Needs Final State Verification Before Broken Classification

When stopping a Windows service during test setup and `win32serviceutil.StopService()` raises `pywintypes.error` code `1053`:

1. Do not immediately conclude product failure if the operation is part of test setup or DB cleanup.
2. Query and poll the final service state before failing the case.
3. Only tolerate this condition when the caller explicitly opts in for a known service-control boundary.
4. Do not swallow other service errors or non-target service failures.
5. If final service state does not reach the expected state within timeout, fail with service name, expected state, last status, timeout, and original exception.

This heuristic extends the baseline cleanup/file-lock rule into the Windows service-control layer.

### 3.5 Device-Isolation Requirement From `LIP-2195`

A device-specific repair must include explicit boundaries:

- target host equals `X1-CarbG14-3514`
- target case or context equals `LIP-2195`
- target API/domain equals `Device Usage Collection`
- target plugin equals `AppInsightsPlugin`
- target scenario equals `Scenario 10: App insight killed by accidentally`
- target branch includes `delete_app_usage_db_file_restart_app_insight_plugin()` or equivalent AppInsights DB deletion + UDC/AppInsights restart flow
- normal collection scenarios such as Scenario 04/05/06 must keep original behavior unless they independently show readiness gaps
- non-target devices must keep original behavior unless the same signature is reproduced

If a code fix changes common service or AppInsights helpers, default behavior must remain unchanged unless the caller explicitly enables the new handling.

### 3.6 Recommended Code-Fix Direction From `LIP-2195`

Prefer this repair shape:

- Replace `time.sleep(10)` after AppInsights restart with polling for current-hour activity readiness.
- Add a helper such as `__wait_until_current_hour_activity_ready(timeout_seconds, interval_seconds)` near `TestLIP2195DeviceUsageCollection`.
- Preserve final assertions but add raw `device_activity` and `user_activity` payloads to assertion messages.
- Add opt-in service stop tolerance, e.g. `tolerate_stop_timeout=True`, only from the affected Scenario 10 call site.
- Extend `ServiceManager.stop()` with optional `tolerate_control_timeout=False` default, and only for `1053` perform final service-state polling.
- Keep the default path strict so unrelated cases continue to expose real service failures.

## 4. Fusion Application Strategy

### 4.1 Experience Integration Map

| Layer | Historical baseline | `LIP-1712` privacy-setting extension | `LIP-2297` empty-stdout extension | `LIP-2195` DB/restart readiness extension | Unified fusion rule |
| --- | --- | --- | --- | --- | --- |
| Failure shape | Simple mismatch is a False Positive candidate. | Empty `issues` after successful API can still be script-side. | `NoneType.strip()` / empty `stdout` in wrapper is infrastructure/script-side first. | `__is_user_active_at_current_hour(None)` after DB deletion/restart is readiness/script-side first. | Identify whether the failure happened before a stable final product payload exists. |
| Timing | Replace fixed `sleep()` with terminal-state polling. | After setting changes, observe scan completion. | After service restart / DB mock insertion, verify plugin/test-tool output readiness or retry narrowly. | After DB deletion and AppInsights restart, poll DB/data readiness, not only process presence. | Fixed waits are weak unless readiness or terminal state is proven. |
| Preconditions | Verify files, paths, processes, signatures, cleanup state. | Verify authoritative Windows setting layer. | Verify DB existence/readability, payload JSON, command context, stdout/stderr. | Verify service final state, DB recreation/readability, current-hour activity records. | Preconditions must match the actual branch under test. |
| Branch comparison | Compare sibling scenarios and devices. | Compare setting layers and related issue domains. | Compare valid data-query branches vs invalid validation branches. | Compare normal collection scenarios vs kill/restart scenario and same-device history. | Branch-specific pass/fail split often exposes setup or wrapper gaps. |
| Isolation | Avoid global fixes that mask defects. | Keep setting-source helpers separated. | Gate retry/empty-output handling by device/API/case/branch. | Gate service timeout tolerance and readiness polling by affected restart scenario. | Apply the narrowest safe fix; common helper defaults must remain stable. |
| Diagnostics | Add raw payloads on failure. | Include setting source and scan result. | Include command, returncode, stdout, stderr, payload path. | Include last service status, DB path/readability, last device/user activity payload. | Diagnostic information must preserve the real failing state. |
| Escalation | Escalate only after script-side causes are ruled out. | Escalate after setting, scan, cache, and payload are verified. | Escalate after wrapper diagnostics, readiness checks, retry, and final payload are stable. | Escalate after service state, DB readiness, and current-hour activity polling are stable. | New rules refine, not replace, the original escalation boundary. |

### 4.2 Decision Order

When analyzing a failed case:

1. Read the failure signature and locate whether failure happened in test code, wrapper code, service-control code, API response parsing, DB/data readiness, or final product assertion.
2. If the failure is a simple assertion mismatch or empty result, apply the baseline False Positive triage.
3. If Windows setting changes are involved, apply the `LIP-1712` setting-source separation rules.
4. If the failure is `NoneType.strip()` / empty `stdout` / missing raw output after test-tool invocation, apply the `LIP-2297` wrapper-boundary rules.
5. If the failure happens after AppInsights/UDC DB deletion or service/plugin restart and activity data is `None` or missing, apply the `LIP-2195` DB/restart readiness rules.
6. If Windows service stop/start returns `1053` during setup/cleanup, apply the `LIP-2195` service-control final-state verification rule before classifying as broken.
7. Compare sibling scenarios, parameter branches, same-device history, and cross-device results when available.
8. Recommend the narrowest repair with explicit boundaries and diagnostics.
9. Escalate only when the corrected script still produces a stable final payload contradicting the product expectation.

### 4.3 Conflict Handling and Priority Rules

Use these rules when multiple experiences appear to match:

1. **Failure-location priority**: classify by the exact failing line first.
   - `stdout.strip()` / JSON parse wrapper failure -> use `LIP-2297` wrapper rules.
   - `__is_user_active_at_current_hour(None)` after DB deletion/restart -> use `LIP-2195` readiness rules.
   - empty `issues` after Windows setting changes -> use `LIP-1712` setting-source rules.
2. **Most-specific boundary priority**: if case key, host, API/plugin, and scenario match a specialized experience, apply that specialized rule before generic baseline rules.
3. **No override of escalation boundary**: specialized rules may add checks, polling, diagnostics, or isolation, but must not skip the baseline requirement to prove terminal state and stable final payload before product-defect escalation.
4. **Opt-in repair priority**: changes to common wrappers, service managers, or shared AppInsights helpers must default to old behavior. Enable new retries/tolerance only from the affected call site or with explicit parameters.
5. **Data-readiness before assertion**: if setup deletes DB/cache or restarts service/plugin, readiness polling outranks immediate final assertions.
6. **Diagnostics before masking**: retry or tolerance must log original exception/state and preserve last raw payload; never convert a diagnostic state into an unrelated generic assertion.
7. **Branch-preservation priority**: passing sibling branches and invalid-input validation branches must keep original behavior unless their own evidence matches the same failure signature.
8. **Device-isolation priority**: device-specific instability should not be generalized to all devices unless reproduced with the same branch and signature.

### 4.4 Trigger Patterns

Apply this skill when one or more of the following signals appear:

- `AssertionError: assert 0 == 4`
- `AssertionError: assert 0 == 1`
- `AssertionError: assert <actual> == <expected>` where the failure is only a simple numeric mismatch
- `len([])` or empty `issues` / `scanData` mismatches after an API call returned `isSuccess=true` and `errorCode=0`
- `AttributeError: 'NoneType' object has no attribute 'strip'` at `stdout.strip()` or API wrapper parsing
- `__is_user_active_at_current_hour(None)` or similar helper receiving `None` after DB deletion/restart
- `pywintypes.error: (1053, 'ControlService', ...)` during service stop/start in setup or cleanup
- API/test-tool logs show command invocation and elapsed time but no raw output line
- Allure / pytest case failures that look like status polling too early
- Case analysis requests that mention **False Positive**, **implement script error**, **script logic**, **polling**, **wait timing**, **app close verification**, **cleanup failure**, **teardown lock**, **Windows privacy setting**, **system setting precondition**, **empty stdout**, **PluginApiTestExe**, **API wrapper**, **service restart**, **DB deletion**, **DB readiness**, **AppInsights restart**, or **device isolation**
- Logs showing API success on the outer layer but unexpected inner result during scan / query status flows
- Failures after `close app` style operations where the script never proves that the relevant apps are truly gone
- Failures after changing OS settings where the script does not prove that the expected setting layer really changed
- Failures after service restart, DB deletion/recreation, mock data insertion, or payload file generation where readiness is assumed by fixed sleep

### 4.5 Default Triage Rule

Treat `AssertionError: assert 0 == 4`, `assert 0 == 1`, `len([]) == 1`, wrapper-level `NoneType.strip()`, and post-restart `None` activity failures as **False Positive candidates first** unless stronger evidence proves a real product defect.

Default to the following interpretation:

1. Consider the issue an **implement script error / test infrastructure error** first.
2. Check whether the test asserted on an intermediate state instead of a terminal state.
3. Check whether the script used fixed `sleep()` plus one-shot assertion instead of polling or readiness verification.
4. Check whether preconditions were only partially validated.
5. Check whether the case assumed an app/service/plugin/DB was ready without proving it.
6. Check whether the case assumed the app was closed without verifying that all target apps had exited.
7. Check whether cleanup, file replacement, cache, stale DB, file lock, or reused scan result polluted the output.
8. For Windows/system-setting cases, check whether adjacent setting layers or state sources were confused.
9. For API wrapper failures, check whether `stdout`, `stderr`, `returncode`, payload, and command context were captured before parsing.
10. For service/plugin restart failures, check whether final service status, DB recreation/readability, and branch-specific data readiness were proven.

### 4.6 Recommended Workflow

#### 4.6.1 Read the Failure Signature

Extract these fields first:

- case key
- device / host
- scenario name
- assertion or exception line
- expected value and actual value, if any
- whether failure occurred before final product payload was available
- whether actual data is empty, stale, intermediate, from the wrong domain, or missing due to wrapper or readiness failure
- command line, payload file, `stdout`, `stderr`, `returncode`, elapsed time, and raw response when available
- service name, service command, final service state, original service-control exception when available
- DB/cache path, deletion/recreation logs, readability, schema/table state, and last queried rows when available
- logs around API request / API response / scan status / setting change / app close / service restart / DB operation / teardown

#### 4.6.2 Apply Fast Judgment

If the signature is a simple mismatch, empty list, wrapper-level empty output, or post-restart missing data:

- probable classification: **False Positive**
- likely bucket: **implement script error / test infrastructure error**
- first suspicion: **polling / wait / assertion timing / app-exit verification / precondition logic / state-source confusion / stale DB / DB readiness / service readiness / API wrapper robustness / device-specific readiness**

#### 4.6.3 Check Common Script-Side Causes

Inspect in this order:

- fixed `sleep()` followed by one-time query
- assertion against a non-terminal `running` or process-present state
- missing retry loop for async plugin, scan status, DB readiness, or known empty-output wrapper boundary
- setting change was requested, but the script never verified the authoritative post-change value
- device-level and app-level setting states are mixed in one helper function or one assertion
- app close action was sent, but the script never verified that all target apps had really exited
- file copy succeeded but target path / signature / active file was not validated
- cleanup teardown failed and left files locked
- service restart, DB recreation, mock data insertion, or cache cleanup was assumed ready without verification
- wrapper parsed `stdout` without checking `None`, empty string, `stderr`, `returncode`, or raw payload
- service-control timeout was raised without checking final service state
- assertion message too weak to expose the real returned payload or last readiness state

#### 4.6.4 Compare Evidence

Before escalation, compare:

- same case on other devices
- same device across historical days
- adjacent scenarios on the same device
- passing invalid-input branches versus failing valid-data branches
- normal collection scenarios versus kill/restart or DB deletion scenarios
- setup/teardown logs before and after the failing scenario
- scan status and `Get-Issues` timestamps relative to the action under test
- expected `issueDomain` / `issueDefinitionId` versus returned issue domains
- command/payload/stdout/stderr differences between passing and failing branches
- service stop/start logs, process-back logs, DB delete/recreate logs, and first successful data-write time

If sibling evidence proves the plugin can respond in one branch but fails before final payload in another branch, prioritize setup, branch-specific precondition, wrapper diagnostics, service/DB readiness, and state isolation.

#### 4.6.5 Recommend Code-Fix Direction

Prefer these repair directions:

- replace `sleep(n)` + one-shot assert with polling until terminal state or explicit readiness
- assert on final response instead of intermediate response
- strengthen precondition validation before scan/API starts
- for system settings, separate read/write helpers for each state layer and assert the exact layer changed
- explicitly trigger or observe a scan after setting change and before `Get-Issues`
- after closing apps, verify that all target apps / sessions / foreground instances have exited
- capture and report raw `stdout`, `stderr`, `returncode`, payload, command, and elapsed time on API wrapper failures
- after DB deletion/restart, poll DB recreation/readability and branch-specific expected rows before final assertions
- for Windows service-control `1053`, optionally verify final service state before failing, only when the affected call site opts in
- add retry only for known transient wrapper/readiness/service boundaries, and gate it by case/device/API/scenario/branch
- add retry for file restore / cleanup when Windows file lock exists
- separate script issue from product issue by rerunning after polling/precondition/wrapper/readiness fixes

### 4.7 Standard Response Style

When using this skill, keep the answer brief and practical. Prefer the following structure:

- **结论**: 优先判定为 False Positive / implement script error / test infrastructure error
- **原因**: 断言时机过早、轮询缺失、App 关闭后未验证其已真正退出、前置校验不足、状态源混淆、cleanup/file lock 干扰、DB/cache 未就绪、service/plugin readiness 未证明、API wrapper 空输出处理缺失等
- **证据**: 引用断言/异常、API 返回、raw stdout/stderr、状态变更日志、scan 终态、服务状态、DB 状态、同设备/跨设备对照、通过/失败分支差异
- **修复方向**: 改轮询、查终态、补 App 退出校验、补前置校验、分离系统设置状态源、增强 API wrapper 诊断、增加 DB/service readiness 验证、设备隔离式重试
- **边界条件**: 说明哪些验证通过后才可升级为产品缺陷

### 4.8 Repair Patterns

#### Pattern A: Fixed Sleep -> Polling

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

#### Pattern B: Weak Precondition -> Explicit Validation

Add checks for:

- expected source file exists
- target file actually replaced
- signature / hash / timestamp changed as expected
- plugin scans the intended target path
- DB/cache exists, is readable, and is not stale when the scenario depends on DB data
- payload file exists and contains valid JSON for `--FromFile` scenarios
- app-close expectations are verified by querying process / session / foreground state after the close action
- system-setting expectations are verified through an authoritative source before scan starts
- service/plugin restart expectations are verified through final service state plus data readiness, not only process presence

#### Pattern C: Cleanup Lock -> Retry

If teardown shows Windows file lock errors, retry cleanup and make the lock visible in logs instead of silently ignoring it.

#### Pattern D: System-Setting State-Source Separation

When a test changes OS privacy or capability settings, avoid using one helper result for multiple adjacent settings.

```python
assert get_device_level_setting() is expected_device_level
assert get_app_level_setting() is expected_app_level
```

For camera privacy cases, validate `Camera access` and `Let apps access your camera` independently. A log proving app-level access is off does not prove device-level camera access is off.

#### Pattern E: Setting Change -> Scan Terminal State -> Final Issue Query

Use this order for cases expecting an issue after a setting change:

```python
change_setting(expected_value)
assert read_setting() is expected_value
scan_result = scan_until_terminal()
assert scan_result["status"] == "completed", scan_result
response = get_issues()
assert response["errorCode"] == 0, response
assert expected_issue in response["issues"], response
```

This prevents asserting against stale issues, pre-change scan data, or a scan that has not consumed the changed state.

#### Pattern F: Empty `stdout` / `NoneType.strip()` -> Diagnostic Wrapper Boundary

Convert this pattern:

```python
console_result = subprocess.run(args, capture_output=True, text=True, check=True)
result = console_result.stdout.strip()
return json.loads(result)
```

Into this pattern when and only when the caller opts in for a known flaky boundary:

```python
console_result = subprocess.run(args, capture_output=True, text=True, check=True)
stdout = console_result.stdout
stderr = console_result.stderr

if stdout is not None and stdout.strip():
    return json.loads(stdout.strip())

raise AssertionError(
    "Test tool returned empty stdout. "
    f"args={args}, returncode={console_result.returncode}, "
    f"stdout={stdout!r}, stderr={stderr!r}"
)
```

If retry is added, keep default retry count as zero and enable retries only from the affected call site.

#### Pattern G: Device-Isolated Retry / Fix Gate

Use explicit gates for device-specific repairs:

```python
if (
    current_host().lower() == "t14samd-3106"
    and case_key == "LIP-2297"
    and api_name == "Get-AppUsage"
    and plugin_name == "AppInsightsPlugin"
    and past_duration in {None, "", "1D", "7d", "2M", "2y"}
):
    response = invoke_api_with_empty_stdout_diagnostics_and_retry(...)
else:
    response = invoke_api_original_behavior(...)
```

This keeps invalid-parameter scenarios and non-target devices on the original path.

#### Pattern H: DB Deletion + Service Restart -> Data-Readiness Polling

Convert this pattern:

```python
appinsights.delete_app_usage_db_file_restart_app_insight_plugin()
appinsights.wait_until_appinsight_process_backon()
time.sleep(10)
device_activity = get_today_device_activity()
user_activity = get_today_user_activity()
assert is_user_active_at_current_hour(device_activity)
assert is_user_active_at_current_hour(user_activity)
```

Into this pattern:

```python
appinsights.delete_app_usage_db_file_restart_app_insight_plugin(
    tolerate_stop_timeout=True
)
appinsights.wait_until_appinsight_process_backon()

device_activity, user_activity = wait_until_current_hour_activity_ready(
    timeout_seconds=180,
    interval_seconds=5,
)

assert is_user_active_at_current_hour(device_activity), device_activity
assert is_user_active_at_current_hour(user_activity), user_activity
```

The readiness helper should preserve the last raw activity payload:

```python
def wait_until_current_hour_activity_ready(timeout_seconds=180, interval_seconds=5):
    deadline = time.monotonic() + timeout_seconds
    last_device_activity = None
    last_user_activity = None

    while time.monotonic() < deadline:
        last_device_activity = get_today_device_activity()
        last_user_activity = get_today_user_activity()

        if (
            is_user_active_at_current_hour(last_device_activity)
            and is_user_active_at_current_hour(last_user_activity)
        ):
            return last_device_activity, last_user_activity

        time.sleep(interval_seconds)

    raise AssertionError(
        "Current-hour activity was not ready after AppInsights restart. "
        f"last_device_activity={last_device_activity!r}, "
        f"last_user_activity={last_user_activity!r}"
    )
```

#### Pattern I: Windows Service `1053` -> Opt-In Final-State Verification

Convert this pattern:

```python
win32serviceutil.StopService(service_name)
return wait_for_status(win32service.SERVICE_STOPPED, timeout)
```

Into this pattern only when the caller opts in:

```python
try:
    win32serviceutil.StopService(service_name)
except pywintypes.error as error:
    error_code = getattr(error, "winerror", None)
    if error_code is None and getattr(error, "args", None):
        error_code = error.args[0]

    if not (tolerate_control_timeout and error_code == 1053):
        raise

    logger.warning(
        "Service(%s) StopService returned 1053; verifying final state",
        service_name,
    )

stopped = wait_for_status(win32service.SERVICE_STOPPED, timeout)
assert stopped, f"Service({service_name}) did not stop within {timeout}s"
```

Default `tolerate_control_timeout` must be `False` to preserve existing strict behavior.

### 4.9 Escalation Boundary

Escalate to product defect only when all of the following are true:

- terminal-state polling or readiness verification is already correct
- app-exit verification is complete and confirms the relevant apps are really closed
- preconditions are explicitly verified
- for system-setting cases, each expected setting layer is verified by an authoritative state source
- file replacement / target path validation is confirmed when relevant
- DB/cache/stale scan result contamination has been cleaned or ruled out
- service/plugin restart final state is verified when relevant
- DB recreation/readability and expected branch-specific data rows are verified when relevant
- test-tool wrapper captured `stdout`, `stderr`, `returncode`, payload, and command context
- any device-specific retry or readiness fix has been applied with narrow isolation where appropriate
- final payload is stable and still contradicts the product expectation after script-side fixes
- rerun still produces the same wrong final behavior

### 4.10 References

Load `references/false-positive-heuristics.md` when a quick classification checklist or wording template is needed.

Load `references/learned-corrections.md` **first and with the highest priority**: it stores human-reviewed corrections absorbed from the daily report. When a failure matches an entry there, prefer that human conclusion/cause/suggestion over a fresh generic guess.

## 5. AI 自动分析输出规范 (Automated Analysis Output Contract)

This section governs how an automated LLM caller (the “分析龙虾” daily report) must use this skill to analyze a single failed scenario and return a structured result. It does **not** change any triage logic above; it only fixes the **output shape and length** for machine consumption.

### 5.1 Context Priority

When analyzing one failed scenario, read context in this order and let earlier sources win on conflict:

1. `references/learned-corrections.md` — human-reviewed corrections (highest priority; if a matching entry exists, reuse its judgment).
2. The specialized experience zones in this `SKILL.md` (`LIP-1712` / `LIP-2297` / `LIP-2195`, etc.) when case key / host / scenario / signature match.
3. The historical baseline and fusion strategy for everything else.

### 5.2 Strict JSON Output

Return **only** a single JSON object, no Markdown, no code fence, no extra prose:

```json
{"conclusion": "...", "cause": "...", "suggestion": "..."}
```

- `conclusion`: 结论，**≤ 20 个汉字**。优先给出 False Positive / implement script error / test infrastructure error / 疑似产品缺陷 的明确判定。
- `cause`: 原因，**≤ 80 个汉字**。简述最可能的失败根因（断言时机、轮询缺失、前置不足、状态源混淆、readiness 未证明、wrapper 空输出等）。
- `suggestion`: 建议，**≤ 80 个汉字**。给出最小可行的修复方向（改轮询 / 查终态 / 补校验 / 设备隔离重试等）。

### 5.3 Length & Language Rules

- 直接产出符合上述字数上限的**简短中文文本**；不要为了凑字数而展开。字数上限由模型自我遵守，调用方不会再做硬截断，网页弹窗会展示全文。
- 三个字段都必须存在且非空；信息不足时也要给出最合理的保守判断，并在 `cause` 中说明“证据不足”。
- 不要输出 `证据`/`边界条件` 等额外字段；它们属于人工深入分析，自动结果只保留结论/原因/建议三项。

### 5.4 Determinism Guidance

同一条失败（相同 case/host/scenario/报错）应尽量给出**一致的结论与原因方向**，措辞可不同但判断要稳定，便于跨日缓存复用与人工复核。
