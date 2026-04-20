import React, { useState, useEffect } from "react";
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

const formatDuration = (ms: number) => {
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(2)}s`;
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s.toFixed(1)}s`;
};

const extractDurationMs = (duration: number | undefined) => {
  if (!duration) return 0;
  // If > 1e8, it's highly likely nanoseconds from Ollama
  // Convert ns to ms by dividing by 1,000,000
  if (duration > 1e8) {
    return duration / 1e6;
  }
  // Otherwise assume it's already ms or sec(if small)
  return duration;
};

export const AnalyticsArea: React.FC<AnalyticsAreaProps> = ({
  currentHistorySession,
  apiBaseUrl,
}) => {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentHistorySession) {
      setData(null);
      return;
    }

    const fetchData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `${apiBaseUrl}/history/sessions/${currentHistorySession}/export`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch session history");
        }
        const exportData = (await response.json()) as ExportMessage[];
        
        let totalAiTokens = 0;
        let inputTokens = 0;
        let outputTokens = 0;
        let totalDurationMs = 0;
        let toolCallsCount = 0;

        exportData.forEach((msg) => {
          if (msg.type === "ai" && msg.data?.response_metadata) {
            const meta = msg.data.response_metadata;
            let usageInput = 0;
            let usageOutput = 0;

            if (msg.data.additional_kwargs && msg.data.additional_kwargs.usage_metadata) {
              const u = msg.data.additional_kwargs.usage_metadata;
              totalAiTokens += u.total_tokens || 0;
              usageInput = u.input_tokens || 0;
              usageOutput = u.output_tokens || 0;
              inputTokens += usageInput;
              outputTokens += usageOutput;
            } else if (meta.eval_count || meta.prompt_eval_count) {
              usageInput = meta.prompt_eval_count || 0;
              usageOutput = meta.eval_count || 0;
              totalAiTokens += usageInput + usageOutput;
              inputTokens += usageInput;
              outputTokens += usageOutput;
            }
            if (meta.total_duration) {
              totalDurationMs += extractDurationMs(meta.total_duration);
            }
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
          totalDurationMs: totalDurationMs,
          toolCallsCount,
          messages: exportData,
        });

      } catch (err: any) {
        setError(err.message || "Unknown error occurred");
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [currentHistorySession, apiBaseUrl]);

  if (!currentHistorySession) {
    return (
      <div className="flex-1 flex flex-col relative bg-white dark:bg-black">
        <div className="flex-1 flex items-center justify-center flex-col text-neutral-400 space-y-4">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="opacity-20"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          <p>Select a historical session to view analytics</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col relative bg-neutral-50 dark:bg-neutral-950 overflow-hidden">
      <div className="h-16 border-b border-neutral-200 dark:border-neutral-800 flex items-center px-6 justify-between flex-shrink-0 bg-white/80 dark:bg-black/80 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center">
          <svg className="w-5 h-5 text-purple-600 dark:text-purple-500 mr-3" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          <span className="font-semibold text-lg tracking-tight text-neutral-800 dark:text-neutral-200">
            {currentHistorySession} <span className="text-sm font-normal text-neutral-500 ml-2">Analytics</span>
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 md:p-10">
        {isLoading ? (
          <div className="flex justify-center items-center h-40">
            <svg className="animate-spin h-8 w-8 text-neutral-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          </div>
        ) : error ? (
          <div className="max-w-2xl mx-auto p-6 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-xl border border-red-200 dark:border-red-800/50">
            <p className="font-semibold mb-2">Error loading session</p>
            <p className="text-sm">{error}</p>
          </div>
        ) : data ? (
          <div className="max-w-5xl mx-auto space-y-8">
            {/* Stats Overview */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-black p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm flex flex-col justify-between">
                <div className="text-neutral-500 text-xs font-semibold uppercase tracking-wider mb-2">Total Turns</div>
                <div className="text-3xl font-bold text-neutral-800 dark:text-neutral-100">{data.totalMessages}</div>
              </div>
              <div className="bg-white dark:bg-black p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm flex flex-col justify-between">
                <div className="text-neutral-500 text-xs font-semibold uppercase tracking-wider mb-2">Est. Tokens</div>
                <div className="text-xs text-neutral-500 mt-2 flex justify-between border-t border-neutral-100 dark:border-neutral-900 pt-2">
                   <span title="Input Tokens">📥 In: {data.inputTokens.toLocaleString()}</span>
                   <span title="Output Tokens">📤 Out: {data.outputTokens.toLocaleString()}</span>
                </div>
                <div className="text-xs text-neutral-500 mt-2 flex justify-between border-t border-neutral-100 dark:border-neutral-900 pt-2">
                </div>
                <div className="flex items-end gap-2">
                   <div className="text-3xl font-bold text-neutral-800 dark:text-neutral-100">{data.totalAiTokens.toLocaleString()}</div>
                </div>
              </div>
              <div className="bg-white dark:bg-black p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm flex flex-col justify-between">
                <div className="text-neutral-500 text-xs font-semibold uppercase tracking-wider mb-2">Tool Calls</div>
                <div className="text-3xl font-bold text-blue-600 dark:text-blue-500">{data.toolCallsCount}</div>
              </div>
              <div className="bg-white dark:bg-black p-5 rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm flex flex-col justify-between">
                <div className="text-neutral-500 text-xs font-semibold uppercase tracking-wider mb-2">AI Processing Time</div>
                <div className="text-3xl font-bold text-neutral-800 dark:text-neutral-100">{formatDuration(data.totalDurationMs)}</div>
              </div>
            </div>

            {/* Timeline */}
            <div className="bg-white dark:bg-black rounded-2xl border border-neutral-200 dark:border-neutral-800 shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-neutral-200 dark:border-neutral-800 bg-neutral-50/50 dark:bg-neutral-900/50">
                <h3 className="font-semibold text-neutral-800 dark:text-neutral-200 text-sm">Interaction Timeline</h3>
              </div>
              <div className="p-6">
                <div className="space-y-6">
                  {data.messages.map((msg, i) => {
                    const meta = msg.data?.response_metadata;
                    const kwUsage = msg.data?.additional_kwargs?.usage_metadata;
                    const durationMs = meta?.total_duration ? extractDurationMs(meta.total_duration) : 0;
                    const inTokens = kwUsage?.input_tokens ?? meta?.prompt_eval_count ?? 0;
                    const outTokens = kwUsage?.output_tokens ?? meta?.eval_count ?? 0;
                    const totTokens = kwUsage?.total_tokens ?? (inTokens + outTokens);

                    return (
                    <div key={i} className="flex gap-4 group">
                      <div className="flex flex-col items-center mt-1">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
                          msg.type === "human" ? "bg-neutral-800 text-white dark:bg-neutral-200 dark:text-black" :
                          msg.type === "ai" ? "bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400" :
                          msg.type === "tool" ? "bg-purple-100 text-purple-600 dark:bg-purple-900/40 dark:text-purple-400" :
                          "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400"
                        }`}>
                          {msg.type === "human" && <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>}
                          {msg.type === "ai" && <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"></rect><circle cx="12" cy="5" r="2"></circle><path d="M12 7v4"></path><line x1="8" y1="16" x2="8" y2="16"></line><line x1="16" y1="16" x2="16" y2="16"></line></svg>}
                          {msg.type === "tool" && <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>}
                          {msg.type === "system" && <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>}
                        </div>
                        {i < data.messages.length - 1 && (
                          <div className="w-0.5 h-full bg-neutral-200 dark:bg-neutral-800 my-2 group-hover:bg-blue-200 dark:group-hover:bg-blue-900 transition-colors"></div>
                        )}
                      </div>
                      
                      <div className="flex-1 pb-6 pt-1">
                        <div className="flex items-baseline mb-2">
                          <span className="font-semibold text-sm capitalize mr-2 text-neutral-800 dark:text-neutral-200">
                            {msg.type === "ai" ? "Agent" : msg.type === "human" ? "User" : msg.type}
                          </span>
                          {msg.type === "tool" && msg.data.name && (
                            <span className="font-mono text-xs px-2 py-0.5 bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-300 rounded">
                              {msg.data.name}
                            </span>
                          )}
                          {msg.type === "ai" && meta?.model && (
                            <span className="font-mono text-xs px-2 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 rounded">
                              {meta.model}
                            </span>
                          )}
                        </div>
                        
                        <div className="prose prose-sm dark:prose-invert max-w-none break-words leading-relaxed text-neutral-700 dark:text-neutral-300">
                          {msg.data.content ? (
                             typeof msg.data.content === 'string' ? msg.data.content : JSON.stringify(msg.data.content)
                          ) : (
                            <span className="italic text-neutral-400">No text content</span>
                          )}
                        </div>

                        {msg.data.tool_calls && msg.data.tool_calls.length > 0 && (
                          <div className="mt-3 space-y-2">
                            {msg.data.tool_calls.map((tc: any, tci: number) => (
                              <div key={tci} className="bg-neutral-50 dark:bg-neutral-900/50 border border-neutral-200 dark:border-neutral-800 p-3 rounded-lg overflow-x-auto text-xs font-mono">
                                <div className="text-purple-600 dark:text-purple-400 mb-1 font-semibold">{tc.name}</div>
                                <div className="text-neutral-600 dark:text-neutral-400">{JSON.stringify(tc.args, null, 2)}</div>
                              </div>
                            ))}
                          </div>
                        )}

                        {msg.type === "ai" && meta && (totTokens > 0 || durationMs > 0) && (
                          <div className="mt-4 flex flex-wrap gap-3 text-xs font-medium">
                            {durationMs > 0 && (
                              <div className="flex items-center text-neutral-500 bg-neutral-100 dark:bg-neutral-800/50 px-2 py-1 rounded">
                                <svg className="w-3.5 h-3.5 mr-1 text-neutral-400" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                                {formatDuration(durationMs)}
                              </div>
                            )}
                            {totTokens > 0 && (
                              <div className="flex items-center text-neutral-500 bg-neutral-100 dark:bg-neutral-800/50 px-2 py-1 rounded">
                                <span className="mr-3" title="Total Tokens">📊 {totTokens.toLocaleString()}</span>
                                <span className="text-blue-500 dark:text-blue-400 mr-2" title="Input Tokens">📥 {inTokens.toLocaleString()}</span>
                                <span className="text-green-600 dark:text-green-500" title="Output Tokens">📤 {outTokens.toLocaleString()}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )})}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};
