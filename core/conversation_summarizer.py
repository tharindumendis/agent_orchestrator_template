"""
core/conversation_summarizer.py
---------------------------------
Rolling conversation-history compressor for Agent_head.

Design
------
  When the raw conversation history grows beyond `trigger_after_n_messages`
  (Human + AI messages only, SystemMessage excluded), a separate, optionally
  lighter LLM is called once to:

    1. Extend/update the existing rolling *narrative summary*.
    2. Extract ONLY *new* discrete facts not already known.

  The caller (main.py REPL loop) is responsible for persisting new/changed facts
  and replacing known_facts with the full updated list via the MemoryBackend.

Data flow per cycle
-------------------
  known_facts  <- replaced entirely with result.facts (full reconciled list)
  storage      <- only result.new_or_changed are persisted (avoids duplicates)
  history      <- replaced with result.trimmed_history
  current_summary <- replaced with result.summary

Public API
----------
  summarizer = ConversationSummarizer(cfg, main_model_cfg)
  if summarizer.should_summarize(conversation_history):
      result = await summarizer.summarize(
          history       = conversation_history,
          prev_summary  = current_summary,
          known_facts   = known_facts,
      )
      # result.summary         – updated narrative (replace current_summary)
      # result.facts           – FULL reconciled fact list (replace known_facts entirely)
      # result.new_or_changed  – only newly added/corrected facts (persist these)
      # result.trimmed_history – ready to swap in as conversation_history
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class SummaryResult:
    summary: str               # updated narrative paragraph
    facts: list[str]           # FULL updated fact list (additions + corrections; replaces known_facts)
    new_or_changed: list[str]  # subset: facts that are new or changed vs. prev (persist to storage)
    trimmed_history: list      # ready-to-use replacement for conversation_history


# ---------------------------------------------------------------------------
# ConversationSummarizer
# ---------------------------------------------------------------------------

class ConversationSummarizer:
    """
    Periodically compresses old conversation messages into a rolling summary
    and extracts new discrete facts in one LLM call.
    """

    # Prompt sent to the summarizer LLM
    _PROMPT_TEMPLATE = """\
You are a memory compression assistant for an AI agent.

Your task is to help maintain concise, accurate memory across a long conversation.

=== PREVIOUS SUMMARY ===
{prev_summary}

=== CURRENT KNOWN FACTS ===
{known_facts_block}
(These may be added to, corrected, or removed if the conversation contradicts them.)

=== NEW MESSAGES TO INCORPORATE ===
{messages_block}

Produce exactly the following format:

SUMMARY:
<An updated 2-4 sentence narrative combining the previous summary with the new messages.>

