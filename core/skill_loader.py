"""
core/skill_loader.py
--------------------
Discovers and serves skill knowledge documents for the orchestrator agent.

A skill is a folder in one or more configured skills directories that contains
a SKILL.md file with optional YAML frontmatter:

    ---
    name: mysql
    description: Plan and review MySQL/InnoDB schema, indexing, query tuning...
    enabled: true       # optional (default true)
    ---
    # Full skill content follows...

Three activation paths:
  1. Skills catalog — compact name+description index always in the system prompt
  2. load_skill tool — agent calls this to fetch full content on demand
  3. /skillname slash command — user types /mysql to trigger a full skill load
  4. always_inject config list — skills listed here are fully injected at startup

Public API
----------
  discover_skills(skills_dirs)          → list[Skill]
  build_catalog_block(skills)           → str  (compact index for system prompt)
  load_skill_content(name, skills)      → str  (full SKILL.md body)
  extract_slash_commands(text, skills)  → (cleaned_text, matched_skills)
  make_load_skill_tool(skills)          → LangChain tool
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    name: str               # unique slug — matches folder name
    description: str        # from frontmatter — shown in catalog
    body: str               # full markdown content of SKILL.md (after frontmatter)
    enabled: bool = True
    path: Path = field(default_factory=Path)
    sub_docs: dict[str, Path] = field(default_factory=dict)
    # sub_docs: relative path → absolute Path, e.g.
    #   "references/commands"  → Path(...)/references/commands.md
    #   "templates/form-automation" → Path(...)/templates/form-automation.sh


# ---------------------------------------------------------------------------
# Frontmatter parser (zero extra dependencies — simple regex split)
# ---------------------------------------------------------------------------


def _parse_skill_md(skill_md_path: Path) -> dict:
    """
    Parse YAML frontmatter and markdown body from a SKILL.md file.

    Handles:
      - Standard --- ... --- frontmatter blocks
      - Files with no frontmatter (entire file treated as body)
      - Quoted and unquoted frontmatter values
      - Multi-line description values (single-line only in frontmatter)
    """
    text = skill_md_path.read_text(encoding="utf-8", errors="replace")

    # Attempt to match --- frontmatter --- block at file start
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not fm_match:
        # No frontmatter — use folder name as skill name, whole file as body
        return {
            "name": skill_md_path.parent.name,
            "description": "",
            "body": text.strip(),
            "enabled": True,
        }

    fm_text = fm_match.group(1)
    body = fm_match.group(2).strip()

    # Simple key: value YAML parsing (handles basic scalar types, no nesting)
    meta: dict = {}
    for line in fm_text.splitlines():
        m = re.match(r'^([\w][\w-]*):\s*(.*)', line)
        if m:
            key = m.group(1).strip()
            val: str | bool = m.group(2).strip().strip("\"'")
            if isinstance(val, str) and val.lower() == "true":
                val = True
            elif isinstance(val, str) and val.lower() == "false":
                val = False
            meta[key] = val

    return {
        "name":        str(meta.get("name",    skill_md_path.parent.name)),
        "description": str(meta.get("description", "")),
        "body":        body,
        "enabled":     bool(meta.get("enabled", True)),
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_skills(skills_dirs: list[str | Path]) -> list[Skill]:
    """
    Scan one or more directories for skill folders containing SKILL.md.

    Rules:
    - Each entry in skills_dirs is scanned for subdirectories.
    - A subdirectory qualifies as a skill if it contains SKILL.md.
    - Duplicate skill names (across dirs) are skipped — first occurrence wins.
    - Skills with enabled=false are silently skipped.
    - Directories that don't exist are silently skipped (logged at DEBUG).

    Returns all discovered, enabled skills sorted alphabetically by name.
    """
    skills: list[Skill] = []
    seen_names: set[str] = set()

    for sd in skills_dirs:
        skills_dir = Path(sd)
        if not skills_dir.is_dir():
            logger.debug("[Skills] Dir not found: %s — skipping", skills_dir)
            continue

        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                parsed = _parse_skill_md(skill_md)
                name = parsed["name"]

                if not parsed["enabled"]:
                    logger.debug("[Skills] Skill '%s' disabled — skipping", name)
                    continue

                if name in seen_names:
                    logger.debug(
                        "[Skills] Duplicate skill '%s' in %s — first-found wins",
                        name, skills_dir,
                    )
                    continue

                skill = Skill(
                    name=name,
                    description=parsed["description"],
                    body=parsed["body"],
                    enabled=parsed["enabled"],
                    path=entry,
                    sub_docs=_discover_sub_docs(entry),
                )
                skills.append(skill)
                seen_names.add(name)
                logger.info(
                    "[Skills] Discovered: %s (%d sub-docs) from %s",
                    name, len(skill.sub_docs), skills_dir,
                )

            except Exception as exc:
                logger.warning(
                    "[Skills] Failed to parse %s: %s", skill_md, exc
                )

    return skills


# ---------------------------------------------------------------------------
# Sub-document discovery
# ---------------------------------------------------------------------------


DOC_EXTENSIONS = {".md", ".txt", ".sh", ".py", ".yaml", ".yml", ".json"}


def _discover_sub_docs(skill_path: Path) -> dict[str, Path]:
    """
    Walk the skill folder for all non-SKILL.md files in sub-folders.
    Returns a dict mapping a relative key to the absolute file path.

    Key format: "<subfolder>/<stem>" (no extension), e.g.:
      "references/commands"        → references/commands.md
      "templates/form-automation"  → templates/form-automation.sh
      "rules/async-parallel"       → rules/async-parallel.md
    """
    sub_docs: dict[str, Path] = {}
    for fpath in sorted(skill_path.rglob("*")):
        if fpath.name == "SKILL.md":
            continue
        if fpath.name.startswith("."):
            continue
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in DOC_EXTENSIONS:
            continue
        rel = fpath.relative_to(skill_path)
        # Key = folder/stem (e.g. references/commands)
        key = str(rel.parent / rel.stem).replace("\\", "/")
        sub_docs[key] = fpath
    return sub_docs


# ---------------------------------------------------------------------------
# Catalog block (compact index for system prompt)
# ---------------------------------------------------------------------------


def build_catalog_block(skills: list[Skill]) -> str:
    """
    Build the compact skills catalog injected into the system prompt.
    Contains only name + description — NOT the full body.

    Example output:
      [Available Skills]
      You have access to the following knowledge skills.
      Use the load_skill tool to fetch full instructions when a skill is relevant.

      - mysql: Plan and review MySQL/InnoDB schema, indexing, query tuning...
      - agent-browser: Browser automation CLI for AI agents...
    """
    if not skills:
        return ""

    lines = [
        "[Available Skills]",
        "You have access to the following knowledge skills.",
        "Use the load_skill tool to get detailed instructions when a skill is relevant to the task.",
        "Sub-documents (references, templates, rules) can be loaded with load_skill('<skill>/<subfolder>/<name>').",
        "",
    ]
    for sk in skills:
        desc = sk.description
        if len(desc) > 220:
            desc = desc[:220] + "..."
        lines.append(f"  - {sk.name}: {desc}")
        # Group sub-docs by folder and list them
        if sk.sub_docs:
            folders: dict[str, list[str]] = {}
            for key in sorted(sk.sub_docs):
                folder, _, stem = key.partition("/")
                folders.setdefault(folder, []).append(stem)
            for folder, stems in folders.items():
                lines.append(f"      ({folder}): {', '.join(stems)}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full content loader
# ---------------------------------------------------------------------------


def load_skill_content(skill_name: str, skills: list[Skill]) -> str:
    """
    Return skill content by name. Two formats supported:

    1. "mysql"                              → full SKILL.md body
    2. "mysql/references/deadlocks"         → specific sub-document
       "agent-browser/references/commands"  → specific sub-document
       "agent-browser/templates/form-automation"
    """
    # Split on the first '/' after the skill name to detect sub-document requests
    parts = skill_name.strip().split("/", maxsplit=1)
    name = parts[0].lower()
    sub_path = parts[1].lower() if len(parts) > 1 else None

    # Find the skill
    sk = next((s for s in skills if s.name.lower() == name), None)
    if sk is None:
        available = ", ".join(s.name for s in skills) or "(none)"
        return (
            f"Skill '{name}' not found.\n"
            f"Available skills: {available}"
        )

    # No sub-path → return full SKILL.md body
    if sub_path is None:
        lines = [
            f"--- [Skill: {sk.name}] ---",
            sk.body,
        ]
        if sk.sub_docs:
            folders: dict[str, list[str]] = {}
            for key in sorted(sk.sub_docs):
                folder, _, stem = key.partition("/")
                folders.setdefault(folder, []).append(stem)
            lines.append("\n[Sub-documents available — use load_skill('<skill>/<subfolder>/<name>') to load:]")
            for folder, stems in folders.items():
                lines.append(f"  {folder}: {', '.join(stems)}")
        lines.append(f"--- [End Skill: {sk.name}] ---")
        return "\n".join(lines)

    # Sub-path → look up in sub_docs index (case-insensitive)
    match = next(
        (path for key, path in sk.sub_docs.items() if key.lower() == sub_path),
        None,
    )
    if match is None:
        available_keys = ", ".join(sorted(sk.sub_docs)) or "(none)"
        return (
            f"Sub-document '{sub_path}' not found in skill '{sk.name}'.\n"
            f"Available: {available_keys}"
        )

    try:
        content = match.read_text(encoding="utf-8", errors="replace")
        return (
            f"--- [Skill: {sk.name} / {sub_path}] ---\n"
            f"{content.strip()}\n"
            f"--- [End Skill: {sk.name} / {sub_path}] ---"
        )
    except Exception as exc:
        return f"Error reading '{sub_path}': {exc}"


# ---------------------------------------------------------------------------
# Slash-command extraction  (/skillname)
# ---------------------------------------------------------------------------


def extract_slash_commands(
    text: str,
    skills: list[Skill],
) -> tuple[str, list[Skill]]:
    """
    Scan user input for /skillname tokens that match known skills.

    Returns:
      (cleaned_text, matched_skills)

    The /skillname token is removed from the text before it is sent to the LLM.
    Unknown /tokens (e.g. /not-a-skill) are left in the text untouched.
    """
    skill_map = {sk.name.lower(): sk for sk in skills}
    tokens = re.findall(r"/([a-zA-Z0-9_-]+)", text)
    matched: list[Skill] = []

    for token in tokens:
        if token.lower() in skill_map and skill_map[token.lower()] not in matched:
            matched.append(skill_map[token.lower()])

    # Strip only the matched /tokens from the text
    cleaned = text
    for sk in matched:
        cleaned = re.sub(rf"/{re.escape(sk.name)}", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip(), matched


# ---------------------------------------------------------------------------
# LangChain tool factory
# ---------------------------------------------------------------------------


def make_load_skill_tool(skills: list[Skill]):
    """
    Create and return the `load_skill` LangChain tool.

    The tool is registered alongside image/audio tools — no subprocess, no MCP.
    The agent calls it when it decides detailed skill guidance is needed.
    """
    from langchain_core.tools import tool as lc_tool

    _skills = skills  # capture in closure

    @lc_tool
    def load_skill(skill_name: str) -> str:
        """
        Load the full instructions or a specific sub-document for a skill.

        Call this when you need detailed guidance on a topic covered by a skill.
        Skills include domain-specific rules, best practices, workflows, references,
        and code templates that help you complete tasks correctly and efficiently.

        USAGE:
          load_skill("mysql")                              → full MySQL skill (SKILL.md)
          load_skill("agent-browser")                     → full agent-browser skill
          load_skill("agent-browser/references/commands") → complete CLI command reference
          load_skill("agent-browser/templates/form-automation") → form automation template
          load_skill("mysql/references/deadlocks")        → deadlock diagnosis guide

        The [Available Skills] catalog shows which sub-documents exist per skill.
        Always load the SKILL.md first (no sub-path) to understand the skill overview,
        then fetch specific sub-documents as needed.

        args:
            skill_name (str): Skill name, or '<skill>/<subfolder>/<name>' for a sub-document.
        """
        return load_skill_content(skill_name, _skills)

    return load_skill
