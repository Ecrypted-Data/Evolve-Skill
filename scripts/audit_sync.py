#!/usr/bin/env python3
"""
Audit sync utility for Evolve-Skill.

Commands:
  init          Initialize evolve/audit.csv if missing
  scopes        List available scope keywords
  filter        Filter rules by scope/platform
  score         One-line scoring, unmatched filtered rules get auto_skip+1
  sync          Sync metrics to EVOLVE.md and platform files
  sync_platform Sync platform files only (does not modify EVOLVE.md)
  report        Print audit report with derived metrics and anomalies
  promote       Print promotion suggestions (platform lessons -> user config)

Usage:
  python audit_sync.py <command> [args] [--project-root <path>] [--platform <name>]

  --project-root      Project root path (default: current working directory)
  --platform          Platform label (claude/gemini/codex/cursor)
  --evolve-platform   Limit EVOLVE.md sync target to universal + this platform
  --no-platform-sync  For sync only: skip platform file sync

Suggested workflow:
  1. scopes
  2. filter "frontend,react" --platform codex
  3. score "R-001:+hit R-003:+vio+err" --scope "frontend,react" --platform codex
  4. sync
"""

import csv
import builtins
import hashlib
import json
import re
import sys
from pathlib import Path
from datetime import date
from typing import Optional

def _configure_stream_utf8(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


_configure_stream_utf8(sys.stdout)
_configure_stream_utf8(sys.stderr)


def _ascii_text(value: object) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _safe_print(*args: object, sep: str = " ", end: str = "\n", file=sys.stdout, flush: bool = False) -> None:
    rendered = sep.join(_ascii_text(arg) for arg in args)
    builtins.print(rendered, end=end, file=file, flush=flush)


print = _safe_print


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

KNOWN_PLATFORM_FILES = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
    "cursor": "CURSOR.md",
}
PLATFORM_TARGETS_CONFIG = "platform_targets.json"
AUTO_SYNC_BEGIN_PREFIX = "<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN"
AUTO_SYNC_END = "<!-- EVOLVE_SKILL:AUTO_SYNC:END -->"
AUTO_SYNC_HEADER = "## Evolve-Skill Auto Sync"


# ── 路径工具 ──

def resolve_root(args: list[str]) -> Path:
    """解析 --project-root 参数，默认当前目录"""
    root = Path.cwd()
    for i, arg in enumerate(args):
        if arg == "--project-root" and i + 1 < len(args):
            root = Path(args[i + 1])
            break
    if not root.exists():
        print(f"Error: project root does not exist -> {root}")
        sys.exit(1)
    return root


def audit_csv_path(root: Path) -> Path:
    return root / "evolve" / "audit.csv"


def evolve_md_path(root: Path) -> Path:
    return root / "EVOLVE.md"


def archived_rules_path(root: Path) -> Path:
    return root / "evolve" / "archived-rules.md"


def platform_targets_path(root: Path) -> Path:
    return root / "evolve" / PLATFORM_TARGETS_CONFIG


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


def extract_evolve_platform_arg(args: list[str]) -> Optional[str]:
    """提取 --evolve-platform 参数，支持 --evolve-platform x / --evolve-platform=x"""
    for i, arg in enumerate(args):
        if arg == "--evolve-platform" and i + 1 < len(args):
            return canonical_platform(args[i + 1])
        if arg.startswith("--evolve-platform="):
            return canonical_platform(arg.split("=", 1)[1])
    return None


def filter_rows_for_evolve_sync(rows: list[dict], evolve_platform: Optional[str]) -> list[dict]:
    """
    限制 EVOLVE.md 的同步目标：
    - 未指定平台或平台为 all：全量
    - 指定平台：保留全部通用规则（R-），以及该平台的 S- 规则
    """
    if not evolve_platform or evolve_platform == PLATFORM_ALL:
        return rows

    filtered = []
    for row in rows:
        if is_platform_rule(row):
            if row_platform(row) == evolve_platform:
                filtered.append(row)
        else:
            filtered.append(row)
    return filtered


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
        print(f"Warning: {path} does not exist. Run init first.")
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


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def load_platform_target_map(root: Path) -> dict[str, str]:
    """读取平台文件映射配置，支持 evolve/platform_targets.json。"""
    config_path = platform_targets_path(root)
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: failed to read platform target config: {config_path} ({exc})")
        return {}

    if not isinstance(data, dict):
        return {}

    raw_map: dict[str, str] = {}
    map_keys = ("platform_file_map", "platform_files")
    if any(k in data for k in map_keys):
        for key in map_keys:
            candidate = data.get(key)
            if isinstance(candidate, dict):
                for platform, filepath in candidate.items():
                    if isinstance(platform, str) and isinstance(filepath, str):
                        raw_map[platform] = filepath
    else:
        for platform, filepath in data.items():
            if isinstance(platform, str) and isinstance(filepath, str):
                raw_map[platform] = filepath

    normalized: dict[str, str] = {}
    for platform, filepath in raw_map.items():
        p = canonical_platform(platform)
        if p and p != PLATFORM_ALL and filepath.strip():
            normalized[p] = filepath.strip()
    return normalized


