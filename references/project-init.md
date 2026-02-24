# 项目进化资产初始化指南

当项目首次触发 `Evolve-Skill` 技能（即工作区根目录不存在 `EVOLVE.md`）时，请按以下步骤完成完整的初始化工作：

## 1. 创建目录结构
在项目根目录创建所需的文件夹结构：
```bash
mkdir -p evolve/history evolve/runbooks evolve/rules
```
Windows PowerShell 可使用：
```powershell
New-Item -ItemType Directory -Force -Path evolve/history,evolve/runbooks,evolve/rules | Out-Null
```

## 2. 创建 EVOLVE.md 骨架
在根目录创建 `EVOLVE.md`，并写入以下基础结构（这是唯一的真理源）：

```markdown
# EVOLVE.md

## TL;DR
<!-- 最常用命令 / 常见排障 / 关键注意事项 -->

## Rules
<!-- 宪法级规则：短而硬、可执行、可验收 -->

## Runbooks
<!-- 按任务的操作手册索引 -->

## History
<!-- 事件记录索引（摘要 + 链接） -->

## Changelog
<!-- 每次进化的变更注记 -->
```

## 3. 初始化审计系统
执行以下命令，在 `evolve/` 目录下生成 `audit.csv` 初始文件：
```bash
python <skill-root>/scripts/audit_sync.py init --project-root .
```

说明：
- 默认模式下，脚本位于 skill 仓库（`<skill-root>/scripts/`），项目内不会创建 `evolve/scripts/`。
- 若你希望“项目内固化脚本版本”（例如离线归档/版本冻结），可手动复制到 `evolve/scripts/`，但后续升级需自行维护。

初始化后，`audit.csv` 表头应包含 `platform` 字段：
```csv
rule_id,platform,scope,title,origin,hit,vio,err,skip,auto_skip,last_reviewed,status,evolve_slot
```

约定：
- `R-xxx`（通用规则）使用 `platform=all`
- `S-xxx`（平台教训）使用明确平台值（如 `claude/gemini/codex/cursor`，或自定义平台名）

初始化后建议先完成一次最小闭环：
```bash
python <skill-root>/scripts/audit_sync.py report --project-root .
python <skill-root>/scripts/audit_sync.py select "1" --project-root .
python <skill-root>/scripts/audit_sync.py sync --project-root .
```

## 4. 初始化平台配置文件（按需）
根据当前使用的 AI 平台（如 Claude），在根目录创建或更新对应的配置文件（如 `CLAUDE.md`），并确保包含以下基础约束章节：

```markdown
## 🧬 自我进化/经验教训
- [Self] 开工前必须先阅读 `EVOLVE.md`。
```

完成以上 4 步后，即可返回主流程继续执行经验的提取与写入。
