# Database schema

Shurly keeps everything in one PostgreSQL database. The diagram below is generated from the SQLAlchemy models in
`server/core/models/`, so it shows what the code expects; the schema itself is created and changed by the Alembic
migrations in `server/migrations/versions/`, which the app runs when it starts.

## The tables

- **`users`** — accounts: people, and service accounts (`kind`) with the person responsible for them. Holds the
  password and API key hashes. **`user_profiles`** — a person's names, country, time zone and avatar, one row per user.
- **`user_identities`** — an account at an identity provider (Google), by the provider's subject.
  **`google_auth_states`** and **`login_codes`** — a Google sign-in in progress, and the one-time code the callback
  hands to the frontend. Both short-lived and stored hashed.
- **`organizations`** and **`organization_members`** — the organization (its logo, the Google domain that joins it)
  and each member's role: owner, admin or member.
- **`domains`** — the hostnames short links are served from; one is the default.
- **`urls`** — the short links: standard, custom or campaign, with their validity window, visit cap, previews and who
  made them (a person, or a service account and its token). A short code is unique per domain.
- **`visits`** — one row per click on a short link, with the anonymized IP, place, user agent and the bot and pixel
  flags. **`orphan_visits`** — requests for short codes that don't exist.
- **`campaigns`** — a CSV-driven batch of personalized links (`urls.campaign_id`).
- **`tags`**, **`url_tags`** and **`campaign_tags`** — labels, and which links and campaigns carry them.
- **`redirect_rules`** — a link's conditional redirects, evaluated by priority before the default destination.
- **`service_tokens`** — a service account's tokens, kept as hashes, with renewal and revocation.
- **`waitlist_entries`** — people outside Griddo who asked for Shurly.
- **`rate_limits`** — rate-limit counters, one row per key, shared by every task.
- **`mcp_oauth_store`** — what the MCP's OAuth proxy keeps between requests (client registrations, codes, tokens),
  as key-value rows per collection.

## Regenerating the diagram

After changing a model (and writing its migration):

```bash
uv run python scripts/generate_schema_diagram.py           # rewrites the block below
uv run python scripts/generate_schema_diagram.py --check   # exits 1 if it's out of date
```

`tests/test_schema_diagram.py` fails while the block differs from what the models generate. Don't edit the block by
hand.

Reading it: each column is `type name keys "notes"`, where the keys are `PK` (primary key), `FK` (foreign key) and
`UK` (unique on its own), and the notes give an enum's values and whether the column is nullable. Each relationship
is labeled with its foreign-key column; `|o` on the parent side means that column is nullable, and `o|` on the child
side means at most one child per parent.

## Diagram

