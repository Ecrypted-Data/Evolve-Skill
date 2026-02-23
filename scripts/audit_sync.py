#!/usr/bin/env python3
"""
审计同步脚本 - Self-Evolve Skill 自动化工具

功能：
  init    - 初始化 evolve/audit.csv（如不存在）
  scopes  - 列出所有有效的 scope 类型
  filter  - 按 scope / platform 筛选相关经验条目（精简输出，节省上下文）
  score   - 一行式批量打分，未打分但 filter 匹配的条目自动 auto_skip+1
  sync    - 从 audit.csv 同步指标到 EVOLVE.md（TL;DR + Rules 内联标签）
  report  - 输出审计报告（推导指标 + 异常检测 + 待审查项）
  promote - 输出晋升建议（平台教训 → 用户级配置，可按平台过滤）

用法：
  python audit_sync.py <command> [args] [--project-root <path>] [--platform <name>]

  --project-root  项目根目录路径（默认：当前工作目录）
  --platform      平台标签（如 claude/gemini/codex/cursor），用于筛选平台教训（S-xxx）

审计辅助工作流（AI 复盘时使用）：
  1. scopes                          → 查看有哪些 scope
  2. filter "前端,React" --platform codex → 筛选相关条目
  3. score "R-001:+hit R-003:+vio+err" --scope "前端,React" --platform codex
                                        → 一行打分（仅 codex 平台教训会被纳入平台筛选）
  4. sync                            → 同步到 EVOLVE.md
"""

import csv
import re
import sys
from pathlib import Path
from datetime import date
from typing import Optional


# ── CSV 字段定义 ──

CSV_HEADER = ["rule_id", "platform", "scope", "title", "origin", "hit", "vio", "err", "skip", "auto_skip", "last_reviewed", "status"]
VALID_STATUSES = {"active", "protected", "review", "archived"}
VALID_ORIGINS = {"error", "preventive", "imported"}
PLATFORM_ALL = "all"
PLATFORM_ALIASES = {
    "all": "all",
    "*": "all",
    "global": "all",
    "universal": "all",
    "shared": "all",
    "通用": "all",
    "全局": "all",
    "claude": "claude",
    "gemini": "gemini",
    "codex": "codex",
    "cursor": "cursor",
    "agents": "codex",
    "agent": "codex",
}
KNOWN_PLATFORM_VALUES = {"all", "claude", "gemini", "codex", "cursor"}

# 待审查阈值
MANUAL_SKIP_THRESHOLD = 5   # 手动 skip 达到此值 → 标记 review
AUTO_SKIP_THRESHOLD = 8     # 自动 skip 达到此值 → 标记 review


# ── 路径工具 ──

def resolve_root(args: list[str]) -> Path:
    """解析 --project-root 参数，默认当前目录"""
    root = Path.cwd()
    for i, arg in enumerate(args):
        if arg == "--project-root" and i + 1 < len(args):
            root = Path(args[i + 1])
            break
    if not root.exists():
        print(f"错误：项目根目录不存在 → {root}")
        sys.exit(1)
    return root


def audit_csv_path(root: Path) -> Path:
    return root / "evolve" / "audit.csv"


def evolve_md_path(root: Path) -> Path:
    return root / "EVOLVE.md"


def archived_rules_path(root: Path) -> Path:
    return root / "evolve" / "archived-rules.md"


# ── CSV 读写 ──

def read_audit(path: Path) -> list[dict]:
    """读取 audit.csv，返回字典列表"""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            # 数值字段转 int
            for field in ("hit", "vio", "err", "skip", "auto_skip"):
                row[field] = int(row.get(field, 0))
            # 兼容旧格式：缺少 title/auto_skip/origin/platform 字段
            row.setdefault("title", "")
            row.setdefault("auto_skip", 0)
            row.setdefault("origin", "error")  # 旧数据默认视为源于实际错误
            raw_platform = row.get("platform", "")
            row["platform"] = canonical_platform(raw_platform)
            if row["platform"] == PLATFORM_ALL and is_platform_rule(row):
                row["platform"] = infer_legacy_platform(row)
            rows.append(row)
        return rows


