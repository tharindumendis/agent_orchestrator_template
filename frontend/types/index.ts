export type EventType = "tool_call" | "tool_result" | "token" | "done" | "error" | "session_ready";

export interface ChatEvent {
  type: EventType;
  name?: string;
  args?: any;
  content?: string;
}

export interface Message {
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

export interface ExportMessageData {
    content?: string;
    additional_kwargs?: any;
    response_metadata?: {
        model?: string;
        created_at?: string;
        total_duration?: number;
        prompt_eval_count?: number;
        eval_count?: number;
        done_reason?: string;
    };
    id?: string;
    tool_calls?: any[];
    name?: string;
    usage_metadata?: {
        input_tokens?: number;
        output_tokens?: number;
        total_tokens?: number;
    };
}

export interface ExportMessage {
    type: "system" | "human" | "ai" | "tool";
    data: ExportMessageData;
}
