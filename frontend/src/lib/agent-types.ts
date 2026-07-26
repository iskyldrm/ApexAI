export type AgentRole =
  | "MGR"
  | "ANL"
  | "DEV_FE"
  | "DEV_BE"
  | "QA"
  | "PM"
  | "SUP";

export type ConverseResponse = {
  success: boolean;
  agent_run_id: string;
  conversation_id: string;
  summary: string;
  steps: number;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  intentional_files: string[];
  error: string | null;
  finish_reason:
    | "finished"
    | "max_steps"
    | "safety_tripped"
    | "budget_exceeded"
    | "error";
};

export type AgentRun = {
  id: string;
  conversation_id: string;
  role: AgentRole;
  model: string | null;
  status: string;
  steps: number;
  input_tokens: number;
  output_tokens: number;
  duration_ms: number | null;
  started_at: string | null;
};

export type AgentRunDetail = AgentRun & {
  error: string | null;
  finished_at: string | null;
  messages: Array<{
    id: string;
    role: "user" | "assistant" | "tool" | "system";
    content: string;
    tool_calls: unknown[] | null;
    tool_result: unknown | null;
    tool_name: string | null;
    tool_call_id: string | null;
    sequence: number;
    input_tokens: number;
    output_tokens: number;
  }>;
};
