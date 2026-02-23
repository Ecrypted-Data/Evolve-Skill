# Evolve-Skill

> 让 AI 编程助手在每次开发结束后自动复盘、沉淀经验、持续进化的核心技能。

---

## 核心理念

AI 编程助手每天处理大量任务，但"踩过的坑、积累的最佳实践"往往随对话结束而消散。  
**Evolve-Skill** 在任务结束时触发一次**结构化复盘**，将隐性经验固化为：

- 可执行的规则（Rules）
- 可检索的事件记录（History）
- 可复用的操作手册（Runbooks）
- 平台特有的行为矫正（CLAUDE.md / GEMINI.md / AGENTS.md / CURSOR.md）

并通过审计系统追踪每条经验的"命中 / 违反 / 致错"次数，让规则有数据支撑，随时间持续优化。

---

## 效果示例

```
开发结束 → 触发复盘 → 自动产出：
  ✅ EVOLVE.md          # 规则 + 手册 + 事件索引（唯一真理源）
  ✅ CLAUDE.md          # Claude 特有行为教训（自动同步审计指标）
  ✅ evolve/audit.csv   # 经验追踪数据
  ✅ evolve/history/    # 分文件事件记录
  ✅ evolve/runbooks/   # 分文件操作手册
```

---

## 触发词

在对话中说出以下任何一个词，即可触发复盘流程：

> **「总结经验」「进化」「evolve」「复盘」**

---

## 产出文件结构

```
<your-project-root>/
├── EVOLVE.md                          # 进化主文档（唯一真理源）
├── EVOLVE.local.md                    # 本地私密内容（应加入 .gitignore）
├── CLAUDE.md / GEMINI.md / AGENTS.md  # 平台配置（仅写平台特有教训）
└── evolve/
    ├── audit.csv                      # 经验审计数据
    ├── history/                       # 事件记录（按日期分文件）
    │   └── YYYY-MM-DD-<topic>.md
    ├── runbooks/                      # 操作手册（按主题分文件）
    │   └── YYYY-MM-DD-<topic>.md
    ├── archived-rules.md              # 已归档规则
    └── changelog-archive.md           # Changelog 历史归档
```

---

## 快速上手

### 1. 安装 Skill

将本仓库中的 `SKILL.md` 注册到你的 AI 助手 Skill 系统（Claude Code / Agent 框架等）。

```bash
# 示例：克隆到本地 skill 目录（路径按你的平台调整）
git clone https://github.com/your-org/Evolve-Skill <skill-root>
```

说明：
- 默认模式下，脚本从 skill 仓库执行（`<skill-root>/scripts/`）。
- 目标项目默认只生成/维护数据与文档，不会自动创建 `evolve/scripts/`。

### 2. 在项目中初始化审计数据

```bash
python <skill-root>/scripts/audit_sync.py init --project-root /path/to/your/project
```

这会在项目根目录创建 `evolve/audit.csv`，作为经验追踪的数据源。

### 3. 开发结束时触发复盘

在 AI 对话中输入：

```
复盘一下今天的开发
```

AI 将自动执行四步复盘流程，产出上述文件。

### 4. 查看健康报告

```bash
python <skill-root>/scripts/health_check.py --project-root /path/to/your/project
```

---

## 脚本命令参考

> 以下示例假设当前目录是 `<skill-root>`；若在其他目录执行，请将 `scripts/...` 改为 `<skill-root>/scripts/...`。

### `audit_sync.py` — 审计生命周期管理

| 命令 | 说明 |
|------|------|
| `init` | 初始化 `evolve/audit.csv` |
| `scopes` | 查看所有已有经验的作用域（scope）列表 |
| `filter <关键词>` | 按关键词筛选相关经验条目 |
| `score <打分表达式>` | 对本次任务相关的规则打分（+hit / +vio / +err） |
| `sync` | 将审计指标同步写入 EVOLVE.md 及平台配置文件 |
| `sync_platform` | 仅同步平台配置文件 |
| `report` | 打印当前审计分析报告 |
| `promote` | 将候选经验提升为正式规则 |

