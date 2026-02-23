#!/usr/bin/env python3
"""
Health check utility for Evolve-Skill.

This script validates `evolve/audit.csv` and `EVOLVE.md`,
then prints a structured report and overall score.

Usage:
  python health_check.py [--project-root <path>] [--json]

  --project-root  Project root path (default: current working directory)
  --json          Output report as JSON for automation

Dimensions:
  1. Data Integrity
  2. EVOLVE.md Consistency
  3. Structure
  4. Freshness
  5. Quality
  6. Anti-Corruption
"""

import csv
import builtins
import hashlib
import re
import sys
import json
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


# ── 常量 ──

VALID_ORIGINS = {"error", "preventive", "imported"}
VALID_STATUSES = {"active", "protected", "review", "archived"}
COUNTER_FIELDS = ("hit", "vio", "err", "skip", "auto_skip")
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
REQUIRED_FIELDS = {"rule_id", "platform", "scope", "title", "origin", "hit", "vio", "err",
                   "skip", "auto_skip", "last_reviewed", "status"}

# 阈值配置
ZOMBIE_DAYS = 30           # 超过此天数未审计 → 僵尸规则
REVIEW_STALE_DAYS = 30     # review 状态超过此天数 → 积压
SCOPE_CONCENTRATION = 0.5  # 单一 scope 占比超过此值 → 过度集中
RULES_MIN = 5              # 规则总数下限
RULES_MAX = 50             # 规则总数上限（建议值）

KNOWN_PLATFORM_FILES = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
    "cursor": "CURSOR.md",
}
PLATFORM_TARGETS_CONFIG = "platform_targets.json"
AUTO_SYNC_BEGIN_PREFIX = "<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN"


# ── 数据结构 ──

class CheckResult:
    """单项检查结果"""

    def __init__(self, name: str, level: str, message: str, details: Optional[list[str]] = None):
        """
        name: 检查项名称
        level: PASS / WARN / FAIL
        message: 结果简述
        details: 具体条目（可选）
        """
        self.name = name
        self.level = level
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"name": self.name, "level": self.level, "message": self.message}
        if self.details:
            d["details"] = self.details
        return d


class DimensionReport:
    """单维度报告"""

    def __init__(self, dimension: str, description: str):
        self.dimension = dimension
        self.description = description
        self.checks: list[CheckResult] = []

    def add(self, result: CheckResult):
        self.checks.append(result)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.level == "PASS")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.level == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.level == "FAIL")

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "description": self.description,
            "summary": f"{self.pass_count}P / {self.warn_count}W / {self.fail_count}F",
            "checks": [c.to_dict() for c in self.checks],
        }


# ── 路径工具 ──

def resolve_root(args: list[str]) -> Path:
    root = Path.cwd()
    for i, arg in enumerate(args):
        if arg == "--project-root" and i + 1 < len(args):
            root = Path(args[i + 1])
            break
    return root


def audit_csv_path(root: Path) -> Path:
    return root / "evolve" / "audit.csv"


def evolve_md_path(root: Path) -> Path:
    return root / "EVOLVE.md"


def platform_targets_path(root: Path) -> Path:
    return root / "evolve" / PLATFORM_TARGETS_CONFIG


# ── CSV 读取 ──

def is_platform_rule(row: dict) -> bool:
    return row.get("rule_id", "").startswith("S-")


