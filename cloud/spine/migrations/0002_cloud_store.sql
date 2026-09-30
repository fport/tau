-- Cloud mode: the store behind /hub/state and /hub/sessions.
-- The tables exist in both modes; a local-mode spine never writes them (its routes answer
-- 404 cloud_mode_off), so they stay empty there.

-- Small JSON documents (for example the network store: net.contacts, net.cursor).
CREATE TABLE state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  -- Unix seconds.
  updated_at INTEGER NOT NULL
);

-- One row per session. `data` and `meta` are JSON text the spine never interprets.
CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  -- ISO 8601 UTC, like the timestamps in Strands' own session records.
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  -- Increases with every write to the session; orders the listing without ties.
  rev INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX sessions_rev ON sessions (rev);

CREATE TABLE agents (
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id)
);

CREATE TABLE messages (
  session_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  message_id INTEGER NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id, message_id)
);

-- Agent events, in insertion order.
CREATE TABLE events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  data TEXT NOT NULL
);

CREATE INDEX events_session ON events (session_id, seq);