**示例**：

```bash
# 查看与"前端/React"相关的已有经验（针对 codex 平台）
python scripts/audit_sync.py scopes --platform codex --project-root /path/to/your/project

# 筛选匹配条目
python scripts/audit_sync.py filter "前端,React" --platform codex --project-root /path/to/your/project

# 打分：R-001 命中，R-008 违反且致错
python scripts/audit_sync.py score "R-001:+hit R-008:+vio+err" --scope "前端,React" --project-root /path/to/your/project

# 同步到 EVOLVE.md 和平台文件
python scripts/audit_sync.py sync --project-root /path/to/your/project

# 查看报告
python scripts/audit_sync.py report --project-root /path/to/your/project
```

### `health_check.py` — 健康度诊断

```bash
# 交互式报告
python scripts/health_check.py --project-root /path/to/your/project

# 机器可读 JSON 输出
python scripts/health_check.py --project-root /path/to/your/project --json
```

---

## 审计数据格式（`evolve/audit.csv`）

每条经验对应一行：

```csv
rule_id,platform,scope,title,origin,hit,vio,err,skip,auto_skip,last_reviewed,status
R-001,all,部署/Docker,必须先检查 .env 是否存在,error,5,1,0,2,0,2026-02-22,active
S-001,claude,Claude/工具,生成 JSX 时必须检查闭合标签,error,2,3,2,0,1,2026-02-22,active
```

| 字段 | 说明 |
|------|------|
| `rule_id` | 规则编号（R=通用规则，S=平台教训） |
| `platform` | `all` / `claude` / `gemini` / `codex` / `cursor` / 自定义 |
| `scope` | 作用域（`分类/子分类`） |
| `hit` | 命中次数：该经验被成功参考 |
| `vio` | 违反次数：行为违反了该规则 |
| `err` | 致错次数：违反且导致可观测错误（vio 的子集） |
| `origin` | `error`（源于实际错误）/ `preventive`（预防性）/ `imported`（导入） |
| `status` | `active` / `protected` / `review` / `archived` |

---

## 安全说明

- **绝不**将明文 IP、token、secret、私钥路径等敏感信息写入 EVOLVE.md
- 敏感内容应放入 `EVOLVE.local.md`（加入 `.gitignore`）
- 可提交文件中只保留**占位符**，例如 `SSH_HOST=<YOUR_HOST>`

---

## 仓库结构

```
Evolve-Skill/
├── SKILL.md              # Skill 定义与完整工作流程
├── AGENTS.md             # 贡献者指南（适用于 AI Agent 仓库）
├── README.md             # 本文件
├── references/
│   ├── audit-system.md   # 审计系统详细规范
│   ├── project-init.md   # 首次初始化指南
│   └── writing-specs.md  # 文档写作规范
└── scripts/
    ├── audit_sync.py     # 审计生命周期 CLI
    └── health_check.py   # 健康度检查 CLI
```

---

## 依赖

- **Python 3**（标准库，无第三方依赖）
- 兼容任何支持 Skill / 自定义指令的 AI 编程助手框架

---

## 适用平台

| 平台 | 平台配置文件 |
|------|-------------|
| Claude Code | `CLAUDE.md` |
| Google Gemini | `GEMINI.md` |
| OpenAI Codex / 通用 | `AGENTS.md` |
| Cursor | `CURSOR.md` |

---

## 贡献

欢迎 Issue 和 PR。提交前请确保：

1. 语法验证通过：`python -m py_compile scripts/audit_sync.py scripts/health_check.py`
2. 报告正常输出：`python scripts/audit_sync.py report --project-root .`
3. 健康检查通过：`python scripts/health_check.py --project-root .`

---

## License

MIT
