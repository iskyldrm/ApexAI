# Multi-Tenant Platform — F Design Spec

**Tarih:** 2026-07-24
**Yazar:** İsak Yıldırım
**Durum:** Onaylandı
**Proje:** ApexAI (yeni, mevcut ApexAITeam'den ayrı)

---

## 1. Amaç ve Kapsam

### 1.1 Amaç

ApexAI, **B2B SaaS** olarak sunulacak çok-kiracılı (multi-tenant) bir AI agent platformudur. Bu spec, **F: Multi-tenant Platform** alt-sistemini tanımlar — yani kimlik doğrulama, RBAC, anahtar kasası (key vault), entegrasyon credential'ları, ayarlar ve denetim kaydı (audit log).

F, diğer tüm alt-sistemlerin (A: Agent Runtime, B: Workflow, C: Task Tracking, D: Cost Optimization, E: Build/Test, G: Frontend) üzerine kurulacağı **iskelet**'tir.

### 1.2 Kapsam (In Scope)

- 4-seviyeli hiyerarşi: Platform → Org → Team → User
- Platform admin tarafından oluşturulan Org'lar
- Davet (invite) tabanlı kullanıcı katılımı
- Email + şifre authentication (OAuth yok)
- JWT (httpOnly cookie) ile session yönetimi
- Çift katmanlı RBAC: org-wide rol + team-level ek izinler
- AI API key vault (org-level + user-level BYOK, kullanıcı öncelikli)
- HashiCorp Vault ile secret şifreleme
- Entegrasyon credential'ları (GitHub App/OAuth/PAT, Telegram Bot, Azure SP)
- Hiyerarşik settings (platform → org → team → user)
- Audit log (yapılandırılmış, retention policy)
- REST API (FastAPI + OpenAPI)
- Next.js 14 frontend (App Router + shadcn)
- k8s deployment (Helm)

### 1.3 Kapsam Dışı (Out of Scope, İleride)

- **A: Agent Runtime** — AI loop, tool execution, model protokol abstraction (ayrı spec)
- **B: Workflow Orchestration** — state machine, queue, agent pipeline (ayrı spec)
- **C: Task Tracking Dashboard** — UI for tasks (şimdilik sadece API var)
- **D: Cost Optimization Cascade** — heuristic → semantic → LLM yönlendirme (API var, model routing F'in scope'unda)
- **E: Build/Test Pipeline** — sandbox runner, k8s pods (ayrı spec)
- **G: Frontend Pages** — Dashboard, Settings UI, AI chat UI (minimal pages F'te, kalan UI G'de)
- Gerçek email gönderimi (şimdilik DB log'a yazılır)
- OAuth/SSO (ileride)
- Billing/payments (ileride)

---

## 2. Mimari Genel Bakış

### 2.1 Katmanlar

```
┌──────────────────────────────────────────────────────────────────────┐
│                  Next.js 14 Frontend (App Router)                    │
│  shadcn/ui • Server Components • Auth Middleware • RSC Actions      │
└─────────────────────────────┬────────────────────────────────────────┘
                              │ HTTPS (JWT in httpOnly cookie)
┌─────────────────────────────▼────────────────────────────────────────┐
│                  FastAPI Backend (Python 3.12+)                      │
│  ┌────────────┐ ┌────────────┐ ┌─────────────┐ ┌──────────────────┐ │
│  │  Auth API  │ │  Org/Team  │ │  Key Vault  │ │  Audit Log API   │ │
│  └────────────┘ └────────────┘ └─────────────┘ └──────────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌─────────────┐                      │
│  │ RBAC Core  │ │  Settings  │ │ Invitations │                      │
│  └────────────┘ └────────────┘ └─────────────┘                      │
└─────────┬─────────────────────────┬─────────────────────┬────────────┘
          │                         │                     │
┌─────────▼───────────┐  ┌──────────▼──────────┐  ┌──────▼─────────────┐
│  PostgreSQL 16      │  │ HashiCorp Vault     │  │  Redis 7           │
│  + RLS policies     │  │ (KV v2 engine)      │  │  (sessions,        │
│  + SQLModel ORM     │  │                     │  │  rate limiting)    │
└─────────────────────┘  └─────────────────────┘  └────────────────────┘
```

### 2.2 Akışlar

**Login:** Browser → Next.js → FastAPI → verify → JWT (httpOnly cookie) → Next.js SSR auth check.

**AI Key Kullanımı:** AI call → resolve_ai_key() (user override > org default) → Vault read → API call → token_usage INSERT.

**Audit:** Her CRUD endpoint'i → audit() helper → audit_log INSERT.

---

## 3. Veritabanı Şeması

### 3.1 Tablolar (15 tablo)

#### 3.1.1 `platform_admins`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL |
| `password_hash` | VARCHAR(255) | NOT NULL (bcrypt) |
| `full_name` | VARCHAR(255) | NOT NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `last_login_at` | TIMESTAMPTZ | NULL |

#### 3.1.2 `users`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `email` | VARCHAR(255) | UNIQUE GLOBAL, NOT NULL |
| `password_hash` | VARCHAR(255) | NOT NULL (bcrypt) |
| `full_name` | VARCHAR(255) | NOT NULL |
| `is_active` | BOOLEAN | DEFAULT TRUE |
| `email_verified_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `last_login_at` | TIMESTAMPTZ | NULL |

Email global olarak unique — bir email tek bir user'a ait.

#### 3.1.3 `orgs`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `slug` | VARCHAR(64) | UNIQUE, NOT NULL |
| `name` | VARCHAR(255) | NOT NULL |
| `status` | VARCHAR(32) | DEFAULT 'active' (active/suspended/deleted) |
| `settings` | JSONB | DEFAULT '{}' |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `created_by` | UUID | FK → platform_admins |

#### 3.1.4 `teams`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → orgs, NOT NULL |
| `name` | VARCHAR(255) | NOT NULL |
| `slug` | VARCHAR(64) | NOT NULL |
| `description` | TEXT | NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `created_by` | UUID | FK → users |

UNIQUE (`org_id`, `slug`).

#### 3.1.5 `org_memberships`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → orgs, NOT NULL |
| `user_id` | UUID | FK → users, NOT NULL |
| `role` | VARCHAR(32) | NOT NULL (admin/manager/developer/analyst/tech_support/hr) |
| `status` | VARCHAR(32) | DEFAULT 'active' (active/pending/suspended) |
| `joined_at` | TIMESTAMPTZ | DEFAULT now() |
| `invited_by` | UUID | FK → users, NULL |

UNIQUE (`org_id`, `user_id`).

#### 3.1.6 `team_memberships`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `team_id` | UUID | FK → teams, NOT NULL |
| `user_id` | UUID | FK → users, NOT NULL |
| `team_role` | VARCHAR(32) | NOT NULL (lead/member/observer) |
| `added_at` | TIMESTAMPTZ | DEFAULT now() |
| `added_by` | UUID | FK → users, NULL |

UNIQUE (`team_id`, `user_id`).

#### 3.1.7 `invitations`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → orgs, NOT NULL |
| `email` | VARCHAR(255) | NOT NULL |
| `role` | VARCHAR(32) | NOT NULL |
| `team_ids` | JSONB | DEFAULT '[]' |
| `token_hash` | VARCHAR(255) | UNIQUE, NOT NULL (SHA256) |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `status` | VARCHAR(32) | DEFAULT 'pending' (pending/accepted/expired/revoked) |
| `invited_by` | UUID | FK → users, NOT NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

#### 3.1.8 `api_keys` (AI API key vault)
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → orgs, NULL |
| `user_id` | UUID | FK → users, NULL |
| `provider` | VARCHAR(32) | NOT NULL (openai/anthropic/google/ollama/custom) |
| `label` | VARCHAR(255) | NOT NULL |
| `vault_path` | VARCHAR(512) | NOT NULL |
| `is_active` | BOOLEAN | DEFAULT TRUE |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `created_by` | UUID | FK → users, NOT NULL |
| `last_used_at` | TIMESTAMPTZ | NULL |

CHECK: `(org_id IS NULL) != (user_id IS NULL)` — tam olarak biri dolu olmalı.

#### 3.1.9 `integration_credentials`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `org_id` | UUID | FK → orgs, NULL |
| `user_id` | UUID | FK → users, NULL |
| `integration_type` | VARCHAR(32) | NOT NULL (github_app/github_oauth/github_pat/telegram_bot/azure_sp) |
| `vault_path` | VARCHAR(512) | NOT NULL |
| `label` | VARCHAR(255) | NOT NULL |
| `is_active` | BOOLEAN | DEFAULT TRUE |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `last_used_at` | TIMESTAMPTZ | NULL |

CHECK: `(org_id IS NULL) != (user_id IS NULL)`.

#### 3.1.10 `audit_log`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `actor_type` | VARCHAR(32) | NOT NULL (user/platform_admin/system) |
| `actor_id` | UUID | NULL |
| `actor_email_snapshot` | VARCHAR(255) | NULL |
| `action` | VARCHAR(64) | NOT NULL |
| `target_type` | VARCHAR(32) | NULL |
| `target_id` | UUID | NULL |
| `org_id` | UUID | FK → orgs, NULL |
| `ip_address` | INET | NULL |
| `user_agent` | VARCHAR(512) | NULL |
| `metadata` | JSONB | DEFAULT '{}' |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

Index: (`org_id`, `created_at` DESC), (`actor_id`, `created_at` DESC), (`action`, `created_at`).

#### 3.1.11 `settings` (hiyerarşik)
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `scope` | VARCHAR(32) | NOT NULL (platform/org/user/team) |
| `scope_id` | UUID | NULL (platform'da NULL) |
| `key` | VARCHAR(128) | NOT NULL |
| `value` | JSONB | NOT NULL |
| `enforced_by_admin` | BOOLEAN | DEFAULT FALSE |
| `updated_at` | TIMESTAMPTZ | DEFAULT now() |
| `updated_by` | UUID | FK → users, NULL |

UNIQUE (`scope`, `scope_id`, `key`).

#### 3.1.12 `token_usage` (Cost tracking — D için temel)
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → users, NOT NULL |
| `org_id` | UUID | FK → orgs, NOT NULL |
| `api_key_id` | UUID | FK → api_keys, NOT NULL |
| `provider` | VARCHAR(32) | NOT NULL |
| `model` | VARCHAR(64) | NOT NULL |
| `input_tokens` | INTEGER | NOT NULL |
| `output_tokens` | INTEGER | NOT NULL |
| `cost_usd` | DECIMAL(10, 6) | NOT NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

Index: (`org_id`, `created_at` DESC), (`user_id`, `created_at` DESC), (`api_key_id`, `created_at` DESC).

#### 3.1.13 `password_reset_tokens`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → users, NOT NULL |
| `token_hash` | VARCHAR(255) | UNIQUE, NOT NULL |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `used_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

Not: `users.password_hash` değiştiğinde tüm unused token'lar implicit olarak iptal olur (uygulama katmanında kontrol).

#### 3.1.14 `email_verification_tokens`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → users, NOT NULL |
| `new_email` | VARCHAR(255) | NULL (email değişikliği için; NULL = mevcut email doğrula) |
| `token_hash` | VARCHAR(255) | UNIQUE, NOT NULL |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `used_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |

Org admin invite akışında user oluşturulurken `email_verified_at` otomatik set edilir, o yüzden yeni user kayıtlarında bu tablo kullanılmaz. Email değişikliği senaryosunda kullanılır.

#### 3.1.15 `refresh_tokens`
| Kolon | Tip | Kısıt |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID | FK → users, NOT NULL |
| `token_hash` | VARCHAR(255) | UNIQUE, NOT NULL |
| `expires_at` | TIMESTAMPTZ | NOT NULL |
| `revoked_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | DEFAULT now() |
| `ip_address` | INET | NULL |

### 3.2 Row-Level Security (RLS) Politikaları

Her tablo için RLS policy'leri yazılır. Amaç: DB seviyesinde `org_id` filtresini zorlamak, uygulama katmanı hatasını engellemek.

**Örnek — `org_memberships`:**
```sql
ALTER TABLE org_memberships ENABLE ROW LEVEL SECURITY;

-- Kullanıcı kendi üyeliklerini görebilir
CREATE POLICY user_sees_own ON org_memberships
  FOR SELECT USING (user_id = current_setting('app.current_user_id', true)::uuid);

-- Org admin kendi org'undaki tüm üyelikleri görebilir
CREATE POLICY org_admin_sees_all ON org_memberships
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM org_memberships om
      WHERE om.org_id = org_memberships.org_id
        AND om.user_id = current_setting('app.current_user_id', true)::uuid
        AND om.role = 'admin' AND om.status = 'active'
    )
  );

-- Platform admin her şeyi görebilir
CREATE POLICY platform_admin_sees_all ON org_memberships
  FOR ALL USING (current_setting('app.is_platform_admin', true)::boolean = true);
```

**Tüm tablolara uygulanacak kurallar:**
- `orgs` → platform admin tüm, user sadece üye olduğu org'ları
- `teams` → org üyesi tüm takımları görür
- `users` → kendi profili + aynı org'daki diğer user'lar
- `org_memberships` → yukarıdaki
- `team_memberships` → kendi + takımdaki diğerleri + org admin
- `api_keys` → owner (user_id) + org admin (org_id)
- `integration_credentials` → owner + org admin
- `audit_log` → org admin + tech_support + platform admin
- `settings` → scope kuralı (user kendi, org admin org-level, user kendi user-level)
- `token_usage` → user kendi + org admin (org-level aggregate)

### 3.3 Indexes

```sql
-- Unique
CREATE UNIQUE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_orgs_slug ON orgs(slug);
CREATE UNIQUE INDEX idx_teams_org_slug ON teams(org_id, slug);
CREATE UNIQUE INDEX idx_org_memberships_org_user ON org_memberships(org_id, user_id);
CREATE UNIQUE INDEX idx_team_memberships_team_user ON team_memberships(team_id, user_id);
CREATE UNIQUE INDEX idx_settings_scope_key ON settings(scope, scope_id, key);

-- Lookup
CREATE INDEX idx_org_memberships_user ON org_memberships(user_id);
CREATE INDEX idx_team_memberships_user ON team_memberships(user_id);
CREATE INDEX idx_api_keys_org_provider ON api_keys(org_id, provider, is_active);
CREATE INDEX idx_api_keys_user_provider ON api_keys(user_id, provider, is_active);
CREATE INDEX idx_audit_log_org_created ON audit_log(org_id, created_at DESC);
CREATE INDEX idx_audit_log_actor_created ON audit_log(actor_id, created_at DESC);
CREATE INDEX idx_audit_log_action_created ON audit_log(action, created_at);
CREATE INDEX idx_token_usage_org_created ON token_usage(org_id, created_at DESC);
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at DESC);
CREATE INDEX idx_invitations_token_hash ON invitations(token_hash);
CREATE INDEX idx_password_reset_token_hash ON password_reset_tokens(token_hash);
CREATE INDEX idx_email_verification_token_hash ON email_verification_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
```

---

## 4. Authentication

### 4.1 Akış

**Login:**
1. Browser → `POST /api/v1/auth/login` (email, password)
2. FastAPI: bcrypt verify
3. JWT access (15 min) + refresh (30 gün) üretilir
4. Refresh token DB'ye hash'li yazılır
5. Her ikisi httpOnly + Secure + SameSite=Lax cookie olarak set edilir
6. Audit log'a `auth.login` yazılır

**Session:**
- Next.js SSR her sayfada cookie'den JWT okur, doğrular
- Token expire olduysa `/api/v1/auth/refresh` ile yenilenir
- Frontend API client: tüm isteklerde `credentials: 'include'`

**Logout:**
- `POST /api/v1/auth/logout` → refresh token revoke + clear cookies
- Access token JTI Redis blacklist'e eklenir (kalan TTL kadar)

### 4.2 JWT Yapısı

```json
{
  "sub": "user_uuid",
  "email": "ali@acme.com",
  "is_platform_admin": false,
  "orgs": [
    {"org_id": "uuid", "role": "developer", "teams": ["uuid1", "uuid2"]},
    {"org_id": "uuid2", "role": "manager", "teams": []}
  ],
  "iat": 1234567890,
  "exp": 1234571490,
  "jti": "unique_token_id"
}
```

**Active Org Context:** Birden fazla org'a üye kullanıcılar için aktif org `X-Org-Id` header'ı veya `active_org_id` cookie ile belirtilir. Backend bu context'i request-scoped olarak set eder, RLS policy'leri bu değeri kullanır.

### 4.3 Invite Akışı

1. Org admin/HR → `POST /api/v1/orgs/{id}/invitations` (email, role, team_ids)
2. Backend: 32-byte rastgele token üretir, SHA256 hash'ini DB'ye yazar
3. Plain token URL'ye konur: `https://app.example.com/invitations/accept?token=<plain>`
4. Şimdilik email_log tablosuna yazılır (ileride SMTP)
5. Kullanıcı linke tıklar → `/invitations/accept` sayfası → `POST /api/v1/invitations/accept` (token)
6. Backend: hash verify + expiry check + user'a password set sayfası
7. User password set eder → user + org_membership + team_memberships INSERT
8. Audit log: `user.joined`

### 4.4 Password Reset

1. `POST /api/v1/auth/forgot-password` (email) → token üretilir, DB'ye yazılır, email_log'a düşer
2. User linke tıklar → `/reset-password?token=...`
3. `POST /api/v1/auth/reset-password` (token, new_password) → bcrypt hash update, token used_at set

### 4.5 Email Verification

Yeni user veya yeni email için `email_verification_tokens` tablosu kullanılır. Login olmadan önce email_verified_at set edilmiş olmalı (org admin invite akışında auto-verify edilebilir).

---

## 5. RBAC — Permission-Based

### 5.1 Permission Enum

```python
class Permission(str, Enum):
    # Org
    ORG_MANAGE = "org:manage"
    ORG_VIEW = "org:view"
    
    # Users
    USERS_INVITE = "users:invite"
    USERS_MANAGE = "users:manage"
    USERS_VIEW = "users:view"
    
    # Teams
    TEAMS_MANAGE = "teams:manage"
    TEAMS_VIEW = "teams:view"
    
    # Tasks (sub-system A bridge)
    TASKS_CREATE = "tasks:create"
    TASKS_VIEW_ALL = "tasks:view:all"
    TASKS_VIEW_TEAM = "tasks:view:team"
    TASKS_VIEW_OWN = "tasks:view:own"
    TASKS_APPROVE = "tasks:approve"
    
    # AI Keys
    KEYS_MANAGE_ORG = "keys:manage:org"
    KEYS_MANAGE_OWN = "keys:manage:own"
    KEYS_VIEW_ALL = "keys:view:all"
    KEYS_VIEW_OWN = "keys:view:own"
    
    # Integrations
    INTEGRATIONS_MANAGE_ORG = "integrations:manage:org"
    INTEGRATIONS_MANAGE_OWN = "integrations:manage:own"
    INTEGRATIONS_VIEW = "integrations:view"
    
    # Audit
    AUDIT_VIEW = "audit:view"
    
    # Settings
    SETTINGS_MANAGE_ORG = "settings:manage:org"
    SETTINGS_MANAGE_OWN = "settings:manage:own"
```

### 5.2 Rol → Permission Mapping

| Permission | Admin | Manager | Developer | Analyst | Tech Support | HR |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| ORG_MANAGE | ✅ | | | | | |
| ORG_VIEW | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| USERS_INVITE | ✅ | | | | | ✅ |
| USERS_MANAGE | ✅ | | | | | ✅ |
| USERS_VIEW | ✅ | ✅ | | | ✅ | ✅ |
| TEAMS_MANAGE | ✅ | | | | | |
| TEAMS_VIEW | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TASKS_CREATE | ✅ | ✅ | ✅ | ✅ | | |
| TASKS_VIEW_ALL | ✅ | ✅ | | ✅ | | |
| TASKS_VIEW_TEAM | ✅ | ✅ | ✅ | | ✅ | ✅ |
| TASKS_VIEW_OWN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| TASKS_APPROVE | ✅ | ✅ | | ✅ | | |
| KEYS_MANAGE_ORG | ✅ | | | | | |
| KEYS_MANAGE_OWN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| KEYS_VIEW_ALL | ✅ | | | | | |
| KEYS_VIEW_OWN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| INTEGRATIONS_MANAGE_ORG | ✅ | | | | ✅ | |
| INTEGRATIONS_MANAGE_OWN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| INTEGRATIONS_VIEW | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AUDIT_VIEW | ✅ | | | | ✅ | ✅ |
| SETTINGS_MANAGE_ORG | ✅ | | | | | |
| SETTINGS_MANAGE_OWN | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### 5.3 Team-Level Extra Permissions

`team_role` alanı, org-wide role'e ek izinler verir:

| Team Role | Ekstra Permission |
|---|---|
| `lead` | `TASKS_VIEW_TEAM` + `TASKS_APPROVE` (sadece o takım için) |
| `member` | `TASKS_VIEW_TEAM` (sadece o takım için) |
| `observer` | Read-only |

**Çift katmanlı kontrol:** Org-wide role her zaman geçerli; team_role ekstra team-scoped izinler ekler. Örnek: Developer + team_role=lead → Developer'ın tüm izinleri + o takım için onay yetkisi.

### 5.4 FastAPI Decorator'lar

```python
@requires_permission(Permission.TASKS_CREATE)
async def create_task(...): ...

@requires_org_role(["admin", "manager"])
async def invite_user(...): ...

@requires_team_role(["lead"])
async def approve_task(team_id: UUID, ...): ...

@requires_any(Permission.TASKS_VIEW_ALL, Permission.TASKS_VIEW_TEAM)
async def list_tasks(...): ...

# Kombine: org role + own resource
@requires_self_or_permission(Permission.USERS_MANAGE, "user_id")
async def update_user(user_id: UUID, ...): ...
```

**Check sırası:**
1. JWT verify → actor + org context
2. Active org context, RLS session variable set
3. Permission decorator explicit check
4. Team-level ekstra kontrol

### 5.5 Multi-Org User Org Switching

User birden fazla org'a üye olabilir. UI "Active Org" seçicisi. Backend her istekte `X-Org-Id` header alır, JWT'deki `orgs` listesinde doğrular, RLS session variable'a set eder.

---

## 6. Key Vault

### 6.1 Mimari

**Metadata PostgreSQL'de, secret'lar HashiCorp Vault'ta.**

```
PostgreSQL                       HashiCorp Vault
(api_keys table)                 (KV v2 engine)
                                 
id: abc-123       ────────▶      secret/data/orgs/<org_id>/ai-keys/<key_id>
provider: openai                {
vault_path: orgs/...              value: sk-abc123xyz
label: "Production OpenAI"      }
last_used_at: 2026-07-24...
```

### 6.2 Vault Layout

```
secret/data/
├── orgs/
│   └── <org_id>/
│       ├── ai-keys/<key_id>           # value: api_key_string
│       └── integrations/
│           ├── github-app/<id>        # value: {app_id, installation_id, private_key}
│           ├── telegram-bot/<id>      # value: {bot_token, chat_id}
│           └── azure-sp/<id>          # value: {tenant_id, client_id, client_secret}
└── users/
    └── <user_id>/
        ├── ai-keys/<key_id>           # BYOK
        └── integrations/<id>          # user-level integrations
```

### 6.3 Resolve Key Logic

```python
async def resolve_ai_key(
    org_id: UUID, 
    user_id: UUID, 
    provider: str
) -> str:
    """User key varsa onu kullan, yoksa org key'ine düş."""
    
    # 1. Önce user-level key
    user_key = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    if user_key:
        return await vault.read(user_key.vault_path)
    
    # 2. Org-level key
    org_key = await db.execute(
        select(ApiKey).where(
            ApiKey.org_id == org_id,
            ApiKey.user_id.is_(None),
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    if org_key:
        return await vault.read(org_key.vault_path)
    
    raise NoApiKeyError(f"No active {provider} key for org={org_id} user={user_id}")
```

### 6.4 Vault Client

```python
import hvac

class VaultClient:
    def __init__(self, url: str, token: str):
        self._client = hvac.AsyncClient(url=url, token=token)
    
    async def read(self, path: str) -> dict:
        response = await self._client.secrets.kv.v2.read_secret_version(path=path)
        return response["data"]["data"]
    
    async def write(self, path: str, data: dict) -> None:
        await self._client.secrets.kv.v2.create_or_update_secret(
            path=path, secret=data
        )
    
    async def delete(self, path: str) -> None:
        await self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path
        )
```

**Kubernetes Auth:** Vault token pod'a K8s ServiceAccount üzerinden otomatik inject edilir. Kısa ömürlü (1 saat), rolling restart'ta yenilenir.

### 6.5 Integration Modelleri

**GitHub App (per-org):**
- Org admin → install GitHub App → callback installation_id alır
- Vault: `{app_id, installation_id, private_key}` saklanır
- API call'larında JWT (RS256) üretilir, installation token exchange edilir

**GitHub OAuth (per-user):**
- User → GitHub OAuth → callback code → exchange for token
- Vault: `{access_token, refresh_token, scope}` saklanır
- Token expire olursa refresh

**GitHub PAT (per-user veya per-org):**
- User/org admin PAT'ı manuel girer
- Vault: `{token}` saklanır

**Telegram Bot (per-org):**
- BotFather'dan alınan token + chat_id
- Vault: `{bot_token, chat_id}`
- SendMessage API kullanılır

**Azure SP (per-org):**
- Service principal credentials
- Vault: `{tenant_id, client_id, client_secret}`
- AKS/ARM/ACR erişimi için

### 6.6 Token Usage Tracking

Her AI API call sonrası:

```python
await db.execute(insert(TokenUsage).values(
    user_id=current_user.id,
    org_id=active_org_id,
    api_key_id=key_id,
    provider=provider,
    model=model,
    input_tokens=resp.usage.input_tokens,
    output_tokens=resp.usage.output_tokens,
    cost_usd=calculate_cost(provider, model, input, output),
))
```

Bu tablo sub-system D (Cost Optimization) için temel olacak.

---

## 7. Settings — Hiyerarşik

### 7.1 Override Chain

```
user → team → org → platform (default)
```

`get_setting(key, scope, scope_id)` lookup sırası:

1. user scope, scope_id=user_id
2. team scope, scope_id=team_id (her team ayrı lookup)
3. org scope, scope_id=org_id
4. platform scope, scope_id=NULL
5. Default değer (kod)

İlk bulunan döner. Bulunamazsa default.

### 7.2 Admin Override

`enforced_by_admin = TRUE` olan setting, user tarafından override edilemez. Örnek: org admin "Tüm developer'lar için default_model'i gpt-4o yap" dediğinde, developer'ın kendi default_model setting'i ignore edilir.

### 7.3 Örnek Settings

```json
{
  "default_ai_provider": "google",
  "default_ai_model": "gemini-2.5-pro",
  "default_approval_mode": "manual",
  "auto_create_pr": true,
  "code_review_enabled": true,
  "notification_channels": ["telegram"],
  "telegram_chat_id": "-1001234567890",
  "timezone": "Europe/Istanbul",
  "theme": "dark"
}
```

---

## 8. Audit Log

### 8.1 Loglanan Olaylar

**Auth (11 events):**
- `auth.login`, `auth.login_failed`, `auth.logout`, `auth.token_refresh`
- `auth.password_reset_requested`, `auth.password_reset_completed`
- `auth.email_verification_requested`, `auth.email_verified`
- `auth.account_locked`, `auth.account_unlocked`

**Org (5):**
- `org.created`, `org.updated`, `org.suspended`, `org.reactivated`, `org.deleted`

**Users (8):**
- `user.created`, `user.invited`, `user.invitation_accepted`
- `user.role_changed`, `user.deactivated`, `user.reactivated`
- `user.password_changed`, `user.deleted`

**Teams (6):**
- `team.created`, `team.updated`, `team.deleted`
- `team.member_added`, `team.member_removed`, `team.member_role_changed`

**Keys (5):**
- `key.created`, `key.used`, `key.label_updated`, `key.deactivated`, `key.deleted`

**Integrations (6):**
- `integration.created`, `integration.connected`
- `integration.test_succeeded`, `integration.test_failed`
- `integration.deactivated`, `integration.deleted`

**Settings (3):**
- `settings.updated`, `settings.enforced_by_admin`, `settings.deleted`

**Toplam:** ~44 olay tipi.

### 8.2 Audit Helper

```python
async def audit(
    action: str,
    actor: User | PlatformAdmin | None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    org_id: UUID | None = None,
    metadata: dict | None = None,
    request: Request | None = None,
):
    await db.execute(insert(AuditLog).values(
        actor_type=type(actor).__name__.lower() if actor else "system",
        actor_id=actor.id if actor else None,
        actor_email_snapshot=actor.email if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        org_id=org_id,
        ip_address=request.client.host if request else None,
        user_agent=request.headers.get("user-agent") if request else None,
        metadata=metadata or {},
    ))
```

### 8.3 Retention

- 90 gün hot (PostgreSQL)
- 1 yıl cold (S3 veya equivalent)
- Partitioning: pg_partman ile aylık partition

### 8.4 Read Access

- Org admin: `org_id = own_org_id` (RLS)
- Tech Support: `audit:view` permission
- Platform admin: hepsini görür
- API: `GET /api/v1/audit-log?org_id=...&action=...&start_date=...&end_date=...`

---

## 9. API Surface (REST v1)

### 9.1 Auth

```
POST   /api/v1/auth/login                  # Public
POST   /api/v1/auth/refresh                # Public
POST   /api/v1/auth/logout                 # Auth
POST   /api/v1/auth/forgot-password        # Public
POST   /api/v1/auth/reset-password         # Public
GET    /api/v1/auth/me                     # Auth
POST   /api/v1/auth/verify-email           # Public
```

### 9.2 Platform Admin

```
POST   /api/v1/platform/orgs               # Platform admin
GET    /api/v1/platform/orgs               # Platform admin
GET    /api/v1/platform/stats              # Platform admin
GET    /api/v1/platform/admins             # Platform admin
POST   /api/v1/platform/admins             # Platform admin
```

### 9.3 Orgs

```
GET    /api/v1/orgs/{id}                   # Org member
PATCH  /api/v1/orgs/{id}                   # Org admin
DELETE /api/v1/orgs/{id}                   # Platform admin
```

### 9.4 Users & Invitations

```
POST   /api/v1/orgs/{id}/invitations       # Org admin, HR
GET    /api/v1/orgs/{id}/invitations       # Org admin
DELETE /api/v1/invitations/{id}            # Org admin
POST   /api/v1/invitations/accept          # Public
GET    /api/v1/orgs/{id}/users             # Org admin, HR
PATCH  /api/v1/orgs/{id}/users/{uid}       # Org admin, HR
DELETE /api/v1/orgs/{id}/users/{uid}       # Org admin, HR
```

### 9.5 Teams

```
POST   /api/v1/orgs/{id}/teams             # Org admin
GET    /api/v1/orgs/{id}/teams             # Org member
PATCH  /api/v1/teams/{id}                  # Org admin, team lead
DELETE /api/v1/teams/{id}                  # Org admin
POST   /api/v1/teams/{id}/members          # Org admin, team lead
DELETE /api/v1/teams/{id}/members/{uid}    # Org admin, team lead
```

### 9.6 Key Vault

```
POST   /api/v1/orgs/{id}/keys/ai           # Org admin
GET    /api/v1/orgs/{id}/keys/ai           # Org admin
GET    /api/v1/users/me/keys/ai            # Self
PATCH  /api/v1/keys/ai/{id}                # Owner or org admin
DELETE /api/v1/keys/ai/{id}                # Owner or org admin
```

### 9.7 Integrations

```
POST   /api/v1/orgs/{id}/integrations      # Org admin, tech_support
GET    /api/v1/orgs/{id}/integrations      # Org member
GET    /api/v1/users/me/integrations       # Self
POST   /api/v1/integrations/{id}/test      # Owner or org admin
DELETE /api/v1/integrations/{id}           # Owner or org admin
```

### 9.8 Audit & Settings

```
GET    /api/v1/audit-log                   # Org admin, tech_support, platform admin
GET    /api/v1/settings/{key}              # Anyone
PUT    /api/v1/settings/{key}              # Owner (or admin override)
DELETE /api/v1/settings/{key}              # Owner (or admin override)
```

---

## 10. Frontend (Next.js 14)

### 10.1 Pages (Minimal, F için)

```
/login                                   # Login
/forgot-password                         # Password reset request
/reset-password?token=...                # Password reset
/invitations/accept?token=...            # Invite acceptance
/dashboard                               # Empty placeholder (sub-system C)
/orgs                                    # Org list (platform admin)
/orgs/{id}                               # Org detail
/orgs/{id}/teams                         # Team list
/orgs/{id}/users                         # User list
/orgs/{id}/keys                          # AI key vault
/orgs/{id}/integrations                  # Integrations
/orgs/{id}/audit                         # Audit log
/settings                                # User settings
/settings/{key}                          # Setting detail
```

### 10.2 Tech Stack

- Next.js 14 App Router
- TypeScript
- shadcn/ui (Radix primitives + Tailwind)
- React Query (server state)
- Zustand (client state)
- Zod (validation)
- Auth: httpOnly cookie + JWT, server-side auth check in middleware

### 10.3 Auth Middleware

```typescript
// middleware.ts
export async function middleware(req: NextRequest) {
  const token = req.cookies.get('access_token')?.value;
  if (!token && !isPublicPath(req.nextUrl.pathname)) {
    return NextResponse.redirect(new URL('/login', req.url));
  }
  // ... verify JWT
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|.*\\.png$).*)'],
};
```

---

## 11. Deployment

### 11.1 Repo Yapısı

```
apexai/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI entry
│   │   ├── config.py                # Settings
│   │   ├── db.py                    # SQLModel session
│   │   ├── deps.py                  # Dependencies (auth, db, etc.)
│   │   ├── enums.py                 # Permission, Role, etc.
│   │   ├── core/
│   │   │   ├── security.py          # JWT, password hashing
│   │   │   ├── rbac.py              # Permission decorators
│   │   │   ├── audit.py             # Audit helper
│   │   │   └── vault.py             # Vault client
│   │   ├── models/                  # SQLModel models
│   │   ├── schemas/                 # Pydantic schemas (request/response)
│   │   ├── api/v1/
│   │   │   ├── auth.py
│   │   │   ├── orgs.py
│   │   │   ├── teams.py
│   │   │   ├── users.py
│   │   │   ├── invitations.py
│   │   │   ├── keys.py
│   │   │   ├── integrations.py
│   │   │   ├── audit.py
│   │   │   └── settings.py
│   │   └── alembic/                 # Migrations
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── alembic.ini
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   ├── package.json
│   ├── next.config.js
│   └── Dockerfile
├── deploy/
│   └── helm/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── fastapi-deployment.yaml
│           ├── fastapi-service.yaml
│           ├── fastapi-ingress.yaml
│           ├── nextjs-deployment.yaml
│           ├── nextjs-service.yaml
│           ├── nextjs-ingress.yaml
│           ├── postgres-statefulset.yaml
│           ├── vault-statefulset.yaml
│           ├── redis-deployment.yaml
│           ├── configmap.yaml
│           ├── secret.yaml
│           └── serviceaccount.yaml
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-07-24-multi-tenant-platform-design.md
├── .github/
│   └── workflows/
│       ├── backend-ci.yaml
│       ├── frontend-ci.yaml
│       └── helm-deploy.yaml
├── Makefile
└── README.md
```

### 11.2 k8s Resources

**FastAPI Deployment:**
- 3 replicas
- Resources: 100m–1Gi CPU, 256Mi–1Gi memory
- Health: `/health`, `/ready`
- Env: DB, Vault, Redis, JWT secret (k8s Secret)
- ServiceAccount: `apex-fastapi` (Vault K8s auth)

**Next.js Deployment:**
- 2 replicas
- Resources: 50m–500m CPU, 128Mi–512Mi memory
- Health: `/api/health`
- Build-time env: `NEXT_PUBLIC_API_URL`

**PostgreSQL StatefulSet:**
- 1 replica (production'da HA için Patroni/Citus)
- PVC: 100Gi
- Image: postgres:16

**Vault StatefulSet:**
- 1 replica (HA mode production'da Raft)
- PVC: 10Gi
- Image: hashicorp/vault:1.17

**Redis Deployment:**
- 1 replica
- PVC: 5Gi (AOF persistence)
- Image: redis:7-alpine

### 11.3 CI/CD

**GitHub Actions:**
- `backend-ci.yaml`: PR → pytest + ruff + black + mypy + alembic upgrade test
- `frontend-ci.yaml`: PR → tsc + eslint + build
- `helm-deploy.yaml`: main → build images → push → helm upgrade

### 11.4 Observability

- Structured logs (JSON, stdout)
- Prometheus metrics (FastAPI middleware)
- OpenTelemetry tracing (sub-system A'da)
- Grafana dashboards (deployment sonrası)

---

## 12. Tech Stack Özeti

| Katman | Teknoloji |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, shadcn/ui, Tailwind, React Query, Zustand, Zod |
| Backend | FastAPI 0.115+, Python 3.12, SQLModel 0.0.22+, Pydantic v2, Alembic, hvac |
| Database | PostgreSQL 16 (RLS enabled), pg_partman, Redis 7 |
| Secrets | HashiCorp Vault 1.17+ (KV v2, K8s auth) |
| Auth | JWT (HS256, httpOnly cookie), bcrypt, refresh tokens |
| Background | ARQ (Redis-based async, lightweight) |
| Email | Şimdilik log (production'da SMTP/SES) |
| Deployment | Kubernetes, Helm, GitHub Actions |
| Observability | Structured logs, Prometheus, OpenTelemetry |

---

## 13. Açık Sorular / Gelecek Alt-Sistemler

Bu spec sadece F'i kapsar. Diğer alt-sistemler ayrı brainstorming turlarıyla tasarlanacak:

- **A: Agent Runtime** — Python'da AI loop, tool execution, model protocol abstraction (OpenAI/Anthropic), token tracking, conversation memory, single-vs-multi-agent kararı
- **B: Workflow Orchestration** — State machine, queue (ARQ vs Celery vs custom), worker pool, retry/DLQ
- **C: Task Tracking Dashboard** — Azure/GitHub Boards tarzı UI, hangi agent ne yaptı timeline
- **D: Cost Optimization** — heuristic → semantic → LightGBM → LLM cascade, başarısız task'larda pahalı API çağrısı yapmama
- **E: Build/Test Pipeline** — Çok-dilli (React Native, Node, Python, Go, Rust, Java) sandbox runner, k8s pod template'leri
- **G: Frontend Pages** — Agent UI, task tracker, chat, agent flow görselleştirme

**F içindeki açık sorular (bilerek ertelendi):**
- 2FA (TOTP) — gelecekte opsiyonel
- Session timeout policy — şimdilik standart (15dk access, 30 gün refresh)
- Vault unseal prosedürü — production deployment'ta netleşecek
- Backup stratejisi (PostgreSQL, Vault) — production'da pgbackrest + vault snapshots

---

## 14. Karar Geçmişi (Brainstorming Log)

| # | Karar | Seçim | Neden |
|---|---|---|---|
| 1 | Alt-sistem | F: Multi-tenant Platform | Diğer tüm alt-sistemler buna bağlı |
| 2 | Tenant hiyerarşisi | 4 seviye (Platform → Org → Team → User) | B2B SaaS, takım-bazlı çalışma |
| 3 | Tenant oluşturma | Platform admin (sen) | B2B SaaS, kontrol sende |
| 4 | Rol kapsamı | Çift katmanlı (org rol + team izinleri) | En esnek, lead/member/observer |
| 5 | Authentication | Email + şifre (OAuth yok) | MVP için yeterli |
| 6 | Veri izolasyonu | Tek DB, ortak şema, `org_id` filtresi | Modern SaaS standardı, RLS ile enforce |
| 7 | AI key sahiplik | İkisi de, user öncelikli | Şirket + BYOK, esnek |
| 8 | Backend framework | FastAPI | Async, AI SDK'ları native, OpenAPI docs |
| 9 | Frontend framework | Next.js 14 App Router | shadcn varsayılan kombinasyonu, SSR |
| 10 | Entegrasyon sahipliği | Karışık (per-org + per-user optional) | Hem default hem override |
| 11 | Encryption | HashiCorp Vault | Audit trail, dynamic secrets, KV v2 |
| 12 | DB / ORM | PostgreSQL + SQLModel | FastAPI native, Pydantic + SQLAlchemy birleşimi |
| 13 | Email | Şimdilik log (DB tablosuna yaz) | Geliştirme aşaması, sonra SMTP |

---

*Bu spec, brainstorming süreciyle oluşturulmuş ve kullanıcı tarafından onaylanmıştır. Implementation planı ayrı bir writing-plans turunda hazırlanacak.*
