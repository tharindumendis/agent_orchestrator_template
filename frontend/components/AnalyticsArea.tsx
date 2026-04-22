"use client";
import React, { useState, useEffect, useRef } from "react";
import { ExportMessage } from "../types";

interface AnalyticsAreaProps {
  currentHistorySession: string | null;
  apiBaseUrl: string;
}

interface AnalyticsData {
  totalMessages: number;
  totalAiTokens: number;
  inputTokens: number;
  outputTokens: number;
  totalDurationMs: number;
  toolCallsCount: number;
  messages: ExportMessage[];
}

type ViewMode = "analytics" | "conversation" | "raw";
type HistoryMode = "working" | "archive";

const formatDuration = (ms: number) => {
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(2)}s`;
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s.toFixed(1)}s`;
};

const extractDurationMs = (duration: number | undefined) => {
  if (!duration) return 0;
  if (duration > 1e8) return duration / 1e6;
  return duration;
};

/** Render any message content — string or array of content blocks */
function renderContent(content: unknown): React.ReactNode {
  if (!content) return <span className="italic text-neutral-400">No text content</span>;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((block: any, i) => (
      <span key={i}>
        {block.type === "text" ? block.text : JSON.stringify(block)}
      </span>
    ));
  }
  return JSON.stringify(content);
}

