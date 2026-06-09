# 分析龙虾 · Allure Report Analyzer

一个**可复用的命令行工具**，解析任意 Allure 2「多机合并报告」，按既定口径产出 scenario 级与 case 级多维分析，并生成**交互式单文件 HTML 仪表盘** + Excel/CSV + Markdown 摘要。

> 传报告路径即可分析，不绑定某一份报告；口径与映射全部集中在 `config.yaml`，换报告通常只改配置。

---

## 1. 快速开始

```bash
# 进入工具目录
cd allure_analyzer

# (可选) 安装增强依赖；不装也能跑（自动降级）
pip install -r requirements.txt

# 分析某份报告，输出到 ./allure_analysis_out
python3 analyze.py --report /path/to/allure_report --output ./allure_analysis_out

# 也可省略 --report：默认自动探测“脚本上级目录”是否为报告根（含 data/test-cases）
python3 analyze.py
```

产物（输出目录下）：

| 文件 | 说明 |
|---|---|
| `report.html` | **单文件自包含交互式仪表盘**（可直接双击/分享，含 CDN 资源） |
| `analysis.xlsx` | 多 sheet 工作簿（需 openpyxl，缺失自动跳过） |
| `csv/*.csv` | 各维度明细 CSV（utf-8-sig，Excel 友好） |
| `summary.md` | Markdown 摘要 |

CLI 参数：

```
--report/-r           报告根目录（含 data/test-cases）
--output/-o           输出目录（默认 ./allure_analysis_out）
--config/-c           配置文件（默认脚本目录 config.yaml）
--formats/-f          输出格式，逗号分隔：html,csv,excel,md（默认全部）
--original-report     原始 Allure 报告链接（写入 HTML 顶部 Original Report）
--report-name         报告显示名
```

---

## 2. 统计口径（重要）

- **数据单元** = `data/test-cases/*.json` 的**全部记录**（本报告 1199 条）。`(host, historyId)` 作唯一键；同键重复时保留 `time.stop` 最新者。
- **visible 1199 vs 411**：Allure 页面默认只展示 `hidden=false` 的 **visible 子集**（本报告 411，= `widgets/summary.json` 的 `statistic.total`）；本工具分析口径采用**全部 1199 条**，并在 HTML 顶部给出对账徽标。
- **状态二元化**：`not_passed = failed + broken`；对外状态列只显示 **Pass / Fail**（broken 计入 Fail）。`pass_rate = passed / total`。
- **scenario 唯一键** = `historyId`（`name` 仅作展示）。
- **case 唯一键** = 归一化 `LIP-<数字>`。
- **计数口径（核心）**：
  - **Step 视图（Step Result Summary）按 scenario 记录计数** —— 每条记录 = 1 scenario × 1 host，本报告 1199 条。
  - **Case 视图（Case Result Summary 与 Case 总览卡）按 (case, host) 行计数** —— 一条 case 在 N 台机器上跑就贡献 N 条记录；行级判定为：该机器上该 case 的所有 scenario 全 passed → Pass，否则 Fail。本报告 178 行（51 个唯一 case 展开后）。
  - 同时保留 `unique_case = 51` 作为参考信息（出现在 markdown 摘要与 HeaderLine 中）。
- **机器 / Device 维度**：一律用 **`host` label**。设备型号 tag（如 `X1_2IN1_2415`、含数字/下划线）是“目标设备清单”，一条挂多个，**不可**用作机器维度。
- **case key 抽取**：按可配置优先级 `suite → subSuite → links.url` 依次尝试，正则 `[Ll][Ii][Pp][-_ ]?(\d+)` 提取并归一化为 `LIP-<n>`，记录 `key_source`；全抽不到 = `UNLINKED`（本报告 100% 命中 suite，51 个 case，无 UNLINKED）。
- **owner**：写在 `tag` 里。默认 `whitelist_only=true`，**只认白名单内的名字**，识别不到就归 `(no-owner)`——不臆造 owner。
- **component（单一归属）**：来自 **`parentSuite` label**（每条记录恰好 1 个）。通过 `config.yaml` 中的 `component.parent_suite_map` 把 parentSuite 取值映射到对外 component 名，本报告：
  - `tests.test_hw_insight` → `UDC plugin HW Insight`
  - `tests.test_app_insight` → `UDC Plugin -APP Insight`
  - 其余（含未映射的 parentSuite、无 parentSuite）→ `(no-component)`，绝不臆造。
  各 component 列**求和恒等于总行数**（不再多归属）。换报告增删 component 只改 `parent_suite_map`。