def canonical_platform(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    if not normalized:
        return PLATFORM_ALL
    return PLATFORM_ALIASES.get(normalized, normalized)


def infer_legacy_platform(row: dict) -> str:
    if not is_platform_rule(row):
        return PLATFORM_ALL
    top_scope = row.get("scope", "").split("/")[0].strip().lower()
    inferred = PLATFORM_ALIASES.get(top_scope)
    if inferred in KNOWN_PLATFORM_VALUES:
        return inferred
    return PLATFORM_ALL


def read_csv_headers(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return set(reader.fieldnames or [])

def read_audit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            for field in COUNTER_FIELDS:
                row[field] = int(row.get(field, 0))
            row.setdefault("title", "")
            row.setdefault("auto_skip", 0)
            row.setdefault("origin", "error")
            row["platform"] = canonical_platform(row.get("platform", ""))
            if row["platform"] == PLATFORM_ALL and is_platform_rule(row):
                row["platform"] = infer_legacy_platform(row)
            rows.append(row)
        return rows


def read_evolve(path: Path) -> str:
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def row_platform(row: dict) -> str:
    return canonical_platform(row.get("platform", PLATFORM_ALL))


def load_platform_target_map(root: Path) -> dict[str, str]:
    config_path = platform_targets_path(root)
    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
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
) -> list[str]:
    platforms = set()
    platforms.update(p for p in config_map.keys() if p != PLATFORM_ALL)
    platforms.update(p for p in marker_map.keys() if p != PLATFORM_ALL)
    platforms.update(
        p for p, filename in KNOWN_PLATFORM_FILES.items()
        if (root / filename).exists()
    )
    for row in rows:
        if is_platform_rule(row):
            p = row_platform(row)
            if p != PLATFORM_ALL:
                platforms.add(p)
    return sorted(platforms)


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


def read_platform_block_state(path: Path, platform: str) -> tuple[bool, Optional[str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False, None

    with_digest = re.search(
        rf"<!--\s*EVOLVE_SKILL:AUTO_SYNC:BEGIN\s+platform={re.escape(platform)}\s+digest=([0-9a-f]+)[^>]*-->",
        content,
        re.IGNORECASE,
    )
    if with_digest:
        return True, with_digest.group(1)

    exists = re.search(
        rf"<!--\s*EVOLVE_SKILL:AUTO_SYNC:BEGIN\s+platform={re.escape(platform)}[^\n>]*-->",
        content,
        re.IGNORECASE,
    )
    return bool(exists), None


# ── 推导指标 ──

def compliance_rate(row: dict) -> Optional[float]:
    total = row["hit"] + row["vio"]
    return row["hit"] / total if total > 0 else None


def danger_rate(row: dict) -> Optional[float]:
    return row["err"] / row["vio"] if row["vio"] > 0 else None


# ══════════════════════════════════════════════════════════
#  维度 1：数据完整性
# ══════════════════════════════════════════════════════════

def check_data_integrity(rows: list[dict], csv_path: Path) -> DimensionReport:
    report = DimensionReport("Data Integrity", "CSV field validity, uniqueness, and logical consistency")

    # 1.1 文件存在性
    if not csv_path.exists():
        report.add(CheckResult("File Presence", "FAIL", "audit.csv is missing"))
        return report
    report.add(CheckResult("File Presence", "PASS", f"audit.csv exists ({len(rows)} rows)"))

    # 1.1b 表头完整性（兼容旧版：缺字段记 WARN）
    headers = read_csv_headers(csv_path)
    missing_headers = sorted(REQUIRED_FIELDS - headers)
    if missing_headers:
        report.add(CheckResult("CSV Header Completeness", "WARN",
                               f"Missing fields: {', '.join(missing_headers)} (run audit_sync.py to auto-fill)"))
    else:
        report.add(CheckResult("CSV Header Completeness", "PASS", "CSV header is complete"))

    if not rows:
        report.add(CheckResult("Non-Empty Data", "WARN", "audit.csv is empty; no rules recorded yet"))
        return report

    # 1.2 rule_id 唯一性
    ids = [r["rule_id"] for r in rows]
    duplicates = [rid for rid in set(ids) if ids.count(rid) > 1]
    if duplicates:
        report.add(CheckResult("Unique rule_id", "FAIL",
                               f"Duplicate rule_id found: {', '.join(duplicates)}",
                               [f"{rid} appears {ids.count(rid)} times" for rid in duplicates]))
    else:
        report.add(CheckResult("Unique rule_id", "PASS", f"All {len(ids)} rule_id values are unique"))

    # 1.3 origin 合法性
    bad_origins = [r["rule_id"] for r in rows if r.get("origin") not in VALID_ORIGINS]
    if bad_origins:
        report.add(CheckResult("Valid origin", "FAIL",
                               f"{len(bad_origins)} rules have invalid origin values",
                               [f"{rid} -> {next(r.get('origin','?') for r in rows if r['rule_id']==rid)}"
                                for rid in bad_origins[:10]]))
    else:
        report.add(CheckResult("Valid origin", "PASS", "All origin values are valid"))

    # 1.4 status 合法性
    bad_status = [r["rule_id"] for r in rows if r.get("status") not in VALID_STATUSES]
    if bad_status:
        report.add(CheckResult("Valid status", "FAIL",
                               f"{len(bad_status)} rules have invalid status values",
                               bad_status[:10]))
    else:
        report.add(CheckResult("Valid status", "PASS", "All status values are valid"))

    # 1.5 数值非负
    negative = []
    for r in rows:
        for f in COUNTER_FIELDS:
            if r[f] < 0:
                negative.append(f"{r['rule_id']}.{f}={r[f]}")
    if negative:
        report.add(CheckResult("Non-Negative Counters", "FAIL", "Negative values found", negative[:10]))
    else:
        report.add(CheckResult("Non-Negative Counters", "PASS", "All counter fields are non-negative"))

    # 1.6 err ≤ vio（逻辑约束）
    err_gt_vio = [f"{r['rule_id']}(err:{r['err']} > vio:{r['vio']})"
                  for r in rows if r["err"] > r["vio"]]
    if err_gt_vio:
        report.add(CheckResult("err <= vio", "FAIL",
                               "err is a subset of vio and must not exceed vio",
                               err_gt_vio[:10]))
    else:
        report.add(CheckResult("err <= vio", "PASS", "All rows satisfy err <= vio"))

    # 1.7 origin=error 的初始值检查
    error_no_vio = [r["rule_id"] for r in rows
                    if r.get("origin") == "error" and r["vio"] == 0 and r["err"] == 0
                    and r["status"] != "archived"]
    if error_no_vio:
        report.add(CheckResult("error Baseline", "WARN",
                               f"{len(error_no_vio)} origin=error rules still have vio=0 and err=0 (baseline may be incorrect)",
                               error_no_vio[:10]))
    else:
        report.add(CheckResult("error Baseline", "PASS",
                               "All origin=error rules have non-zero initial vio/err history"))

    # 1.8 平台标签检查（仅 S- 规则要求强平台标签）
    weak_platform_tags = []
    for r in rows:
        if not is_platform_rule(r):
            continue
        platform = canonical_platform(r.get("platform", ""))
        if platform == PLATFORM_ALL:
            weak_platform_tags.append(r["rule_id"])
    if weak_platform_tags:
        report.add(CheckResult("Platform Tag Completeness", "WARN",
                               f"{len(weak_platform_tags)} platform lessons still use platform=all; specify claude/gemini/codex/cursor",
                               weak_platform_tags[:10]))
    else:
        report.add(CheckResult("Platform Tag Completeness", "PASS", "All platform lessons have explicit platform tags"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 2：EVOLVE.md 一致性
# ══════════════════════════════════════════════════════════

def check_consistency(rows: list[dict], evolve_content: str, evolve_path: Path, root: Path) -> DimensionReport:
    report = DimensionReport("EVOLVE.md Consistency", "Sync consistency between CSV and EVOLVE.md")

    if not evolve_content:
        report.add(CheckResult("EVOLVE.md Presence", "FAIL", f"{evolve_path} is missing"))
        return report
    report.add(CheckResult("EVOLVE.md Presence", "PASS", "EVOLVE.md exists"))

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]

    # 2.1 规则覆盖率：CSV 中 active 规则是否在 EVOLVE.md 中有对应
    missing_in_md = []
    for r in active_rows:
        pattern = re.escape(r["rule_id"])
        if not re.search(rf"\[{pattern}\]", evolve_content):
            missing_in_md.append(r["rule_id"])

    if missing_in_md:
        report.add(CheckResult("Rule Coverage", "WARN",
                               f"{len(missing_in_md)}/{len(active_rows)} active rules are missing in EVOLVE.md",
                               missing_in_md[:10]))
    else:
        total = len(active_rows)
        report.add(CheckResult("Rule Coverage", "PASS",
                               f"All {total} active rules are present in EVOLVE.md"))

    # 2.2 内联标签同步：EVOLVE.md 中的 {hit:N vio:N err:N} 是否与 CSV 一致
    out_of_sync = []
    for r in active_rows:
        rule_id = re.escape(r["rule_id"])
        tag_match = re.search(
            rf"\[{rule_id}\][^\n]*`\{{hit:(\d+) vio:(\d+) err:(\d+)\}}`",
            evolve_content
        )
        if tag_match:
            md_hit, md_vio, md_err = int(tag_match.group(1)), int(tag_match.group(2)), int(tag_match.group(3))
            if md_hit != r["hit"] or md_vio != r["vio"] or md_err != r["err"]:
                out_of_sync.append(
                    f"{r['rule_id']}: MD({md_hit}/{md_vio}/{md_err}) != CSV({r['hit']}/{r['vio']}/{r['err']})"
                )

    if out_of_sync:
        report.add(CheckResult("Inline Tag Sync", "WARN",
                               f"{len(out_of_sync)} inline tags differ from CSV (run sync)",
                               out_of_sync[:10]))
    else:
        report.add(CheckResult("Inline Tag Sync", "PASS", "Inline tags match CSV data"))

    # 2.3 TL;DR 一致性：高频违反规则是否出现在 TL;DR 中
    should_in_tldr = [
        r
        for r in active_rows
        if r["vio"] >= 3 and (cr := compliance_rate(r)) is not None and cr < 0.5
    ]

    # 提取 TL;DR 章节
    tldr_match = re.search(r"^## TL;DR\s*\n(.*?)(?=^## (?!TL;DR)|\Z)", evolve_content,
                           re.MULTILINE | re.DOTALL)
    tldr_text = tldr_match.group(1) if tldr_match else ""

    missing_tldr = [r["rule_id"] for r in should_in_tldr
                    if r["rule_id"] not in tldr_text]
    if missing_tldr:
        report.add(CheckResult("TL;DR Sync", "WARN",
                               f"{len(missing_tldr)} frequently violated rules are missing from TL;DR (run sync)",
                               missing_tldr[:10]))
    else:
        report.add(CheckResult("TL;DR Sync", "PASS",
                               "Frequently violated rules are present in TL;DR" if should_in_tldr else "No TL;DR warnings needed"))

    # 2.4 平台文件自动同步一致性
    config_map = load_platform_target_map(root)
    marker_map = extract_platform_marker_map(root)
    platforms = discover_sync_platforms(root, rows, config_map, marker_map)

    if not platforms:
        report.add(CheckResult("Platform File Coverage", "PASS", "No platform files require sync"))
        report.add(CheckResult("Platform Auto Blocks", "PASS", "No platform targets; block check skipped"))
        report.add(CheckResult("Platform Digest Freshness", "PASS", "No platform targets; digest check skipped"))
        return report

    missing_files = []
    missing_blocks = []
    missing_digest = []
    stale_digest = []
    for platform in platforms:
        target_path = resolve_platform_file_path(root, platform, config_map, marker_map)
        if not target_path.exists():
            missing_files.append(f"{platform} -> {target_path}")
            continue

        has_block, current_digest = read_platform_block_state(target_path, platform)
        if not has_block:
            missing_blocks.append(f"{platform} -> {target_path}")
            continue
        if not current_digest:
            missing_digest.append(f"{platform} -> {target_path}")
            continue

        expected_digest = build_platform_digest(platform, evolve_content, rows)
        if current_digest != expected_digest:
            stale_digest.append(
                f"{platform} -> {target_path} (current:{current_digest} expected:{expected_digest})"
            )

    if missing_files:
        report.add(CheckResult(
            "Platform File Coverage",
            "WARN",
            f"{len(missing_files)}/{len(platforms)} platform targets are missing files (run sync)",
            missing_files[:10],
        ))
    else:
        report.add(CheckResult(
            "Platform File Coverage",
            "PASS",
            f"All {len(platforms)} platform targets have files",
        ))

    block_issues = missing_blocks + missing_digest
    if block_issues:
        report.add(CheckResult(
            "Platform Auto Blocks",
            "WARN",
            f"{len(block_issues)} platform files are missing valid auto-sync blocks (run sync)",
            block_issues[:10],
        ))
    else:
        report.add(CheckResult("Platform Auto Blocks", "PASS", "All platform files include valid auto-sync blocks"))

    if stale_digest:
        report.add(CheckResult(
            "Platform Digest Freshness",
            "WARN",
            f"{len(stale_digest)} platform file digests are stale (run sync)",
            stale_digest[:10],
        ))
    else:
        report.add(CheckResult("Platform Digest Freshness", "PASS", "Platform file digests match current data"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 3：体系结构
# ══════════════════════════════════════════════════════════

def check_structure(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("Structure", "Rule count, distribution balance, and source diversity")

    active_rows = [r for r in rows if r["status"] != "archived"]
    total = len(active_rows)

    # 3.1 规则总数
    if total < RULES_MIN:
        report.add(CheckResult("Rule Count", "WARN",
                               f"Only {total} active rules (< {RULES_MIN}); knowledge base is sparse"))
    elif total > RULES_MAX:
        report.add(CheckResult("Rule Count", "WARN",
                               f"{total} active rules (> {RULES_MAX}); maintenance overhead is high"))
    else:
        report.add(CheckResult("Rule Count", "PASS", f"{total} active rules; count is in a healthy range"))

    if total == 0:
        return report

    # 3.2 scope 分布均衡度
    # 提取顶级 scope（/ 前的部分）
    top_scopes: dict[str, int] = {}
    for r in active_rows:
        top = r["scope"].split("/")[0].strip()
        top_scopes[top] = top_scopes.get(top, 0) + 1

    max_scope = max(top_scopes.items(), key=lambda x: x[1])
    concentration = max_scope[1] / total
    if concentration > SCOPE_CONCENTRATION:
        report.add(CheckResult("Scope Distribution", "WARN",
                               f"'{max_scope[0]}' accounts for {concentration:.0%} (> {SCOPE_CONCENTRATION:.0%}); over-concentrated",
                               [f"{k}: {v} rules ({v/total:.0%})" for k, v in
                                sorted(top_scopes.items(), key=lambda x: -x[1])]))
    else:
        report.add(CheckResult("Scope Distribution", "PASS",
                               f"Largest scope '{max_scope[0]}' is {concentration:.0%}; distribution is balanced",
                               [f"{k}: {v} rules" for k, v in
                                sorted(top_scopes.items(), key=lambda x: -x[1])]))

    # 3.3 origin 分布
    origin_dist: dict[str, int] = {}
    for r in active_rows:
        o = r.get("origin", "error")
        origin_dist[o] = origin_dist.get(o, 0) + 1

    error_pct = origin_dist.get("error", 0) / total
    preventive_pct = origin_dist.get("preventive", 0) / total
    imported_pct = origin_dist.get("imported", 0) / total

    dist_details = [f"{k}: {v} rules ({v/total:.0%})" for k, v in
                    sorted(origin_dist.items(), key=lambda x: -x[1])]

    if error_pct == 1.0:
        report.add(CheckResult("Origin Distribution", "WARN",
                               "All rules come from errors; preventive knowledge is missing",
                               dist_details))
    elif imported_pct > 0.7:
        report.add(CheckResult("Origin Distribution", "WARN",
                               f"Imported rules account for {imported_pct:.0%}; practical local learnings are limited",
                               dist_details))
    else:
        report.add(CheckResult("Origin Distribution", "PASS",
                               "Origin diversity looks healthy",
                               dist_details))

    # 3.4 status 分布
    status_dist: dict[str, int] = {}
    for r in rows:
        status_dist[r["status"]] = status_dist.get(r["status"], 0) + 1

    archived_count = status_dist.get("archived", 0)
    review_count = status_dist.get("review", 0)
    total_all = len(rows)

    status_details = [f"{k}: {v} rules" for k, v in sorted(status_dist.items())]

    if total_all > 0 and archived_count / total_all > 0.5:
        report.add(CheckResult("Status Distribution", "WARN",
                               f"archived accounts for {archived_count/total_all:.0%}; more than half are retired",
                               status_details))
    elif review_count > 5:
        report.add(CheckResult("Status Distribution", "WARN",
                               f"{review_count} rules are in review; backlog is high",
                               status_details))
    else:
        report.add(CheckResult("Status Distribution", "PASS", "Status distribution is healthy", status_details))

    # 3.5 平台教训解耦情况
    platform_rows = [r for r in active_rows if is_platform_rule(r)]
    if not platform_rows:
        report.add(CheckResult("Platform Decoupling", "PASS", "No platform lessons (S-xxx) found"))
    else:
        platform_dist: dict[str, int] = {}
        for r in platform_rows:
            p = canonical_platform(r.get("platform", PLATFORM_ALL))
            platform_dist[p] = platform_dist.get(p, 0) + 1
        details = [f"{k}: {v} rules" for k, v in sorted(platform_dist.items(), key=lambda x: (-x[1], x[0]))]
        weak_count = platform_dist.get(PLATFORM_ALL, 0)
        if weak_count > 0:
            report.add(CheckResult("Platform Decoupling", "WARN",
                                   f"{weak_count}/{len(platform_rows)} platform lessons still use platform=all",
                                   details))
        else:
            report.add(CheckResult("Platform Decoupling", "PASS",
                                   f"Platform lessons are decoupled by platform ({len(platform_dist)} platforms)",
                                   details))

    return report


# ══════════════════════════════════════════════════════════
#  维度 4：审计活跃度
# ══════════════════════════════════════════════════════════

def check_freshness(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("Freshness", "Audit coverage, stale rules, and review backlog")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    if not active_rows:
        report.add(CheckResult("Active Rules", "WARN", "No active rules found"))
        return report

    today = date.today()

    # 4.1 僵尸规则（超过 ZOMBIE_DAYS 未审计）
    zombies = []
    for r in active_rows:
        try:
            last = date.fromisoformat(r["last_reviewed"])
            days = (today - last).days
            if days > ZOMBIE_DAYS:
                zombies.append(f"{r['rule_id']} ({days} days since last review)")
        except (ValueError, KeyError):
            zombies.append(f"{r['rule_id']} (invalid or missing review date)")

    if zombies:
        pct = len(zombies) / len(active_rows)
        level = "FAIL" if pct > 0.5 else "WARN"
        report.add(CheckResult("Zombie Rules", level,
                               f"{len(zombies)}/{len(active_rows)} rules exceed {ZOMBIE_DAYS} days without review",
                               zombies[:10]))
    else:
        report.add(CheckResult("Zombie Rules", "PASS",
                               f"All {len(active_rows)} active rules were reviewed within {ZOMBIE_DAYS} days"))

    # 4.2 最近 7 天审计覆盖率
    recent_7 = 0
    for r in active_rows:
        try:
            last = date.fromisoformat(r["last_reviewed"])
            if (today - last).days <= 7:
                recent_7 += 1
        except (ValueError, KeyError):
            pass

    coverage_7 = recent_7 / len(active_rows) if active_rows else 0
    if coverage_7 < 0.3:
        report.add(CheckResult("7-Day Coverage", "WARN",
                               f"Only {recent_7}/{len(active_rows)} rules reviewed in last 7 days ({coverage_7:.0%})"))
    else:
        report.add(CheckResult("7-Day Coverage", "PASS",
                               f"{recent_7}/{len(active_rows)} rules reviewed in last 7 days ({coverage_7:.0%})"))

    # 4.3 review 积压
    review_rows = [r for r in rows if r["status"] == "review"]
    stale_reviews = []
    for r in review_rows:
        try:
            last = date.fromisoformat(r["last_reviewed"])
            days = (today - last).days
            if days > REVIEW_STALE_DAYS:
                stale_reviews.append(f"{r['rule_id']} (review pending for {days} days)")
        except (ValueError, KeyError):
            stale_reviews.append(f"{r['rule_id']} (invalid or missing date)")

    if stale_reviews:
        report.add(CheckResult("Review Backlog", "WARN",
                               f"{len(stale_reviews)} review items exceed {REVIEW_STALE_DAYS} days",
                               stale_reviews[:10]))
    else:
        pending = len(review_rows)
        report.add(CheckResult("Review Backlog", "PASS",
                               f"No stale review items (current pending: {pending})" if pending else "No items pending review"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 5：质量指标
# ══════════════════════════════════════════════════════════

def check_quality(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("Quality", "Compliance, high-risk/hard-to-follow/low-value ratios")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    if not active_rows:
        report.add(CheckResult("Active Rules", "WARN", "No active rules found"))
        return report

    # 5.1 整体加权遵守率
    total_hit = sum(r["hit"] for r in active_rows)
    total_vio = sum(r["vio"] for r in active_rows)
    total_actions = total_hit + total_vio
    if total_actions > 0:
        overall_cr = total_hit / total_actions
        level = "PASS" if overall_cr >= 0.8 else ("WARN" if overall_cr >= 0.6 else "FAIL")
        report.add(CheckResult("Overall Compliance", level,
                               f"{overall_cr:.0%} (hit:{total_hit} vio:{total_vio})"))
    else:
        report.add(CheckResult("Overall Compliance", "WARN", "No audit data; compliance cannot be calculated"))

    # 5.2 高危规则占比
    high_danger = [
        r
        for r in active_rows
        if r["err"] >= 2 and (dr := danger_rate(r)) is not None and dr >= 0.5
    ]
    hd_pct = len(high_danger) / len(active_rows)
    if high_danger:
        level = "FAIL" if hd_pct > 0.2 else "WARN"
        report.add(CheckResult("High-Risk Rules", level,
                               f"{len(high_danger)} high-risk rules ({hd_pct:.0%})",
                               [f"{r['rule_id']} (danger {danger_rate(r):.0%})" for r in high_danger]))
    else:
        report.add(CheckResult("High-Risk Rules", "PASS", "No high-risk rules"))

    # 5.3 难执行规则占比
    hard = [r for r in active_rows if r["hit"] >= 3 and r["vio"] >= 3]
    if hard:
        report.add(CheckResult("Hard-to-Follow Rules", "WARN",
                               f"{len(hard)} hard-to-follow rules (hit>=3 and vio>=3); consider rewrite",
                               [f"{r['rule_id']} (compliance {compliance_rate(r):.0%})" for r in hard]))
    else:
        report.add(CheckResult("Hard-to-Follow Rules", "PASS", "No hard-to-follow rules"))

    # 5.4 低价值嫌疑占比
    low_value = [r for r in active_rows
                 if r["hit"] >= 8 and r["vio"] == 0 and r["err"] == 0
                 and r.get("origin") != "error"]
    if low_value:
        report.add(CheckResult("Low-Value Candidates", "WARN",
                               f"{len(low_value)} low-value candidates (origin!=error, hit>=8, vio=0)",
                               [f"{r['rule_id']} ({r.get('origin','?')}, hit:{r['hit']})" for r in low_value]))
    else:
        report.add(CheckResult("Low-Value Candidates", "PASS", "No low-value candidates"))

    # 5.5 protected 确认率
    protected = [r for r in rows if r["status"] == "protected"]
    total_non_archived = len([r for r in rows if r["status"] != "archived"])
    if total_non_archived > 0:
        prot_pct = len(protected) / total_non_archived
        report.add(CheckResult("Protected Ratio", "PASS",
                               f"{len(protected)}/{total_non_archived} ({prot_pct:.0%}) confirmed by user"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 6：防腐检查
# ══════════════════════════════════════════════════════════

def check_anti_corruption(rows: list[dict], evolve_content: str) -> DimensionReport:
    report = DimensionReport("Anti-Corruption", "Zero-touch rules, orphan rules, and logical anomalies")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]

    # 6.1 全零规则（从未被触及）
    zero_rules = [r["rule_id"] for r in active_rows
                  if r["hit"] == 0 and r["vio"] == 0 and r["err"] == 0
                  and r["skip"] == 0 and r["auto_skip"] == 0]
    if zero_rules:
        report.add(CheckResult("Zero-Touch Rules", "WARN",
                               f"{len(zero_rules)} rules were never touched (hit/vio/err/skip all zero)",
                               zero_rules[:10]))
    else:
        report.add(CheckResult("Zero-Touch Rules", "PASS", "No zero-touch rules; all rules have audit activity"))

    # 6.2 孤儿规则：CSV 中 active 但 EVOLVE.md 中已不存在
    if evolve_content:
        orphans = []
        for r in active_rows:
            rule_id = re.escape(r["rule_id"])
            if not re.search(rf"\[{rule_id}\]", evolve_content):
                orphans.append(r["rule_id"])
        if orphans:
            report.add(CheckResult("Orphan Rules", "WARN",
                                   f"{len(orphans)} active rules are missing in EVOLVE.md (possibly manually removed)",
                                   orphans[:10]))
        else:
            report.add(CheckResult("Orphan Rules", "PASS", "No orphan rules"))
    else:
        report.add(CheckResult("Orphan Rules", "WARN", "EVOLVE.md is missing; orphan check skipped"))

    # 6.3 err > vio 异常（与数据完整性有交叉，这里侧重"腐化"视角）
    corrupted = [f"{r['rule_id']}(err:{r['err']} vio:{r['vio']})"
                 for r in rows if r["err"] > r["vio"]]
    if corrupted:
        report.add(CheckResult("Data Corruption", "FAIL",
                               f"{len(corrupted)} rows have err > vio (logical inconsistency)",
                               corrupted[:10]))
    else:
        report.add(CheckResult("Data Corruption", "PASS", "No logical inconsistency found"))

    # 6.4 scope 为空
    empty_scope = [r["rule_id"] for r in active_rows if not r.get("scope", "").strip()]
    if empty_scope:
        report.add(CheckResult("Empty Scope", "WARN",
                               f"{len(empty_scope)} rules are missing scope tags",
                               empty_scope[:10]))
    else:
        report.add(CheckResult("Empty Scope", "PASS", "All rules have scope tags"))

    # 6.5 title 为空
    empty_title = [r["rule_id"] for r in active_rows if not r.get("title", "").strip()]
    if empty_title:
        report.add(CheckResult("Empty Title", "WARN",
                               f"{len(empty_title)} rules are missing title",
                               empty_title[:10]))
    else:
        report.add(CheckResult("Empty Title", "PASS", "All rules have title"))

    return report


# ══════════════════════════════════════════════════════════
#  报告汇总与输出
# ══════════════════════════════════════════════════════════

LEVEL_ICON = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
LEVEL_WEIGHT = {"PASS": 1.0, "WARN": 0.5, "FAIL": 0.0}


def compute_score(dimensions: list[DimensionReport]) -> float:
    """计算总健康度评分（0-100）"""
    total_checks = 0
    weighted_sum = 0.0
    for dim in dimensions:
        for check in dim.checks:
            total_checks += 1
            weighted_sum += LEVEL_WEIGHT[check.level]
    return (weighted_sum / total_checks * 100) if total_checks > 0 else 0


def score_grade(score: float) -> str:
    if score >= 90:
        return "A (Excellent)"
    elif score >= 75:
        return "B (Good)"
    elif score >= 60:
        return "C (Fair)"
    elif score >= 40:
        return "D (Poor)"
    else:
        return "F (Critical)"


def print_text_report(dimensions: list[DimensionReport], score: float):
    """输出文本格式报告"""
    print("=" * 64)
    print("  Evolve Health Check Report")
    print("=" * 64)
    print(f"\n  Overall Score: {score:.0f}/100  {score_grade(score)}\n")

    for dim in dimensions:
        header = f"  [{dim.dimension}] {dim.description}"
        print(f"\n{'-' * 64}")
        print(header)
        print(f"  {dim.pass_count} PASS / {dim.warn_count} WARN / {dim.fail_count} FAIL")
        print(f"{'-' * 64}")

        for check in dim.checks:
            icon = LEVEL_ICON[check.level]
            print(f"  {icon} {check.name}: {check.message}")
            for detail in check.details[:5]:
                print(f"      -> {detail}")
            if len(check.details) > 5:
                print(f"      ... and {len(check.details) - 5} more")

    # 汇总建议
    all_fails = [(dim.dimension, c) for dim in dimensions for c in dim.checks if c.level == "FAIL"]
    all_warns = [(dim.dimension, c) for dim in dimensions for c in dim.checks if c.level == "WARN"]

    if all_fails or all_warns:
        print(f"\n{'=' * 64}")
        print("  Suggested Fixes")
        print(f"{'=' * 64}")
        if all_fails:
            print("\n  [Must Fix]")
            for dim_name, check in all_fails:
                print(f"    [FAIL] [{dim_name}] {check.name}: {check.message}")
        if all_warns:
            print("\n  [Needs Attention]")
            for dim_name, check in all_warns:
                print(f"    [WARN] [{dim_name}] {check.name}: {check.message}")

    print(f"\n{'=' * 64}")
    print(f"  Completed: {sum(len(d.checks) for d in dimensions)} checks")
    print(f"{'=' * 64}\n")


def print_json_report(dimensions: list[DimensionReport], score: float):
    """输出 JSON 格式报告"""
    output = {
        "score": round(score, 1),
        "grade": score_grade(score),
        "dimensions": [dim.to_dict() for dim in dimensions],
        "fails": [
            {"dimension": dim.dimension, **c.to_dict()}
            for dim in dimensions for c in dim.checks if c.level == "FAIL"
        ],
        "warns": [
            {"dimension": dim.dimension, **c.to_dict()}
            for dim in dimensions for c in dim.checks if c.level == "WARN"
        ],
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))


# ── 入口 ──

def main():
    args = sys.argv[1:]
    use_json = "--json" in args
    root = resolve_root(args)

    csv_path = audit_csv_path(root)
    md_path = evolve_md_path(root)

    rows = read_audit(csv_path)
    evolve_content = read_evolve(md_path)

    # 执行 6 个维度的检查
    dimensions = [
        check_data_integrity(rows, csv_path),
        check_consistency(rows, evolve_content, md_path, root),
        check_structure(rows),
        check_freshness(rows),
        check_quality(rows),
        check_anti_corruption(rows, evolve_content),
    ]

    score = compute_score(dimensions)

    if use_json:
        print_json_report(dimensions, score)
    else:
        print_text_report(dimensions, score)


if __name__ == "__main__":
    main()

