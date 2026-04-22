import React from "react";
import { Message } from "../types";

interface ChatAreaProps {
  currentSession: string | null;
  messages: Message[];
  isBackendProcessing: boolean;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  sendMessage: (e?: React.FormEvent) => void;
  inputMessage: string;
  setInputMessage: (val: string) => void;
  isStreaming: boolean;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  currentSession,
  messages,
  isBackendProcessing,
  messagesEndRef,
  sendMessage,
  inputMessage,
  setInputMessage,
  isStreaming
}) => {
  if (!currentSession) {
    return (
      <div className="flex-1 flex flex-col relative bg-white dark:bg-black">
        <div className="flex-1 flex items-center justify-center flex-col text-neutral-400 space-y-4">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="opacity-20"><path d="M2 12h4l3-9 5 18 3-9h5" /></svg>
          <p>Select or create a session to begin live chat</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col relative bg-white dark:bg-black">
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
          <div key={msg.id} className={`max-w-3xl mx-auto flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
            <div className={`p-4 rounded-2xl max-w-full ${msg.role === "user" ? "bg-neutral-900 text-white dark:bg-white dark:text-black shadow-md rounded-br-sm" : "bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 text-neutral-800 dark:text-neutral-200 rounded-bl-sm"}`}>
              <div className="text-sm leading-relaxed whitespace-pre-wrap">
                {msg.content || (msg.isStreaming && !msg.toolCalls?.length ? (
                  isBackendProcessing ? (
                    <span className="flex items-center text-neutral-500 italic">
                      <svg className="animate-spin h-3.5 w-3.5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      Reasoning Backend...
                    </span>
                  ) : <span className="animate-pulse">...</span>
                ) : null)}
              </div>

              {msg.role === "agent" && msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="mt-4 space-y-2 border-t border-neutral-200 dark:border-neutral-800 pt-3">
                  {msg.toolCalls.map((tc, idx) => (
                    <div key={idx} className="bg-white dark:bg-black border border-neutral-200 dark:border-neutral-800 rounded-lg overflow-hidden text-xs">
                      <div className="px-3 py-2 bg-neutral-100 dark:bg-neutral-950 flex items-center justify-between border-b border-neutral-200 dark:border-neutral-800">
                        <div className="flex items-center font-mono text-neutral-700 dark:text-neutral-300">
                          <svg className="w-3 h-3 mr-2 opacity-50" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg>
                          {tc.name}
                        </div>
                        <div className="flex items-center">
                          {tc.status === "running" ? (
                            <span className="flex items-center text-blue-600 dark:text-blue-500">
                              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-ping mr-2"></span>
                              running
                            </span>
                          ) : <span className="text-neutral-400">done</span>}
                        </div>
                      </div>
                      {tc.args && Object.keys(tc.args).length > 0 && (
                        <div className="p-3 bg-neutral-50 dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 overflow-x-auto">
                          <pre className="text-neutral-600 dark:text-neutral-400 m-0">{JSON.stringify(tc.args, null, 2)}</pre>
                        </div>
                      )}
                      {tc.result && (
                        <div className="p-3 bg-white dark:bg-black overflow-x-auto max-h-48 overflow-y-auto">
                          <pre className="text-neutral-800 dark:text-neutral-200 m-0 text-xs">{tc.result}</pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {/* We need to use generic ref casting since React typing can be annoying for forwarded refs down props without forwardRef */}
        <div ref={messagesEndRef as any} />
      </div>

      <div className="p-4 md:p-6 bg-white dark:bg-black border-t border-neutral-200 dark:border-neutral-800">
        <form onSubmit={sendMessage} className="max-w-4xl mx-auto relative group">
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder="Message the orchestrated agent..."
            className="w-full bg-white dark:bg-neutral-950 border border-neutral-300 dark:border-neutral-800 rounded-xl px-4 py-4 pr-14 text-sm focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-all shadow-sm placeholder-neutral-400 text-black dark:text-white"
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={!inputMessage.trim() || isStreaming || isBackendProcessing}
            className="absolute right-2 top-2 bottom-2 aspect-square flex items-center justify-center bg-black dark:bg-white text-white dark:text-black rounded-lg transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 disabled:cursor-not-allowed"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
          </button>
        </form>
      </div>
    </div>
  );
};
