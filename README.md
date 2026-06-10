# 分析龙虾 · Allure Report Analyzer

一个**可复用的命令行工具**，解析任意 Allure 2「多机合并报告」，按既定口径产出 scenario 级与 case 级多维分析，并生成**交互式单文件 HTML 仪表盘** + Excel/CSV + Markdown 摘要。

> 传报告路径即可分析，不绑定某一份报告；口径与映射全部集中在 `config.yaml`，换报告通常只改配置。

---

## 1. 快速开始

> 日常工作流请直接看 [§ 8. 趋势分析](#8-趋势分析每天积累按周月看走势)，用 `run_daily.py` 一键完成。
> 本节的 `analyze.py` 适合**单份临时分析**（如同事丢来一份报告临时看一眼）。

```bash
# 进入工具目录
cd allure_analyzer

# (可选) 安装增强依赖；不装也能跑（自动降级）
pip install -r requirements.txt

# 临时分析某份报告，输出到 ./out
python3 analyze.py --report /path/to/allure_report --output ./out

# 也可省略 --report：默认自动探测"脚本上级目录"是否为报告根（含 data/test-cases）
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
--output/-o           输出目录（默认 ./out）
--config/-c           配置文件（默认脚本目录 config.yaml）
--formats/-f          输出格式，逗号分隔：html,csv,excel,md（默认全部）
--original-report     原始 Allure 报告链接（写入 HTML 顶部 Original Report）
--report-name         报告显示名
--snapshot-dir        （进阶）导出趋势快照到指定目录；run_daily.py 会自动传
--snapshot-date       （进阶）快照日期 YYYY-MM-DD
```

> 历史的 `allure_analysis_out/` 默认目录已废弃；推荐使用 `run_daily.py`，它会按日期分子目录归档，避免覆盖。

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
├── analyze.py                # CLI 入口（单份报告分析 + 可选导出趋势快照）
├── trend.py                  # CLI：读快照，聚合 7d/30d 趋势，出 trend.html/csv/md
├── run_daily.py              # 一键脚本：定位 → analyze → snapshot → trend
├── analyzer/
│   ├── config.py             # 配置加载 + 内置默认
│   ├── models.py             # TestCaseRecord 数据模型
│   ├── loader.py             # 解析全部记录 + (host,historyId) 去重 + 容错
│   ├── owner.py              # owner 识别（白名单/启发式）
│   ├── classify.py           # case key 抽取/归一化 + component(parentSuite 映射) + 二元判定
│   ├── metrics.py            # 四维度聚合 + 下钻条件 + 矩阵/TopN/不一致/UNLINKED
│   ├── reconcile.py          # 与 summary.json 对账
│   ├── locator.py            # 智能定位：日期目录(3 种格式) + allure 报告根 + 多候选阻塞
│   ├── snapshot.py           # 紧凑每日快照（趋势分析的唯一数据源）
│   └── reporters/
│       ├── csv_reporter.py
│       ├── excel_reporter.py
│       ├── html_reporter.py
│       └── markdown_reporter.py
├── templates/
│   ├── report.html.j2        # 单文件仪表盘外壳（占位符内嵌 JSON）
│   └── trend.html.j2         # 趋势页外壳（Chart.js 折线，7d/30d 切换）
└── trend_data/               # 趋势相关产物（运行时生成，建议加入 .gitignore）
    ├── snapshots/            # 每日快照 YYYY-MM-DD.json（几 KB/份，长期保留）
    ├── _unpack_cache/        # 压缩包解压缓存（幂等，可随时整目录删除）
    ├── daily_out/            # 每日详细分析报告（按日期分子目录，可按需归档/清理）
    └── trend_out/            # trend.html / trend.csv / trend.md
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

---

## 8. 趋势分析（每天积累，按周/月看走势）

### 8.1 设计概览

- **数据源唯一**：每天分析报告时顺手吐一份**紧凑快照**（几 KB/份）落到 `trend_data/snapshots/<YYYY-MM-DD>.json`。趋势分析**只读快照**，与原始 allure 大报告完全解耦——原始报告超过保留期可归档/删除，趋势历史不受影响。
- **覆盖维度**：整体通过率（scenario / case / unique-case）、按 owner / component / device 的通过率、报告体量（scenario 数 / (case,host) 行 / unique case / 机器数 / 跨机不一致数）、case 状态流转（相对前一日的 新增 / 修复 / 回归 / 移除 / 仍通过 / 仍失败）。
- **窗口**：同一份 trend.html 同时提供「最近 7 天」与「最近 30 天」切换，按**日历日**计算（以最末一份快照日期为基准向前数 7 / 30 天），曲线复用 `config.yaml` 的 `thresholds.pass_rate_good / pass_rate_warn` 着色。
  - 补历史快照（如把 30 天前的某天补进来）只会出现在 30d 视图，**不会污染 7d 视图**。
  - 数据极稀（窗口内 < 2 份快照）时会兜底显示最近 2 份，避免画出孤点。
- **第一天就能用**：只有 1 份快照时图上是单点，第二天会自动接成线。

### 8.2 收件目录约定（智能识别）

每天把整份 allure 报告丢到「收件根」下，**层级嵌套随意**，**目录或压缩包都行**，只要目录路径中**任一层**目录名是日期即可（顶层带日期的压缩包也支持）。

支持的日期格式（统一归一化为 `YYYY-MM-DD`）：

| 写法 | 示例 |
|---|---|
| `YYYY-MM-DD` | `2026-06-09` |
| `YYYYMMDD` | `20260609` |
| `YYYY_MM_DD` | `2026_06_09` |

支持的压缩包格式（标准库即可，不需额外依赖）：

| 格式 | 备注 |
|---|---|
| `.zip` | 自动处理 cp437/gbk/utf-8 三种编码的中文文件名 |
| `.tar` / `.tar.gz` / `.tgz` / `.tar.bz2` / `.tbz2` | tarfile 自动识别 |

> `.7z` / `.rar` 暂不支持（依赖第三方库），请提前转成 `zip`。

合法的存放方式（都能被识别，混用没问题）：

```
reports_inbox/
├── 2026-06-09/                       # 日期目录直接是 allure 报告根
│   ├── data/test-cases/*.json
│   ├── widgets/
│   └── index.html
├── 2026-06-10/allure-report.zip      # 日期目录里直接放压缩包（推荐）
├── 20260611/run1/report.tar.gz       # 嵌套也行，自动向下找
├── 2026_06_12.zip                    # 顶层文件名带日期，也认
└── projectX/2026-06-13/foo/bar/allure-report/   # 日期不在第一层也行
```

**报告根判定**：含 `data/test-cases/*.json`，或 `index.html` + `data/`（兜底）。

**自动解压**：默认开启。压缩包会被解压到 `trend_data/_unpack_cache/<date>/<stem>__<指纹>/`，**幂等**——同一个压缩包重复跑不会重复解压（指纹 = size+mtime）。要关闭可加 `--no-unpack`。

**同一天有多份候选时不会自动选**：会列出所有候选并阻塞，需用 `--report-root` 显式指定。例如 `2026-06-12/` 下既有解压目录又有压缩包时会同时识别为 2 份候选并报错。

### 8.3 每日 SOP（推荐用 `run_daily.py` 一键搞定）

```bash
cd allure_analyzer

# 1) 一键模式：扫 inbox，分析所有未处理的日期、刷新趋势、打印汇报
python3 run_daily.py --inbox /path/to/reports_inbox

# 2) 单日模式
python3 run_daily.py --date-dir /path/to/reports_inbox/2026-06-09

# 3) 多候选时显式指定（run_daily 会在控制台列出候选）
python3 run_daily.py --report-root /path/to/.../allure-report --date 2026-06-09

# 4) 强制重跑所有日期（默认增量；指纹一致的日期会跳过）
python3 run_daily.py --inbox /path/to/reports_inbox --force
```

`run_daily.py` 默认把产物写到脚本目录下的 `trend_data/`：

| 子目录 | 内容 | 保留建议 |
|---|---|---|
| `snapshots/` | 每日紧凑快照（几 KB/份） | **永久保留**——趋势的唯一数据源 |
| `daily_out/<date>/` | 每日详细 HTML/CSV/MD | 可按需保留 N 天后归档 |
| `trend_out/` | `trend.html` / `trend.csv` / `trend.md` / `daily_briefing.md` | 每次刷新时整体覆盖 |

#### 增量识别（重要）

为避免每次 `run_daily.py` 都把全部历史日期重新分析一遍，工具会在每份快照里写入一个 **source_fingerprint**（来自压缩包 size+mtime 与/或报告目录 file_count+total_size+max_mtime）：

- 默认行为：跑前对比"现源指纹"与"快照里指纹"——**完全相同就跳过**该日期，否则重跑。
- 加 `--force` 忽略指纹强制全跑。
- 第一次升级到本版本时（旧快照无指纹）会全量重跑一次，写入指纹后续即生效。
- 30 天历史 + 每天新增 1 天的场景下，从"每天跑全量"变成"只跑新增/变更"，速度从分钟级降到秒级。

#### 汇报卡（值班汇报）

跑完后会在控制台打印一段「今日值班汇报」，并落盘 `trend_data/trend_out/daily_briefing.md`，包含：

- 本次执行情况：分析了哪些日期、跳过了哪些、哪些被阻塞
- 最新一天 vs 前一日的关键指标变化（通过率涨跌、device 增减、跨机不一致变化）
- case 状态流转：哪些 case 回归、修复、新增失败（最多列前 10 个）
- 直达入口：趋势 / 最新日报告路径

加 `--no-briefing` 可关闭。

#### 仅刷新趋势

如果只想拿最新快照重新刷一遍 `trend.html`（不再跑 analyze）：

```bash
python3 run_daily.py --skip-analyze
# 等价于：
python3 trend.py --snapshots ./trend_data/snapshots --output ./trend_data/trend_out --daily-out ./trend_data/daily_out
```

### 8.4 直接调用 `analyze.py` 时手动写快照

如果你不用 `run_daily.py`，也可以在常规分析时加两个开关：

```bash
python3 analyze.py \
  --report /path/to/allure_report \
  --output ./out \
  --snapshot-dir ./trend_data/snapshots \
  --snapshot-date 2026-06-09          # 不传则尝试从 --report 路径反推日期，仍无法识别就用今天
```

不传 `--snapshot-dir` 时**完全不影响原有行为**，老用法照常。

### 8.5 历史报告处置建议

- **快照**（`trend_data/snapshots/`）：**永久保留**。每份几 KB，30 天 ≈ 几十 KB，全年 ≈ 1 MB，可以无脑放着。
- **每日详细报告**（`trend_data/daily_out/`）：体量大，建议保留近 N 天后归档/删除（不影响趋势）。
- **解压缓存**（`trend_data/_unpack_cache/`）：默认保留以方便复查；**任何时候都可以整目录删掉**，下次跑时会按指纹自动重解。
- **`reports_inbox/` 原始报告/压缩包**：分析完成可移走/压缩归档，趋势侧不依赖它。
- 建议把 `reports_inbox/` 与 `allure_analyzer/trend_data/daily_out/`、`allure_analyzer/trend_data/_unpack_cache/` 加入 `.gitignore`。

### 8.6 产物速查

- `trend.html`：自包含单文件，浏览器双击打开。
  - 顶部可切「7d / 30d」窗口，所有图与卡片随之联动。
  - **每日明细表**置顶，"日期"列点击直跳当天的完整分析报告。
  - 概览卡片为**窗口聚合值**（平均通过率、最低通过率及其日期、累计修复/回归 等），与下方明细不重复。
  - 6 张图标题旁有 ⓘ 图标，悬浮显示口径解释。
  - owner / component / device 三张图右上角是**多选下拉**，支持「全选 / 全不选 / 默认 Top 8」。
- `trend.csv`：每天一行，含通过率（scenario / case / unique-case）、体量、状态流转 7 项。utf-8-sig，Excel 直接打开不乱码。
- `trend.md`：日总览表 + 状态流转表，方便贴到日报/周报。
- `daily_briefing.md`：每次 `run_daily.py` 跑完落盘的「今日值班汇报」，含执行情况 + 当日 vs 前日变化 + case 流转明细，可直接贴到群/邮件。

