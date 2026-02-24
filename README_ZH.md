# Evolve-Skill 🧬

> **让 AI 编程助手在每次开发结束后自动复盘、沉淀经验、持续进化的核心技能仓库。**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/downloads/)

语言: [English](README.md) | **简体中文**

![Evolve-Skill 首页横幅](asset/images/readme/Hero%20Banner.png)

**Evolve-Skill** 是一个专为 AI 编程协作场景（如 Claude Code, Cursor, Gemini, GitHub Copilot 等）设计的**经验进化框架**。它通过结构化的复盘流程与本地 CLI 工具链，将零散的隐性经验转化为可审计、可量化、可隔离的工程资产。让你的 AI 助手学会自我总结、自我约束与自我进化。

---

## ❓ 为什么需要 Evolve-Skill？

在长期使用 AI 编程助手进行项目开发时，开发者通常会面临以下痛点：

* **🐠 像金鱼一样的记忆**：新开一个会话，AI 就忘记了之前的架构决策、踩过的坑和项目独有的规范。
* **🔁 重复踩踏同类陷阱**：相同的环境配置问题、特定的 API 陷阱，AI 可能会在不同的会话中反复犯错，消耗大量 Token 与时间。
* **🚧 跨平台“水土不服”**：Claude、Gemini、Cursor 等不同模型或平台有各自的脾气和局限性，缺乏统一且隔离的行为矫正机制，导致规则互相污染。
* **🗙 经验难以交接**：复盘经验散落在漫长的聊天记录里，无法形成体系，也无法在团队协作中进行 Code Review 和知识流转。

---

## ✨ 核心理念与价值

**Evolve-Skill** 通过建立一套标准化的“项目进化资产”目录和自动化审计脚本，构建了 **“复盘 → 打分 → 同步 → 健康检查”** 的完整闭环。

* **📘 唯一真理源 (Single Source of Truth)**
所有的通用规则、操作手册 (Runbooks) 和历史事件索引统一落盘至 `EVOLVE.md`，便于团队交接与 PR Review。
* **⚖️ 审计驱动的规则治理**
不再是盲目堆砌 prompt。系统通过追踪 `hit` (命中)、`vio` (违反)、`err` (致错) 等量化指标，精准评估每一条规则的有效性与危险度，自动识别低价值与过时规则，并支持 `review` 和 `archived` 淘汰流程。
* **🛡️ 平台差异隔离**
通用业务经验写入 `EVOLVE.md`，而平台特有的行为教训与矫正指令则精准写入 `CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md` 等对应文件，彻底避免跨平台污染。

---

## 🚀 快速开始

**依赖**：Python 3.9+，仅标准库，无第三方依赖。
> 说明：人工侧只需要“安装 Skill + 触发复盘”。初始化、审计打分、同步由 AI 按 `SKILL.md` 自动执行。

### 1. 安装 Skill

将本仓库克隆到你的本地 skill 目录：

```bash
git clone https://github.com/Ecrypted-Data/Evolve-Skill.git ~/.claude/skills/Evolve-Skill
```

确保你的 AI 助手能读取该目录下的 `SKILL.md` 作为系统提示词或工具说明（Claude Code / Agent 框架等均适用）。

### 2. 触发复盘

在 AI 对话中说出以下任意一个词即可：

> **「总结经验」「进化」「evolve」「复盘」「summarize lessons」「retrospective」「postmortem」**

触发后，AI 会自动执行读取上下文、审计打分（`scopes/filter/score`）、同步（`sync`），并通常在收尾阶段执行健康检查。

---

## 🛠️ 它是如何工作的？

skill触发后，AI 将按“概览 + 执行版”两层流程运行。

![闭环工作流](asset/images/readme/The%20Closed-Loop%20Workflow.png)

### 概览流程（6 步）

1. **读取上下文**：扫描 `EVOLVE.md` 与平台配置文件。
2. **提取与分类**：从对话中提取“项目通用资产”和“平台特有教训”。
3. **审计与打分**：通过 `scopes / filter / score` 复用已有规则并更新指标。
4. **生成写入建议**：执行 `report` 输出编号的待写入候选条目。
5. **最终选择**：执行 `select "<numbers>"` 标记最终写入的条目（设置 `evolve_slot`）。
6. **同步与校验**：执行 `sync` 写回文档与自动区块，并做健康检查。

