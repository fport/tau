//! Read-only looks at a hub: its lock, its control API, `tau hub status --json` and launchd.
//!
//! Nothing here starts, stops or changes a hub.

use super::launch::{Launch, LaunchdAgent, LAUNCHD_LABEL};
use serde::Serialize;
use serde_json::Value;
use std::fs::File;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};

/// The hub lock is held by a running hub (`flock`), and the pid it wrote.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LockProbe {
    pub held: bool,
    pub pid: Option<u32>,
}

/// `HubLock.probe` in tau-core: try a shared, non-blocking `flock`. Held → a hub runs.
///
/// Only call it while a hub is known to run or right before starting one: for the moment the
/// shared lock is held, a hub that starts at that very instant would fail to take its lock.
pub fn probe_lock(path: &Path) -> LockProbe {
    let Ok(mut file) = File::open(path) else {
        return LockProbe {
            held: false,
            pid: None,
        };
    };
    let fd = file.as_raw_fd();
    // SAFETY: flock on a descriptor we own; it is closed when `file` drops.
    let locked = unsafe { libc::flock(fd, libc::LOCK_SH | libc::LOCK_NB) } == 0;
    if locked {
        unsafe { libc::flock(fd, libc::LOCK_UN) };
        return LockProbe {
            held: false,
            pid: None,
        };
    }
    let mut text = String::new();
    let pid = file
        .read_to_string(&mut text)
        .ok()
        .and_then(|_| text.trim().parse().ok());
    LockProbe { held: true, pid }
}

/// `GET http://127.0.0.1:<port><path>` → (status, body). HTTP/1.1 with `Connection: close`;
/// the hub's control API answers and closes.
pub fn http_get(port: u16, path: &str, timeout: Duration) -> Result<(u16, String), String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, timeout).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(timeout)).ok();
    stream.set_write_timeout(Some(timeout)).ok();
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAccept: application/json\r\n\
         Connection: close\r\n\r\n"
    )
    .map_err(|e| e.to_string())?;
    let mut raw = Vec::new();
    stream
        .take(1024 * 1024)
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    parse_http_response(&raw)
}

pub fn parse_http_response(raw: &[u8]) -> Result<(u16, String), String> {
    let text = String::from_utf8_lossy(raw);
    let (head, body) = text
        .split_once("\r\n\r\n")
        .ok_or("incomplete HTTP response")?;
    let status = head
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|code| code.parse().ok())
        .ok_or("no HTTP status line")?;
    Ok((status, body.to_string()))
}

/// A JSON object from the control API, or `None` when the hub does not answer with 200.
pub fn get_json(port: u16, path: &str, timeout: Duration) -> Option<Value> {
    match http_get(port, path, timeout) {
        Ok((200, body)) => serde_json::from_str(&body).ok(),
        _ => None,
    }
}

/// What `tau hub status --json` resolves for this configuration.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Resolved {
    pub control_port: u16,
    pub data_dir: PathBuf,
    pub hub_dir: PathBuf,
    pub lock: PathBuf,
}

impl Resolved {
    pub fn control_url(&self) -> String {
        format!("http://127.0.0.1:{}", self.control_port)
    }

    /// The hub's own log (`[logs]` of tau-core).
    pub fn hub_log(&self) -> PathBuf {
        self.data_dir.join("logs").join("tau.log")
    }

    /// Where TauBar sends the hub's stdout and stderr (next to launchd's).
    pub fn output_logs(&self) -> (PathBuf, PathBuf) {
        let dir = self.hub_dir.join("logs");
        (dir.join("taubar.out.log"), dir.join("taubar.err.log"))
    }
}

