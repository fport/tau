//! TauBar's own short log: sleep mode and login item changes, and (from 084 on) every hub
//! start, exit and restart. One line per event, local time first. The file is rotated once
//! (`taubar.log` → `taubar.log.1`) when it passes `max_bytes`, so it stays short.

use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub const LOG_FILE: &str = "taubar.log";
const MAX_BYTES: u64 = 256 * 1024;

pub struct EventLog {
    path: PathBuf,
    max_bytes: u64,
    guard: Mutex<()>,
}

impl EventLog {
    pub fn new(dir: &Path) -> Self {
        Self::with_limit(dir, MAX_BYTES)
    }

    pub fn with_limit(dir: &Path, max_bytes: u64) -> Self {
        Self {
            path: dir.join(LOG_FILE),
            max_bytes,
            guard: Mutex::new(()),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one line. Never fails: a log that cannot be written must not stop TauBar.
    pub fn write(&self, message: impl AsRef<str>) {
        let _guard = self.guard.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(parent) = self.path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let full = fs::metadata(&self.path)
            .map(|m| m.len() >= self.max_bytes)
            .unwrap_or(false);
        if full {
            let _ = fs::rename(&self.path, self.rotated());
        }
        let line = format!("{} {}\n", local_timestamp(), message.as_ref());
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        {
            let _ = file.write_all(line.as_bytes());
        }
        // Visible in `pnpm tauri dev` and when TauBar is started from a terminal.
        eprint!("taubar: {line}");
    }

    /// The last `n` lines of the current file, oldest first.
    pub fn tail(&self, n: usize) -> Vec<String> {
        let _guard = self.guard.lock().unwrap_or_else(|e| e.into_inner());
        let Ok(file) = fs::File::open(&self.path) else {
            return Vec::new();
        };
        let lines: Vec<String> = BufReader::new(file).lines().map_while(Result::ok).collect();
        let start = lines.len().saturating_sub(n);
        lines[start..].to_vec()
    }

    fn rotated(&self) -> PathBuf {
        let mut name = self.path.as_os_str().to_owned();
        name.push(".1");
        PathBuf::from(name)
    }
}

/// `YYYY-MM-DD HH:MM:SS` in local time.
pub fn local_timestamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0) as libc::time_t;
    // SAFETY: localtime_r only writes into the zeroed `tm` we own.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    unsafe { libc::localtime_r(&secs, &mut tm) };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        tm.tm_year + 1900,
        tm.tm_mon + 1,
        tm.tm_mday,
        tm.tm_hour,
        tm.tm_min,
        tm.tm_sec
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("taubar-log-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn writes_and_tails_lines() {
        let dir = tmpdir("tail");
        let log = EventLog::new(&dir);
        for i in 0..5 {
            log.write(format!("event {i}"));
        }
        let tail = log.tail(2);
        assert_eq!(tail.len(), 2);
        assert!(tail[0].ends_with(" event 3"));
        assert!(tail[1].ends_with(" event 4"));
        assert_eq!(tail[1].len(), "YYYY-MM-DD HH:MM:SS event 4".len());
    }

    #[test]
    fn rotates_once_past_the_limit() {
        let dir = tmpdir("rotate");
        let log = EventLog::with_limit(&dir, 64);
        for i in 0..10 {
            log.write(format!("a fairly long event line number {i}"));
        }
        assert!(dir.join("taubar.log.1").is_file());
        assert!(fs::metadata(dir.join(LOG_FILE)).unwrap().len() < 200);
        assert!(log.tail(1)[0].ends_with("number 9"));
    }
}
