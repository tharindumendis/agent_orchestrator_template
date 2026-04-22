import React from "react";

export type TabT = "chat" | "analytics";

interface SidebarProps {
  setShowSettings: (show: boolean) => void;
  activeTab: TabT;
  setActiveTab: (tab: TabT) => void;
  
  // Chat Tab Props
  newSessionId: string;
  setNewSessionId: (val: string) => void;
  isCreatingSession: boolean;
  createSession: (e?: React.FormEvent) => void;
  sessions: string[];
  isLoadingSessions: boolean;
  currentSession: string | null;
  joinSession: (sid: string) => void;
  clearSessionBackend: (sid: string) => void;
  deletingSessionId: string | null;

  // Analytics Tab Props
  historySessions: string[];
  isLoadingHistory: boolean;
  currentHistorySession: string | null;
  joinHistorySession: (sid: string) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  setShowSettings,
  activeTab,
  setActiveTab,
  
  newSessionId,
  setNewSessionId,
  isCreatingSession,
  createSession,
  sessions,
  isLoadingSessions,
  currentSession,
  joinSession,
  clearSessionBackend,
  deletingSessionId,

  historySessions,
  isLoadingHistory,
  currentHistorySession,
  joinHistorySession
}) => {
  return (
    <div className="w-1/4 max-w-sm flex flex-col border-r border-neutral-200 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-950">
      <div className="p-6 pb-2">
        <div className="flex justify-between items-center mb-1">
          <h1 className="text-xl font-bold tracking-tight flex items-center text-black dark:text-white">
            <span className="w-3 h-3 bg-blue-600 rounded-full inline-block mr-3"></span>
            Agent Head
          </h1>
          <button
            onClick={() => setShowSettings(true)}
            className="p-2 text-neutral-400 hover:text-blue-600 hover:bg-neutral-100 dark:hover:bg-neutral-900 rounded-md transition-colors"
            title="Settings"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
          </button>
        </div>
        <p className="text-sm text-neutral-500 mb-4">
          Autonomous Orchestrator
        </p>

        {/* Desktop Tabs */}
        <div className="flex space-x-1 bg-neutral-200/50 dark:bg-neutral-900/50 p-1 rounded-lg mb-6">
          <button
            onClick={() => setActiveTab("chat")}
            className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${
              activeTab === "chat"
                ? "bg-white dark:bg-neutral-800 text-blue-600 dark:text-blue-400 shadow-sm"
                : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
            }`}
          >
            Live Chat
          </button>
          <button
            onClick={() => setActiveTab("analytics")}
            className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${
              activeTab === "analytics"
                ? "bg-white dark:bg-neutral-800 text-blue-600 dark:text-blue-400 shadow-sm"
                : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
            }`}
          >
          History
          </button>
        </div>

        {activeTab === "chat" && (
          <form onSubmit={createSession} className="relative group">
            <input
              type="text"
              placeholder="Start new session..."
              value={newSessionId}
              onChange={(e) => setNewSessionId(e.target.value)}
              className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-lg px-4 py-3 pr-10 text-sm focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-all placeholder-neutral-400 text-black dark:text-white"
            />
            <button
              type="submit"
              disabled={!newSessionId.trim() || isCreatingSession}
              className="absolute right-2 top-2 bottom-2 aspect-square flex items-center justify-center text-neutral-400 hover:text-blue-600 hover:bg-neutral-100 dark:hover:bg-neutral-900 rounded-md transition-colors disabled:opacity-50"
            >
              {isCreatingSession ? (
                <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              )}
            </button>
          </form>
        )}
      </div>

      <div className="flex-1 overflow-y-auto mt-2 px-4 pb-4">
        {activeTab === "chat" ? (
          <>
            <div className="text-xs font-semibold text-neutral-400 tracking-wider uppercase mb-3 px-2">
              Memory Active
            </div>
            {isLoadingSessions ? (
              <div className="text-sm text-neutral-500 italic px-2 flex items-center">
                <svg className="animate-spin h-3 w-3 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                Loading...
              </div>
            ) : sessions.length === 0 ? (
              <div className="text-sm text-neutral-500 italic px-2">No active sessions.</div>
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
                      <svg className="w-4 h-4 mr-3 opacity-70" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                      <span className="truncate">{sid}</span>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        clearSessionBackend(sid);
                      }}
                      disabled={deletingSessionId === sid}
                      className="opacity-0 group-hover:opacity-100 p-1.5 text-neutral-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded transition-all disabled:opacity-100"
                      title="Clear Session"
                    >
                      {deletingSessionId === sid ? (
                        <svg className="animate-spin h-3.5 w-3.5 text-red-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      ) : (
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <div className="text-xs font-semibold text-neutral-400 tracking-wider uppercase mb-3 px-2">
              Database History
            </div>
            {isLoadingHistory ? (
              <div className="text-sm text-neutral-500 italic px-2 flex items-center">
                <svg className="animate-spin h-3 w-3 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                Loading...
              </div>
            ) : historySessions.length === 0 ? (
              <div className="text-sm text-neutral-500 italic px-2">No past sessions found.</div>
            ) : (
              <div className="space-y-1">
                {historySessions.map((sid) => (
                  <div
                    key={sid}
                    className={`group flex items-center p-3 rounded-lg cursor-pointer transition-colors border ${
                      currentHistorySession === sid
                        ? "bg-purple-50/50 dark:bg-purple-900/10 border-purple-500/20 text-purple-700 dark:text-purple-400 font-medium"
                        : "border-transparent text-neutral-700 dark:text-neutral-300 hover:bg-white dark:hover:bg-black hover:border-neutral-200 dark:hover:border-neutral-800"
                    }`}
                    onClick={() => joinHistorySession(sid)}
                  >
                    <svg className="w-4 h-4 mr-3 opacity-70" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/>
                      <polyline points="12 6 12 12 16 14"/>
                    </svg>
                    <span className="truncate">{sid}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="p-4 border-t border-neutral-200 dark:border-neutral-800 text-xs text-neutral-500 text-center">
        UniversAI Orchestrator
      </div>
    </div>
  );
};
