import React from "react";

interface SettingsModalProps {
  showSettings: boolean;
  setShowSettings: (show: boolean) => void;
  apiBaseUrl: string;
  settingsUrlInput: string;
  setSettingsUrlInput: (url: string) => void;
  healthStatus: "idle" | "testing" | "success" | "error";
  setHealthStatus: (status: "idle" | "testing" | "success" | "error") => void;
  testConnection: () => void;
  saveSettings: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  showSettings,
  setShowSettings,
  apiBaseUrl,
  settingsUrlInput,
  setSettingsUrlInput,
  healthStatus,
  setHealthStatus,
  testConnection,
  saveSettings,
}) => {
  if (!showSettings) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-neutral-900 rounded-xl max-w-md w-full p-6 shadow-2xl border border-neutral-200 dark:border-neutral-800">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold">Settings</h2>
          <button
            onClick={() => {
              setShowSettings(false);
              setSettingsUrlInput(apiBaseUrl);
              setHealthStatus("idle");
            }}
            className="text-neutral-400 hover:text-black dark:hover:text-white transition-colors"
            title="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-1">
              Agent Head Base URL
            </label>
            <input
              type="text"
              value={settingsUrlInput}
              onChange={(e) => {
                setSettingsUrlInput(e.target.value);
                setHealthStatus("idle");
              }}
              className="w-full bg-transparent border border-neutral-300 dark:border-neutral-700 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-all text-black dark:text-white"
            />
          </div>
          
          <div className="flex items-center justify-between">
            <button
              onClick={testConnection}
              disabled={healthStatus === "testing" || !settingsUrlInput.trim()}
              className="px-4 py-2 text-sm bg-neutral-100 dark:bg-neutral-800 hover:bg-neutral-200 dark:hover:bg-neutral-700 rounded-lg transition-colors flex items-center disabled:opacity-50 text-neutral-800 dark:text-neutral-200"
              type="button"
            >
              {healthStatus === "testing" ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-neutral-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  Testing...
                </>
              ) : "Test Connection"}
            </button>
            
            {healthStatus === "success" && (
              <span className="text-green-600 dark:text-green-500 text-sm flex items-center">
                <svg className="w-4 h-4 mr-1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                API Online
              </span>
            )}
            {healthStatus === "error" && (
              <span className="text-red-600 dark:text-red-500 text-sm flex items-center">
                <svg className="w-4 h-4 mr-1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                Connection Failed
              </span>
            )}
          </div>
        </div>

        <div className="mt-8 flex justify-end space-x-3">
          <button
            onClick={() => {
              setShowSettings(false);
              setSettingsUrlInput(apiBaseUrl);
              setHealthStatus("idle");
            }}
            className="px-4 py-2 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 rounded-lg transition-colors"
            type="button"
          >
            Cancel
          </button>
          <button
            onClick={saveSettings}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
            type="button"
          >
            Save Base URL
          </button>
        </div>
      </div>
    </div>
  );
};
