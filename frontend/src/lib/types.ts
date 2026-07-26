export type User = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_platform_admin: boolean;
};

export type Org = {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended" | "archived";
  created_at: string;
};

export type Team = {
  id: string;
  org_id: string;
  slug: string;
  name: string;
  description: string | null;
  created_at: string;
};

export type Membership = {
  id: string;
  org_id: string;
  user_id: string;
  role: "owner" | "admin" | "manager" | "developer" | "viewer" | "tech_support";
  status: string;
  joined_at: string;
  email?: string;
  full_name?: string | null;
};

export type Invitation = {
  id: string;
  org_id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  token: string;
  expires_at: string;
  created_at: string;
};

export type ApiKey = {
  id: string;
  provider: string;
  label: string;
  is_active: boolean;
  org_id: string | null;
  last_used_at: string | null;
  created_at: string;
};

export type Integration = {
  id: string;
  integration_type: string;
  label: string;
  is_active: boolean;
  org_id: string | null;
  last_used_at: string | null;
  created_at: string;
};

export type AuditLogEntry = {
  id: string;
  actor_type: string;
  actor_id: string | null;
  actor_email_snapshot: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  org_id: string | null;
  ip_address: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

export type Setting = {
  scope: "user" | "team" | "org" | "platform";
  scope_id: string | null;
  key: string;
  value: unknown;
  enforced_by_admin: boolean;
  updated_by: string | null;
  updated_at: string;
};