### 执行版流程（标准顺序）

1. **读取与初始化**
   - 读取 `EVOLVE.md`、`CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md`（按平台选择）。
   - 若目标项目缺少 `EVOLVE.md` 或 `evolve/audit.csv`，先执行初始化：
     - `python scripts/audit_sync.py init --project-root <project-root>`

2. **先审计再提炼（强制）**
   - 先运行 `scopes` 查看领域，再运行 `filter` 缩小范围，最后运行 `score` 打分。
   - 若复盘的是平台教训（`S-xxx`），`filter` 和 `score` 必须使用同一个 `--platform <name>`，避免跨平台污染。
   - 推荐阶段（生成写入建议 + 选择）：
     - `python scripts/audit_sync.py report --project-root <project-root>`
     - `python scripts/audit_sync.py select "1,3" --project-root <project-root>`

3. **双通道提炼**
   - 通用资产写入 `EVOLVE.md`：TL;DR、Runbooks、Rules、History 索引、Changelog。
   - 平台特有教训写入对应平台文件：`CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md`。

4. **安全与脱敏（强制）**
   - 不写入明文 IP、Token、Secret、私钥路径等敏感信息。
   - 可提交文档只保留占位符，真实值放入 `EVOLVE.local.md`（并加入 `.gitignore`）。

5. **同步与收尾**
   - 核心同步：`python scripts/audit_sync.py sync --project-root <project-root>`
   - 可选：
     - 仅同步单个平台：`--platform <name>`
     - 限制 EVOLVE 同步目标（仅通用规则 + 指定平台）：`--evolve-platform <name>`
     - 仅同步平台文件：`sync_platform`
     - 跳过平台自动区块：`--no-platform-sync`
   - 建议执行健康检查：
     - `python scripts/health_check.py --project-root <project-root>`

### 完成判定（建议）

- `EVOLVE.md` 与平台文件均已更新到本次复盘结果。
- `evolve/audit.csv` 指标已完成打分并可追踪。
- 自动区块由脚本同步完成（非手工改写）。
- 敏感信息已脱敏或转移到本地私有文件。

---

## 📦 产物与目录结构

在目标项目的根目录下，Evolve-Skill 会为你维护资产：

```text
<project-root>/
├── EVOLVE.md                          # 唯一真理源：规则 + Runbooks + History 索引 + 指标标签
├── EVOLVE.local.md                    # 敏感信息与本地特有配置（需加入 .gitignore）
├── CLAUDE.md / GEMINI.md / AGENTS.md / CURSOR.md
│                                       # 平台特有教训（自动同步审计指标，不覆盖手写内容）
└── evolve/
    ├── audit.csv                      # 核心：经验追踪与生命周期审计数据
    ├── history/                       # 分文件存储的重大事件复盘记录
    ├── runbooks/                      # 分文件存储的标准操作手册（如部署、发版步骤）
    ├── rules/                         # 每条规则的详细内容与追溯链接（history/runbooks）
    ├── archived-rules.md              # 归档规则（用户确认过时后迁入）
    └── changelog-archive.md           # Changelog 归档（主文件条目过多时迁移）

```

---

## 🚀 快速开始 & CLI 工具链

本仓库的脚本可作为独立工具本地执行，也可被 AI Agent 无缝集成到开发闭环中。工具脚本默认位于 skill 仓库的 `scripts/` 目录，通过 `--project-root` 指向目标项目进行读写。

### 1️⃣ 审计生命周期管理 (`audit_sync.py`)

```bash
# 初始化审计系统
python scripts/audit_sync.py init --project-root /path/to/your/project

# 查看当前项目的所有规则领域 (Scopes)
python scripts/audit_sync.py scopes --project-root /path/to/your/project

# 筛选特定平台或领域的规则
python scripts/audit_sync.py filter --project-root /path/to/your/project --platform claude

# 生成可写入 EVOLVE 的编号建议，并由 Agent 选择最终条目
python scripts/audit_sync.py report --project-root /path/to/your/project
python scripts/audit_sync.py select "1,3" --project-root /path/to/your/project

# 同步数据到 EVOLVE.md 与平台自动区块
python scripts/audit_sync.py sync --project-root /path/to/your/project

# 限制 EVOLVE 同步目标（仅通用规则 + 指定平台）
python scripts/audit_sync.py sync --project-root /path/to/your/project --evolve-platform codex

# 输出晋升建议（仅输出候选项，不会自动改写规则）
python scripts/audit_sync.py promote --project-root /path/to/your/project

```