def extract_platform_marker_map(root: Path) -> dict[str, Path]:
    """扫描根目录 markdown，提取已存在的平台自动同步区块。"""
    marker_map: dict[str, Path] = {}
    pattern = re.compile(
        r"<!--\s*EVOLVE_SKILL:AUTO_SYNC:BEGIN\s+platform=([^\s>]+)[^>]*-->",
        re.IGNORECASE,
    )
    for md_path in root.glob("*.md"):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in pattern.finditer(text):
            platform = canonical_platform(match.group(1))
            if platform and platform != PLATFORM_ALL and platform not in marker_map:
                marker_map[platform] = md_path
    return marker_map


def platform_slug(platform: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", platform.lower()).strip("-_.")
    return slug or "platform"


def default_platform_filename(platform: str) -> str:
    if platform in KNOWN_PLATFORM_FILES:
        return KNOWN_PLATFORM_FILES[platform]
    return f"{platform_slug(platform).upper()}.md"


def resolve_platform_file_path(
    root: Path,
    platform: str,
    config_map: dict[str, str],
    marker_map: dict[str, Path],
) -> Path:
    if platform in config_map:
        configured = Path(config_map[platform])
        return configured if configured.is_absolute() else root / configured
    if platform in marker_map:
        return marker_map[platform]
    return root / default_platform_filename(platform)


def discover_sync_platforms(
    root: Path,
    rows: list[dict],
    config_map: dict[str, str],
    marker_map: dict[str, Path],
    only_platform: Optional[str] = None,
) -> list[str]:
    platforms = set()

    platforms.update(p for p in config_map.keys() if p != PLATFORM_ALL)
    platforms.update(p for p in marker_map.keys() if p != PLATFORM_ALL)
    platforms.update(
        p for p, filename in KNOWN_PLATFORM_FILES.items()
        if (root / filename).exists()
    )

    for row in rows:
        if not is_platform_rule(row):
            continue
        p = row_platform(row)
        if p != PLATFORM_ALL:
            platforms.add(p)

    if only_platform:
        p = canonical_platform(only_platform)
        if p and p != PLATFORM_ALL:
            return [p]
    return sorted(platforms)


def extract_markdown_section(content: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", content, re.MULTILINE)
    if not match:
        return ""
    next_section = re.search(r"^##\s+", content[match.end():], re.MULTILINE)
    end = match.end() + next_section.start() if next_section else len(content)
    return content[match.end():end].strip()


def trim_multiline(text: str, max_lines: int = 8, max_chars: int = 900) -> list[str]:
    if not text.strip():
        return ["- (no data)"]

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    trimmed: list[str] = []
    total = 0
    for line in lines:
        if len(trimmed) >= max_lines:
            break
        if total + len(line) > max_chars:
            remain = max_chars - total
            if remain > 20:
                trimmed.append(line[:remain].rstrip() + " ...")
            break
        trimmed.append(line)
        total += len(line)

    if len(lines) > len(trimmed):
        trimmed.append("- ...")
    return trimmed or ["- (no data)"]


def select_high_signal_rules(rows: list[dict], limit: int) -> list[dict]:
    ranked = sorted(
        rows,
        key=lambda r: (r["err"], r["vio"], activity(r), r["hit"], r["rule_id"]),
        reverse=True,
    )
    return ranked[:limit]


def build_platform_digest(platform: str, evolve_content: str, rows: list[dict]) -> str:
    relevant = []
    for row in rows:
        if row["status"] not in ("active", "protected"):
            continue
        if is_platform_rule(row):
            if row_platform(row) != platform:
                continue
        relevant.append(
            {
                "rule_id": row["rule_id"],
                "platform": row_platform(row),
                "scope": row.get("scope", ""),
                "title": row.get("title", ""),
                "hit": row["hit"],
                "vio": row["vio"],
                "err": row["err"],
                "status": row.get("status", ""),
            }
        )
    relevant.sort(key=lambda r: r["rule_id"])

    payload = {
        "platform": platform,
        "evolve_sha1": hashlib.sha1(evolve_content.encode("utf-8")).hexdigest(),
        "rules": relevant,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def clean_rule_content_line(line: str, rule_id: str) -> str:
    text = line.strip()
    text = re.sub(r"^[>\-*+\d.\s]+", "", text)
    text = re.sub(r"\s*`\{hit:\d+\s+vio:\d+\s+err:\d+\}`\s*$", "", text)
    text = re.sub(rf"^\[{re.escape(rule_id)}\]\s*", "", text)
    text = text.replace("**", "")
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_rule_content_map(evolve_content: str) -> dict[str, str]:
    """从 EVOLVE.md 的 Rules 章节抽取每条规则的可读正文。"""
    rules_text = extract_markdown_section(evolve_content, "Rules")
    if not rules_text.strip():
        return {}

    content_map: dict[str, str] = {}
    for raw_line in rules_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("<!--"):
            continue
        match = re.search(r"\[((?:R|S)-\d+)\]", line)
        if not match:
            continue
        rule_id = match.group(1)
        content = clean_rule_content_line(line, rule_id)
        if content:
            content_map[rule_id] = content
    return content_map


def format_rule_line(row: dict, rule_content_map: Optional[dict[str, str]] = None) -> str:
    title = row.get("title", "").strip()
    title_suffix = f" - {title}" if title else ""
    base = (
        f"- [{row['rule_id']}] [{row.get('scope', '')}]{title_suffix} "
        f"`{{hit:{row['hit']} vio:{row['vio']} err:{row['err']}}}`"
    )
    if not rule_content_map:
        return base

    content = rule_content_map.get(row["rule_id"], "").strip()
    if not content:
        return base
    return f"{base}\n  Content: {content}"


def render_platform_sync_block(platform: str, evolve_content: str, rows: list[dict], digest: str) -> str:
    tldr_text = extract_markdown_section(evolve_content, "TL;DR")
    changelog_text = extract_markdown_section(evolve_content, "Changelog")
    rule_content_map = extract_rule_content_map(evolve_content)

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    platform_rows = [
        r for r in active_rows
        if is_platform_rule(r) and row_platform(r) == platform
    ]
    universal_rows = [r for r in active_rows if not is_platform_rule(r)]

    selected_platform_rows = select_high_signal_rules(platform_rows, limit=8)
    selected_universal_rows = select_high_signal_rules(universal_rows, limit=6)

    lines = [
        AUTO_SYNC_HEADER,
        "",
        "This block is auto-generated from `EVOLVE.md` and `evolve/audit.csv`.",
        "Edit `EVOLVE.md` instead of editing this block.",
        f"- Platform: `{platform}`",
        f"- Updated: `{date.today().isoformat()}`",
        f"- Digest: `{digest}`",
        "",
        "### TL;DR Snapshot",
        *trim_multiline(tldr_text, max_lines=8, max_chars=900),
        "",
        f"### Platform Rules ({platform})",
    ]

    if selected_platform_rows:
        lines.extend(format_rule_line(row, rule_content_map) for row in selected_platform_rows)
    else:
        lines.append("- (no platform-specific rules found)")

    lines.extend(["", "### Universal High-Signal Rules"])
    if selected_universal_rows:
        lines.extend(format_rule_line(row, rule_content_map) for row in selected_universal_rows)
    else:
        lines.append("- (no universal rules found)")

    lines.extend(["", "### Recent Changelog Snapshot"])
    lines.extend(trim_multiline(changelog_text, max_lines=8, max_chars=900))
    return "\n".join(lines)


def upsert_platform_sync_block(content: str, platform: str, block_content: str, digest: str) -> str:
    begin_line = (
        f"{AUTO_SYNC_BEGIN_PREFIX} platform={platform} "
        f"digest={digest} updated={date.today().isoformat()} -->"
    )
    block = f"{begin_line}\n{block_content}\n{AUTO_SYNC_END}"
    pattern = re.compile(
        rf"<!--\s*EVOLVE_SKILL:AUTO_SYNC:BEGIN\s+platform={re.escape(platform)}[^\n]*-->\n.*?<!--\s*EVOLVE_SKILL:AUTO_SYNC:END\s*-->",
        re.DOTALL,
    )
    if pattern.search(content):
        return pattern.sub(block, content, count=1)

    base = content.rstrip()
    if not base:
        return block + "\n"
    return base + "\n\n" + block + "\n"


def sync_platform_files(
    root: Path,
    rows: list[dict],
    evolve_content: str,
    args: Optional[list[str]] = None,
) -> dict[str, list[str]]:
    args = args or []
    if has_flag(args, "--no-platform-sync"):
        return {"targets": [], "created": [], "updated": [], "unchanged": []}

    config_map = load_platform_target_map(root)
    marker_map = extract_platform_marker_map(root)
    only_platform = extract_platform_arg(args)
    platforms = discover_sync_platforms(root, rows, config_map, marker_map, only_platform)

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    targets: list[str] = []

    for platform in platforms:
        target_path = resolve_platform_file_path(root, platform, config_map, marker_map)
        targets.append(f"{platform}:{target_path}")

        old_content = ""
        existed = target_path.exists()
        if existed:
            try:
                old_content = target_path.read_text(encoding="utf-8")
            except OSError:
                old_content = ""

        digest = build_platform_digest(platform, evolve_content, rows)
        block_content = render_platform_sync_block(platform, evolve_content, rows, digest)
        new_content = upsert_platform_sync_block(old_content, platform, block_content, digest)

        if new_content == old_content:
            unchanged.append(str(target_path))
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        if existed:
            updated.append(str(target_path))
        else:
            created.append(str(target_path))

    return {
        "targets": targets,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
    }


def print_platform_sync_summary(summary: dict[str, list[str]]) -> None:
    targets = summary.get("targets", [])
    if not targets:
        print("Platform file sync: no targets (skipped)")
        return

    created = summary.get("created", [])
    updated = summary.get("updated", [])
    unchanged = summary.get("unchanged", [])
    print(
        f"Platform file sync complete: {len(targets)} targets, "
        f"created={len(created)} updated={len(updated)} unchanged={len(unchanged)}"
    )
    if created:
        print("  Created:")
        for path in created:
            print(f"    - {path}")
    if updated:
        print("  Updated:")
        for path in updated:
            print(f"    - {path}")


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
        print(f"audit.csv already exists -> {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_audit(path, [])
    print(f"Created -> {path}")


def cmd_scopes(root: Path, args: Optional[list[str]] = None) -> None:
    """列出所有有效的 scope 类型"""
    args = args or []
    platform = extract_platform_arg(args)
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing")
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
        hint = f" (platform filter: {platform})" if platform else ""
        print(f"No valid scopes found{hint}")
        return

    platform_text = platform if platform else "all"
    print(f"[{len(scope_map)} scopes, {sum(v['count'] for v in scope_map.values())} active rules | platform: {platform_text}]\n")

    print("Available keywords (sorted by rule count):")
    for kw, count in sorted(all_keywords.items(), key=lambda x: -x[1]):
        print(f"  {kw:<20} ({count} rules)")

    print("\nFull scope list:")
    for scope, info in sorted(scope_map.items()):
        ids = ", ".join(info["ids"][:5])
        suffix = "..." if len(info["ids"]) > 5 else ""
        print(f"  {scope:<30} -> {ids}{suffix}")


def cmd_filter(root: Path, args: list[str]) -> None:
    """按 scope 关键词筛选相关经验条目"""
    platform = extract_platform_arg(args)
    keywords = extract_keywords(args)
    if not keywords and not platform:
        print("Usage: audit_sync.py filter <keyword1,keyword2,...> [--platform <name>]")
        print("   or: audit_sync.py filter --platform <name>")
        print("Hint: run `scopes` to list available keywords")
        return

    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing")
        return

    matched = [
        r for r in rows
        if r["status"] != "archived"
        and match_platform(r, platform)
        and (not keywords or match_scope(r["scope"], keywords))
    ]

    if not matched:
        if keywords:
            print(f"No entries matched (keywords: {', '.join(keywords)}, platform: {platform or 'all'})")
        else:
            print(f"No entries matched (platform: {platform})")
        print("Hint: run `scopes` to list available keywords")
        return

    # 按遵守率排序：低遵守率优先（需要重点关注的排前面）
    def sort_key(r):
        cr = compliance_rate(r)
        return cr if cr is not None else 1.0

    matched.sort(key=sort_key)

    keyword_text = ", ".join(keywords) if keywords else "*"
    print(f"[{len(matched)} matched rules | scope: {keyword_text} | platform: {platform or 'all'}]")
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

    print(f"\nScoring syntax: score \"R-001:+hit R-002:+vio+err ...\" [--scope \"keywords\"] [--platform \"{platform or 'name'}\"]")
    print(f"{len(matched)} unmatched filtered rules will receive auto_skip+1")


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
        print("Usage: audit_sync.py score \"R-001:+hit R-003:+vio+err\" [--scope \"frontend,react\"] [--platform \"codex\"]")
        return

    scores = parse_score_string(score_str)
    if not scores:
        print(f"Cannot parse score string: {score_str}")
        print("Format: R-001:+hit R-003:+vio+err S-002:+hit")
        return

    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing")
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
    print(f"Scoring complete: {updated_count} rules updated")
    for rule_id, actions in scores.items():
        if rule_id not in not_found:
            print(f"  {rule_id} -> +{', +'.join(actions)}")
    if auto_skipped:
        print(f"\nAuto auto_skip+1: {len(auto_skipped)} rules")
        print(f"  {', '.join(auto_skipped)}")
        if platform:
            print(f"  Platform filter: {platform}")
    if not_found:
        print(f"\nWarning: unknown rule_id(s): {', '.join(not_found)}")


def cmd_sync(root: Path, args: Optional[list[str]] = None) -> None:
    """从 audit.csv 同步指标到 EVOLVE.md"""
    args = args or []
    csv_path = audit_csv_path(root)
    md_path = evolve_md_path(root)

    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing; nothing to sync")
        return

    content = read_evolve(md_path)
    if not content:
        return

    evolve_platform = extract_evolve_platform_arg(args)
    evolve_rows = filter_rows_for_evolve_sync(rows, evolve_platform)

    # 1) 更新 Rules 内联标签
    content = update_rules_inline_tags(content, evolve_rows)

    # 2) 更新 TL;DR 章节
    content = update_tldr_section(content, evolve_rows)

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
    platform_summary = sync_platform_files(root, updated_rows, content, args)

    print(f"Sync complete -> {md_path}")
    if evolve_platform and evolve_platform != PLATFORM_ALL:
        print(f"EVOLVE.md sync target: universal + platform={evolve_platform}")
    print_platform_sync_summary(platform_summary)
    if review_items:
        print(f"Warning: marked for review: {', '.join(review_items)}")
    if low_value_items:
        print(f"Low-value candidates (hit>=8 with no violations): {', '.join(low_value_items)}")
        print("  -> Run `report` and confirm whether to mark as protected or archived")


def cmd_sync_platform(root: Path, args: Optional[list[str]] = None) -> None:
    """仅同步平台文件（不改写 EVOLVE.md 内容）。"""
    args = args or []
    csv_path = audit_csv_path(root)
    md_path = evolve_md_path(root)

    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing; cannot sync platform files")
        return

    content = read_evolve(md_path)
    if not content:
        return

    summary = sync_platform_files(root, rows, content, args)
    print_platform_sync_summary(summary)


def cmd_report(root: Path) -> None:
    """输出审计报告"""
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing")
        return

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    review_rows = [r for r in rows if r["status"] == "review"]
    archived_rows = [r for r in rows if r["status"] == "archived"]
    protected_rows = [r for r in rows if r["status"] == "protected"]

    print("=" * 60)
    print("  Audit Report")
    print("=" * 60)
    print(f"\nTotal: {len(rows)} (active: {len(active_rows) - len(protected_rows)}, protected: {len(protected_rows)}, review: {len(review_rows)}, archived: {len(archived_rows)})\n")

    # 高频违反
    high_vio = [
        r
        for r in active_rows
        if r["vio"] >= 3 and (cr := compliance_rate(r)) is not None and cr < 0.5
    ]
    if high_vio:
        print("[WARN] Frequent violations (needs emphasis):")
        for r in high_vio:
            print(f"  [{r['rule_id']}] {r['scope']} - compliance: {compliance_rate(r):.0%}, vio: {r['vio']}")
        print()

    # 高危规则
    high_danger = [
        r
        for r in active_rows
        if r["err"] >= 2 and (dr := danger_rate(r)) is not None and dr >= 0.5
    ]
    if high_danger:
        print("[HIGH-RISK] Rules where violations often cause errors:")
        for r in high_danger:
            print(f"  [{r['rule_id']}] {r['scope']} - danger: {danger_rate(r):.0%}, err: {r['err']}")
        print()

    # 难执行规则（重要但经常违反）
    hard_to_follow = [r for r in active_rows if r["hit"] >= 3 and r["vio"] >= 3]
    if hard_to_follow:
        print("[REWRITE] Important but hard-to-follow rules:")
        for r in hard_to_follow:
            cr = compliance_rate(r)
            print(f"  [{r['rule_id']}] {r['scope']} - compliance: {cr:.0%}, hit:{r['hit']} vio:{r['vio']}")
        print()

    # 低价值嫌疑（正确的废话）：hit >= 8 且历史 vio=0 err=0，排除 protected 和 origin=error
    low_value = [r for r in rows if r["status"] == "active" and r["hit"] >= 8 and r["vio"] == 0 and r["err"] == 0 and r.get("origin") != "error"]
    if low_value:
        print("[REVIEW] Low-value candidates (high hit, never violated, origin!=error):")
        for r in low_value:
            print(f"  [{r['rule_id']}] {r['scope']} (origin:{r.get('origin', '?')}) - hit:{r['hit']} vio:0 err:0 - {r.get('title', '')}")
        print("  -> User decision: keep as protected, or archive as low-value")
        print()

    # 优质规则（表述清晰、执行良好）
    quality = [r for r in active_rows if r["hit"] >= 3 and r["vio"] == 0 and r["hit"] < 8]
    if quality:
        print("[GOOD] Clear and reliably followed rules:")
        for r in quality:
            print(f"  [{r['rule_id']}] {r['scope']} - hit: {r['hit']}")
        print()

    # 待审查
    if review_rows:
        print("[PENDING REVIEW] Possibly outdated rules:")
        for r in review_rows:
            print(f"  [{r['rule_id']}] {r['scope']} - skip: {r['skip']}, auto_skip: {r['auto_skip']}, last: {r['last_reviewed']}")
        print()

    # 活跃度 Top 5
    sorted_by_activity = sorted(active_rows, key=lambda r: activity(r), reverse=True)[:5]
    if sorted_by_activity:
        print("[TOP 5] Highest activity rules:")
        for r in sorted_by_activity:
            act = activity(r)
            if act > 0:
                print(f"  [{r['rule_id']}] {r['scope']} - activity: {act} (hit:{r['hit']} vio:{r['vio']})")
        print()


def cmd_promote(root: Path, args: Optional[list[str]] = None) -> None:
    """输出晋升建议"""
    args = args or []
    platform = extract_platform_arg(args)
    csv_path = audit_csv_path(root)
    rows = read_audit(csv_path)
    if not rows:
        print("audit.csv is empty or missing")
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
            candidates.append({**r, "reason": f"Frequent violations (compliance {cr:.0%})"})
            continue
        # 条件2：err >= 2 且危险度 >= 0.5
        dr = danger_rate(r)
        if r["err"] >= 2 and dr is not None and dr >= 0.5:
            candidates.append({**r, "reason": f"High risk (danger {dr:.0%})"})

    if not candidates:
        if platform:
            print(f"No promotion suggestions (platform: {platform})")
        else:
            print("No promotion suggestions")
        return

    print("=" * 60)
    print("  User-Level Promotion Suggestions")
    print("=" * 60)
    title_suffix = f" (platform: {platform})" if platform else ""
    print(f"\nSuggested platform lessons to promote to user-level config{title_suffix}:\n")
    for c in candidates:
        print(f"  [{c['rule_id']}] [{row_platform(c)}] {c['scope']}")
        print(f"    Reason: {c['reason']}")
        print(f"    Stats: hit={c['hit']} vio={c['vio']} err={c['err']}")
        print()
    print("Please confirm promotion with the user during retrospective.")


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
        cmd_sync(root, remaining_args)
    elif command == "sync_platform":
        cmd_sync_platform(root, remaining_args)
    elif command == "report":
        cmd_report(root)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: init, scopes, filter, score, sync, sync_platform, report, promote")
        sys.exit(1)


if __name__ == "__main__":
    main()
