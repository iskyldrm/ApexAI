import { apiFetch } from "@/lib/api";
import type {
  AgentRole,
  AgentRun,
  AgentRunDetail,
  ConverseResponse,
} from "@/lib/agent-types";
import type {
  DLQEntry,
  ProcessEvent,
  ProcessRecord,
} from "@/lib/process-types";
import type {
  ActivityFeedEntry,
  Notification,
  Task,
  TaskComment,
} from "@/lib/task-types";
import type {
  ApiKey,
  AuditLogEntry,
  Integration,
  Invitation,
  Membership,
  Org,
  Setting,
  Team,
  User,
} from "@/lib/types";

export const auth = {
  register: (body: { email: string; password: string; full_name?: string }) =>
    apiFetch<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/register",
      { method: "POST", body: JSON.stringify(body) },
    ),
  login: (body: { email: string; password: string }) =>
    apiFetch<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify(body) },
    ),
  refresh: (refresh_token: string) =>
    apiFetch<{ access_token: string; refresh_token: string }>("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token }),
    }),
  logout: () => apiFetch("/auth/logout", { method: "POST" }),
  me: () => apiFetch<User>("/auth/me"),
};

export const orgs = {
  list: () => apiFetch<Org[]>("/orgs"),
  create: (body: { slug: string; name: string }) =>
    apiFetch<Org>("/orgs", { method: "POST", body: JSON.stringify(body) }),
  get: (id: string) => apiFetch<Org>(`/orgs/${id}`),
  listTeams: (orgId: string) => apiFetch<Team[]>(`/orgs/${orgId}/teams`),
  createTeam: (orgId: string, body: { slug: string; name: string; description?: string }) =>
    apiFetch<Team>(`/orgs/${orgId}/teams`, { method: "POST", body: JSON.stringify(body) }),
  listMembers: (orgId: string) => apiFetch<Membership[]>(`/orgs/${orgId}/members`),
};

export const invitations = {
  list: (orgId: string) => apiFetch<Invitation[]>(`/orgs/${orgId}/invitations`),
  create: (orgId: string, body: { email: string; role: string }) =>
    apiFetch<Invitation>(`/orgs/${orgId}/invitations`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  revoke: (orgId: string, invitationId: string) =>
    apiFetch(`/orgs/${orgId}/invitations/${invitationId}`, { method: "DELETE" }),
  accept: (token: string) =>
    apiFetch<{ org_id: string }>("/invitations/accept", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
};

export const keys = {
  listAi: (orgId?: string) =>
    apiFetch<ApiKey[]>(orgId ? `/keys/ai?org_id=${orgId}` : "/keys/ai"),
  createAi: (body: {
    provider: string;
    label: string;
    value: string;
    org_id?: string;
  }) =>
    apiFetch<ApiKey>("/keys/ai", { method: "POST", body: JSON.stringify(body) }),
  deleteAi: (id: string) => apiFetch(`/keys/ai/${id}`, { method: "DELETE" }),
  listIntegrations: (orgId?: string) =>
    apiFetch<Integration[]>(orgId ? `/keys/integrations?org_id=${orgId}` : "/keys/integrations"),
  createIntegration: (body: {
    integration_type: string;
    label: string;
    value: Record<string, unknown>;
    org_id?: string;
  }) =>
    apiFetch<Integration>("/keys/integrations", { method: "POST", body: JSON.stringify(body) }),
  deleteIntegration: (id: string) =>
    apiFetch(`/keys/integrations/${id}`, { method: "DELETE" }),
};

export const settings = {
  get: (key: string, scopeId?: string) =>
    apiFetch<Setting>(scopeId ? `/settings/${key}?scope_id=${scopeId}` : `/settings/${key}`),
  set: (
    key: string,
    body: { scope: string; scope_id?: string; value: unknown; enforced_by_admin?: boolean },
  ) =>
    apiFetch(`/settings/${key}`, { method: "PUT", body: JSON.stringify(body) }),
  delete: (key: string, scope: string, scopeId?: string) =>
    apiFetch(
      `/settings/${key}?scope=${scope}${scopeId ? `&scope_id=${scopeId}` : ""}`,
      { method: "DELETE" },
    ),
};

export const audit = {
  list: (params: {
    org_id?: string;
    action?: string;
    actor_id?: string;
    skip?: number;
    take?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) qs.set(k, String(v));
    }
    return apiFetch<{ items: AuditLogEntry[]; skip: number; take: number }>(
      `/audit-log${qs.toString() ? `?${qs.toString()}` : ""}`,
    );
  },
};

export const agent = {
  converse: (body: {
    role: AgentRole;
    prompt: string;
    work_dir: string;
    org_id?: string;
    max_steps?: number;
    model_override?: string;
  }) =>
    apiFetch<ConverseResponse>("/agent/converse", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listRuns: (params: { org_id?: string; role?: string; status?: string } = {}) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v) qs.set(k, v);
    }
    return apiFetch<{ items: AgentRun[] }>(
      `/agent/runs${qs.toString() ? `?${qs.toString()}` : ""}`,
    );
  },
  getRun: (id: string) => apiFetch<AgentRunDetail>(`/agent/runs/${id}`),
};

