"""
core/conversation_summarizer.py
---------------------------------
Rolling conversation-history compressor for Agent_head.

Design
------
  State tracked by caller (main.py / api/server.py / mcp_server.py):

    conversation_history  – bounded working window fed to LLM each turn:
                            [SystemMsg] + [SummaryAIMsg?] + [last keep_n raw msgs]

    to_summarize_buffer   – append-only list of ALL new messages since the last
                            compression cycle (human + AI + tool). When this list
                            reaches `summarize_every_n_messages` the summarizer fires.

    current_summary       – rolling narrative text; updated each cycle.

  Per-turn flow (managed by caller):
    1.  Append human_msg → to_summarize_buffer AND conversation_history.
    2.  Run LLM (graph.astream) with conversation_history.
    3.  Delta-append new AI/tool msgs → to_summarize_buffer AND conversation_history.
    4.  Archive ALL new messages (human + AI/tool) to persistent store.
    5.  if len(to_summarize_buffer) >= summarize_every_n_messages:
            result = summarizer.summarize(buffer=to_summarize_buffer, prev_summary=...)
            rebuild conversation_history = [sys] + [SummaryAIMsg] + last keep_n msgs
            to_summarize_buffer = []          # reset buffer
            current_summary = result.summary  # keep updated narrative

  The summarizer only ever sees the buffer (bounded to trigger size) — never
  the full growing history. Token cost is therefore O(trigger), not O(total msgs).

Public API
----------
  summarizer = ConversationSummarizer(cfg, main_model_cfg)
  if summarizer.should_summarize(to_summarize_buffer):
      result = await summarizer.summarize(
          buffer       = to_summarize_buffer,
          prev_summary = current_summary,
          known_global_facts  = known_global_facts,
          known_private_facts = known_private_facts,
      )
      # result.summary           – updated narrative (replace current_summary)
      # result.global_facts      – FULL reconciled global fact list
      # result.private_facts     – FULL reconciled private fact list
      # result.new_global_facts  – only new/changed global facts (persist these)
      # result.new_private_facts – only new/changed private facts (persist these)
      # result.summary_ai_msg    – ready-made AIMessage("[Session summary] ...") to
      #                            inject into conversation_history by the caller
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from main import _c

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class SummaryResult:
    summary: str                 # updated narrative paragraph
    global_facts: list[str]      # FULL updated global fact list
    private_facts: list[str]     # FULL updated private fact list
    new_global_facts: list[str]  # subset: global facts that are new or changed
    new_private_facts: list[str] # subset: private facts that are new or changed
    summary_ai_msg: object       # ready-made AIMessage("[Session summary] ...") for
                                 # the caller to inject into conversation_history


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

=== RECENT MESSAGES TO INCORPORATE ===
{messages_block}

Produce exactly the following format:

SUMMARY:
<An updated 2-4 sentence narrative combining the previous summary with the new messages.>

NEW GLOBAL FACTS:
Extract ONLY facts that meet ALL of the following criteria:
  1. Explicitly stated or directly demonstrated in the recent messages (not inferred)
  2. Objectively true regardless of this specific session (e.g. library APIs, config formats, domain rules, error fixes)
  3. Genuinely useful to recall in a completely different future conversation

DO NOT include:
  - Observations about how the AI agent behaves or responds (e.g. "The system greets users warmly")
  - Generic workflow descriptions (e.g. "The system checks memory before responding")
  - Facts that are obvious, trivial, or common knowledge
  - Anything that is only true within this session's context

Example of a GOOD global fact: "ChromaDB requires metadata values to be str, int, float, or bool — not None."
Example of a BAD global fact: "The system responds to greetings with friendly acknowledgments."

- <Concrete, durable, externally-true fact from the conversation>
(Write "none" on a single line if there are no qualifying global facts.)

NEW PRIVATE FACTS:
Extract ONLY facts that are specific to this user or session and would be useful to recall later:
  - User names, stated preferences, or explicit personal context
  - Project-specific paths, names, or configuration the user mentioned
  - Goals or constraints the user explicitly described

DO NOT include generic session observations or agent behavior descriptions.

- <User/session-specific fact explicitly stated in the conversation>
(Write "none" on a single line if there are no new private facts to add.)
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

    def should_summarize(self, buffer: list) -> bool:
        """
        Return True when the to_summarize_buffer has accumulated enough new
        messages to warrant a compression cycle.

        Args:
            buffer – the to_summarize_buffer list managed by the caller.
                     Contains every new message (human + AI + tool) added
                     since the last compression.  SystemMessages are excluded
                     by convention (callers never add them to the buffer).
        """
        return len(buffer) >= self._trigger

    async def summarize(
        self,
        buffer: list,
        prev_summary: str = "",
        known_global_facts: list[str] | None = None,
        known_private_facts: list[str] | None = None,
    ) -> SummaryResult:
        """
        Compress the to_summarize_buffer into an updated rolling summary.

        The buffer contains every new message (human + AI + tool) accumulated
        since the last compression cycle — NOT the full conversation_history.
        This keeps token cost bounded to O(trigger size), not O(total history).

        Args:
            buffer              – new messages since last compression (the buffer)
            prev_summary        – narrative from previous cycle (or "")
            known_global_facts  – global facts already extracted in earlier cycles
            known_private_facts – private facts already extracted in earlier cycles

        Returns:
            SummaryResult with updated summary, fact lists, and a ready-made
            summary_ai_msg for the caller to inject into conversation_history.
        """
        known_global_facts = known_global_facts or []
        known_private_facts = known_private_facts or []

        if not buffer:
            logger.warning("[Summarizer] should_summarize returned True but buffer is empty.")
            return SummaryResult(
                summary=prev_summary,
                global_facts=known_global_facts,
                private_facts=known_private_facts,
                new_global_facts=[],
                new_private_facts=[],
                summary_ai_msg=AIMessage(content=f"[Session summary] {prev_summary}"),
            )

        # Serialise buffer messages into plain text for the prompt
        messages_block = self._messages_to_text(buffer)

        # Build the prompt: last summary + new buffer messages
        prompt = self._PROMPT_TEMPLATE.format(
            prev_summary=prev_summary or "(none yet)",
            messages_block=messages_block,
        )

        model_id = f"{self._llm.__class__.__name__}"
        print(_c("90", f"\n[Summarizer] Calling LLM ({model_id}) — "
                       f"compressing {len(buffer)} new msgs (buffer) + last summary..."))
        logger.info(
            "[Summarizer] Compressing buffer of %d messages.",
            len(buffer),
        )

        try:
            response = await self._llm.ainvoke(prompt)
            raw_text = self._extract_text(response)
        except Exception as exc:
            logger.error("[Summarizer] LLM call failed: %s", exc)
            # Graceful degradation — return unchanged facts, keep old summary
            return SummaryResult(
                summary=prev_summary,
                global_facts=known_global_facts,
                private_facts=known_private_facts,
                new_global_facts=[],
                new_private_facts=[],
                summary_ai_msg=AIMessage(content=f"[Session summary] {prev_summary}"),
            )

        # Parse sections
        summary, new_global_facts, new_private_facts = self._parse_response(raw_text)

        global_facts  = known_global_facts  + new_global_facts
        private_facts = known_private_facts + new_private_facts

        # Build the summary AIMessage — caller injects this into conversation_history
        summary_ai_msg = AIMessage(
            content=f"[Session summary] {summary}",
            response_metadata=getattr(response, "response_metadata", {}),
            usage_metadata=getattr(response, "usage_metadata", None),
            additional_kwargs=getattr(response, "additional_kwargs", {}),
        )

        logger.info(
            "[Summarizer] Done. Summary: %d chars. "
            "Global Facts: %d (new: %d), Private Facts: %d (new: %d).",
            len(summary),
            len(global_facts), len(new_global_facts),
            len(private_facts), len(new_private_facts),
        )

        return SummaryResult(
            summary=summary,
            global_facts=global_facts,
            private_facts=private_facts,
            new_global_facts=new_global_facts,
            new_private_facts=new_private_facts,
            summary_ai_msg=summary_ai_msg,
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _messages_to_text(messages: list) -> str:
        from langchain_core.messages import ToolMessage
        lines = []
        for m in messages:
            if isinstance(m, HumanMessage):
                role = "Human"
                content = m.content
            elif isinstance(m, AIMessage):
                # AI message may carry tool_calls, text content, or both
                tool_calls = getattr(m, "tool_calls", None)
                content = m.content
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", str(b)) if isinstance(b, dict) else str(b)
                        for b in content
                    )
                if tool_calls and not content:
                    # Pure tool-dispatch message — no visible text
                    calls_repr = ", ".join(
                        f"{tc.get('name','?')}({tc.get('args',{})})"
                        for tc in tool_calls
                    )
                    role = "Assistant[tool_calls]"
                    content = calls_repr
                elif tool_calls:
                    calls_repr = ", ".join(
                        f"{tc.get('name','?')}({tc.get('args',{})})"
                        for tc in tool_calls
                    )
                    role = "Assistant"
                    content = f"{content} [called: {calls_repr}]"
                else:
                    role = "Assistant"
            elif isinstance(m, ToolMessage):
                tool_name = getattr(m, "name", None) or getattr(m, "tool_call_id", "tool")
                role = f"Tool[{tool_name}]"
                content = m.content
            else:
                role = "System"
                content = m.content

            if isinstance(content, list):
                content = " ".join(
                    b.get("text", str(b)) if isinstance(b, dict) else str(b)
                    for b in content
                )
            # Truncate very long tool results so the summarizer prompt stays sane
            content = str(content)
            if len(content) > 800:
                content = content[:800] + "…[truncated]"
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
    def _parse_response(text: str) -> tuple[str, list[str], list[str]]:
        """
        Parse the LLM response for SUMMARY:, GLOBAL FACTS:, and PRIVATE FACTS: sections.
        Robust to minor formatting variations.
        """
        summary = ""
        global_facts: list[str] = []
        private_facts: list[str] = []

        # Extract SUMMARY section
        summary_match = re.search(
            r"SUMMARY:\s*(.*?)(?=\nNEW GLOBAL FACTS:|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if summary_match:
            summary = summary_match.group(1).strip()

        # Extract GLOBAL FACTS section
        global_facts_match = re.search(
            r"NEW GLOBAL FACTS:\s*(.*?)(?=\nNEW PRIVATE FACTS:|$)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if global_facts_match:
            raw_facts = global_facts_match.group(1).strip()
            if raw_facts.lower() != "none" and raw_facts.lower() != "none.":
                for line in raw_facts.splitlines():
                    line = re.sub(r"^[-*•]\s*", "", line).strip()
                    if line and line.lower() != "none":
                        global_facts.append(line)

        # Extract PRIVATE FACTS section
        private_facts_match = re.search(
            r"NEW PRIVATE FACTS:\s*(.*?)$",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if private_facts_match:
            raw_facts = private_facts_match.group(1).strip()
            if raw_facts.lower() != "none":
                for line in raw_facts.splitlines():
                    line = re.sub(r"^[-*•]\s*", "", line).strip()
                    if line and line.lower() != "none":
                        private_facts.append(line)

        # Fallback: if parsing failed, treat entire response as summary
        if not summary:
            summary = text.strip()

        return summary, global_facts, private_facts
