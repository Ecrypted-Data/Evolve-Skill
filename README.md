# Evolve-Skill 🧬

> **A core skill repository that helps AI coding assistants run retrospectives, capture knowledge, and continuously evolve after each development task.**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/Python-3.9+-green.svg)](https://www.python.org/downloads/)

Language: **English** | [简体中文](README_ZH.md)

![Evolve-Skill Hero Banner](asset/images/readme/Hero%20Banner.png)

**Evolve-Skill** is an **experience evolution framework** designed for AI coding collaboration (Claude Code, Cursor, Gemini, GitHub Copilot, etc.). Through a structured retrospective workflow and a local CLI toolchain, it turns fragmented tacit knowledge into auditable, quantifiable, and isolated engineering assets. It enables your AI assistant to self-summarize, self-constrain, and self-improve.

---

## ❓ Why Evolve-Skill?

When using AI coding assistants for long-term project development, teams usually face these pain points:

* **🐠 Goldfish-like memory**: a new session starts, and the AI forgets prior architectural decisions, pitfalls, and project-specific conventions.
* **🔁 Repeatedly stepping on similar traps**: environment setup issues and API edge cases can recur across sessions, wasting tokens and time.
* **🚧 Cross-platform mismatch**: Claude, Gemini, Cursor, and other platforms each have different behavior limits. Without an isolated correction mechanism, rules can contaminate each other.
* **🗙 Knowledge is hard to hand over**: retrospective insights are buried in long chat logs, making them hard to systematize, review, and transfer in team collaboration.

---

## ✨ Core Principles and Value

**Evolve-Skill** builds a complete closed loop of **"retrospect -> score -> sync -> health check"** through standardized project evolution assets and automated audit scripts.

* **📘 Single Source of Truth**
All shared rules, runbooks, and historical event indexes are consolidated into `EVOLVE.md` for easier team handover and PR review.
* **⚖️ Audit-driven rule governance**
Instead of blindly stacking prompts, the system tracks quantitative metrics such as `hit`, `vio`, and `err` to evaluate each rule's effectiveness and risk, detect low-value or outdated rules, and support `review` / `archived` retirement flows.
* **🛡️ Platform isolation**
Shared project experience is written to `EVOLVE.md`, while platform-specific behavior lessons and correction instructions are written to `CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md`, preventing cross-platform pollution.

---

## 🚀 Quick Start

**Requirements**: Python 3.9+, standard library only, no third-party dependencies.
> Note: on the human side, you only need to install the skill and trigger a retrospective. Initialization, scoring, and sync are executed automatically by AI following `SKILL.md`.

### 1. Install the Skill

Place this repository in your local skill directory:

```bash
git clone https://github.com/Ecrypted-Data/Evolve-Skill.git ~/.claude/skills/Evolve-Skill
```

Ensure your AI assistant can read `SKILL.md` in this directory as system prompt/tool instructions (works with Claude Code, agent frameworks, etc.).

### 2. Trigger a Retrospective

Say any of the following in AI chat:

> **"总结经验" "进化" "evolve" "复盘" "summarize lessons" "retrospective" "postmortem"**

After triggering, the AI automatically runs context reading, audit scoring (`scopes/filter/score`), sync (`sync`), and usually performs a final health check.

---

## 🛠️ How Does It Work?

After the skill is triggered, the AI runs in two layers: "overview + executable flow".

![The Closed-Loop Workflow](asset/images/readme/The%20Closed-Loop%20Workflow.png)

### Overview Flow (6 Steps)

1. **Read context**: scan `EVOLVE.md` and platform config files.
2. **Extract and classify**: extract "shared project assets" and "platform-specific lessons" from the conversation.
3. **Audit and score**: reuse existing rules and update metrics through `scopes / filter / score`.
4. **Generate write suggestions**: run `report` to get numbered EVOLVE-ready candidates based on audit metrics.
5. **Agent final decision**: run `select "<numbers>"` to mark final entries (`evolve_slot`).
6. **Sync and validate**: run `sync` to generate EVOLVE content from selected slots and update auto blocks.

### Executable Flow (Standard Order)

1. **Read and initialize**
   - Read `EVOLVE.md`, `CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md` (based on platform).
   - If the target project is missing `EVOLVE.md` or `evolve/audit.csv`, initialize first:
     - `python scripts/audit_sync.py init --project-root <project-root>`

2. **Audit before extraction (required)**
   - Run `scopes` to inspect domains, `filter` to narrow scope, then `score`.
   - If reviewing platform lessons (`S-xxx`), `filter` and `score` must use the same `--platform <name>` to avoid cross-platform pollution.
   - Recommendation stage:
     - `python scripts/audit_sync.py report --project-root <project-root>`
     - `python scripts/audit_sync.py select "1,3,5" --project-root <project-root>`

3. **Two-channel extraction**
   - Write shared assets to `EVOLVE.md`: TL;DR, Runbooks, Rules, History index, Changelog.
   - Write platform-specific lessons to their corresponding platform files: `CLAUDE.md` / `GEMINI.md` / `AGENTS.md` / `CURSOR.md`.

4. **Security and redaction (required)**
   - Do not write plaintext IPs, Tokens, Secrets, private key paths, or similar sensitive data.
   - Keep only placeholders in committable docs, and put real values in `EVOLVE.local.md` (and add it to `.gitignore`).

5. **Sync and close**
   - Core sync: `python scripts/audit_sync.py sync --project-root <project-root>`
   - Optional:
     - Sync only one platform: `--platform <name>`
     - Limit EVOLVE sync target: `--evolve-platform <name>` (universal + this platform)
     - Sync only platform files: `sync_platform`
     - Skip platform auto blocks: `--no-platform-sync`
   - Recommended health check:
     - `python scripts/health_check.py --project-root <project-root>`

### Completion Criteria (Recommended)

- `EVOLVE.md` and platform files have been updated with this retrospective result.
- Metrics in `evolve/audit.csv` have been scored and are traceable.
- Auto blocks are updated by script synchronization (not manual edits).
- Sensitive data has been redacted or moved to local private files.

---

## 📦 Outputs and Directory Structure

Under the target project's root directory, Evolve-Skill maintains:

```text
<project-root>/
├── EVOLVE.md                          # Single source of truth: Rules + Runbooks + History index + metric tags
├── EVOLVE.local.md                    # Sensitive and local-only config (should be in .gitignore)
├── CLAUDE.md / GEMINI.md / AGENTS.md / CURSOR.md
│                                       # Platform-specific lessons (auto-syncs metrics, does not overwrite hand-written content)
└── evolve/
    ├── audit.csv                      # Core audit data for lifecycle tracking
    ├── history/                       # Major event retrospectives as separate files
    ├── runbooks/                      # Standard operational runbooks (deployment, release steps, etc.)
    ├── rules/                         # Detailed rule content and traceability links (generated by sync)
    ├── archived-rules.md              # Archived rules after user confirmation
    └── changelog-archive.md           # Changelog archive when EVOLVE changelog grows large
```

---

## 🚀 Quick Start & CLI Toolchain

Scripts in this repository can be used as standalone local tools or integrated into an AI agent workflow. By default, scripts are in the skill repository `scripts/` directory and operate on target projects via `--project-root`.

### 1️⃣ Audit Lifecycle Management (`audit_sync.py`)

```bash
# Initialize audit system
python scripts/audit_sync.py init --project-root /path/to/your/project

# List all rule scopes in current project
python scripts/audit_sync.py scopes --project-root /path/to/your/project

# Filter rules by platform or scope
python scripts/audit_sync.py filter --project-root /path/to/your/project --platform claude

# Generate numbered EVOLVE suggestions and select final entries
python scripts/audit_sync.py report --project-root /path/to/your/project
python scripts/audit_sync.py select "1,3" --project-root /path/to/your/project

# Sync data to EVOLVE.md and platform auto blocks
python scripts/audit_sync.py sync --project-root /path/to/your/project

# Output promotion suggestions (candidate output only; does not rewrite rules automatically)
python scripts/audit_sync.py promote --project-root /path/to/your/project

```

### 2️⃣ Experience Health Diagnostics (`health_check.py`)

Evaluate accumulated rules from six dimensions: integrity, consistency, structure, freshness, quality, and anti-corruption.

```bash
# Output text diagnostic report
python scripts/health_check.py --project-root /path/to/your/project

# Output JSON report (for CI/CD or automated workflows)
python scripts/health_check.py --project-root /path/to/your/project --json

```

---

## 📊 Data Format and Conventions

### Audit Data (`evolve/audit.csv`)

Each experience occupies one CSV row as the data source of system evolution:

| Field | Description | Example |
| --- | --- | --- |
| `rule_id` | Rule ID (`R-xxx` = shared rule, `S-xxx` = platform-specific lesson) | `R-001` |
| `platform` | Applicable AI platform (`all` / `claude` / `gemini` / `codex` / `cursor` / custom) | `all` |
| `scope` | Scope category (`category/subcategory`) | `Deployment/Docker` |
| `title` | Rule title (short and readable summary) | `Check .env before proceeding` |
| `origin` | Rule origin (`error` = from real issue / `preventive` = proactive / `imported` = externally imported) | `error` |
| `hit` | **Hit count**: times the AI successfully retrieved and referenced this experience in later sessions | `5` |
| `vio` | **Violation count**: times AI or developers violated this rule | `1` |
| `err` | **Error-causing count**: violations that caused observable code/runtime errors (subset of `vio`) | `0` |
| `skip` | **Manual skip count**: times manually judged as "not applicable this round" and skipped | `0` |
| `auto_skip` | **Auto skip count**: times auto-incremented when matched but unscored in current round | `2` |
| `last_reviewed` | Last audit date (ISO format) | `2026-02-23` |
| `status` | Rule lifecycle status (`active` / `protected` / `review` / `archived`) | `active` |
| `evolve_slot` | Agent-selected write order for EVOLVE generation (`0` means not selected) | `2` |

### Auto Block Conventions

The `sync` command maintains special auto blocks in markdown files for dynamic metrics/content updates. **Do not manually edit inside these blocks**, or changes may be overwritten:

```markdown
<!-- EVOLVE_SKILL:AUTO_SYNC:BEGIN platform=codex digest=xxxx updated=YYYY-MM-DD -->
## Evolve-Skill Auto Sync
(Auto-maintained content and metrics)
<!-- EVOLVE_SKILL:AUTO_SYNC:END -->
```

The same `sync` flow also maintains per-rule detail files under `evolve/rules/`.
Each rule file includes an auto-managed traceability block that links related `evolve/history/*.md` and `evolve/runbooks/*.md` entries.

---

## 🔒 Core Security Notes

Security is the first principle when allowing AI to automatically capture experience:

* ❌ **Strictly forbidden**: writing plaintext IPs, Tokens, API Secrets, passwords, private key paths, or similar sensitive data into `EVOLVE.md` or any versioned file.
* ✅ Sensitive content must go into **`EVOLVE.local.md`** and that file must be in `.gitignore`.
* ✅ In committable shared rules and runbooks, keep only **placeholders** (for example: `SSH_HOST=<YOUR_HOST>`, `API_KEY=${ENV_API_KEY}`).

## 📁 Repository Structure

```text
.
├── SKILL.md                  # Skill definition and complete execution workflow
├── AGENTS.md                 # Repository development conventions
├── scripts/
│   ├── audit_sync.py         # Audit sync CLI
│   └── health_check.py       # Health check CLI
└── references/
    ├── audit-system.md       # Audit model and command conventions
    ├── project-init.md       # Project evolution asset initialization guide
    └── writing-specs.md      # Documentation templates and writing conventions
```

---

## 🤝 Contributing

Issues and PRs are welcome. Before submitting, please ensure:

```bash
python -m py_compile scripts/audit_sync.py scripts/health_check.py
python scripts/audit_sync.py report --project-root .
python scripts/health_check.py --project-root .
```

---

## License

This project is open-sourced under the Apache-2.0 License.