---

## 3. HTML 仪表盘三视图

1. **Case Result**：行 = `(case, 机器)`。列含 Case(超链 Jira)、Owner、Component、Device、Status(Pass/Fail，带 `n/n` 分片计数)。
   - 行首三角可**展开**该 (case,机器) 下全部 scenario 子行；
   - 顶部筛选：Device / Status / Owner / Component 下拉 + 关键字搜索；列可排序。
2. **Case Result Summary**：Owner / Component / Device 三个子 Tab；**每行 = 该维度取值，列 = Pass / Fail / Pass Rate，按 (case, host) 行计数**（即 LIP-2365 在 2 台机器上 pass 时，Owner=Judy 的 Pass 列会 +2）。**Pass/Fail 数字为超链接**，点击下钻到 Case Result 并自动套用过滤。
3. **Step Result Summary**：结构同上但为 scenario 记录级（1199 口径）；数字超链接点击**弹出对应 scenario 清单**。
4. **总览 + 附属**：scenario/case 指标卡、状态环形图、host/owner pass rate 条形图；附属页含**跨机不一致 case**、耗时/重试 TopN、host×owner 矩阵、key_source 分布、UNLINKED 清单。

---

## 4. 配置（`config.yaml`）

换一份新报告时，通常只需改这里（未装 PyYAML 时自动使用 `analyzer/config.py` 内置等价默认值）：

```yaml
case_key:
  order: [suite, subSuite, links.url]   # 抽取优先级
  regex: '[Ll][Ii][Pp][-_ ]?(\d+)'
owner:
  whitelist: [Steven, Marcus, Qingting, Judy]
  whitelist_only: true                  # true=只认白名单，绝不臆造 owner
component:
  functional_tags: [HW_Insight, App_Insight, Power, Smoke, Relay, Keyboard]
device:
  display_map: {}                       # host -> 展示名 美化；未配置原样显示
jira:
  browse_base: "https://jira.tc.lenovo.com/browse/"
thresholds:
  pass_rate_good: 0.90   # >=绿
  pass_rate_warn: 0.70   # >=黄 否则红
top_n: 10
```

---

## 5. 目录结构

```
allure_analyzer/
├── README.md
├── requirements.txt          # PyYAML/openpyxl/jinja2（均可选，缺失自动降级）
├── config.yaml               # 可复用配置（口径/白名单/功能词/美化映射/阈值）
├── analyze.py                # CLI 入口
├── analyzer/
│   ├── config.py             # 配置加载 + 内置默认
│   ├── models.py             # TestCaseRecord 数据模型
│   ├── loader.py             # 解析全部记录 + (host,historyId) 去重 + 容错
│   ├── owner.py              # owner 识别（白名单/启发式）
│   ├── classify.py           # case key 抽取/归一化 + component(parentSuite 映射) + 二元判定
│   ├── metrics.py            # 四维度聚合 + 下钻条件 + 矩阵/TopN/不一致/UNLINKED
│   ├── reconcile.py          # 与 summary.json 对账
│   └── reporters/
│       ├── csv_reporter.py
│       ├── excel_reporter.py
│       ├── html_reporter.py
│       └── markdown_reporter.py
└── templates/
    └── report.html.j2        # 单文件仪表盘外壳（占位符内嵌 JSON，无需 jinja2）
```

---

## 6. 依赖与降级

| 依赖 | 用途 | 缺失时 |
|---|---|---|
| PyYAML | 读取 `config.yaml` | 回落到内置默认配置 |
| openpyxl | 导出 `analysis.xlsx` | 跳过 Excel，仍出 CSV |
| Jinja2 | （预留）模板渲染 | HTML 用占位符替换生成，不受影响 |

纯标准库即可运行核心分析与 HTML/CSV/Markdown 输出。

---

## 7. 后续可扩展（已预留）

- **失败原因归类**：`status_message` 已随记录保留，可在 `classify` 旁加 `failure_classifier.py`，按历史失败标签做关键词/正则归类。
- **每日定时 + 跨报告趋势**：本工具是「报告路径 → 产物」的 CLI，外层用定时任务每天扫描新报告目录、跑分析并聚合趋势即可。