def write_audit(path: Path, rows: list[dict]) -> None:
    """写入 audit.csv"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


# ── 推导指标计算 ──

def compliance_rate(row: dict) -> Optional[float]:
    """遵守率 = hit / (hit + vio)"""
    total = row["hit"] + row["vio"]
    if total == 0:
        return None
    return row["hit"] / total


def danger_rate(row: dict) -> Optional[float]:
    """危险度 = err / vio"""
    if row["vio"] == 0:
        return None
    return row["err"] / row["vio"]


def activity(row: dict) -> int:
    """活跃度 = hit + vio"""
    return row["hit"] + row["vio"]


def is_platform_rule(row: dict) -> bool:
    """S- 前缀代表平台教训"""
    return row.get("rule_id", "").startswith("S-")


def canonical_platform(raw: str) -> str:
    """标准化平台标签，未知值原样保留，空值回退 all"""
    normalized = (raw or "").strip().lower()
    if not normalized:
        return PLATFORM_ALL
    return PLATFORM_ALIASES.get(normalized, normalized)


def infer_legacy_platform(row: dict) -> str:
    """
    兼容旧数据：
    若 S- 规则缺失 platform，则尝试从 scope 顶级目录推断（如 Claude/工具 → claude）。
    """
    if not is_platform_rule(row):
        return PLATFORM_ALL
    top_scope = row.get("scope", "").split("/")[0].strip().lower()
    inferred = PLATFORM_ALIASES.get(top_scope)
    if inferred in KNOWN_PLATFORM_VALUES:
        return inferred
    return PLATFORM_ALL


def row_platform(row: dict) -> str:
    return canonical_platform(row.get("platform", PLATFORM_ALL))


def extract_platform_arg(args: list[str]) -> Optional[str]:
    """提取 --platform 参数，支持 --platform x / --platform=x"""
    for i, arg in enumerate(args):
        if arg == "--platform" and i + 1 < len(args):
            return canonical_platform(args[i + 1])
        if arg.startswith("--platform="):
            return canonical_platform(arg.split("=", 1)[1])
    return None


def match_platform(row: dict, platform: Optional[str], include_universal: bool = True) -> bool:
    """
    平台匹配规则：
    - 未指定 --platform：全部匹配
    - 指定 --platform：S- 规则按 platform 严格匹配
    - 非 S- 规则（通用规则）默认保留（可通过 include_universal 控制）
    """
    if not platform:
        return True
    if is_platform_rule(row):
        return row_platform(row) == platform
    return include_universal


# ── EVOLVE.md 操作 ──

def read_evolve(path: Path) -> str:
    """读取 EVOLVE.md 内容"""
    if not path.exists():
        print(f"警告：{path} 不存在，请先执行初始化")
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_evolve(path: Path, content: str) -> None:
    """写入 EVOLVE.md"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def update_rules_inline_tags(content: str, rows: list[dict]) -> str:
    """在 Rules 章节中更新内联审计标签 {hit:N vio:N err:N}"""
    for row in rows:
        if row["status"] == "archived":
            continue
        rule_id = re.escape(row["rule_id"])
        tag = f"`{{hit:{row['hit']} vio:{row['vio']} err:{row['err']}}}`"
        # 先尝试替换已有标签
        pattern = rf"(\[{rule_id}\][^\n]*?)\s*`\{{hit:\d+ vio:\d+ err:\d+\}}`"
        new_content = re.sub(pattern, rf"\1  {tag}", content)
        if new_content != content:
            content = new_content
        else:
            # 没有已有标签，尝试在规则行末追加
            pattern = rf"(\[{rule_id}\][^\n]+)"
            match = re.search(pattern, content)
            if match:
                original_line = match.group(1)
                content = content.replace(original_line, f"{original_line}  {tag}", 1)
    return content


