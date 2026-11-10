-- 0004: MagicWorkshop V2 All-Module Parallel Schema (PG_RUNTIME NOT RUN)
-- Covers AI Hub, Agent OS, Compute & Pairing, Client Sync, and Data Integrations

CREATE TABLE IF NOT EXISTS ai_providers (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  adapter_kind TEXT NOT NULL CHECK (adapter_kind IN ('openai_compatible','gemini_native','mistral_native')),
  endpoint_url TEXT NOT NULL,
  credential_ref TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'UNKNOWN',
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  models_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  owner_sub TEXT NOT NULL,
  agent_id TEXT,
  work_item_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sequence INT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  spawned_task_id UUID,
  approval_id UUID,
  idempotency_key TEXT NOT NULL,
  request_hash CHAR(64) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(conversation_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS plugins (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  previous_version TEXT,
  signature_sha256 CHAR(64) NOT NULL,
  requested_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  source_repo TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compute_runs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  runtime_kind TEXT NOT NULL CHECK (runtime_kind IN ('local_worker','colab_ephemeral','remote_node')),
  git_commit TEXT NOT NULL,
  dataset_sha256 CHAR(64) NOT NULL,
  execution_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL DEFAULT 'PREPARED',
  checkpoints_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  last_checkpoint_artifact_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS client_devices (
  device_id TEXT PRIMARY KEY,
  owner_sub TEXT NOT NULL,
  platform TEXT NOT NULL CHECK (platform IN ('web','android','macos','windows')),
  app_version TEXT NOT NULL,
  os_arch TEXT NOT NULL,
  keystore_kind TEXT NOT NULL,
  wipe_pending BOOLEAN NOT NULL DEFAULT FALSE,
  revoked BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS client_sync_states (
  owner_sub TEXT PRIMARY KEY,
  revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
  cursor TEXT NOT NULL,
  draft_work_items JSONB NOT NULL DEFAULT '[]'::jsonb,
  ui_preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS upload_tickets (
  ticket_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_sub TEXT NOT NULL,
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  byte_size BIGINT NOT NULL CHECK (byte_size > 0),
  expected_sha256 CHAR(64) NOT NULL,
  task_id UUID,
  state TEXT NOT NULL DEFAULT 'ISSUED',
  artifact_id UUID,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
