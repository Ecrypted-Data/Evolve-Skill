# Evolve-Skill 🧠

**Evolve-Skill** 是一个专为 AI 编程助手（如 Claude Code, Cursor, Gemini, GitHub Copilot 等）设计的**核心进化技能（Skill）**。

它的核心理念是：**在每次开发任务结束后进行复盘，将隐性经验固化为“可执行的规则 + 可检索的事件记录 + 可维护的运行手册”，并对不同 AI 平台做最小必要的行为矫正，实现可审计、可复用的持续进化。**

---

## 🌟 为什么需要 Evolve-Skill？

在使用 AI 编程助手进行长期项目开发时，我们经常遇到以下痛点：
- **上下文遗忘**：新开一个会话，AI 就忘记了之前的架构决策、踩过的坑和项目规范。
- **重复犯错**：同一个环境配置问题或 API 陷阱，AI 可能会在不同会话中反复踩坑。
- **平台差异**：Claude、Gemini、Cursor 等不同模型/平台有各自的脾气和局限，缺乏统一的行为矫正机制。

**Evolve-Skill** 通过建立一套标准化的”项目进化资产”目录和自动化审计脚本，让 AI 学会**自我总结、自我约束、自我进化**。

## ✨ 核心特性

- 📝 **自动化经验沉淀**：自动提取对话中的关键决策、排障套路和项目规则，写入 `EVOLVE.md`（唯一真理源）。
- 📊 **规则审计与打分系统**：内置 Python 脚本（`audit_sync.py`），对已有规则进行打分（命中/违反/错误/跳过），量化规则价值，自动淘汰过时规则。
- 🤖 **多平台行为矫正**：支持将平台特有的教训分别写入 `CLAUDE.md`、`GEMINI.md`、`AGENTS.md` 或 `CURSOR.md`，避免跨平台污染。
- 🔒 **强制安全脱敏**：内置安全约束，禁止将明文 IP、Token、密钥等敏感信息写入可提交的文档中。
- 🩺 **健康度检查**：内置 `health_check.py`，一键诊断项目进化文档的健康状态。

## 📂 产出文件结构

当 AI 触发进化技能后，会在你的项目根目录生成/维护以下结构：

```text
<project-root>/
├── EVOLVE.md                          # 进化主文档（唯一真理源：包含 TL;DR, Runbooks, Rules, History）
├── EVOLVE.local.md                    # 本地私密文件（建议加入 .gitignore）
├── CLAUDE.md / GEMINI.md / AGENTS.md  # 平台配置文件（仅记录特定 AI 平台的行为教训）
└── evolve/
    ├── audit.csv                      # 审计数据（经验指标追踪）
    ├── history/                       # 事件记录（按日期和主题归档）
    ├── runbooks/                      # 操作手册（部署/排障等可执行流程）
    ├── archived-rules.md              # 已归档的过时规则
    └── changelog-archive.md           # 历史变更归档
```

默认模式说明：
- 工具脚本驻留在 skill 仓库的 `<skill-root>/scripts/`（不是项目内 `evolve/scripts/`）。
- 脚本通过 `--project-root` 读写目标项目；如需项目内固化版本，可手动复制（可选）。

## 🚀 如何使用

### 1. 触发方式
在与 AI 助手的对话结束时，发送以下触发词之一：
> **"总结经验"**、**"进化"**、**"evolve"**、**"复盘"**

*注：不适用于仅完成简单查询、单文件小改动或未产生可沉淀资产的场景。*

### 2. AI 工作流
触发后，AI 将自动执行以下流程：
1. **读取上下文**：扫描 `EVOLVE.md` 及平台配置文件。
2. **经验审计与打分**：调用 `audit_sync.py` 筛选相关领域的规则并进行打分。
3. **深度回顾与分析**：提取“项目进化资产”（通用规则）和“AI 行为教训”（平台特有规则）。
4. **安全脱敏与写入**：将脱敏后的内容同步到对应的 Markdown 文件和 CSV 审计库中。

### 3. CLI 工具链
本仓库提供了强大的本地 CLI 工具，供开发者或 AI 调用：

```bash
# 初始化审计系统
python <skill-root>/scripts/audit_sync.py init --project-root .

# 查看当前项目的所有规则领域 (Scopes)
python <skill-root>/scripts/audit_sync.py scopes --project-root .

# 筛选特定领域的规则
python <skill-root>/scripts/audit_sync.py filter "前端,React" --project-root .

# 同步审计数据到 EVOLVE.md 和平台文件
python <skill-root>/scripts/audit_sync.py sync --project-root .

# 生成审计报告
python <skill-root>/scripts/audit_sync.py report --project-root .

# 运行项目进化健康度检查
python <skill-root>/scripts/health_check.py --project-root .
```

## 📖 详细文档

更多关于规范和系统设计的详细说明，请参阅 `references/` 目录：
- [项目初始化指南 (project-init.md)](references/project-init.md)
- [审计系统说明 (audit-system.md)](references/audit-system.md)
- [编写规范 (writing-specs.md)](references/writing-specs.md)

## 🛠️ 安装与集成

如果你使用的是支持 Skill/MCP/自定义指令的 AI 助手（如 Claude Code）：
1. 将本仓库克隆到你的本地技能目录（例如 `~/.claude/skills/Evolve-Skill` 或 `~/.codex/skills/Evolve-Skill`）。
2. 确保 AI 助手能够读取本目录下的 `SKILL.md` 作为其系统提示词或工具说明。
3. 在你的目标项目中，直接对 AI 说“复盘”即可开始体验。

## 📄 许可证

MIT License