def update_tldr_section(content: str, rows: list[dict]) -> str:
    """根据审计数据更新 TL;DR 章节"""
    # 找到 TL;DR 章节的位置
    tldr_match = re.search(r"^## TL;DR\s*\n", content, re.MULTILINE)
    if not tldr_match:
        return content

    # 找到下一个 ## 章节的位置
    next_section = re.search(r"^## (?!TL;DR)", content[tldr_match.end():], re.MULTILINE)
    tldr_end = tldr_match.end() + next_section.start() if next_section else len(content)

    # 提取当前 TL;DR 内容
    tldr_content = content[tldr_match.end():tldr_end]

    # 需要强调的规则（高频违反）
    emphasize = []
    # 需要标注高危的规则
    critical = []
    # 难执行规则（重要但表述不清）
    hard_to_follow = []

    for row in rows:
        if row["status"] not in ("active", "protected"):
            continue
        cr = compliance_rate(row)
        dr = danger_rate(row)

        # 高频违反：vio >= 3 且遵守率 < 50%
        if row["vio"] >= 3 and cr is not None and cr < 0.5:
            emphasize.append(row)

        # 高危：err >= 2 且危险度 >= 0.5
        if row["err"] >= 2 and dr is not None and dr >= 0.5:
            critical.append(row)

        # 难执行：hit >= 3 且 vio >= 3（重要但经常违反）
        if row["hit"] >= 3 and row["vio"] >= 3:
            hard_to_follow.append(row)

    changes_made = False

    # 追加需要强调的规则
    for row in emphasize:
        marker = f"[{row['rule_id']}]"
        if marker not in tldr_content:
            line = f"- ⚠️ **高频违反** [{row['rule_id']}] [{row['scope']}]：遵守率 {compliance_rate(row):.0%}，请重点关注\n"
            tldr_content = line + tldr_content
            changes_made = True

    # 标注高危规则
    for row in critical:
        marker = f"[{row['rule_id']}]"
        if marker not in tldr_content:
            line = f"- 🚨 **高危** [{row['rule_id']}] [{row['scope']}]：危险度 {danger_rate(row):.0%}，违反极易导致错误\n"
            tldr_content = line + tldr_content
            changes_made = True

    # 标注难执行规则
    for row in hard_to_follow:
        marker = f"[{row['rule_id']}]"
        # 避免与上面重复标注
        if marker not in tldr_content:
            cr = compliance_rate(row)
            line = f"- 🔧 **需重写** [{row['rule_id']}] [{row['scope']}]：遵守率 {cr:.0%}，规则重要但难以执行\n"
            tldr_content = line + tldr_content
            changes_made = True

    if changes_made:
        content = content[:tldr_match.end()] + tldr_content + content[tldr_end:]

    return content


# ── Scope 匹配工具 ──

def match_scope(row_scope: str, keywords: list[str]) -> bool:
    """判断 scope 是否匹配任一关键词（大小写不敏感，支持部分匹配）"""
    scope_lower = row_scope.lower()
    return any(kw.lower() in scope_lower for kw in keywords)


def extract_keywords(args: list[str]) -> list[str]:
    """从命令行参数提取关键词（逗号分隔或空格分隔）"""
    keywords = []
    for arg in args:
        if arg.startswith("--"):
            break
        for part in arg.split(","):
            stripped = part.strip()
            if stripped:
                keywords.append(stripped)
    return keywords


def parse_score_string(score_str: str) -> dict[str, list[str]]:
    """
    解析一行式打分字符串
    格式：R-001:+hit R-003:+vio+err S-002:+hit
    返回：{"R-001": ["hit"], "R-003": ["vio", "err"], "S-002": ["hit"]}
    """
    result = {}
    tokens = score_str.strip().split()
    for token in tokens:
        if ":" not in token:
            continue
        rule_id, actions_str = token.split(":", 1)
        actions = re.findall(r"\+(\w+)", actions_str)
        valid_actions = [a for a in actions if a in ("hit", "vio", "err", "skip")]
        if valid_actions:
            result[rule_id.strip()] = valid_actions
    return result


