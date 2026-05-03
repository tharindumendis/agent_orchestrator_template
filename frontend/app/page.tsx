"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Message, ChatEvent } from "../types";
import { SettingsModal } from "../components/SettingsModal";
import { Sidebar, TabT } from "../components/Sidebar";
import { ChatArea } from "../components/ChatArea";
import { AnalyticsArea } from "../components/AnalyticsArea";

export default function Home() {
  // App Config Settings
  const [apiBaseUrl, setApiBaseUrl] = useState("http://localhost:8000");
  const [showSettings, setShowSettings] = useState(false);
  const [settingsUrlInput, setSettingsUrlInput] = useState("http://localhost:8000");
  const [healthStatus, setHealthStatus] = useState<"idle" | "testing" | "success" | "error">("idle");

  // Navigation
  const [activeTab, setActiveTab] = useState<TabT>("chat");

  // Chat State
  const [sessions, setSessions] = useState<string[]>([]);
  const [currentSession, setCurrentSession] = useState<string | null>(null);
  const [newSessionId, setNewSessionId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  // Chat View loading states
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [isBackendProcessing, setIsBackendProcessing] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // WebSocket ref — one persistent socket per active session
  const wsRef = useRef<WebSocket | null>(null);
  // Track the agent message ID currently being streamed
  const streamingMsgIdRef = useRef<string | null>(null);

  // Analytics State
  const [historySessions, setHistorySessions] = useState<string[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [currentHistorySession, setCurrentHistorySession] = useState<string | null>(null);

  // On mount
  useEffect(() => {
    const savedUrl = localStorage.getItem("apiBaseUrl");
    if (savedUrl) {
      setApiBaseUrl(savedUrl);
      setSettingsUrlInput(savedUrl);
    }
  }, []);

  // Sync sessions based on tab
  useEffect(() => {
    if (activeTab === "chat") {
      fetchSessions();
    } else {
      fetchHistorySessions();
    }
  }, [activeTab, apiBaseUrl]);

  // Scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── WebSocket helpers ──────────────────────────────────────────────────────

  const disconnectWs = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null; // suppress auto-reconnect
      wsRef.current.close();
      wsRef.current = null;
    }
    streamingMsgIdRef.current = null;
  }, []);

  const connectWs = useCallback(
    (sessionId: string) => {
      disconnectWs();

      const wsBase = apiBaseUrl.replace(/^http/, "ws");
      const ws = new WebSocket(`${wsBase}/ws/${encodeURIComponent(sessionId)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log(`[WS] Connected to session '${sessionId}'`);
      };

      ws.onmessage = (event) => {
        let eventData: ChatEvent & { session_id?: string; message_count?: number };
        try {
          eventData = JSON.parse(event.data);
        } catch {
          console.error("[WS] Failed to parse message", event.data);
          return;
        }

        if (eventData.type === "session_ready") {
          // Server confirmed session is booted — nothing extra to do for now
          return;
        }

        const agentMsgId = streamingMsgIdRef.current;
        if (!agentMsgId) return;

        setMessages((prev) => {
          const newMessages = [...prev];
          const msgIndex = newMessages.findIndex((m) => m.id === agentMsgId);
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
            case "tool_result": {
              const tcIndex = [...msg.toolCalls]
                .reverse()
                .findIndex(
                  (tc) => tc.name === eventData.name && tc.status === "running"
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
            }
            case "token":
              setIsBackendProcessing(false);
              msg.content += eventData.content || "";
              break;
            case "done":
              setIsBackendProcessing(false);
              msg.isStreaming = false;
              setIsStreaming(false);
              streamingMsgIdRef.current = null;
              break;
            case "error":
              setIsBackendProcessing(false);
              msg.content += `\n\n[Error: ${eventData.content}]`;
              msg.isStreaming = false;
              setIsStreaming(false);
              streamingMsgIdRef.current = null;
              break;
          }

          newMessages[msgIndex] = msg;
          return newMessages;
        });
      };

      ws.onerror = (err) => {
        console.error("[WS] Socket error", err);
        setIsStreaming(false);
        setIsBackendProcessing(false);
        streamingMsgIdRef.current = null;
      };

      ws.onclose = (e) => {
        console.log(`[WS] Disconnected (code ${e.code})`);
        if (wsRef.current === ws) wsRef.current = null;
        setIsStreaming(false);
        setIsBackendProcessing(false);
        streamingMsgIdRef.current = null;
      };
    },
    [apiBaseUrl, disconnectWs]
  );

  // Reconnect whenever apiBaseUrl changes while a session is active
  useEffect(() => {
    if (currentSession) {
      connectWs(currentSession);
    }
    return () => {
      disconnectWs();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSession, apiBaseUrl]);

  // --- Network / Settings Methods ---
  const testConnection = async () => {
    setHealthStatus("testing");
    try {
      const res = await fetch(`${settingsUrlInput}/health`);
      if (res.ok) {
        const data = await res.json();
        if (data.status === "ok") {
          setHealthStatus("success");
          return;
        }
      }
      setHealthStatus("error");
    } catch {
      setHealthStatus("error");
    }
  };

  const saveSettings = () => {
    setApiBaseUrl(settingsUrlInput);
    localStorage.setItem("apiBaseUrl", settingsUrlInput);
    setShowSettings(false);
    setHealthStatus("idle");
  };

  // --- Live Chat Methods ---
  const fetchSessions = async () => {
    try {
      setIsLoadingSessions(true);
      const res = await fetch(`${apiBaseUrl}/sessions`);
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
      const res = await fetch(`${apiBaseUrl}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: newSessionId.trim() }),
      });
      if (res.ok) {
        setCurrentSession(newSessionId.trim());
        setNewSessionId("");
        setMessages([]); 
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
    setMessages([]);
  };

  const clearSessionBackend = async (sessionId: string) => {
    if (deletingSessionId) return;
    try {
      setDeletingSessionId(sessionId);
      await fetch(`${apiBaseUrl}/sessions/${sessionId}`, { method: "DELETE" });
      if (currentSession === sessionId) {
        disconnectWs();
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

  const sendMessage = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!inputMessage.trim() || !currentSession || isStreaming) return;

    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn("[WS] Socket not ready — reconnecting...");
      connectWs(currentSession);
      // Give it a tick then retry
      setTimeout(() => sendMessage(), 300);
      return;
    }

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: inputMessage.trim(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage("");
    setIsStreaming(true);

    const agentMsgId = (Date.now() + 1).toString();
    streamingMsgIdRef.current = agentMsgId;
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

    ws.send(JSON.stringify({ message: userMsg.content }));
  };

  // --- Analytics Methods ---
  const fetchHistorySessions = async () => {
    try {
      setIsLoadingHistory(true);
      const res = await fetch(`${apiBaseUrl}/history/sessions`);
      if (!res.ok) throw new Error("Failed");
      const data = await res.json();
      if (data.sessions) {
        setHistorySessions(data.sessions);
      }
    } catch (err) {
      console.error("Failed to fetch history sessions", err);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const joinHistorySession = (sid: string) => {
    setCurrentHistorySession(sid);
  };

  return (
    <div className="flex h-screen w-full bg-white dark:bg-black text-black dark:text-white font-sans overflow-hidden selection:bg-blue-500 selection:text-white">
      <Sidebar
        setShowSettings={setShowSettings}
        activeTab={activeTab}
        setActiveTab={setActiveTab}

        newSessionId={newSessionId}
        setNewSessionId={setNewSessionId}
        isCreatingSession={isCreatingSession}
        createSession={createSession}
        sessions={sessions}
        isLoadingSessions={isLoadingSessions}
        currentSession={currentSession}
        joinSession={joinSession}
        clearSessionBackend={clearSessionBackend}
        deletingSessionId={deletingSessionId}

        historySessions={historySessions}
        isLoadingHistory={isLoadingHistory}
        currentHistorySession={currentHistorySession}
        joinHistorySession={joinHistorySession}
        fetchHistorySessions={fetchHistorySessions}
      />

      {activeTab === "chat" ? (
        <ChatArea
          currentSession={currentSession}
          messages={messages}
          isBackendProcessing={isBackendProcessing}
          messagesEndRef={messagesEndRef}
          sendMessage={sendMessage}
          inputMessage={inputMessage}
          setInputMessage={setInputMessage}
          isStreaming={isStreaming}
        />
      ) : (
        <AnalyticsArea 
           currentHistorySession={currentHistorySession} 
           apiBaseUrl={apiBaseUrl} 
        />
      )}

      <SettingsModal
        showSettings={showSettings}
        setShowSettings={setShowSettings}
        apiBaseUrl={apiBaseUrl}
        settingsUrlInput={settingsUrlInput}
        setSettingsUrlInput={setSettingsUrlInput}
        healthStatus={healthStatus}
        setHealthStatus={setHealthStatus}
        testConnection={testConnection}
        saveSettings={saveSettings}
      />
    </div>
  );
}
