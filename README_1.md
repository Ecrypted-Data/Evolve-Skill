# Evolve-Skill

一个面向 AI 编程协作场景的“经验进化”技能仓库。

它通过两类脚本把复盘经验沉淀为可审计资产：
- `audit_sync.py`：管理经验审计生命周期，并把审计指标同步到项目文档
- `health_check.py`：从 6 个维度评估经验体系健康度

该仓库可作为独立工具使用，也可被 AI Agent 集成到开发闭环中（复盘 → 打分 → 同步 → 健康检查）。

默认执行模型：
- 工具脚本位于 skill 仓库的 `scripts/` 目录。
- 通过 `--project-root` 指向目标项目进行读写（如 `EVOLVE.md`、`evolve/audit.csv`）。
- 默认不会在目标项目创建 `evolve/scripts/`（仅在需要固化版本时手动复制）。

## 核心能力

- 审计生命周期管理：`init / scopes / filter / score / sync / sync_platform / report / promote`
- 平台解耦经验追踪：支持 `claude / gemini / codex / cursor` 及自定义平台
- 自动同步机制：更新 `EVOLVE.md` 指标标签与平台自动区块（不覆盖手写内容）
- 健康度诊断：完整性、一致性、结构、活跃度、质量、防腐六维评分
- 低价值与过时规则识别：支持 review/archived 流程和晋升建议

## 仓库结构

```text
.
├── SKILL.md                  # 技能定义与执行流程
├── AGENTS.md                 # 仓库开发约定
├── scripts/
│   ├── audit_sync.py         # 审计同步 CLI
│   └── health_check.py       # 健康检查 CLI
└── references/
    ├── audit-system.md       # 审计模型与命令规范
    ├── project-init.md       # 项目进化资产初始化指南
    └── writing-specs.md      # 文档写入模板与规范
```

## 环境要求

- Python 3.9+
- 仅使用标准库，无第三方依赖
- 推荐终端使用 UTF-8 编码（脚本已做 stdout/stderr UTF-8 兼容处理）

## 快速开始

在仓库根目录执行：

```bash
# 1) 语法检查
python -m py_compile scripts/audit_sync.py scripts/health_check.py

# 2) 初始化审计数据（写入目标项目）
python scripts/audit_sync.py init --project-root /path/to/your/project

# 3) 查看审计报告
python scripts/audit_sync.py report --project-root /path/to/your/project

# 4) 运行健康检查
python scripts/health_check.py --project-root /path/to/your/project
```

## CLI 用法

### 1) 审计同步脚本

```bash
python scripts/audit_sync.py <command> [args] [--project-root <path>] [--platform <name>]
```

常用命令：

```bash
# 查看可用 scope
python scripts/audit_sync.py scopes --project-root /path/to/your/project

# 按关键词筛选规则（支持平台过滤）
python scripts/audit_sync.py filter "前端,React" --platform codex --project-root /path/to/your/project

# 一行式打分
python scripts/audit_sync.py score "R-001:+hit R-008:+vio+err" --scope "前端,React" --platform codex --project-root /path/to/your/project

# 同步审计指标到 EVOLVE.md，并同步平台自动区块
python scripts/audit_sync.py sync --project-root /path/to/your/project

# 仅同步平台自动区块
python scripts/audit_sync.py sync_platform --project-root /path/to/your/project

# 输出晋升建议（平台教训 → 用户级配置）
python scripts/audit_sync.py promote --project-root /path/to/your/project
```

### 2) 健康检查脚本

```bash
# 文本报告
python scripts/health_check.py --project-root /path/to/your/project

# JSON 报告（用于自动化）
python scripts/health_check.py --project-root /path/to/your/project --json
```

## 典型工作流

推荐在一次开发任务结束后执行以下流程：

1. `scopes`：确认本次任务涉及的领域
2. `filter`：筛选相关规则（必要时加 `--platform`）
3. `score`：对命中/违反/致错进行打分
4. `sync`：同步到 `EVOLVE.md` 与平台文件自动区块
5. `health_check`：验证经验体系健康度

## 数据与约定

- 审计数据文件：`evolve/audit.csv`
- 规则编号约定：
  - `R-xxx`：通用规则（`platform=all`）
  - `S-xxx`：平台教训（`platform` 必须是具体平台）
- `sync` 会维护自动区块：
  - `<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN ... -->`
  - `<!-- EVOLVE_SKILL:AUTO_SYNC:END -->`

## 安全与开源建议

- 不要提交任何真实密钥、主机地址、令牌或私密配置
- 敏感信息应放入本地私有文件（如 `*.local.md`）并加入 `.gitignore`
- 对示例、日志、报告中的敏感字段进行脱敏

## 开发验证（最小检查）

每次修改后至少运行：

```bash
python -m py_compile scripts/audit_sync.py scripts/health_check.py
python scripts/audit_sync.py report --project-root .
python scripts/health_check.py --project-root .
```

## 参考文档

- `SKILL.md`：完整技能流程
- `references/audit-system.md`：审计字段、指标与自动化规则
- `references/project-init.md`：首次初始化流程
- `references/writing-specs.md`：规则/Runbook/History/Changelog 写入模板

## 贡献

欢迎提交 Issue / PR。

建议在 PR 描述中包含：
- 变更目的
- 关键文件改动
- 运行过的验证命令与结果

