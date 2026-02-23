#!/usr/bin/env python3
"""
经验体系健康度检查 - Self-Evolve Skill 独立诊断工具

对 evolve/ 目录下的 audit.csv 和 EVOLVE.md 进行全面健康度检查，
输出结构化报告和总评分。

用法：
  python health_check.py [--project-root <path>] [--json]

  --project-root  项目根目录路径（默认：当前工作目录）
  --json          以 JSON 格式输出（便于自动化消费）

检查维度：
  1. 数据完整性（Data Integrity）
  2. EVOLVE.md 一致性（Consistency）
  3. 体系结构（Structure）
  4. 审计活跃度（Freshness）
  5. 质量指标（Quality）
  6. 防腐检查（Anti-Corruption）
"""

import csv
import re
import sys
import json
from pathlib import Path
from datetime import date
from typing import Optional


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
    report = DimensionReport("数据完整性", "CSV 字段合法性、唯一性、逻辑一致性")

    # 1.1 文件存在性
    if not csv_path.exists():
        report.add(CheckResult("文件存在", "FAIL", "audit.csv 不存在"))
        return report
    report.add(CheckResult("文件存在", "PASS", f"audit.csv 存在（{len(rows)} 条记录）"))

    # 1.1b 表头完整性（兼容旧版：缺字段记 WARN）
    headers = read_csv_headers(csv_path)
    missing_headers = sorted(REQUIRED_FIELDS - headers)
    if missing_headers:
        report.add(CheckResult("CSV 表头完整", "WARN",
                               f"缺少字段：{', '.join(missing_headers)}（可通过运行 audit_sync.py 自动补齐）"))
    else:
        report.add(CheckResult("CSV 表头完整", "PASS", "CSV 表头完整"))

    if not rows:
        report.add(CheckResult("数据非空", "WARN", "audit.csv 为空，尚无经验记录"))
        return report

    # 1.2 rule_id 唯一性
    ids = [r["rule_id"] for r in rows]
    duplicates = [rid for rid in set(ids) if ids.count(rid) > 1]
    if duplicates:
        report.add(CheckResult("rule_id 唯一", "FAIL",
                               f"发现重复 rule_id：{', '.join(duplicates)}",
                               [f"{rid} 出现 {ids.count(rid)} 次" for rid in duplicates]))
    else:
        report.add(CheckResult("rule_id 唯一", "PASS", f"全部 {len(ids)} 个 rule_id 唯一"))

    # 1.3 origin 合法性
    bad_origins = [r["rule_id"] for r in rows if r.get("origin") not in VALID_ORIGINS]
    if bad_origins:
        report.add(CheckResult("origin 合法", "FAIL",
                               f"{len(bad_origins)} 条 origin 值非法",
                               [f"{rid} → {next(r.get('origin','?') for r in rows if r['rule_id']==rid)}"
                                for rid in bad_origins[:10]]))
    else:
        report.add(CheckResult("origin 合法", "PASS", "全部 origin 值合法"))

    # 1.4 status 合法性
    bad_status = [r["rule_id"] for r in rows if r.get("status") not in VALID_STATUSES]
    if bad_status:
        report.add(CheckResult("status 合法", "FAIL",
                               f"{len(bad_status)} 条 status 值非法",
                               bad_status[:10]))
    else:
        report.add(CheckResult("status 合法", "PASS", "全部 status 值合法"))

    # 1.5 数值非负
    negative = []
    for r in rows:
        for f in COUNTER_FIELDS:
            if r[f] < 0:
                negative.append(f"{r['rule_id']}.{f}={r[f]}")
    if negative:
        report.add(CheckResult("数值非负", "FAIL", f"发现负值", negative[:10]))
    else:
        report.add(CheckResult("数值非负", "PASS", "全部数值字段非负"))

    # 1.6 err ≤ vio（逻辑约束）
    err_gt_vio = [f"{r['rule_id']}(err:{r['err']} > vio:{r['vio']})"
                  for r in rows if r["err"] > r["vio"]]
    if err_gt_vio:
        report.add(CheckResult("err ≤ vio", "FAIL",
                               "err 是 vio 的子集，不应大于 vio",
                               err_gt_vio[:10]))
    else:
        report.add(CheckResult("err ≤ vio", "PASS", "全部记录 err ≤ vio"))

    # 1.7 origin=error 的初始值检查
    error_no_vio = [r["rule_id"] for r in rows
                    if r.get("origin") == "error" and r["vio"] == 0 and r["err"] == 0
                    and r["status"] != "archived"]
    if error_no_vio:
        report.add(CheckResult("error 初始值", "WARN",
                               f"{len(error_no_vio)} 条 origin=error 但 vio=0 err=0（初始值可能未正确设置）",
                               error_no_vio[:10]))
    else:
        report.add(CheckResult("error 初始值", "PASS",
                               "全部 origin=error 的规则都有 vio/err 初始值"))

    # 1.8 平台标签检查（仅 S- 规则要求强平台标签）
    weak_platform_tags = []
    for r in rows:
        if not is_platform_rule(r):
            continue
        platform = canonical_platform(r.get("platform", ""))
        if platform == PLATFORM_ALL:
            weak_platform_tags.append(r["rule_id"])
    if weak_platform_tags:
        report.add(CheckResult("平台标签完整", "WARN",
                               f"{len(weak_platform_tags)} 条平台教训仍为 platform=all，建议指定 claude/gemini/codex/cursor 以实现解耦",
                               weak_platform_tags[:10]))
    else:
        report.add(CheckResult("平台标签完整", "PASS", "全部平台教训均有明确平台标签"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 2：EVOLVE.md 一致性
# ══════════════════════════════════════════════════════════

def check_consistency(rows: list[dict], evolve_content: str, evolve_path: Path) -> DimensionReport:
    report = DimensionReport("EVOLVE.md 一致性", "CSV 与 EVOLVE.md 之间的数据同步状态")

    if not evolve_content:
        report.add(CheckResult("EVOLVE.md 存在", "FAIL", f"{evolve_path} 不存在"))
        return report
    report.add(CheckResult("EVOLVE.md 存在", "PASS", "EVOLVE.md 存在"))

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]

    # 2.1 规则覆盖率：CSV 中 active 规则是否在 EVOLVE.md 中有对应
    missing_in_md = []
    for r in active_rows:
        pattern = re.escape(r["rule_id"])
        if not re.search(rf"\[{pattern}\]", evolve_content):
            missing_in_md.append(r["rule_id"])

    if missing_in_md:
        report.add(CheckResult("规则覆盖率", "WARN",
                               f"{len(missing_in_md)}/{len(active_rows)} 条 active 规则在 EVOLVE.md 中未找到",
                               missing_in_md[:10]))
    else:
        total = len(active_rows)
        report.add(CheckResult("规则覆盖率", "PASS",
                               f"全部 {total} 条 active 规则在 EVOLVE.md 中有对应"))

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
                    f"{r['rule_id']}: MD({md_hit}/{md_vio}/{md_err}) ≠ CSV({r['hit']}/{r['vio']}/{r['err']})"
                )

    if out_of_sync:
        report.add(CheckResult("内联标签同步", "WARN",
                               f"{len(out_of_sync)} 条内联标签与 CSV 不一致（需运行 sync）",
                               out_of_sync[:10]))
    else:
        report.add(CheckResult("内联标签同步", "PASS", "内联标签与 CSV 数据一致"))

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
        report.add(CheckResult("TL;DR 同步", "WARN",
                               f"{len(missing_tldr)} 条高频违反规则未出现在 TL;DR（需运行 sync）",
                               missing_tldr[:10]))
    else:
        report.add(CheckResult("TL;DR 同步", "PASS",
                               "高频违反规则已在 TL;DR 中标注" if should_in_tldr else "当前无需 TL;DR 警告"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 3：体系结构
# ══════════════════════════════════════════════════════════

def check_structure(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("体系结构", "规则数量、分布均衡度、来源多样性")

    active_rows = [r for r in rows if r["status"] != "archived"]
    total = len(active_rows)

    # 3.1 规则总数
    if total < RULES_MIN:
        report.add(CheckResult("规则总数", "WARN",
                               f"仅 {total} 条活跃规则（< {RULES_MIN}），经验沉淀不足"))
    elif total > RULES_MAX:
        report.add(CheckResult("规则总数", "WARN",
                               f"{total} 条活跃规则（> {RULES_MAX}），维护负担较重，建议审查归档"))
    else:
        report.add(CheckResult("规则总数", "PASS", f"{total} 条活跃规则，数量适中"))

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
        report.add(CheckResult("scope 分布", "WARN",
                               f"'{max_scope[0]}' 占比 {concentration:.0%}（> {SCOPE_CONCENTRATION:.0%}），经验过度集中",
                               [f"{k}: {v} 条 ({v/total:.0%})" for k, v in
                                sorted(top_scopes.items(), key=lambda x: -x[1])]))
    else:
        report.add(CheckResult("scope 分布", "PASS",
                               f"最大 scope '{max_scope[0]}' 占 {concentration:.0%}，分布均衡",
                               [f"{k}: {v} 条" for k, v in
                                sorted(top_scopes.items(), key=lambda x: -x[1])]))

    # 3.3 origin 分布
    origin_dist: dict[str, int] = {}
    for r in active_rows:
        o = r.get("origin", "error")
        origin_dist[o] = origin_dist.get(o, 0) + 1

    error_pct = origin_dist.get("error", 0) / total
    preventive_pct = origin_dist.get("preventive", 0) / total
    imported_pct = origin_dist.get("imported", 0) / total

    dist_details = [f"{k}: {v} 条 ({v/total:.0%})" for k, v in
                    sorted(origin_dist.items(), key=lambda x: -x[1])]

    if error_pct == 1.0:
        report.add(CheckResult("origin 分布", "WARN",
                               "全部规则源于实际错误，缺少预防性经验",
                               dist_details))
    elif imported_pct > 0.7:
        report.add(CheckResult("origin 分布", "WARN",
                               f"imported 占 {imported_pct:.0%}，大量外部导入但缺少实战沉淀",
                               dist_details))
    else:
        report.add(CheckResult("origin 分布", "PASS",
                               "来源多样性良好",
                               dist_details))

    # 3.4 status 分布
    status_dist: dict[str, int] = {}
    for r in rows:
        status_dist[r["status"]] = status_dist.get(r["status"], 0) + 1

    archived_count = status_dist.get("archived", 0)
    review_count = status_dist.get("review", 0)
    total_all = len(rows)

    status_details = [f"{k}: {v} 条" for k, v in sorted(status_dist.items())]

    if total_all > 0 and archived_count / total_all > 0.5:
        report.add(CheckResult("status 分布", "WARN",
                               f"archived 占 {archived_count/total_all:.0%}，超半数规则已淘汰",
                               status_details))
    elif review_count > 5:
        report.add(CheckResult("status 分布", "WARN",
                               f"{review_count} 条处于 review 状态，积压较多",
                               status_details))
    else:
        report.add(CheckResult("status 分布", "PASS", "状态分布正常", status_details))

    # 3.5 平台教训解耦情况
    platform_rows = [r for r in active_rows if is_platform_rule(r)]
    if not platform_rows:
        report.add(CheckResult("平台解耦", "PASS", "当前无平台教训（S-xxx）"))
    else:
        platform_dist: dict[str, int] = {}
        for r in platform_rows:
            p = canonical_platform(r.get("platform", PLATFORM_ALL))
            platform_dist[p] = platform_dist.get(p, 0) + 1
        details = [f"{k}: {v} 条" for k, v in sorted(platform_dist.items(), key=lambda x: (-x[1], x[0]))]
        weak_count = platform_dist.get(PLATFORM_ALL, 0)
        if weak_count > 0:
            report.add(CheckResult("平台解耦", "WARN",
                                   f"{weak_count}/{len(platform_rows)} 条平台教训使用 platform=all，尚未完全解耦",
                                   details))
        else:
            report.add(CheckResult("平台解耦", "PASS",
                                   f"平台教训已按 platform 解耦（{len(platform_dist)} 个平台）",
                                   details))

    return report


# ══════════════════════════════════════════════════════════
#  维度 4：审计活跃度
# ══════════════════════════════════════════════════════════

def check_freshness(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("审计活跃度", "审计覆盖率、僵尸规则、积压项")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    if not active_rows:
        report.add(CheckResult("活跃规则", "WARN", "无活跃规则"))
        return report

    today = date.today()

    # 4.1 僵尸规则（超过 ZOMBIE_DAYS 未审计）
    zombies = []
    for r in active_rows:
        try:
            last = date.fromisoformat(r["last_reviewed"])
            days = (today - last).days
            if days > ZOMBIE_DAYS:
                zombies.append(f"{r['rule_id']}（{days} 天未审计）")
        except (ValueError, KeyError):
            zombies.append(f"{r['rule_id']}（无有效审计日期）")

    if zombies:
        pct = len(zombies) / len(active_rows)
        level = "FAIL" if pct > 0.5 else "WARN"
        report.add(CheckResult("僵尸规则", level,
                               f"{len(zombies)}/{len(active_rows)} 条超过 {ZOMBIE_DAYS} 天未审计",
                               zombies[:10]))
    else:
        report.add(CheckResult("僵尸规则", "PASS",
                               f"全部 {len(active_rows)} 条活跃规则均在 {ZOMBIE_DAYS} 天内被审计"))

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
        report.add(CheckResult("7 天覆盖率", "WARN",
                               f"最近 7 天仅审计 {recent_7}/{len(active_rows)} 条（{coverage_7:.0%}）"))
    else:
        report.add(CheckResult("7 天覆盖率", "PASS",
                               f"最近 7 天审计 {recent_7}/{len(active_rows)} 条（{coverage_7:.0%}）"))

    # 4.3 review 积压
    review_rows = [r for r in rows if r["status"] == "review"]
    stale_reviews = []
    for r in review_rows:
        try:
            last = date.fromisoformat(r["last_reviewed"])
            days = (today - last).days
            if days > REVIEW_STALE_DAYS:
                stale_reviews.append(f"{r['rule_id']}（review 已 {days} 天）")
        except (ValueError, KeyError):
            stale_reviews.append(f"{r['rule_id']}（无有效日期）")

    if stale_reviews:
        report.add(CheckResult("review 积压", "WARN",
                               f"{len(stale_reviews)} 条 review 超过 {REVIEW_STALE_DAYS} 天未处理",
                               stale_reviews[:10]))
    else:
        pending = len(review_rows)
        report.add(CheckResult("review 积压", "PASS",
                               f"无过期 review（当前 {pending} 条待审查）" if pending else "无待审查项"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 5：质量指标
# ══════════════════════════════════════════════════════════

def check_quality(rows: list[dict]) -> DimensionReport:
    report = DimensionReport("质量指标", "遵守率、高危/难执行/低价值占比")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]
    if not active_rows:
        report.add(CheckResult("活跃规则", "WARN", "无活跃规则"))
        return report

    # 5.1 整体加权遵守率
    total_hit = sum(r["hit"] for r in active_rows)
    total_vio = sum(r["vio"] for r in active_rows)
    total_actions = total_hit + total_vio
    if total_actions > 0:
        overall_cr = total_hit / total_actions
        level = "PASS" if overall_cr >= 0.8 else ("WARN" if overall_cr >= 0.6 else "FAIL")
        report.add(CheckResult("整体遵守率", level,
                               f"{overall_cr:.0%}（hit:{total_hit} vio:{total_vio}）"))
    else:
        report.add(CheckResult("整体遵守率", "WARN", "无审计数据，无法计算遵守率"))

    # 5.2 高危规则占比
    high_danger = [
        r
        for r in active_rows
        if r["err"] >= 2 and (dr := danger_rate(r)) is not None and dr >= 0.5
    ]
    hd_pct = len(high_danger) / len(active_rows)
    if high_danger:
        level = "FAIL" if hd_pct > 0.2 else "WARN"
        report.add(CheckResult("高危规则", level,
                               f"{len(high_danger)} 条高危（占 {hd_pct:.0%}）",
                               [f"{r['rule_id']}（危险度 {danger_rate(r):.0%}）" for r in high_danger]))
    else:
        report.add(CheckResult("高危规则", "PASS", "无高危规则"))

    # 5.3 难执行规则占比
    hard = [r for r in active_rows if r["hit"] >= 3 and r["vio"] >= 3]
    if hard:
        report.add(CheckResult("难执行规则", "WARN",
                               f"{len(hard)} 条难执行（hit≥3 且 vio≥3），建议重写",
                               [f"{r['rule_id']}（遵守率 {compliance_rate(r):.0%}）" for r in hard]))
    else:
        report.add(CheckResult("难执行规则", "PASS", "无难执行规则"))

    # 5.4 低价值嫌疑占比
    low_value = [r for r in active_rows
                 if r["hit"] >= 8 and r["vio"] == 0 and r["err"] == 0
                 and r.get("origin") != "error"]
    if low_value:
        report.add(CheckResult("低价值嫌疑", "WARN",
                               f"{len(low_value)} 条低价值嫌疑（origin≠error, hit≥8, vio=0）",
                               [f"{r['rule_id']}（{r.get('origin','?')}, hit:{r['hit']}）" for r in low_value]))
    else:
        report.add(CheckResult("低价值嫌疑", "PASS", "无低价值嫌疑"))

    # 5.5 protected 确认率
    protected = [r for r in rows if r["status"] == "protected"]
    total_non_archived = len([r for r in rows if r["status"] != "archived"])
    if total_non_archived > 0:
        prot_pct = len(protected) / total_non_archived
        report.add(CheckResult("protected 比例", "PASS",
                               f"{len(protected)}/{total_non_archived} 条（{prot_pct:.0%}）经过用户确认"))

    return report


# ══════════════════════════════════════════════════════════
#  维度 6：防腐检查
# ══════════════════════════════════════════════════════════

def check_anti_corruption(rows: list[dict], evolve_content: str) -> DimensionReport:
    report = DimensionReport("防腐检查", "全零规则、孤儿规则、逻辑异常")

    active_rows = [r for r in rows if r["status"] in ("active", "protected")]

    # 6.1 全零规则（从未被触及）
    zero_rules = [r["rule_id"] for r in active_rows
                  if r["hit"] == 0 and r["vio"] == 0 and r["err"] == 0
                  and r["skip"] == 0 and r["auto_skip"] == 0]
    if zero_rules:
        report.add(CheckResult("全零规则", "WARN",
                               f"{len(zero_rules)} 条从未被触及（hit/vio/err/skip 全为 0）",
                               zero_rules[:10]))
    else:
        report.add(CheckResult("全零规则", "PASS", "无全零规则，全部规则已被审计触及"))

    # 6.2 孤儿规则：CSV 中 active 但 EVOLVE.md 中已不存在
    if evolve_content:
        orphans = []
        for r in active_rows:
            rule_id = re.escape(r["rule_id"])
            if not re.search(rf"\[{rule_id}\]", evolve_content):
                orphans.append(r["rule_id"])
        if orphans:
            report.add(CheckResult("孤儿规则", "WARN",
                                   f"{len(orphans)} 条 active 规则在 EVOLVE.md 中未找到（可能被手动删除）",
                                   orphans[:10]))
        else:
            report.add(CheckResult("孤儿规则", "PASS", "无孤儿规则"))
    else:
        report.add(CheckResult("孤儿规则", "WARN", "EVOLVE.md 不存在，无法检查"))

    # 6.3 err > vio 异常（与数据完整性有交叉，这里侧重"腐化"视角）
    corrupted = [f"{r['rule_id']}(err:{r['err']} vio:{r['vio']})"
                 for r in rows if r["err"] > r["vio"]]
    if corrupted:
        report.add(CheckResult("数据腐化", "FAIL",
                               f"{len(corrupted)} 条 err > vio（数据逻辑矛盾）",
                               corrupted[:10]))
    else:
        report.add(CheckResult("数据腐化", "PASS", "无逻辑矛盾数据"))

    # 6.4 scope 为空
    empty_scope = [r["rule_id"] for r in active_rows if not r.get("scope", "").strip()]
    if empty_scope:
        report.add(CheckResult("空 scope", "WARN",
                               f"{len(empty_scope)} 条规则缺少 scope 标签",
                               empty_scope[:10]))
    else:
        report.add(CheckResult("空 scope", "PASS", "全部规则都有 scope 标签"))

    # 6.5 title 为空
    empty_title = [r["rule_id"] for r in active_rows if not r.get("title", "").strip()]
    if empty_title:
        report.add(CheckResult("空 title", "WARN",
                               f"{len(empty_title)} 条规则缺少 title",
                               empty_title[:10]))
    else:
        report.add(CheckResult("空 title", "PASS", "全部规则都有 title"))

    return report


# ══════════════════════════════════════════════════════════
#  报告汇总与输出
# ══════════════════════════════════════════════════════════

LEVEL_ICON = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
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
        return "A（优秀）"
    elif score >= 75:
        return "B（良好）"
    elif score >= 60:
        return "C（及格）"
    elif score >= 40:
        return "D（较差）"
    else:
        return "F（危险）"


def print_text_report(dimensions: list[DimensionReport], score: float):
    """输出文本格式报告"""
    print("=" * 64)
    print("  经验体系健康度检查报告")
    print("=" * 64)
    print(f"\n  总评分：{score:.0f}/100  {score_grade(score)}\n")

    for dim in dimensions:
        header = f"  [{dim.dimension}] {dim.description}"
        print(f"\n{'─' * 64}")
        print(header)
        print(f"  {dim.pass_count} PASS / {dim.warn_count} WARN / {dim.fail_count} FAIL")
        print(f"{'─' * 64}")

        for check in dim.checks:
            icon = LEVEL_ICON[check.level]
            print(f"  {icon} {check.name}：{check.message}")
            for detail in check.details[:5]:
                print(f"      → {detail}")
            if len(check.details) > 5:
                print(f"      ... 还有 {len(check.details) - 5} 条")

    # 汇总建议
    all_fails = [(dim.dimension, c) for dim in dimensions for c in dim.checks if c.level == "FAIL"]
    all_warns = [(dim.dimension, c) for dim in dimensions for c in dim.checks if c.level == "WARN"]

    if all_fails or all_warns:
        print(f"\n{'═' * 64}")
        print("  修复建议")
        print(f"{'═' * 64}")
        if all_fails:
            print("\n  [必须修复]")
            for dim_name, check in all_fails:
                print(f"    ❌ [{dim_name}] {check.name}：{check.message}")
        if all_warns:
            print("\n  [建议关注]")
            for dim_name, check in all_warns:
                print(f"    ⚠️ [{dim_name}] {check.name}：{check.message}")

    print(f"\n{'═' * 64}")
    print(f"  检查完成，共 {sum(len(d.checks) for d in dimensions)} 项检查")
    print(f"{'═' * 64}\n")


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
    print(json.dumps(output, ensure_ascii=False, indent=2))


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
        check_consistency(rows, evolve_content, md_path),
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