# ── 命令实现 ──

def cmd_init(root: Path) -> None:
    """初始化 audit.csv"""
    path = audit_csv_path(root)
    if path.exists():
        print(f"audit.csv 已存在 → {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_audit(path, [])
    print(f"已创建 → {path}")


def cmd_scopes(root: Path, args: Optional[list[str]] = None) -> None:
    """列出所有有效的 scope 类型"""
    args = args or []
    platform = extract_platform_arg(args)
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在")
        return

    # 收集所有 scope 及其层级拆分
    scope_map: dict[str, dict] = {}
    for row in rows:
        if row["status"] == "archived":
            continue
        if not match_platform(row, platform):
            continue
        scope = row["scope"]
        if scope not in scope_map:
            scope_map[scope] = {"count": 0, "ids": []}
        scope_map[scope]["count"] += 1
        scope_map[scope]["ids"].append(row["rule_id"])

    # 提取所有独立关键词（按 / 拆分）
    all_keywords: dict[str, int] = {}
    for scope in scope_map:
        for part in scope.split("/"):
            part = part.strip()
            if part:
                all_keywords[part] = all_keywords.get(part, 0) + scope_map[scope]["count"]

    if not scope_map:
        hint = f"（平台过滤：{platform}）" if platform else ""
        print(f"未找到有效 scope {hint}")
        return

    platform_text = platform if platform else "all"
    print(f"[共 {len(scope_map)} 个 scope，{sum(v['count'] for v in scope_map.values())} 条活跃规则 | platform: {platform_text}]\n")

    print("可用关键词（按规则数排序）：")
    for kw, count in sorted(all_keywords.items(), key=lambda x: -x[1]):
        print(f"  {kw:<20} ({count} 条)")

    print(f"\n完整 scope 列表：")
    for scope, info in sorted(scope_map.items()):
        ids = ", ".join(info["ids"][:5])
        suffix = "..." if len(info["ids"]) > 5 else ""
        print(f"  {scope:<30} → {ids}{suffix}")


def cmd_filter(root: Path, args: list[str]) -> None:
    """按 scope 关键词筛选相关经验条目"""
    platform = extract_platform_arg(args)
    keywords = extract_keywords(args)
    if not keywords and not platform:
        print("用法：audit_sync.py filter <关键词1,关键词2,...> [--platform <name>]")
        print("或：audit_sync.py filter --platform <name>")
        print("提示：先运行 scopes 命令查看可用关键词")
        return

    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在")
        return

    matched = [
        r for r in rows
        if r["status"] != "archived"
        and match_platform(r, platform)
        and (not keywords or match_scope(r["scope"], keywords))
    ]

    if not matched:
        if keywords:
            print(f"未匹配到任何条目（关键词：{', '.join(keywords)}，platform: {platform or 'all'}）")
        else:
            print(f"未匹配到任何条目（platform: {platform}）")
        print("提示：运行 scopes 命令查看可用关键词")
        return

    # 按遵守率排序：低遵守率优先（需要重点关注的排前面）
    def sort_key(r):
        cr = compliance_rate(r)
        return cr if cr is not None else 1.0

    matched.sort(key=sort_key)

    keyword_text = ", ".join(keywords) if keywords else "*"
    print(f"[{len(matched)} 条匹配 scope: {keyword_text} | platform: {platform or 'all'}]")
    # 精简表格输出
    id_w = max(len(r["rule_id"]) for r in matched)
    platform_w = max(len(row_platform(r)) for r in matched)
    scope_w = max(len(r["scope"]) for r in matched)
    for r in matched:
        stats = f"hit:{r['hit']} vio:{r['vio']} err:{r['err']}"
        origin = r.get("origin", "error")
        title = r.get("title", "")[:50]
        platform_tag = row_platform(r)
        print(f"  {r['rule_id']:<{id_w}} | {platform_tag:<{platform_w}} | {r['scope']:<{scope_w}} | {origin:<11} | {stats:<20} | {title}")

    print(f"\n打分语法：score \"R-001:+hit R-002:+vio+err ...\" [--scope \"关键词\"] [--platform \"{platform or 'name'}\"]")
    print(f"未打分的 {len(matched)} 条将自动 auto_skip+1")


def cmd_score(root: Path, args: list[str]) -> None:
    """一行式批量打分，未打分的 filter 匹配项自动 auto_skip+1"""
    # 解析参数：score "R-001:+hit R-003:+vio" [--scope "前端,React"] [--platform "codex"]
    score_str = ""
    scope_keywords = []
    platform = extract_platform_arg(args)
    i = 0
    while i < len(args):
        if args[i] == "--scope" and i + 1 < len(args):
            scope_keywords = [k.strip() for k in args[i + 1].split(",") if k.strip()]
            i += 2
        elif args[i].startswith("--scope="):
            scope_keywords = [k.strip() for k in args[i].split("=", 1)[1].split(",") if k.strip()]
            i += 1
        elif args[i] == "--platform":
            i += 2
        elif args[i].startswith("--platform="):
            i += 1
        elif args[i] == "--project-root":
            i += 2
        elif args[i].startswith("--project-root="):
            i += 1
        else:
            if not score_str and not args[i].startswith("--"):
                score_str = args[i]
            i += 1

    if not score_str:
        print("用法：audit_sync.py score \"R-001:+hit R-003:+vio+err\" [--scope \"前端,React\"] [--platform \"codex\"]")
        return

    scores = parse_score_string(score_str)
    if not scores:
        print(f"无法解析打分字符串：{score_str}")
        print("格式：R-001:+hit R-003:+vio+err S-002:+hit")
        return

    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在")
        return

    today = date.today().isoformat()
    scored_ids = set(scores.keys())
    updated_count = 0
    auto_skipped = []
    not_found = []

    # 确定匹配范围（--scope / --platform）
    matched_ids = set()
    if scope_keywords or platform:
        matched_ids = {
            r["rule_id"]
            for r in rows
            if r["status"] != "archived"
            and (not scope_keywords or match_scope(r["scope"], scope_keywords))
            and match_platform(r, platform)
        }

    updated_rows = []
    for row in rows:
        new_row = {**row}
        rule_id = row["rule_id"]

        if rule_id in scored_ids:
            # 应用打分
            actions = scores[rule_id]
            for action in actions:
                if action == "hit":
                    new_row["hit"] += 1
                elif action == "vio":
                    new_row["vio"] += 1
                elif action == "err":
                    new_row["err"] += 1
                elif action == "skip":
                    new_row["skip"] += 1
            new_row["last_reviewed"] = today
            # 手动打分时清零 auto_skip（证明 AI 是有意识的）
            new_row["auto_skip"] = 0
            updated_count += 1

        elif (scope_keywords or platform) and rule_id in matched_ids and rule_id not in scored_ids:
            # 匹配但未被打分 → auto_skip+1
            if new_row["status"] == "active":
                new_row["auto_skip"] += 1
                new_row["last_reviewed"] = today
                auto_skipped.append(rule_id)

        updated_rows.append(new_row)

    # 检查打分中是否有不存在的 rule_id
    existing_ids = {r["rule_id"] for r in rows}
    not_found = [rid for rid in scored_ids if rid not in existing_ids]

    write_audit(csv_path, updated_rows)

    # 输出结果
    print(f"打分完成：{updated_count} 条已更新")
    for rule_id, actions in scores.items():
        if rule_id not in not_found:
            print(f"  {rule_id} → +{', +'.join(actions)}")
    if auto_skipped:
        print(f"\n自动 auto_skip+1：{len(auto_skipped)} 条")
        print(f"  {', '.join(auto_skipped)}")
        if platform:
            print(f"  平台过滤：{platform}")
    if not_found:
        print(f"\n⚠️ 以下 rule_id 不存在：{', '.join(not_found)}")


def cmd_sync(root: Path) -> None:
    """从 audit.csv 同步指标到 EVOLVE.md"""
    csv_path = audit_csv_path(root)
    md_path = evolve_md_path(root)

    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在，无需同步")
        return

    content = read_evolve(md_path)
    if not content:
        return

    # 1) 更新 Rules 内联标签
    content = update_rules_inline_tags(content, rows)

    # 2) 更新 TL;DR 章节
    content = update_tldr_section(content, rows)

    # 3) 标记待审查（区分手动 skip 和 auto_skip，protected 不参与）
    updated_rows = []
    review_items = []
    low_value_items = []
    for row in rows:
        if row["status"] == "active":
            # 待审查：skip 过多
            should_review = (
                row["skip"] >= MANUAL_SKIP_THRESHOLD or
                row["auto_skip"] >= AUTO_SKIP_THRESHOLD
            )
            if should_review:
                row = {**row, "status": "review"}
                reason = "skip" if row["skip"] >= MANUAL_SKIP_THRESHOLD else "auto_skip"
                review_items.append(f"{row['rule_id']}({reason})")

            # 低价值嫌疑：hit >= 8 且从未违反，且 origin 非 error
            elif row["hit"] >= 8 and row["vio"] == 0 and row["err"] == 0 and row.get("origin") != "error":
                low_value_items.append(row["rule_id"])

        updated_rows.append(row)

    write_evolve(md_path, content)
    write_audit(csv_path, updated_rows)

    print(f"同步完成 → {md_path}")
    if review_items:
        print(f"⚠️ 以下规则已标记为待审查：{', '.join(review_items)}")
    if low_value_items:
        print(f"❔ 低价值嫌疑（hit≥8 且从未违反）：{', '.join(low_value_items)}")
        print("  → 运行 report 查看详情，由用户确认是否 protected 或 archived")


def cmd_report(root: Path) -> None:
    """输出审计报告"""
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在")
        return

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    review_rows = [r for r in rows if r["status"] == "review"]
    archived_rows = [r for r in rows if r["status"] == "archived"]
    protected_rows = [r for r in rows if r["status"] == "protected"]

    print("=" * 60)
    print("  审计报告")
    print("=" * 60)
    print(f"\n总计：{len(rows)} 条（active: {len(active_rows) - len(protected_rows)}, protected: {len(protected_rows)}, review: {len(review_rows)}, archived: {len(archived_rows)}）\n")

    # 高频违反
    high_vio = [
        r
        for r in active_rows
        if r["vio"] >= 3 and (cr := compliance_rate(r)) is not None and cr < 0.5
    ]
    if high_vio:
        print("⚠️ 高频违反（需重点强调）：")
        for r in high_vio:
            print(f"  [{r['rule_id']}] {r['scope']} — 遵守率: {compliance_rate(r):.0%}, vio: {r['vio']}")
        print()

    # 高危规则
    high_danger = [
        r
        for r in active_rows
        if r["err"] >= 2 and (dr := danger_rate(r)) is not None and dr >= 0.5
    ]
    if high_danger:
        print("🚨 高危规则（违反极易导致错误）：")
        for r in high_danger:
            print(f"  [{r['rule_id']}] {r['scope']} — 危险度: {danger_rate(r):.0%}, err: {r['err']}")
        print()

    # 难执行规则（重要但经常违反）
    hard_to_follow = [r for r in active_rows if r["hit"] >= 3 and r["vio"] >= 3]
    if hard_to_follow:
        print("🔧 难执行（规则重要但表述可能不清晰，建议重写）：")
        for r in hard_to_follow:
            cr = compliance_rate(r)
            print(f"  [{r['rule_id']}] {r['scope']} — 遵守率: {cr:.0%}, hit:{r['hit']} vio:{r['vio']}")
        print()

    # 低价值嫌疑（正确的废话）：hit >= 8 且历史 vio=0 err=0，排除 protected 和 origin=error
    low_value = [r for r in rows if r["status"] == "active" and r["hit"] >= 8 and r["vio"] == 0 and r["err"] == 0 and r.get("origin") != "error"]
    if low_value:
        print("❔ 低价值嫌疑（从未被违反的高频命中规则，且非源于实际错误）：")
        for r in low_value:
            print(f"  [{r['rule_id']}] {r['scope']} (origin:{r.get('origin', '?')}) — hit:{r['hit']} vio:0 err:0 — {r.get('title', '')}")
        print("  → 用户确认：'防患于未然' → protected；'正确的废话' → archived")
        print()

    # 优质规则（表述清晰、执行良好）
    quality = [r for r in active_rows if r["hit"] >= 3 and r["vio"] == 0 and r["hit"] < 8]
    if quality:
        print("✅ 优质规则（表述清晰，每次读到都能正确执行）：")
        for r in quality:
            print(f"  [{r['rule_id']}] {r['scope']} — hit: {r['hit']}")
        print()

    # 待审查
    if review_rows:
        print("❓ 待审查（可能已过时，需用户确认）：")
        for r in review_rows:
            print(f"  [{r['rule_id']}] {r['scope']} — skip: {r['skip']}, auto_skip: {r['auto_skip']}, last: {r['last_reviewed']}")
        print()

    # 活跃度 Top 5
    sorted_by_activity = sorted(active_rows, key=lambda r: activity(r), reverse=True)[:5]
    if sorted_by_activity:
        print("📊 活跃度 Top 5：")
        for r in sorted_by_activity:
            act = activity(r)
            if act > 0:
                print(f"  [{r['rule_id']}] {r['scope']} — 活跃度: {act} (hit:{r['hit']} vio:{r['vio']})")
        print()


def cmd_promote(root: Path, args: Optional[list[str]] = None) -> None:
    """输出晋升建议"""
    args = args or []
    platform = extract_platform_arg(args)
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv 为空或不存在")
        return

    # 平台教训（S-xxx）中高频违反的
    candidates = []
    for r in rows:
        if not r["rule_id"].startswith("S-"):
            continue
        if r["status"] != "active":
            continue
        if platform and row_platform(r) != platform:
            continue
        cr = compliance_rate(r)
        # 条件1：vio >= 3 且遵守率 < 50%
        if r["vio"] >= 3 and cr is not None and cr < 0.5:
            candidates.append({**r, "reason": f"高频违反（遵守率 {cr:.0%}）"})
            continue
        # 条件2：err >= 2 且危险度 >= 0.5
        dr = danger_rate(r)
        if r["err"] >= 2 and dr is not None and dr >= 0.5:
            candidates.append({**r, "reason": f"高危（危险度 {dr:.0%}）"})

    if not candidates:
        if platform:
            print(f"当前无晋升建议（platform: {platform}）")
        else:
            print("当前无晋升建议")
        return

    print("=" * 60)
    print("  用户级晋升建议")
    print("=" * 60)
    title_suffix = f"（platform: {platform}）" if platform else ""
    print(f"\n以下平台教训建议晋升至用户级配置文件{title_suffix}：\n")
    for c in candidates:
        print(f"  [{c['rule_id']}] [{row_platform(c)}] {c['scope']}")
        print(f"    原因：{c['reason']}")
        print(f"    数据：hit={c['hit']} vio={c['vio']} err={c['err']}")
        print()
    print("请在复盘时由用户确认是否执行晋升。")


# ── 入口 ──

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1]
    remaining_args = sys.argv[2:]
    root = resolve_root(remaining_args)

    if command == "filter":
        cmd_filter(root, remaining_args)
    elif command == "score":
        cmd_score(root, remaining_args)
    elif command == "scopes":
        cmd_scopes(root, remaining_args)
    elif command == "promote":
        cmd_promote(root, remaining_args)
    elif command == "init":
        cmd_init(root)
    elif command == "sync":
        cmd_sync(root)
    elif command == "report":
        cmd_report(root)
    else:
        print(f"未知命令：{command}")
        print(f"可用命令：init, scopes, filter, score, sync, report, promote")
        sys.exit(1)


if __name__ == "__main__":
    main()
