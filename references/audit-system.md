# 审计系统（经验追踪与自动化）

## 数据存储：`evolve/audit.csv`

每条经验/规则对应一行记录，CSV 格式：

```csv
rule_id,platform,scope,title,origin,hit,vio,err,skip,auto_skip,last_reviewed,status
R-001,all,部署/Docker,必须先检查 .env 是否存在,error,5,1,0,2,0,2026-02-22,active
R-002,all,前端/React,状态更新必须用 immutable 模式,preventive,3,0,0,0,0,2026-02-20,active
S-001,claude,Claude/工具,生成 JSX 时必须检查闭合标签,error,2,3,2,0,1,2026-02-22,active
R-003,all,Git/提交,commit 前必须运行 lint,imported,8,0,0,0,0,2026-02-21,active
```

**字段说明**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `rule_id` | string | 规则/经验编号（R=通用规则，S=平台教训） |
| `platform` | string | 平台标签（`all` / `claude` / `gemini` / `codex` / `cursor` / 自定义）；**S- 规则必须尽量使用明确平台值** |
| `scope` | string | 作用域标签（`分类/子分类`），用于判断是否与当前任务相关 |
| `title` | string | 规则简述（用于 filter 输出，50 字以内） |
| `hit` | int | 命中次数：该经验被成功参考并指导了行为 |
| `vio` | int | 违反次数：行为违反了该经验（无论是否导致错误） |
| `err` | int | 致错次数：违反且导致了可观测的错误/返工（`vio` 的子集） |
| `skip` | int | 手动跳过：AI 审视后确认"本次确实没触及"（信号可靠） |
| `auto_skip` | int | 自动跳过：filter 匹配但未被打分（信号较弱，权重低于手动 skip） |
| `last_reviewed` | date | 最后一次审计日期 |
| `origin` | enum | 规则来源：`error`（源于实际错误/返工） / `preventive`（预防性，未出过错） / `imported`（从外部导入的最佳实践） |
| `status` | enum | `active` / `protected`（用户确认有价值） / `review`（待审查） / `archived`（已归档） |

## 复盘时的审计流程（使用辅助工具）

AI 复盘时使用以下流程，最大限度减少上下文消耗和审计阻力：

### 1) 查看可用 scope
```bash
python audit_sync.py scopes --project-root .
```
输出所有有效关键词及规则数量，避免 filter 打空。

按平台查看（仅筛选对应平台的 S- 规则，R- 规则默认保留）：
```bash
python audit_sync.py scopes --platform codex --project-root .
```

### 2) 筛选相关条目
```bash
python audit_sync.py filter "前端,React" --platform codex --project-root .
```
输出精简表格（仅 scope 匹配的 active 条目）：
```
[4 条匹配 scope: 前端,React]
  R-001 | all   | 前端/React      | hit:3 vio:1 err:0   | 状态更新必须用 immutable 模式
  R-005 | all   | 前端/React/路由 | hit:1 vio:0 err:0   | 路由切换前必须保存表单状态
  R-008 | all   | 前端/CSS        | hit:2 vio:2 err:1   | 禁止使用 !important
  S-003 | codex | Codex/前端      | hit:0 vio:1 err:0   | 生成 JSX 时必须检查闭合标签
```

### 3) 一行式打分
```bash
python audit_sync.py score "R-001:+hit R-008:+vio+err" --scope "前端,React" --platform codex --project-root .
```
- 已打分的条目更新对应计数，`auto_skip` 清零
- 未打分但匹配条件（scope/platform）命中的条目自动 `auto_skip+1`
- `--scope` / `--platform` 共同决定哪些未打分条目会被 auto_skip（都省略则不自动 skip）

### 4) 核心同步（EVOLVE + 平台文件）
```bash
python audit_sync.py sync --project-root .
```
- 默认执行两类同步：
  - EVOLVE.md 指标同步（TL;DR + Rules 内联标签）
  - 平台文件自动同步（已知平台 + 新增平台 + 配置映射平台）