/// Parse `tau hub status --json`. An older tau-core prints no `hub_dir`/`lock`/`data_dir`;
/// then the default layout under `fallback_data_dir` is assumed.
pub fn parse_status(text: &str, fallback_data_dir: &Path) -> Result<Resolved, String> {
    let value: Value =
        serde_json::from_str(text).map_err(|e| format!("tau hub status --json: {e}"))?;
    let control_port = value
        .get("control_port")
        .and_then(Value::as_u64)
        .or_else(|| {
            value
                .get("control_url")
                .and_then(Value::as_str)
                .and_then(|url| url.rsplit(':').next())
                .and_then(|port| port.parse().ok())
        })
        .and_then(|port| u16::try_from(port).ok())
        .ok_or("tau hub status --json has no control port")?;
    let path = |key: &str| value.get(key).and_then(Value::as_str).map(PathBuf::from);
    let data_dir = path("data_dir").unwrap_or_else(|| fallback_data_dir.to_path_buf());
    let hub_dir = path("hub_dir").unwrap_or_else(|| data_dir.join("hub"));
    let lock = path("lock").unwrap_or_else(|| hub_dir.join("hub.lock"));
    Ok(Resolved {
        control_port,
        data_dir,
        hub_dir,
        lock,
    })
}

/// Run `tau hub status --json` (at most `timeout`) and parse it.
pub fn resolve(status: &Launch, timeout: Duration) -> Result<Resolved, String> {
    let mut child = status
        .command()
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{} could not run: {e}", status.program.display()))?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!("tau hub status did not answer within {timeout:?}"));
            }
            Err(e) => return Err(e.to_string()),
        }
    }
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let reason = stderr
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("no output")
            .trim()
            .to_string();
        return Err(format!("tau hub status failed: {reason}"));
    }
    let fallback = status
        .env
        .get("HOME")
        .map(|home| Path::new(home).join(".local/share/tau"))
        .unwrap_or_else(|| PathBuf::from(".local/share/tau"));
    let fallback = status
        .env
        .get("TAU_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or(fallback);
    parse_status(&String::from_utf8_lossy(&output.stdout), &fallback)
}