export const AnalyticsArea: React.FC<AnalyticsAreaProps> = ({
  currentHistorySession,
  apiBaseUrl,
}) => {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("conversation");
  const [historyMode, setHistoryMode] = useState<HistoryMode>("archive");
  const [expandedMsg, setExpandedMsg] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [copySuccess, setCopySuccess] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!currentHistorySession) {
      setData(null);
      return;
    }
    fetchData(currentHistorySession, historyMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentHistorySession, apiBaseUrl, historyMode]);

  const fetchData = async (sessionId: string, mode: HistoryMode) => {
    setIsLoading(true);
    setError(null);
    setSearchQuery("");
    setExpandedMsg(null);
    try {
      const endpoint =
        mode === "archive"
          ? `${apiBaseUrl}/history/sessions/${sessionId}/full-export`
          : `${apiBaseUrl}/history/sessions/${sessionId}/export`;

      const response = await fetch(endpoint);
      if (!response.ok) throw new Error(`HTTP ${response.status}: failed to fetch session history`);
      const exportData = (await response.json()) as ExportMessage[];

      let totalAiTokens = 0;
      let inputTokens = 0;
      let outputTokens = 0;
      let totalDurationMs = 0;
      let toolCallsCount = 0;

      exportData.forEach((msg) => {
        if (msg.type === "ai" && msg.data?.response_metadata) {
          const meta = msg.data.response_metadata;
          if (msg.data.additional_kwargs?.usage_metadata) {
            const u = msg.data.additional_kwargs.usage_metadata;
            totalAiTokens += u.total_tokens || 0;
            inputTokens += u.input_tokens || 0;
            outputTokens += u.output_tokens || 0;
          } else if (meta.eval_count || meta.prompt_eval_count) {
            const i = meta.prompt_eval_count || 0;
            const o = meta.eval_count || 0;
            totalAiTokens += i + o;
            inputTokens += i;
            outputTokens += o;
          }
          if (meta.total_duration) totalDurationMs += extractDurationMs(meta.total_duration);
        }
        if (msg.type === "ai" && msg.data.tool_calls) {
          toolCallsCount += msg.data.tool_calls.length;
        }
      });

      setData({
        totalMessages: exportData.length,
        totalAiTokens,
        inputTokens,
        outputTokens,
        totalDurationMs,
        toolCallsCount,
        messages: exportData,
      });
    } catch (err: any) {
      setError(err.message || "Unknown error occurred");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyRaw = async () => {
    if (!data) return;
    await navigator.clipboard.writeText(JSON.stringify(data.messages, null, 2));
    setCopySuccess("Copied!");
    setTimeout(() => setCopySuccess(null), 2000);
  };

  // Filtered messages for conversation / analytics views
  const filteredMessages = data?.messages.filter((msg) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    const text = typeof msg.data?.content === "string"
      ? msg.data.content
      : JSON.stringify(msg.data?.content ?? "");
    return (
      text.toLowerCase().includes(q) ||
      msg.type.toLowerCase().includes(q) ||
      (msg.data?.name ?? "").toLowerCase().includes(q)
    );
  }) ?? [];

  // Empty state
  if (!currentHistorySession) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-neutral-400 space-y-4 bg-neutral-50 dark:bg-neutral-950">
        <svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="opacity-15">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <p className="text-sm font-medium">Select a session from the sidebar to review its history</p>
      </div>
    );
  }

  const msgTypeColor = (type: string) => {
    if (type === "human") return "bg-neutral-800 text-white dark:bg-white dark:text-black";
    if (type === "ai") return "bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400";
    if (type === "tool") return "bg-purple-100 text-purple-600 dark:bg-purple-900/40 dark:text-purple-400";
    return "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400";
  };

  return (
    <div className="flex-1 flex flex-col bg-neutral-50 dark:bg-neutral-950 overflow-hidden">
      {/* ── Header ── */}
      <div className="h-16 border-b border-neutral-200 dark:border-neutral-800 flex items-center px-5 justify-between flex-shrink-0 bg-white dark:bg-black">
        <div className="flex items-center gap-3 min-w-0">
          <svg className="w-4 h-4 text-purple-500 shrink-0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span className="font-semibold text-base text-neutral-800 dark:text-neutral-200 truncate">{currentHistorySession}</span>
          {data && (
            <span className="text-xs font-medium px-2 py-0.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-500 rounded-full shrink-0">
              {data.totalMessages} msgs
            </span>
          )}
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-2 shrink-0 ml-4">
          {/* Archive toggle */}
          <div className="flex items-center bg-neutral-100 dark:bg-neutral-800 rounded-lg p-0.5 text-xs font-medium">
            <button
              onClick={() => setHistoryMode("archive")}
              className={`px-3 py-1.5 rounded-md transition-all ${
                historyMode === "archive"
                  ? "bg-white dark:bg-neutral-700 text-purple-600 dark:text-purple-400 shadow-sm"
                  : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
              }`}
              title="Full Archive — every message ever sent, never trimmed"
            >
              Full Archive
            </button>
            <button
              onClick={() => setHistoryMode("working")}
              className={`px-3 py-1.5 rounded-md transition-all ${
                historyMode === "working"
                  ? "bg-white dark:bg-neutral-700 text-blue-600 dark:text-blue-400 shadow-sm"
                  : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
              }`}
              title="Working Copy — windowed slice fed to the LLM (may be trimmed)"
            >
              Working Copy
            </button>
          </div>

          {/* View mode */}
          <div className="flex items-center bg-neutral-100 dark:bg-neutral-800 rounded-lg p-0.5 text-xs font-medium">
            {(["conversation", "analytics", "raw"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setViewMode(m)}
                className={`px-3 py-1.5 rounded-md transition-all capitalize ${
                  viewMode === m
                    ? "bg-white dark:bg-neutral-700 text-neutral-800 dark:text-neutral-100 shadow-sm"
                    : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Archive mode badge ── */}
      <div className={`px-5 py-2 text-xs font-medium flex items-center gap-2 border-b ${
        historyMode === "archive"
          ? "bg-purple-50 dark:bg-purple-950/20 border-purple-200 dark:border-purple-900 text-purple-700 dark:text-purple-400"
          : "bg-blue-50 dark:bg-blue-950/20 border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-400"
      }`}>
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          {historyMode === "archive"
            ? <><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="m10 12 2 2 4-4"/></>
            : <><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></>
          }
        </svg>
        {historyMode === "archive"
          ? "Showing full archive — every message ever sent, never trimmed by summarisation."
          : "Showing working copy — this is the windowed slice fed to the LLM. Older messages may have been summarised away."}
      </div>

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center items-center h-40">
            <svg className="animate-spin h-7 w-7 text-neutral-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
        ) : error ? (
          <div className="m-6 p-5 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-xl border border-red-200 dark:border-red-800/50">
            <p className="font-semibold mb-1">Failed to load history</p>
            <p className="text-sm">{error}</p>
          </div>
        ) : data ? (
          <>
            {/* ══ CONVERSATION VIEW ══ */}
            {viewMode === "conversation" && (
              <div className="flex flex-col h-full">
                {/* Search bar */}
                <div className="px-5 py-3 border-b border-neutral-200 dark:border-neutral-800 bg-white dark:bg-black sticky top-0 z-10">
                  <div className="relative max-w-lg">
                    <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-neutral-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                    </svg>
                    <input
                      ref={searchRef}
                      type="text"
                      placeholder="Search messages…"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-4 py-2 text-sm bg-neutral-100 dark:bg-neutral-800 border border-transparent focus:border-neutral-300 dark:focus:border-neutral-600 rounded-lg focus:outline-none text-neutral-800 dark:text-neutral-200 placeholder-neutral-400"
                    />
                    {searchQuery && (
                      <button onClick={() => setSearchQuery("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200">
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                      </button>
                    )}
                  </div>
                  {searchQuery && (
                    <p className="text-xs text-neutral-400 mt-1.5">
                      {filteredMessages.length} matching message{filteredMessages.length !== 1 ? "s" : ""}
                    </p>
                  )}
                </div>

                {/* Messages */}
                <div className="flex-1 overflow-y-auto">
                  {filteredMessages.length === 0 ? (
                    <p className="text-sm italic text-neutral-400 text-center mt-20">No messages match your search.</p>
                  ) : (
                    filteredMessages.map((msg, i) => {
                      const isExpanded = expandedMsg === i;
                      const meta = msg.data?.response_metadata;
                      const kwUsage = msg.data?.additional_kwargs?.usage_metadata;
                      const durationMs = meta?.total_duration ? extractDurationMs(meta.total_duration) : 0;
                      const inTok = kwUsage?.input_tokens ?? meta?.prompt_eval_count ?? 0;
                      const outTok = kwUsage?.output_tokens ?? meta?.eval_count ?? 0;
                      const totTok = kwUsage?.total_tokens ?? (inTok + outTok);

                      const labelMap: Record<string, string> = { human: "User", ai: "Agent", tool: "Tool", system: "System" };

                      return (
                        <div
                          key={i}
                          className={`border-b border-neutral-100 dark:border-neutral-800/60 transition-colors ${
                            msg.type === "human"
                              ? "bg-neutral-50 dark:bg-neutral-900/30"
                              : msg.type === "system"
                              ? "bg-amber-50/30 dark:bg-amber-950/10"
                              : "bg-white dark:bg-neutral-950"
                          }`}
                        >
                          <div className="flex gap-3 px-5 py-4">
                            {/* Avatar */}
                            <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-xs font-bold ${msgTypeColor(msg.type)}`}>
                              {labelMap[msg.type]?.[0] ?? "?"}
                            </div>

                            <div className="flex-1 min-w-0">
                              {/* Row header */}
                              <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                                <span className="text-xs font-semibold text-neutral-700 dark:text-neutral-300">
                                  {labelMap[msg.type] ?? msg.type}
                                </span>
                                {msg.type === "tool" && msg.data.name && (
                                  <span className="font-mono text-xs px-1.5 py-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 rounded">
                                    {msg.data.name}
                                  </span>
                                )}
                                {msg.type === "ai" && meta?.model && (
                                  <span className="font-mono text-xs px-1.5 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded">
                                    {meta.model}
                                  </span>
                                )}
                                <span className="ml-auto text-xs text-neutral-400 font-mono">#{i + 1}</span>
                              </div>

                              {/* Content */}
                              <div className={`text-sm text-neutral-700 dark:text-neutral-300 leading-relaxed whitespace-pre-wrap break-words ${
                                !isExpanded && msg.type === "system" ? "line-clamp-3" : ""
                              }`}>
                                {renderContent(msg.data?.content)}
                              </div>

                              {/* Expand system prompt */}
                              {msg.type === "system" && (
                                <button
                                  onClick={() => setExpandedMsg(isExpanded ? null : i)}
                                  className="mt-1.5 text-xs text-blue-500 hover:text-blue-600 dark:text-blue-400 font-medium"
                                >
                                  {isExpanded ? "Show less ↑" : "Show full prompt ↓"}
                                </button>
                              )}

                              {/* Tool calls inline */}
                              {(msg.data.tool_calls?.length ?? 0) > 0 && (
                                <div className="mt-3 space-y-2">
                                  {msg.data.tool_calls?.map((tc: any, tci: number) => (
                                    <div key={tci} className="bg-neutral-50 dark:bg-neutral-900/60 border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden">
                                      <div className="px-3 py-1.5 bg-purple-50 dark:bg-purple-900/20 border-b border-neutral-200 dark:border-neutral-800 flex items-center gap-2">
                                        <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-purple-500">
                                          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                                        </svg>
                                        <span className="text-xs font-mono font-semibold text-purple-600 dark:text-purple-400">{tc.name}</span>
                                      </div>
                                      <pre className="px-3 py-2 text-xs font-mono text-neutral-600 dark:text-neutral-400 overflow-x-auto">
                                        {JSON.stringify(tc.args, null, 2)}
                                      </pre>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {/* Token / timing badges */}
                              {msg.type === "ai" && meta && (totTok > 0 || durationMs > 0) && (
                                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                                  {durationMs > 0 && (
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-500 rounded">
                                      <svg className="w-3 h-3" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                                      {formatDuration(durationMs)}
                                    </span>
                                  )}
                                  {totTok > 0 && (
                                    <>
                                      <span className="px-2 py-0.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-500 rounded">📊 {totTok.toLocaleString()} tok</span>
                                      <span className="px-2 py-0.5 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 rounded">📥 {inTok.toLocaleString()}</span>
                                      <span className="px-2 py-0.5 bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-500 rounded">📤 {outTok.toLocaleString()}</span>
                                    </>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}

            {/* ══ ANALYTICS VIEW ══ */}
            {viewMode === "analytics" && (
              <div className="p-6 md:p-8 max-w-5xl mx-auto space-y-8">
                {/* Stat cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { label: "Total Messages", value: data.totalMessages.toLocaleString(), color: "text-neutral-800 dark:text-neutral-100" },
                    { label: "AI Tokens", value: data.totalAiTokens.toLocaleString(), color: "text-neutral-800 dark:text-neutral-100",
                      sub: `📥 ${data.inputTokens.toLocaleString()} in · 📤 ${data.outputTokens.toLocaleString()} out` },
                    { label: "Tool Calls", value: data.toolCallsCount.toLocaleString(), color: "text-blue-600 dark:text-blue-400" },
                    { label: "AI Processing", value: formatDuration(data.totalDurationMs), color: "text-neutral-800 dark:text-neutral-100" },
                  ].map((card, i) => (
                    <div key={i} className="bg-white dark:bg-black p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm flex flex-col gap-1">
                      <div className="text-neutral-500 text-xs font-semibold uppercase tracking-wider">{card.label}</div>
                      <div className={`text-3xl font-bold ${card.color}`}>{card.value}</div>
                      {card.sub && <div className="text-xs text-neutral-400 mt-1">{card.sub}</div>}
                    </div>
                  ))}
                </div>

                {/* Message type breakdown */}
                <div className="bg-white dark:bg-black rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm p-6">
                  <h3 className="font-semibold text-neutral-800 dark:text-neutral-200 text-sm mb-4">Message Breakdown</h3>
                  {(() => {
                    const counts: Record<string, number> = {};
                    data.messages.forEach((m) => { counts[m.type] = (counts[m.type] ?? 0) + 1; });
                    const total = data.totalMessages;
                    const colors: Record<string, string> = {
                      human: "bg-neutral-700 dark:bg-neutral-300",
                      ai: "bg-blue-500",
                      tool: "bg-purple-500",
                      system: "bg-amber-400",
                    };
                    return (
                      <div className="space-y-3">
                        {Object.entries(counts).map(([type, count]) => (
                          <div key={type} className="flex items-center gap-3">
                            <span className="text-xs font-medium text-neutral-600 dark:text-neutral-400 w-14 capitalize">{type}</span>
                            <div className="flex-1 bg-neutral-100 dark:bg-neutral-800 rounded-full h-2 overflow-hidden">
                              <div
                                className={`h-full rounded-full ${colors[type] ?? "bg-neutral-400"}`}
                                style={{ width: `${(count / total) * 100}%` }}
                              />
                            </div>
                            <span className="text-xs font-semibold text-neutral-700 dark:text-neutral-300 w-8 text-right">{count}</span>
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </div>

                {/* Per-turn token chart */}
                <div className="bg-white dark:bg-black rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm overflow-hidden">
                  <div className="px-6 py-4 border-b border-neutral-200 dark:border-neutral-800">
                    <h3 className="font-semibold text-neutral-800 dark:text-neutral-200 text-sm">Token Usage Per AI Turn</h3>
                  </div>
                  <div className="p-6 overflow-x-auto">
                    <div className="flex items-end gap-2 min-w-max h-32">
                      {data.messages
                        .filter((m) => m.type === "ai")
                        .map((msg, i) => {
                          const kwu = msg.data?.additional_kwargs?.usage_metadata;
                          const meta = msg.data?.response_metadata;
                          const tok = kwu?.total_tokens ?? ((meta?.prompt_eval_count ?? 0) + (meta?.eval_count ?? 0));
                          const maxTok = Math.max(...data.messages
                            .filter((m) => m.type === "ai")
                            .map((m) => {
                              const k = m.data?.additional_kwargs?.usage_metadata;
                              const me = m.data?.response_metadata;
                              return k?.total_tokens ?? ((me?.prompt_eval_count ?? 0) + (me?.eval_count ?? 0));
                            }), 1);
                          const h = Math.round((tok / maxTok) * 100);
                          return (
                            <div key={i} className="flex flex-col items-center gap-1 group" title={`Turn ${i + 1}: ${tok.toLocaleString()} tokens`}>
                              <span className="text-xs text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity">{tok > 0 ? tok.toLocaleString() : ""}</span>
                              <div
                                className="w-5 rounded-t bg-blue-400 dark:bg-blue-600 hover:bg-blue-500 transition-colors cursor-default"
                                style={{ height: `${Math.max(h, tok > 0 ? 4 : 0)}%` }}
                              />
                            </div>
                          );
                        })}
                    </div>
                    <p className="text-xs text-neutral-400 mt-2 text-center">Each bar = one AI turn. Hover for token count.</p>
                  </div>
                </div>
              </div>
            )}

            {/* ══ RAW JSON VIEW ══ */}
            {viewMode === "raw" && (
              <div className="p-5 h-full flex flex-col">
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs text-neutral-500">Raw exported JSON ({data.messages.length} messages)</p>
                  <button
                    onClick={handleCopyRaw}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-300 rounded-lg transition-colors font-medium"
                  >
                    {copySuccess ? (
                      <><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg> {copySuccess}</>
                    ) : (
                      <><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy JSON</>
                    )}
                  </button>
                </div>
                <pre className="flex-1 overflow-auto text-xs font-mono bg-neutral-900 text-green-400 p-5 rounded-xl leading-relaxed">
                  {JSON.stringify(data.messages, null, 2)}
                </pre>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
};