UPDATED FACTS:
- <The complete, reconciled list of facts. Include all previous facts that are still true, correct any that changed, add new ones. One fact per line.>
- <another fact>
(Write "none" on a single line if there are genuinely no facts at all.)
"""

    def __init__(self, summarizer_cfg, main_model_cfg):
        """
        Build the summarizer LLM.

        summarizer_cfg  – SummarizerConfig from config_loader (may be None/disabled)
        main_model_cfg  – ModelConfig for the main orchestrator (fallback)
        """
        # Use summarizer-specific model if configured, else fall back to main model
        model_cfg = (
            summarizer_cfg.model
            if summarizer_cfg is not None and summarizer_cfg.model is not None
            else main_model_cfg
        )
        self._trigger = (
            summarizer_cfg.summarize_every_n_messages
            if summarizer_cfg is not None
            else 8
        )
        self._keep = (
            summarizer_cfg.keep_recent_messages
            if summarizer_cfg is not None
            else 6
        )

        from core.llm import get_llm
        self._llm = get_llm(model_cfg)

    # ── Removed duplicate LLM factory in favour of core.llm ─────────

    # ── Public API ──────────────────────────────────────────────────────────

    def should_summarize(self, history: list) -> bool:
        """
        Return True when the number of Human+AI messages meets the threshold.
        We ensure it triggers deterministically by adding the 'keep' baseline,
        meaning it waits for exactly `trigger` new messages before compressing again.
        """
        count = sum(
            1 for m in history
            if isinstance(m, (HumanMessage, AIMessage))
        )
        # Baseline = kept raw messages + 1 (the injected summary message)
        baseline = self._keep + 1
        return count >= (baseline + self._trigger)

    async def summarize(
        self,
        history: list,
        prev_summary: str = "",
        known_facts: list[str] | None = None,
    ) -> SummaryResult:
        """
        Compress the oldest messages in *history* into an updated rolling
        summary and a list of NEW facts.

        Args:
            history      – full conversation_history list (SystemMessage at [0])
            prev_summary – narrative from previous summarization cycle (or "")
            known_facts  – facts already extracted in earlier cycles

        Returns:
            SummaryResult with updated summary, new-only facts, and trimmed history.
        """
        known_facts = known_facts or []

        # Split history: pin SystemMessage(s), keep last N raw, compress the rest
        system_msgs = [m for m in history if isinstance(m, SystemMessage)]
        non_system  = [m for m in history if not isinstance(m, SystemMessage)]

        # Messages to compress = all non-system except the last keep_last_n
        to_compress = non_system[:-self._keep] if len(non_system) > self._keep else []
        to_keep     = non_system[-self._keep:] if len(non_system) > self._keep else non_system

        if not to_compress:
            # Nothing old enough to compress — return history unchanged
            logger.warning("[Summarizer] should_summarize returned True but nothing to compress.")
            return SummaryResult(
                summary=prev_summary,
                facts=known_facts,
                new_or_changed=[],
                trimmed_history=history,
            )

        # Serialise messages to compress into plain text
        messages_block = self._messages_to_text(to_compress)

        # Serialise known facts
        known_facts_block = (
            "\n".join(f"- {f}" for f in known_facts)
            if known_facts
            else "(none yet)"
        )

        # Build the prompt
        prompt = self._PROMPT_TEMPLATE.format(
            prev_summary=prev_summary or "(none yet)",
            known_facts_block=known_facts_block,
            messages_block=messages_block,
        )

        logger.info(
            "[Summarizer] Compressing %d messages (keep last %d). Known facts: %d.",
            len(to_compress), self._keep, len(known_facts),
        )

        # Call the summarizer LLM (plain invoke, not ReAct)
        model_id = f"{self._llm.__class__.__name__}"
        print(
            f"\n\033[90m[Summarizer] Calling LLM ({model_id}) — "
            f"compressing {len(to_compress)} msgs, "
            f"{len(known_facts)} facts known...\033[0m"
        )
        try:
            response = await self._llm.ainvoke(prompt)
            raw_text = self._extract_text(response)
        except Exception as exc:
            logger.error("[Summarizer] LLM call failed: %s", exc)
            # Graceful degradation: return history unchanged
            return SummaryResult(
                summary=prev_summary,
                facts=known_facts,
                new_or_changed=[],
                trimmed_history=history,
            )

        # Parse SUMMARY and UPDATED FACTS sections
        summary, updated_facts = self._parse_response(raw_text)

        # Compute delta: facts that are new or changed vs. known_facts
        known_set = set(known_facts)
        new_or_changed = [f for f in updated_facts if f not in known_set]

        # Build trimmed history: pinned SystemMsg(s) + summary AIMessage + recent raw msgs
        trimmed = list(system_msgs)
        if summary:
            trimmed.append(AIMessage(content=f"[Session summary] {summary}"))
        trimmed.extend(to_keep)

        logger.info(
            "[Summarizer] Done. Summary: %d chars. Facts total: %d (new/changed: %d).",
            len(summary), len(updated_facts), len(new_or_changed),
        )

        return SummaryResult(
            summary=summary,
            facts=updated_facts,          # full list — caller replaces known_facts
            new_or_changed=new_or_changed, # only persisted to storage
            trimmed_history=trimmed,
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _messages_to_text(messages: list) -> str:
        lines = []
        for m in messages:
            role = (
                "Human" if isinstance(m, HumanMessage)
                else "Assistant" if isinstance(m, AIMessage)
                else "Tool"
            )
            content = m.content
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", str(b)) if isinstance(b, dict) else str(b)
                    for b in content
                )
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response) -> str:
        content = getattr(response, "content", str(response))
        if isinstance(content, list):
            return " ".join(
                b.get("text", str(b)) if isinstance(b, dict) else str(b)
                for b in content
            )
        return str(content)

    @staticmethod
    def _parse_response(text: str) -> tuple[str, list[str]]:
        """
        Parse the LLM response for SUMMARY: and UPDATED FACTS: sections.
        Robust to minor formatting variations.
        """
        summary = ""
        facts: list[str] = []

        # Extract SUMMARY section
        summary_match = re.search(
            r"SUMMARY:\s*(.*?)(?=\nUPDATED FACTS:|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if summary_match:
            summary = summary_match.group(1).strip()

        # Extract UPDATED FACTS section
        facts_match = re.search(
            r"UPDATED FACTS:\s*(.*?)$",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if facts_match:
            raw_facts = facts_match.group(1).strip()
            if raw_facts.lower() != "none":
                for line in raw_facts.splitlines():
                    line = re.sub(r"^[-*•]\s*", "", line).strip()
                    if line and line.lower() != "none":
                        facts.append(line)

        # Fallback: if parsing failed, treat entire response as summary
        if not summary:
            summary = text.strip()

        return summary, facts
