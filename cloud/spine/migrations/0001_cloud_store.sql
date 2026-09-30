-- Cloud mode: the store behind /hub/state and /hub/sessions.
-- Only the cloud configuration (wrangler.cloud.example.jsonc) binds a D1 database; local
-- mode has none. The mailbox and the replay guard are not here: they live in the Mailbox
-- Durable Object's own SQLite storage (src/mailbox.ts) in both modes.
--
-- Development databases created before the Mailbox existed ran this file as 0002 and kept
-- the mailbox in D1, so every statement below is safe to run on them again, and the old
-- tables go.
DROP TABLE IF EXISTS mailbox;
DROP TABLE IF EXISTS seen;

-- Small JSON documents (for example the network store: net.contacts, net.cursor).
CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  -- Unix seconds.
  updated_at INTEGER NOT NULL
);

-- One row per session. `data` and `meta` are JSON text the spine never interprets.
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  -- ISO 8601 UTC, like the timestamps in Strands' own session records.
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  -- Increases with every write to the session; orders the listing without ties.
  rev INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS sessions_rev ON sessions (rev);

CREATE TABLE IF NOT EXISTS agents (
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id)
);

CREATE TABLE IF NOT EXISTS messages (
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id, message_id)
);

-- Agent events, in insertion order.
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  data TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS events_session ON events (session_id, seq);