- 可选参数：
  - `--platform <name>`：仅同步指定平台文件
  - `--no-platform-sync`：仅更新 EVOLVE.md，跳过平台文件同步
- 仅做平台同步：
```bash
python audit_sync.py sync_platform --project-root . [--platform <name>]
```

## 推导指标（按需计算，不存储）

| 指标 | 公式 | 用途 |
|------|------|------|
| 遵守率 | `hit / (hit + vio)` | 越低 → 越需要强调 |
| 危险度 | `err / vio` | 越高 → 越应设为硬规则 |
| 活跃度 | `hit + vio` | 越高 → 越常被触及 |

> **关于"已内化"的澄清**：AI 没有跨会话记忆，不存在"内化"。`hit高 vio=0` 的正确解读是"规则表述清晰、AI 每次读到都能正确执行"，**不能**因此降低展示优先级或建议淘汰——移除规则 = AI 下次读不到 = 可能违反。

**规则质量分类**（基于数据的正确解读）：

| 数据特征 | 含义 | 建议操作 |
|---------|------|---------|
| `hit高 vio=0` | 规则清晰、易执行 | **保留**，是优质规则 |
| `hit高 vio高` | 规则重要但难执行 | **强化**，重写规则使其更精确 |
| `vio高 err高` | 高危规则 | **置顶 TL;DR**，加警告 |
| `hit≥8 且历史vio=0 err=0 且 origin≠error` | 低价值嫌疑（可能是"正确的废话"） | **待审查**，用户确认 |
| `skip/auto_skip 持续增长` | 可能已过时 | **待审查**，用户确认 |

## 自动化规则（脚本驱动）

以下规则由 `<skill-root>/scripts/audit_sync.py` 自动执行：

### 1) TL;DR 同步
- **强调规则**：`vio ≥ 3 且遵守率 < 50%` → 自动追加至 EVOLVE.md 的 TL;DR 章节顶部，标注 `⚠️ 高频违反`
- **高危规则**：`err ≥ 2 且危险度 ≥ 0.5` → TL;DR 中标注 `🚨 高危`
- **难执行规则**：`hit ≥ 3 且 vio ≥ 3` → TL;DR 中标注 `🔧 需重写`（规则重要但表述不清或执行困难）

### 2) Rules 内联指标同步
将 CSV 中的指标同步到 EVOLVE.md 的 Rules 章节，在每条规则末尾追加/更新审计标签：
```markdown
- [R-001] **[部署/Docker]** 必须先检查 .env 是否存在  `{hit:5 vio:1 err:0}`
```

### 3) 平台文件自动同步
- 自动发现目标平台：已知平台文件 + `S-xxx` 中出现的平台 + 现有自动区块 + `evolve/platform_targets.json` 映射
- 未预设平台默认输出到 `<PLATFORM>.md`（大写）
- 同步采用区块替换，不覆盖手写内容：
  - `<!-- SELF_EVOLVE:AUTO_SYNC:BEGIN platform=<name> digest=<hash> ... -->`
  - `<!-- SELF_EVOLVE:AUTO_SYNC:END -->`

### 4) 待审查标记
- **手动 skip ≥ 5** → status 改为 `review`（AI 明确确认"没触及"，信号可靠）
- **auto_skip ≥ 8** → status 改为 `review`（多次 filter 匹配但未被打分，信号较弱，阈值更高）
- 用户确认"已过时" → status 改为 `archived`，规则移至 `evolve/archived-rules.md`
- 用户确认"仍有效" → skip 和 auto_skip 清零，status 恢复 `active`

