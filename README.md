# Evolve-Skill

面向 AI 编程协作场景的”经验进化”技能仓库：把每次开发/排障复盘沉淀为可审计资产，并用数据追踪每条规则的价值与风险。

- **EVOLVE.md 作为唯一真理源**：规则、手册、事件索引统一落盘，便于 PR review 与团队交接  
- **审计驱动的规则治理**：hit / vio / err / skip 指标量化规则有效性与危险度，支持 review/archived 流程  
- **平台差异隔离**：通用经验写入 EVOLVE.md，平台特有教训写入 CLAUDE.md / GEMINI.md / AGENTS.md / CURSOR.md（避免跨平台污染）

---

## 它解决什么问题？

长期使用 AI 编程助手时常见痛点：
- 新开会话就“失忆”，同类坑反复踩
- 经验散落在聊天记录里，无法审计、无法交接
- 不同平台（Claude/Gemini/Codex/Cursor）行为差异导致规则难复用

Evolve-Skill 通过 **”复盘 → 打分 → 同步 → 健康检查”** 的闭环，把隐性经验变成团队可维护的工程资产。

---

## 你会得到哪些产物？

在你的项目根目录维护这些文件/目录：

```text
<project-root>/
├── EVOLVE.md                          # 唯一真理源：规则 + Runbooks + History 索引 + 指标标签
├── EVOLVE.local.md                    # 本地私密内容（建议加入 .gitignore）
├── CLAUDE.md / GEMINI.md / AGENTS.md  # 平台配置（仅记录平台特有教训）
└── evolve/
    ├── audit.csv                      # 审计数据（经验指标追踪）
    ├── history/                       # 事件记录（按日期/主题归档）
    ├── runbooks/                      # 操作手册（部署/排障等可执行流程）
    ├── archived-rules.md              # 已归档规则
    └── changelog-archive.md           # 历史变更归档
````

---

## 快速开始（作为独立工具使用）

> 依赖：Python 3.9+，仅标准库，无第三方依赖。
> 默认模式：脚本位于 skill 仓库 `scripts/`，通过 `--project-root` 操作目标项目；不会自动复制到目标项目的 `evolve/scripts/`。

在本仓库根目录：

```bash
# 1) 基础语法检查
python -m py_compile scripts/audit_sync.py scripts/health_check.py

# 2) 在你的项目里初始化审计数据（在项目根目录生成 evolve/audit.csv）
python scripts/audit_sync.py init --project-root /path/to/your/project

# 3) 查看当前审计报告
python scripts/audit_sync.py report --project-root /path/to/your/project

# 4) 运行健康检查（六维诊断）
python scripts/health_check.py --project-root /path/to/your/project
```

---

## 集成到 AI 编程助手（Skill 用法）

1. 将本仓库作为 skill 注册到你的框架（Claude Code / 自研 Agent / 其他支持自定义指令的系统）
2. 在每次任务结束后触发一次“复盘/进化”
3. 由 AI 按 SKILL.md 的流程调用本仓库脚本与写入规范，沉淀资产

> 常见触发词（可按你的框架配置）：`总结经验 / 进化 / evolve / 复盘`

---

## CLI 用法

### audit_sync.py — 审计生命周期管理

```bash
python scripts/audit_sync.py <command> [args] --project-root <path> [--platform <name>]
```

常用命令：

```bash
# 查看可用 scope
python scripts/audit_sync.py scopes --project-root /path/to/your/project

# 按关键词筛选规则（支持平台过滤）
python scripts/audit_sync.py filter "前端,React" --platform codex --project-root /path/to/your/project

# 一行式打分（+hit / +vio / +err）
python scripts/audit_sync.py score "R-001:+hit R-008:+vio+err" --scope "前端,React" --platform codex --project-root /path/to/your/project

# 同步审计指标到 EVOLVE.md，并同步平台自动区块（不覆盖手写内容）
python scripts/audit_sync.py sync --project-root /path/to/your/project

# 仅同步平台自动区块
python scripts/audit_sync.py sync_platform --project-root /path/to/your/project

# 输出晋升建议（平台教训 → 用户级配置）
python scripts/audit_sync.py promote --project-root /path/to/your/project
```

### health_check.py — 经验体系健康度诊断

```bash
# 文本报告
python scripts/health_check.py --project-root /path/to/your/project

# JSON 报告（用于自动化）
python scripts/health_check.py --project-root /path/to/your/project --json
```

---

## 审计数据格式（evolve/audit.csv）

每条经验对应一行：

```csv
rule_id,platform,scope,title,origin,hit,vio,err,skip,auto_skip,last_reviewed,status
R-001,all,部署/Docker,必须先检查 .env 是否存在,error,5,1,0,2,0,2026-02-22,active
S-001,claude,Claude/工具,生成 JSX 时必须检查闭合标签,error,2,3,2,0,1,2026-02-22,active
```

字段含义（节选）：

* `hit`: 命中次数（该经验被成功参考）
* `vio`: 违反次数
* `err`: 致错次数（vio 的子集）
* `origin`: error / preventive / imported
* `status`: active / protected / review / archived

---

## 自动区块与写入约定

`sync` 会维护自动区块（用于写入指标与平台自动内容）：

* `<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN ... -->`
* `<!-- EVOLVE_SKILL:AUTO_SYNC:END -->

它会 **追加/更新自动区块内容**，不会覆盖你的手写段落。

---

## 安全说明

* 不要把明文 IP、token、secret、私钥路径等写入可提交文档
* 敏感信息放入 `EVOLVE.local.md` 并加入 `.gitignore`
* 示例与日志请脱敏：用占位符如 `SSH_HOST=<YOUR_HOST>`

---

## 仓库结构

```text
.
├── SKILL.md                  # Skill 定义与执行流程
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

## 贡献

欢迎 Issue / PR。

建议在 PR 描述中包含：

* 变更目的
* 关键文件改动
* 运行过的验证命令与结果（py_compile / report / health_check）

---

## License

MIT


