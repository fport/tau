-- The tau network: the mailbox of sealed envelopes and the replay guard.
-- Both tables hold only what is in transit; the cron prunes them.

-- Envelopes that passed every inbox check, kept until the hub acknowledges them.
CREATE TABLE mailbox (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  sender TEXT NOT NULL,
  -- {"payload": b64u, "sig": b64u}, exactly as the sender posted it (other keys dropped).
  envelope TEXT NOT NULL,
  -- Unix seconds.
  received_at INTEGER NOT NULL
);

CREATE INDEX mailbox_received_at ON mailbox (received_at);

-- Envelope ids seen per sender: duplicates are answered without storing them again, and
-- the rows of the last hour count against the sender's rate limit.
CREATE TABLE seen (
  sender TEXT NOT NULL,
  id TEXT NOT NULL,
  -- Unix seconds of arrival.
  ts INTEGER NOT NULL,
  PRIMARY KEY (sender, id)
);

CREATE INDEX seen_sender_ts ON seen (sender, ts);
CREATE INDEX seen_ts ON seen (ts);