### 2️⃣ 经验体系健康诊断 (`health_check.py`)

从 6 个维度（完整性、一致性、结构、活跃度、质量、防腐）全面评估你当前积累的规则是否健康。

```bash
# 输出文本诊断报告
python scripts/health_check.py --project-root /path/to/your/project

# 输出 JSON 格式报告（适用于 CI/CD 或自动化工作流接入）
python scripts/health_check.py --project-root /path/to/your/project --json

```

---

## 📊 数据格式与约定

### 审计数据 (`evolve/audit.csv`)

每条经验在 CSV 中对应一行，作为系统进化的数据源：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `rule_id` | 规则编号（`R-xxx`=通用规则，`S-xxx`=平台特有教训） | `R-001` |
| `platform` | 适用的 AI 平台 (`all` / `claude` / `gemini` / `codex` / `cursor` / 自定义) | `all` |
| `scope` | 作用域分类 (`分类/子分类`) | `部署/Docker` |
| `title` | 规则标题（简短可读的规则说明） | `先检查 .env 是否存在` |
| `origin` | 规则来源 (`error`=源于实际踩坑 / `preventive`=预防性预判 / `imported`=外部导入) | `error` |
| `hit` | **命中次数**：该经验在后续对话中被 AI 成功检索并参考的次数 | `5` |
| `vio` | **违反次数**：AI 或开发者行为违反了该规则的次数 | `1` |
| `err` | **致错次数**：违反规则且导致了可观测的代码或运行错误（vio 的子集） | `0` |
| `skip` | **手动跳过次数**：被人工判定“本次不适用”并跳过的次数 | `0` |
| `auto_skip` | **自动跳过次数**：在筛选范围内但本轮未打分时自动累计的次数 | `2` |
| `last_reviewed` | 最近一次审计日期（ISO 格式） | `2026-02-23` |
| `status` | 规则当前生命周期 (`active` / `protected` / `review` / `archived`) | `active` |
| `evolve_slot` | Agent 选择的写入 EVOLVE 的顺序槽位，`0` 表示不写入 | `2` |

### 自动区块约定

`sync` 命令会在 Markdown 文件中维护特殊的自动区块，用于动态写入指标与内容。**请勿手动修改区块内部的内容**，以防被覆盖：

```markdown
<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN platform=codex digest=xxxx updated=YYYY-MM-DD -->
## Evolve-Skill Auto Sync
（由脚本自动维护的内容与指标）
<!-- EVOLVE_SKILL:AUTO_SYNC:END -->
```

---

## 🔒 核心安全说明

在让 AI 自动沉淀经验时，安全性是第一原则：

* ❌ **绝对禁止**将明文 IP、Token、API Secret、密码或私钥路径等敏感信息写入 `EVOLVE.md` 或任何提交到版本库的文件中。
* ✅ 敏感内容必须放入 **`EVOLVE.local.md`**，并确保该文件已加入 `.gitignore`。
* ✅ 在可提交的通用规则和操作手册中，务必只保留**占位符**（例如：`SSH_HOST=<YOUR_HOST>`，`API_KEY=${ENV_API_KEY}`）。

## 📁 仓库结构

```text
.
├── SKILL.md                  # Skill 定义与完整执行流程
├── AGENTS.md                 # 仓库开发约定
├── scripts/
│   ├── audit_sync.py         # 审计同步 CLI
│   └── health_check.py       # 健康检查 CLI
└── references/
    ├── audit-system.md       # 审计模型与命令规范
    ├── project-init.md       # 项目进化资产初始化指南
    └── writing-specs.md      # 文档写入模板与规范
```

---

## 🤝 贡献

欢迎 Issue / PR。提交前请确保：

```bash
python -m py_compile scripts/audit_sync.py scripts/health_check.py
python scripts/audit_sync.py report --project-root .
python scripts/health_check.py --project-root .
```

---

## License

本项目基于 Apache-2.0 License 开源。
