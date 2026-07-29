export type TaskStatus = "todo" | "in_progress" | "review" | "done" | "cancelled";

export type TaskPriority = "low" | "medium" | "high" | "urgent";

export type Task = {
  id: string;
  org_id: string | null;
  user_id: string | null;
  assignee_id: string | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  source: "manual" | "agent_run" | "process";
  source_id: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type TaskComment = {
  id: string;
  task_id: string;
  author_id: string | null;
  author_type: "user" | "agent" | "system";
  body: string;
  created_at: string;
};

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
};

export type ActivityFeedEntry = {
  id: string;
  source: "task" | "process" | "audit";
  action: string;
  title: string;
  body: string | null;
  actor_id: string | null;
  actor_type: string | null;
  created_at: string;
  link: string | null;
};