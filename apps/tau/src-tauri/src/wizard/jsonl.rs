//! The JSON lines `tau setup … --json`, `tau telegram pair --json` and `tau net spine deploy
//! --json` print: one JSON object per line (`docs/reference/setup.md`).
//!
//! [`LineSplitter`] turns the chunks a pipe delivers into whole lines (a line, or a UTF-8
//! character, can be split across two reads), and [`parse`] turns a line into the object the
//! wizard page gets. A line that is not a JSON object (a stray `print`, the output of `curl` or
//! of uv's installer) becomes `{"event": "text", "line": …}`, so nothing a child prints is lost
//! and nothing breaks the stream.

use serde_json::{json, Value};

/// The longest line kept whole; the rest of a longer one is dropped (a protocol line is a few
/// hundred bytes, a status object a few dozen KiB).
pub const MAX_LINE: usize = 1024 * 1024;

/// Bytes in, whole lines out.
#[derive(Debug, Default)]
pub struct LineSplitter {
    buffer: Vec<u8>,
    /// The current line passed [`MAX_LINE`]: drop bytes until its newline.
    overflowed: bool,
}

impl LineSplitter {
    pub fn new() -> Self {
        Self::default()
    }

    /// The lines `chunk` completes, without their `\n` (or `\r\n`), decoded as UTF-8 (invalid
    /// bytes become U+FFFD).
    pub fn push(&mut self, chunk: &[u8]) -> Vec<String> {
        let mut lines = Vec::new();
        let mut rest = chunk;
        while let Some(end) = rest.iter().position(|&b| b == b'\n') {
            self.append(&rest[..end]);
            lines.push(self.take());
            rest = &rest[end + 1..];
        }
        self.append(rest);
        lines
    }

    /// What is left after the stream ended without a final newline.
    pub fn finish(&mut self) -> Option<String> {
        if self.buffer.is_empty() && !self.overflowed {
            return None;
        }
        Some(self.take())
    }

    fn append(&mut self, bytes: &[u8]) {
        let room = MAX_LINE.saturating_sub(self.buffer.len());
        if bytes.len() > room {
            self.overflowed = true;
        }
        self.buffer
            .extend_from_slice(&bytes[..bytes.len().min(room)]);
    }

    fn take(&mut self) -> String {
        let mut bytes = std::mem::take(&mut self.buffer);
        if bytes.last() == Some(&b'\r') {
            bytes.pop();
        }
        self.overflowed = false;
        String::from_utf8_lossy(&bytes).into_owned()
    }
}

/// One line as the page gets it: a JSON object as it is, anything else that is not blank as
/// `{"event": "text", "line": …}`; `None` for a blank line.
pub fn parse(line: &str) -> Option<Value> {
    let trimmed = line.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed.starts_with('{') {
        if let Ok(value @ Value::Object(_)) = serde_json::from_str::<Value>(trimmed) {
            return Some(value);
        }
    }
    Some(text(line.trim_end()))
}

/// A line of plain output.
pub fn text(line: &str) -> Value {
    json!({"event": "text", "line": line})
}

/// A line the child wrote to stderr (free text for a log, never part of the protocol).
pub fn stderr(line: &str) -> Value {
    json!({"event": "stderr", "line": line})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splits_lines_across_chunks() {
        let mut lines = LineSplitter::new();
        assert!(lines.push(b"{\"event\": \"prog").is_empty());
        assert_eq!(
            lines.push(b"ress\"}\n{\"event\": \"log\", \"line\": \"a\"}\r\npartial"),
            [
                "{\"event\": \"progress\"}",
                "{\"event\": \"log\", \"line\": \"a\"}"
            ]
        );
        assert_eq!(lines.push(b" end\n\n"), ["partial end", ""]);
        assert_eq!(lines.finish(), None);
        lines.push(b"no newline");
        assert_eq!(lines.finish().as_deref(), Some("no newline"));
        assert_eq!(lines.finish(), None);
    }

    #[test]
    fn keeps_a_utf8_character_split_across_reads() {
        let text = "{\"label\": \"Sahip koruması · ğüşİ\"}\n".as_bytes();
        // Split inside the two-byte "ğ".
        let cut = text.iter().position(|&b| b == 0xc4).unwrap() + 1;
        let mut lines = LineSplitter::new();
        assert!(lines.push(&text[..cut]).is_empty());
        let got = lines.push(&text[cut..]);
        assert_eq!(got, ["{\"label\": \"Sahip koruması · ğüşİ\"}"]);
        assert_eq!(parse(&got[0]).unwrap()["label"], "Sahip koruması · ğüşİ");
        // Invalid bytes do not stop the stream.
        assert_eq!(lines.push(b"a\xffb\n"), ["a\u{fffd}b"]);
    }

    #[test]
    fn caps_a_runaway_line() {
        let mut lines = LineSplitter::new();
        let big = vec![b'x'; MAX_LINE + 10];
        assert!(lines.push(&big).is_empty());
        let got = lines.push(b"yyy\nnext\n");
        assert_eq!(got.len(), 2);
        assert_eq!(got[0].len(), MAX_LINE);
        assert_eq!(got[1], "next");
    }

    #[test]
    fn parses_objects_and_wraps_everything_else() {
        let event = parse(r#"{"event": "done", "ok": true, "installed": []}"#).unwrap();
        assert_eq!(event["event"], "done");
        assert_eq!(event["ok"], true);
        // `tau net spine deploy --json` says `type`, not `event`: passed on as it is.
        let spine =
            parse(r#"{"type": "need_token", "link": "https://dash.cloudflare.com/"}"#).unwrap();
        assert_eq!(spine["type"], "need_token");
        assert_eq!(parse("   "), None);
        assert_eq!(parse(""), None);
        for line in [
            "Resolved 42 packages in 1.20s",
            "[1, 2]",
            "\"a string\"",
            "{not json",
            "downloading uv 0.10.11 aarch64-apple-darwin",
        ] {
            let wrapped = parse(line).unwrap();
            assert_eq!(wrapped, json!({"event": "text", "line": line}), "{line}");
        }
        assert_eq!(stderr("warning")["event"], "stderr");
    }
}