<!-- schema:begin -->
```mermaid
erDiagram
    campaign_tags {
        uuid campaign_id PK, FK
        uuid tag_id PK, FK
        datetime created_at
    }
    campaigns {
        uuid id PK
        string name
        text original_url
        json csv_columns
        uuid created_by FK
        datetime created_at
        uuid organization_id FK "nullable"
    }
    domains {
        uuid id PK
        string hostname UK
        bool is_default
        datetime created_at
    }
    google_auth_states {
        string state_hash PK
        string code_verifier
        datetime expires_at
    }
    login_codes {
        string code_hash PK
        uuid user_id FK
        datetime expires_at
    }
    mcp_oauth_store {
        string collection PK
        text key PK
        text value
        datetime created_at "nullable"
        datetime expires_at "nullable"
    }
    organization_members {
        uuid organization_id PK, FK
        uuid user_id PK, FK
        enum role "OWNER/ADMIN/MEMBER"
        datetime joined_at
    }
    organizations {
        uuid id PK
        string name
        string google_domain UK "nullable"
        datetime created_at
        bytes logo "nullable"
        string logo_content_type "nullable"
        datetime logo_updated_at "nullable"
    }
    orphan_visits {
        uuid id PK
        enum type "BASE_URL/INVALID_SHORT_URL/REGULAR_404"
        string attempted_path
        string ip "nullable"
        text user_agent "nullable"
        text referer "nullable"
        datetime created_at
    }
    rate_limits {
        string key PK
        int window_start
        int count
    }
    redirect_rules {
        uuid id PK
        uuid url_id FK
        int priority
        json conditions
        text target_url
        datetime created_at
    }
    service_tokens {
        uuid id PK
        uuid service_account_id FK
        string prefix
        string token_hash UK
        datetime expires_at "nullable"
        datetime last_used_at "nullable"
        uuid created_by_user_id FK "nullable"
        datetime created_at
        datetime replaced_at "nullable"
        datetime revoked_at "nullable"
        uuid revoked_by_user_id FK "nullable"
    }
    tags {
        uuid id PK
        string name UK
        string display_name
        string color
        bool is_predefined
        datetime created_at
        uuid created_by FK "nullable"
    }
    url_tags {
        uuid url_id PK, FK
        uuid tag_id PK, FK
        datetime created_at
    }
    urls {
        uuid id PK
        string short_code
        uuid domain_id FK "nullable"
        text original_url
        enum url_type "STANDARD/CUSTOM/CAMPAIGN"
        string title "nullable"
        uuid campaign_id FK "nullable"
        json user_data "nullable"
        bool forward_parameters
        string og_title "nullable"
        text og_description "nullable"
        text og_image_url "nullable"
        datetime og_fetched_at "nullable"
        string page_og_title "nullable"
        text page_og_description "nullable"
        text page_og_image_url "nullable"
        text page_favicon_url "nullable"
        datetime page_fetched_at "nullable"
        datetime last_click_at "nullable"
        datetime valid_since "nullable"
        datetime valid_until "nullable"
        int max_visits "nullable"
        bool crawlable
        uuid created_by FK
        datetime created_at
        datetime updated_at
        uuid organization_id FK "nullable"
        uuid via_service_account_id FK "nullable"
        uuid via_token_id FK "nullable"
    }
    user_identities {
        uuid id PK
        uuid user_id FK
        string provider
        string subject
        string email
        datetime created_at
    }
    user_profiles {
        uuid user_id PK, FK
        string first_name "nullable"
        string last_name "nullable"
        string country "nullable"
        string timezone "nullable"
        datetime updated_at
        bytes avatar "nullable"
        string avatar_content_type "nullable"
        datetime avatar_updated_at "nullable"
    }
    users {
        uuid id PK
        string email UK
        string password_hash "nullable"
        string api_key_hash UK "nullable"
        string api_key_prefix "nullable"
        enum api_key_scope "FULL_ACCESS/READ_ONLY/CREATE_ONLY/DOMAIN_SPECIFIC"
        json api_key_constraints "nullable"
        bool is_active
        datetime created_at
        datetime sessions_valid_from "nullable"
        string kind
        string display_name "nullable"
        text description "nullable"
        uuid responsible_user_id FK "nullable"
    }
    visits {
        uuid id PK
        uuid url_id FK
        string short_code
        string ip
        string country "nullable"
        string city "nullable"
        text user_agent "nullable"
        text referer "nullable"
        bool is_bot
        bool is_pixel
        datetime visited_at
    }
    waitlist_entries {
        uuid id PK
        string email UK
        string name
        string kind
        string company "nullable"
        string company_size "nullable"
        string role "nullable"
        string use_case "nullable"
        string source "nullable"
        datetime consent_at
        datetime created_at
        datetime updated_at "nullable"
    }
    campaigns ||--o{ campaign_tags : "campaign_id"
    tags ||--o{ campaign_tags : "tag_id"
    users ||--o{ campaigns : "created_by"
    organizations |o--o{ campaigns : "organization_id"
    users ||--o{ login_codes : "user_id"
    organizations ||--o{ organization_members : "organization_id"
    users ||--o{ organization_members : "user_id"
    urls ||--o{ redirect_rules : "url_id"
    users ||--o{ service_tokens : "service_account_id"
    users |o--o{ service_tokens : "created_by_user_id"
    users |o--o{ service_tokens : "revoked_by_user_id"
    users |o--o{ tags : "created_by"
    urls ||--o{ url_tags : "url_id"
    tags ||--o{ url_tags : "tag_id"
    domains |o--o{ urls : "domain_id"
    campaigns |o--o{ urls : "campaign_id"
    users ||--o{ urls : "created_by"
    organizations |o--o{ urls : "organization_id"
    users |o--o{ urls : "via_service_account_id"
    service_tokens |o--o{ urls : "via_token_id"
    users ||--o{ user_identities : "user_id"
    users ||--o| user_profiles : "user_id"
    users |o--o{ users : "responsible_user_id"
    urls ||--o{ visits : "url_id"
```
<!-- schema:end -->
