export type ProcessStatus =
  | "draft"
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "stuck";

export type StepStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "retrying"
  | "skipped"
  | "cancelled"
  | "paused";

export type ProcessStep = {
  id: string;
  step_name: string;
  role: string;
  status: StepStatus;
  attempt: number;
  max_attempts: number;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  next_retry_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  agent_run_id: string | null;
};

export type ProcessRecord = {
  id: string;
  name: string;
  status: ProcessStatus;
  current_step: string | null;
  definition: { steps: unknown[]; edges: unknown[] };
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: ProcessStep[];
};

export type ProcessEvent = {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  actor_id: string | null;
  step_id: string | null;
  created_at: string;
};

export type DLQEntry = {
  id: string;
  process_id: string | null;
  step_id: string | null;
  reason: string | null;
  retry_count: number;
  failed_at: string | null;
  payload: Record<string, unknown>;
};
