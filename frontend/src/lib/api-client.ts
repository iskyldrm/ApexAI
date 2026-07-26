import { apiFetch } from "@/lib/api";
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