### 5) 低价值嫌疑检测
- **条件**：`hit ≥ 8 且历史 vio = 0 且历史 err = 0 且 origin ≠ error`（从未被违反的高频命中规则，且非源于实际错误）
- **含义**：可能是"正确的废话"——规则表述的是 AI 本就会做的事，没有实际约束力
- **排除**：`origin = error` 的规则即使 vio=0 也不触发低价值检测（它曾经真实出过错，当前 vio=0 只说明规则写得好）
- **动作**：在 report 中标记 `[低价值嫌疑]`，由用户确认：
  - "确实重要，防患于未然" → status 改为 `protected`（不再检测低价值）
  - "正确的废话，可以删除" → status 改为 `archived`

### 6) 用户级晋升建议
- 平台教训（S-xxx）`vio ≥ 3 且遵守率 < 50%` → 建议晋升至用户级配置文件
- 可通过 `--platform` 仅查看某个平台的晋升建议
- 脚本输出晋升建议列表，由 AI 在复盘时呈现给用户确认

## 脚本使用

```bash
# 初始化 audit.csv
python audit_sync.py init

# 查看所有有效 scope 关键词
python audit_sync.py scopes

# 按平台查看 scope（解耦平台教训）
python audit_sync.py scopes --platform codex

# 筛选与当前任务相关的经验条目
python audit_sync.py filter "前端,React"

# 按 scope + platform 筛选（避免跨平台教训干扰）
python audit_sync.py filter "前端,React" --platform codex

# 一行式打分（未打分的 filter 匹配项自动 auto_skip+1）
python audit_sync.py score "R-001:+hit R-003:+vio+err" --scope "前端,React"

# 一行式打分（限定平台教训）
python audit_sync.py score "R-001:+hit S-003:+vio" --scope "前端,React" --platform codex

# 从 CSV 同步指标到 EVOLVE.md（TL;DR + Rules 内联标签）
python audit_sync.py sync

# 仅同步某个平台文件
python audit_sync.py sync --platform codex

# 跳过平台文件同步，仅更新 EVOLVE.md
python audit_sync.py sync --no-platform-sync

# 仅同步平台文件（不改写 EVOLVE.md）
python audit_sync.py sync_platform

# 查看审计报告（推导指标 + 异常检测）
python audit_sync.py report

# 输出晋升建议（平台教训 → 用户级）
python audit_sync.py promote

# 仅输出 codex 平台晋升建议
python audit_sync.py promote --platform codex
```

> **注意**：`audit_sync.py` 位于 self-evolve skill 目录（`<skill-root>/scripts/`），执行时需传入项目根目录路径。

## 健康度检查（独立脚本）

`health_check.py` 对经验体系进行全面诊断，输出 6 维度评分报告：

```bash
# 文本报告（默认）
python health_check.py --project-root .

# JSON 格式（便于自动化消费）
python health_check.py --project-root . --json
```

**检查维度**：

| # | 维度 | 检查项 |
|---|------|--------|
| 1 | 数据完整性 | 文件存在、表头完整、rule_id 唯一、origin/status 合法、数值非负、err≤vio、error 初始值、平台标签完整性 |
| 2 | EVOLVE.md 一致性 | 规则覆盖率、内联标签同步、TL;DR 同步、平台文件覆盖/区块/digest 新鲜度 |
| 3 | 体系结构 | 规则总数、scope 分布均衡度、origin 多样性、status 分布 |
| 4 | 审计活跃度 | 僵尸规则（>30天未审计）、7天覆盖率、review 积压 |
| 5 | 质量指标 | 整体遵守率、高危/难执行/低价值占比、protected 确认率 |
| 6 | 防腐检查 | 全零规则、孤儿规则、数据腐化、空 scope/title |

**评分体系**：每项 PASS=1 / WARN=0.5 / FAIL=0，总分 0-100，等级 A(≥90) / B(≥75) / C(≥60) / D(≥40) / F(<40)。

**建议使用时机**：
- 每次 `sync` 之后运行一次，确保体系健康
- 项目交接时运行，快速了解经验体系状态
- 定期巡检（如每周一次）

> **注意**：`health_check.py` 与 `audit_sync.py` 位于同一目录（`<skill-root>/scripts/`）。