/// Whether an installed, loaded `com.tau.hub` launchd agent runs a hub for `data_dir`.
/// Then launchd is that hub's supervisor and TauBar must not become a second one.
pub fn launchd_manages(user_home: &Path, data_dir: &Path) -> bool {
    let Some(agent) = LaunchdAgent::read(&LaunchdAgent::plist_path(user_home)) else {
        return false;
    };
    let agent_dir = agent
        .data_dir
        .unwrap_or_else(|| user_home.join(".local/share/tau"));
    if !same_path(&agent_dir, data_dir) {
        return false;
    }
    // SAFETY: getuid has no preconditions.
    let uid = unsafe { libc::getuid() };
    std::process::Command::new("/bin/launchctl")
        .args(["print", &format!("gui/{uid}/{LAUNCHD_LABEL}")])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn same_path(a: &Path, b: &Path) -> bool {
    let canon = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
    canon(a) == canon(b)
}

/// For a hub TauBar adopted (no exit status): did it write `stopped_at` on its way out?
pub fn stopped_cleanly(hub_dir: &Path, pid: u32) -> bool {
    let Ok(text) = std::fs::read_to_string(hub_dir.join("state.json")) else {
        return false;
    };
    let Ok(state) = serde_json::from_str::<Value>(&text) else {
        return false;
    };
    state.get("pid").and_then(Value::as_u64) == Some(u64::from(pid))
        && state.get("stopped_at").is_some_and(|v| !v.is_null())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    fn tmpdir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("taubar-probe-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn lock_probe_sees_a_held_lock_and_its_pid() {
        let dir = tmpdir("lock");
        let path = dir.join("hub.lock");
        assert_eq!(
            probe_lock(&path),
            LockProbe {
                held: false,
                pid: None
            }
        );
        std::fs::write(&path, "4242\n").unwrap();
        assert!(!probe_lock(&path).held);

        let holder = File::open(&path).unwrap();
        assert_eq!(unsafe { libc::flock(holder.as_raw_fd(), libc::LOCK_EX) }, 0);
        assert_eq!(
            probe_lock(&path),
            LockProbe {
                held: true,
                pid: Some(4242)
            }
        );
        drop(holder);
        assert!(!probe_lock(&path).held);
    }

    #[test]
    fn parses_http_responses() {
        let raw = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\": true}";
        assert_eq!(
            parse_http_response(raw).unwrap(),
            (200, "{\"ok\": true}".into())
        );
        assert!(parse_http_response(b"garbage").is_err());
    }

    #[test]
    fn get_json_talks_to_a_loopback_server() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = std::thread::spawn(move || {
            let (mut conn, _) = listener.accept().unwrap();
            // Read the whole request head: closing with unread bytes would reset the connection.
            let mut raw = Vec::new();
            let mut buf = [0u8; 256];
            while !raw.windows(4).any(|w| w == b"\r\n\r\n") {
                let n = conn.read(&mut buf).unwrap();
                if n == 0 {
                    break;
                }
                raw.extend_from_slice(&buf[..n]);
            }
            let request = String::from_utf8_lossy(&raw).to_string();
            let body = r#"{"ok": true, "pid": 4242, "uptime_s": 1.5}"#;
            write!(
                conn,
                "HTTP/1.0 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
            request
        });
        let value = get_json(port, "/health", Duration::from_secs(2)).unwrap();
        assert_eq!(value["pid"], 4242);
        let request = server.join().unwrap();
        assert!(request.starts_with("GET /health HTTP/1.1\r\n"));
        assert!(request.contains(&format!("Host: 127.0.0.1:{port}\r\n")));
    }

    #[test]
    fn get_json_is_none_without_a_server() {
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        assert!(get_json(port, "/health", Duration::from_millis(300)).is_none());
    }

    #[test]
    fn parses_tau_hub_status_json() {
        let text = r#"{"running": false, "pid": null, "control_url": "http://127.0.0.1:7897",
            "control_port": 7897, "data_dir": "/tmp/d", "hub_dir": "/tmp/d/hub",
            "lock": "/tmp/d/hub/hub.lock"}"#;
        let resolved = parse_status(text, Path::new("/unused")).unwrap();
        assert_eq!(resolved.control_port, 7897);
        assert_eq!(resolved.lock, PathBuf::from("/tmp/d/hub/hub.lock"));
        assert_eq!(resolved.hub_log(), PathBuf::from("/tmp/d/logs/tau.log"));
        assert_eq!(resolved.control_url(), "http://127.0.0.1:7897");
    }

    #[test]
    fn older_status_json_falls_back_to_the_default_layout() {
        let text = r#"{"running": false, "control_url": "http://127.0.0.1:7877"}"#;
        let resolved = parse_status(text, Path::new("/x/tau")).unwrap();
        assert_eq!(resolved.control_port, 7877);
        assert_eq!(resolved.hub_dir, PathBuf::from("/x/tau/hub"));
        assert_eq!(resolved.lock, PathBuf::from("/x/tau/hub/hub.lock"));
        assert!(parse_status("{}", Path::new("/x")).is_err());
        assert!(parse_status("not json", Path::new("/x")).is_err());
    }

    #[test]
    fn stopped_cleanly_reads_state_json() {
        let dir = tmpdir("state");
        assert!(!stopped_cleanly(&dir, 10));
        std::fs::write(dir.join("state.json"), r#"{"pid": 10, "stopped_at": null}"#).unwrap();
        assert!(!stopped_cleanly(&dir, 10));
        std::fs::write(
            dir.join("state.json"),
            r#"{"pid": 10, "stopped_at": "2026-09-30T00:00:00+00:00"}"#,
        )
        .unwrap();
        assert!(stopped_cleanly(&dir, 10));
        assert!(!stopped_cleanly(&dir, 11));
    }

    #[test]
    fn launchd_manages_nothing_without_a_plist() {
        let dir = tmpdir("nolaunchd");
        assert!(!launchd_manages(&dir, &dir.join("data")));
    }
}
