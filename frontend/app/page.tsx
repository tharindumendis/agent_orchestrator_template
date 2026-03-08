"use client";

import React, { useState, useEffect, useRef } from "react";

// Types
type EventType = "tool_call" | "tool_result" | "token" | "done" | "error";

interface ChatEvent {
  type: EventType;
  name?: string;
  args?: any;
  content?: string;
}

interface Message {
  id: string;
  role: "user" | "agent";
  content: string;
  toolCalls?: {
    name: string;
    args: any;
    status: "running" | "done";
    result?: string;
  }[];
  isStreaming?: boolean;
}

const API_BASE = "http://localhost:8000";

export default function Home() {
  const [sessions, setSessions] = useState<string[]>([]);
  const [currentSession, setCurrentSession] = useState<string | null>(null);
  const [newSessionId, setNewSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  // New loading states
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(
    null,
  );
  const [isBackendProcessing, setIsBackendProcessing] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Fetch sessions on mount
  useEffect(() => {
    fetchSessions();
  }, []);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const fetchSessions = async () => {
    try {
      setIsLoadingSessions(true);
      const res = await fetch(`${API_BASE}/sessions`);
      const data = await res.json();
      if (data.sessions) {
        setSessions(data.sessions);
      }
    } catch (err) {
      console.error("Failed to fetch sessions", err);
    } finally {
      setIsLoadingSessions(false);
    }
  };

  const createSession = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!newSessionId.trim() || isCreatingSession) return;
    try {
      setIsCreatingSession(true);
      const res = await fetch(`${API_BASE}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: newSessionId.trim() }),
      });
      if (res.ok) {
        setCurrentSession(newSessionId.trim());
        setNewSessionId("");
        setMessages([]); // Fresh view since we don't have a fetch history endpoint
        await fetchSessions();
      }
    } catch (err) {
      console.error("Failed to create session", err);
    } finally {
      setIsCreatingSession(false);
    }
  };

  const joinSession = (sessionId: string) => {
    setCurrentSession(sessionId);
    setMessages([]); // Fresh view
  };

  const clearSessionBackend = async (sessionId: string) => {
    if (deletingSessionId) return;
    try {
      setDeletingSessionId(sessionId);
      await fetch(`${API_BASE}/sessions/${sessionId}`, { method: "DELETE" });
      if (currentSession === sessionId) {
        setCurrentSession(null);
        setMessages([]);
      }
      await fetchSessions();
    } catch (err) {
      console.error("Failed to clear session", err);
    } finally {
      setDeletingSessionId(null);
    }
  };

  const sendMessage = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputMessage.trim() || !currentSession || isStreaming) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputMessage.trim(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage("");
    setIsStreaming(true);

    // Initialise agent message placeholder
    const agentMsgId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      {
        id: agentMsgId,
        role: "agent",
        content: "",
        toolCalls: [],
        isStreaming: true,
      },
    ]);

    setIsBackendProcessing(true);

    try {
      const response = await fetch(
        `${API_BASE}/sessions/${currentSession}/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ message: userMsg.content }),
        },
      );

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split by SSE double newline boundary
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || ""; // Keep the incomplete part

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const dataStr = line.replace("data: ", "").trim();
              if (!dataStr) continue;
              const eventData = JSON.parse(dataStr) as ChatEvent;

              setMessages((prev) => {
                const newMessages = [...prev];
                const msgIndex = newMessages.findIndex(
                  (m) => m.id === agentMsgId,
                );
                if (msgIndex === -1) return newMessages;

                const msg = { ...newMessages[msgIndex] };
                msg.toolCalls = msg.toolCalls ? [...msg.toolCalls] : [];

                switch (eventData.type) {
                  case "tool_call":
                    setIsBackendProcessing(false);
                    msg.toolCalls.push({
                      name: eventData.name || "unknown_tool",
                      args: eventData.args,
                      status: "running",
                    });
                    break;
                  case "tool_result":
                    // Find the last tool call that is running and has the same name
                    const tcIndex = [...msg.toolCalls]
                      .reverse()
                      .findIndex(
                        (tc) =>
                          tc.name === eventData.name && tc.status === "running",
                      );
                    if (tcIndex !== -1) {
                      const actualIndex = msg.toolCalls.length - 1 - tcIndex;
                      msg.toolCalls[actualIndex] = {
                        ...msg.toolCalls[actualIndex],
                        status: "done",
                        result: eventData.content,
                      };
                    }
                    break;
                  case "token":
                    setIsBackendProcessing(false);
                    msg.content += eventData.content || "";
                    break;
                  case "done":
                    setIsBackendProcessing(false);
                    msg.isStreaming = false;
                    // API sends final answer in "done" event if you want to replace or ensure completeness
                    // BUT it seems the "token" stream handles it. We just close streaming state.
                    setIsStreaming(false);
                    break;
                  case "error":
                    setIsBackendProcessing(false);
                    msg.content += `\n\n[Error: ${eventData.content}]`;
                    msg.isStreaming = false;
                    setIsStreaming(false);
                    break;
                }

                newMessages[msgIndex] = msg;
                return newMessages;
              });
            } catch (err) {
              console.error("Parse error for line", line, err);
            }
          }
        }
      }
      setIsStreaming(false);
      setIsBackendProcessing(false);
    } catch (err) {
      console.error("Chat error", err);
      setIsStreaming(false);
      setIsBackendProcessing(false);
    }
  };

  return (
    <div className="flex h-screen w-full bg-white dark:bg-black text-black dark:text-white font-sans overflow-hidden selection:bg-blue-500 selection:text-white">
      {/* Sidebar - Pure black and white, sleek */}
      <div className="w-1/4 max-w-sm flex flex-col border-r border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950">
        <div className="p-6 pb-2">
          <h1 className="text-xl font-bold tracking-tight mb-1 flex items-center">
            <span className="w-3 h-3 bg-blue-600 rounded-full inline-block mr-3"></span>
            Agent Head
          </h1>
          <p className="text-sm text-neutral-500 mb-6">
            Autonomous Orchestrator
          </p>

          <form onSubmit={createSession} className="relative group">
            <input
              type="text"
              placeholder="Start new session..."
              value={newSessionId}
              onChange={(e) => setNewSessionId(e.target.value)}
              className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-lg px-4 py-3 pr-10 text-sm focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-all placeholder-neutral-400"
            />
            <button
              type="submit"
              disabled={!newSessionId.trim() || isCreatingSession}
              className="absolute right-2 top-2 bottom-2 aspect-square flex items-center justify-center text-neutral-400 hover:text-blue-600 hover:bg-neutral-100 dark:hover:bg-neutral-900 rounded-md transition-colors disabled:opacity-50"
            >
              {isCreatingSession ? (
                <svg
                  className="animate-spin h-4 w-4"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  ></circle>
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  ></path>
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              )}
            </button>
          </form>
        </div>

        <div className="flex-1 overflow-y-auto mt-4 px-4 pb-4">
          <div className="text-xs font-semibold text-neutral-400 tracking-wider uppercase mb-3 px-2">
            Active Sessions
          </div>
          {isLoadingSessions ? (
            <div className="text-sm text-neutral-500 italic px-2 flex items-center">
              <svg
                className="animate-spin h-3 w-3 mr-2"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
              Loading sessions...
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-sm text-neutral-500 italic px-2">
              No active sessions.
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((sid) => (
                <div
                  key={sid}
                  className={`group flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors border ${
                    currentSession === sid
                      ? "bg-blue-50/50 dark:bg-blue-900/10 border-blue-500/20 text-blue-700 dark:text-blue-400 font-medium"
                      : "border-transparent text-neutral-700 dark:text-neutral-300 hover:bg-white dark:hover:bg-black hover:border-neutral-200 dark:hover:border-neutral-800"
                  }`}
                  onClick={() => joinSession(sid)}
                >
                  <div className="flex items-center truncate">
                    <svg
                      className="w-4 h-4 mr-3 opacity-70"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <span className="truncate">{sid}</span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      clearSessionBackend(sid);
                    }}
                    disabled={deletingSessionId === sid}
                    className="opacity-0 group-hover:opacity-100 p-1.5 text-neutral-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded transition-all disabled:opacity-100"
                    title="Delete Session"
                  >
                    {deletingSessionId === sid ? (
                      <svg
                        className="animate-spin h-3.5 w-3.5 text-red-500"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                    ) : (
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M3 6h18"></path>
                        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
                        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path>
                      </svg>
                    )}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footnote */}
        <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 text-xs text-neutral-500 text-center">
          UniversAI Orchestrator
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col relative bg-white dark:bg-black">
        {!currentSession ? (
          <div className="flex-1 flex items-center justify-center flex-col text-neutral-400 space-y-4">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="48"
              height="48"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="opacity-20"
            >
              <path d="M2 12h4l3-9 5 18 3-9h5" />
            </svg>
            <p>Select or create a session to begin</p>
          </div>
        ) : (
          <>
            <div className="h-16 border-b border-neutral-200 dark:border-neutral-800 flex items-center px-6 justify-between flex-shrink-0 bg-white/80 dark:bg-black/80 backdrop-blur-md sticky top-0 z-10">
              <div className="flex items-center">
                <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse mr-3"></div>
                <span className="font-mono text-sm tracking-tight text-neutral-800 dark:text-neutral-200">
                  {currentSession}
                </span>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6 md:p-10 space-y-8 scroll-smooth">
              {messages.length === 0 && (
                <div className="text-center mt-20 text-neutral-400">
                  <p>Session ready. Send a message to start.</p>
                </div>
              )}
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`max-w-3xl mx-auto flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
                >
                  <div
                    className={`p-4 rounded-2xl max-w-full ${
                      msg.role === "user"
                        ? "bg-neutral-900 text-white dark:bg-white dark:text-black shadow-md rounded-br-sm"
                        : "bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-800 dark:text-neutral-200 rounded-bl-sm"
                    }`}
                  >
                    {/* Message Text Container */}
                    <div className="text-sm leading-relaxed whitespace-pre-wrap">
                      {msg.content ||
                        (msg.isStreaming && !msg.toolCalls?.length ? (
                          isBackendProcessing ? (
                            <span className="flex items-center text-neutral-500 italic">
                              <svg
                                className="animate-spin h-3.5 w-3.5 mr-2"
                                xmlns="http://www.w3.org/2000/svg"
                                fill="none"
                                viewBox="0 0 24 24"
                              >
                                <circle
                                  className="opacity-25"
                                  cx="12"
                                  cy="12"
                                  r="10"
                                  stroke="currentColor"
                                  strokeWidth="4"
                                ></circle>
                                <path
                                  className="opacity-75"
                                  fill="currentColor"
                                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                                ></path>
                              </svg>
                              Reasoning Backend...
                            </span>
                          ) : (
                            <span className="animate-pulse">...</span>
                          )
                        ) : null)}
                    </div>

                    {/* Tool Calls Container */}
                    {msg.role === "agent" &&
                      msg.toolCalls &&
                      msg.toolCalls.length > 0 && (
                        <div className="mt-4 space-y-2 border-t border-neutral-200 dark:border-neutral-800 pt-3">
                          {msg.toolCalls.map((tc, idx) => (
                            <div
                              key={idx}
                              className="bg-white dark:bg-black border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden text-xs"
                            >
                              <div className="px-3 py-2 bg-neutral-100 dark:bg-neutral-950 flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800">
                                <div className="flex items-center font-mono text-neutral-700 dark:text-neutral-300">
                                  <svg
                                    className="w-3 h-3 mr-2 opacity-50"
                                    xmlns="http://www.w3.org/2000/svg"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                  >
                                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                                  </svg>
                                  {tc.name}
                                </div>
                                <div className="flex items-center">
                                  {tc.status === "running" ? (
                                    <span className="flex items-center text-blue-600 dark:text-blue-500">
                                      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-ping mr-2"></span>
                                      running
                                    </span>
                                  ) : (
                                    <span className="text-neutral-400">
                                      done
                                    </span>
                                  )}
                                </div>
                              </div>

                              {/* Args View (Collapsible ideally, but statically shows for simplicity) */}
                              {tc.args && Object.keys(tc.args).length > 0 && (
                                <div className="p-3 bg-neutral-50 dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 overflow-x-auto">
                                  <pre className="text-neutral-600 dark:text-neutral-400 m-0">
                                    {JSON.stringify(tc.args, null, 2)}
                                  </pre>
                                </div>
                              )}

                              {/* Result View */}
                              {tc.result && (
                                <div className="p-3 bg-white dark:bg-black overflow-x-auto max-h-48 overflow-y-auto">
                                  <pre className="text-neutral-800 dark:text-neutral-200 m-0 text-xs">
                                    {tc.result}
                                  </pre>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            <div className="p-4 md:p-6 bg-white dark:bg-black border-t border-neutral-200 dark:border-neutral-800">
              <form
                onSubmit={sendMessage}
                className="max-w-4xl mx-auto relative group"
              >
                <input
                  type="text"
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  placeholder="Message the orchestrated agent..."
                  className="w-full bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-800 rounded-xl px-4 py-4 pr-14 text-sm focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-all shadow-sm placeholder-neutral-400"
                  disabled={isStreaming}
                />
                <button
                  type="submit"
                  disabled={
                    !inputMessage.trim() || isStreaming || isBackendProcessing
                  }
                  className="absolute right-2 top-2 bottom-2 aspect-square flex items-center justify-center bg-black dark:bg-white text-white dark:text-black rounded-lg transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 disabled:cursor-not-allowed"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                  </svg>
                </button>
              </form>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