export const processes = {
  list: (status?: string) =>
    apiFetch<ProcessRecord[]>(`/processes${status ? `?status=${status}` : ""}`),
  get: (id: string) => apiFetch<ProcessRecord>(`/processes/${id}`),
  create: (body: {
    name: string;
    steps: { name: string; role: string; prompt: string }[];
    edges: { from: string; to: string }[];
    inputs?: Record<string, unknown>;
  }) =>
    apiFetch<ProcessRecord>("/processes", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  start: (id: string) =>
    apiFetch<ProcessRecord>(`/processes/${id}/start`, { method: "POST" }),
  cancel: (id: string) =>
    apiFetch<ProcessRecord>(`/processes/${id}/cancel`, { method: "POST" }),
  resume: (id: string) =>
    apiFetch<ProcessRecord>(`/processes/${id}/resume`, { method: "POST" }),
  events: (id: string) => apiFetch<ProcessEvent[]>(`/processes/${id}/events`),
  listDLQ: () => apiFetch<{ items: DLQEntry[] }>("/process-dlq"),
  replayDLQ: (id: string) =>
    apiFetch<{ replayed: boolean; step_id?: string }>(
      `/process-dlq/${id}/replay`,
      { method: "POST" },
    ),
};

export const tasks = {
  list: (params: { scope?: "mine" | "all"; status?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.scope) qs.set("scope", params.scope);
    if (params.status) qs.set("status", params.status);
    return apiFetch<Task[]>(`/tasks${qs.toString() ? `?${qs.toString()}` : ""}`);
  },
  get: (id: string) => apiFetch<Task>(`/tasks/${id}`),
  create: (body: {
    title: string;
    description?: string;
    assignee_id?: string;
    priority?: "low" | "medium" | "high" | "urgent";
  }) =>
    apiFetch<Task>("/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (id: string, body: Partial<Task>) =>
    apiFetch<Task>(`/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  transition: (id: string, to: string) =>
    apiFetch<Task>(`/tasks/${id}/transition`, {
      method: "POST",
      body: JSON.stringify({ to }),
    }),
  comments: (id: string) => apiFetch<TaskComment[]>(`/tasks/${id}/comments`),
  addComment: (id: string, body: string) =>
    apiFetch<TaskComment>(`/tasks/${id}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
};

export const notifications = {
  list: (unreadOnly = false) =>
    apiFetch<Notification[]>(
      `/notifications${unreadOnly ? "?unread_only=true" : ""}`,
    ),
  markAllRead: () =>
    apiFetch<{ marked_read: number }>("/notifications/read-all", {
      method: "POST",
    }),
  markRead: (id: string) =>
    apiFetch<{ id: string; read_at: string }>(
      `/notifications/${id}/read`,
      { method: "POST" },
    ),
};

export const activity = {
  feed: (orgId?: string) =>
    apiFetch<ActivityFeedEntry[]>(
      `/activity-feed${orgId ? `?org_id=${orgId}` : ""}`,
    ),
};
