//! Runs one wizard job (`tau setup … --json`, `tau telegram pair --json`, uv) as a child of the
//! app and streams what it prints.
//!
//! - **Its own process group,** like the version check in `chat/home.rs`: cancelling or a
//!   timeout reaches whatever the job started. Cancel sends SIGINT first (the Ctrl-C a terminal
//!   would send: `tau telegram pair` withdraws its code), then SIGKILL after a grace period.
//!   Every signal is sent before the child is reaped, so it can never hit a recycled pid.
//! - **Input on stdin only:** the job's input (keys and tokens included) is written to the
//!   child's stdin and the pipe is closed; it never reaches argv, the environment or a log.
//! - **Output as events:** every stdout line goes through [`jsonl::parse`], every stderr line
//!   becomes a `stderr` event, in the order they arrive.

use super::jsonl::{self, LineSplitter};
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::PathBuf;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

/// How often the runner looks at the child while no output comes.
const POLL: Duration = Duration::from_millis(50);
/// After the child exited, how long the output pipes get to close (a grandchild that left the
/// group may still hold them).
const PIPE_GRACE: Duration = Duration::from_secs(1);
/// After SIGINT, how long the job gets before SIGKILL.
pub const STOP_GRACE: Duration = Duration::from_secs(3);

/// A process to run: program, arguments, working directory, its complete environment, its
/// input and how long it may take.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Job {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: PathBuf,
    pub env: BTreeMap<String, String>,
    /// Written to stdin, which is then closed; `None`: stdin is `/dev/null`.
    pub stdin: Option<Vec<u8>>,
    pub timeout: Duration,
    pub stop_grace: Duration,
}

impl Job {
    /// The command line, for the app's log and error messages. Never the input.
    pub fn display(&self) -> String {
        let mut parts = vec![self.program.display().to_string()];
        parts.extend(self.args.iter().cloned());
        parts.join(" ")
    }
}

/// How a job ended.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct Ended {
    /// The exit code; `None` when a signal ended the job.
    pub code: Option<i32>,
    pub signal: Option<i32>,
    /// The job ran past its timeout and was stopped.
    pub timed_out: bool,
    /// The job was cancelled and stopped.
    pub cancelled: bool,
}

impl Ended {
    pub fn success(&self) -> bool {
        self.code == Some(0)
    }

    fn from_status(status: ExitStatus, timed_out: bool, cancelled: bool) -> Self {
        Self {
            code: status.code(),
            signal: status.signal(),
            timed_out,
            cancelled,
        }
    }
}

/// Run `job` to its end, handing every event to `on_event` on this thread. `cancel` stops it
/// (SIGINT, then SIGKILL after the grace period). `Err` only when it could not start.
pub fn run(
    job: &Job,
    cancel: &AtomicBool,
    mut on_event: impl FnMut(Value),
) -> Result<Ended, String> {
    let mut command = Command::new(&job.program);
    command
        .args(&job.args)
        .current_dir(&job.cwd)
        .env_clear()
        .envs(&job.env)
        .stdin(if job.stdin.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);
    let mut child = command
        .spawn()
        .map_err(|err| format!("`{}` could not start: {err}", job.display()))?;
    let pid = child.id() as libc::pid_t;

    if let (Some(input), Some(mut stdin)) = (job.stdin.clone(), child.stdin.take()) {
        // Its own thread: a child that does not read must not block the runner. A child that
        // exits first makes the write fail with EPIPE, which is fine (SIGPIPE is ignored).
        let _ = std::thread::Builder::new()
            .name("tau-wizard-stdin".into())
            .spawn(move || {
                let _ = stdin.write_all(&input);
            });
    }

    let (tx, rx) = mpsc::channel::<Value>();
    if let Some(stdout) = child.stdout.take() {
        let tx = tx.clone();
        spawn_reader("tau-wizard-stdout", stdout, move |line| {
            if let Some(event) = jsonl::parse(&line) {
                let _ = tx.send(event);
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        let tx = tx.clone();
        spawn_reader("tau-wizard-stderr", stderr, move |line| {
            if !line.trim().is_empty() {
                let _ = tx.send(jsonl::stderr(line.trim_end()));
            }
        });
    }
    drop(tx);

    let started = Instant::now();
    let mut readers_done = false;
    let mut status: Option<ExitStatus> = None;
    let mut exited_at: Option<Instant> = None;
    let mut stopping: Option<Instant> = None;
    let mut killed = false;
    let mut timed_out = false;
    let mut cancelled = false;
    loop {
        if !readers_done {
            match rx.recv_timeout(POLL) {
                // What has queued up as well, but not without end: a job that prints without
                // pause must still see its cancel and its timeout.
                Ok(event) => {
                    on_event(event);
                    for event in rx.try_iter().take(256) {
                        on_event(event);
                    }
                }
                Err(RecvTimeoutError::Disconnected) => readers_done = true,
                Err(RecvTimeoutError::Timeout) => {}
            }
        } else if status.is_none() {
            std::thread::sleep(POLL);
        }
        if status.is_none() {
            let now = Instant::now();
            match stopping {
                None if cancel.load(Ordering::SeqCst) => {
                    cancelled = true;
                    signal_group(pid, libc::SIGINT);
                    stopping = Some(now);
                }
                None if now.duration_since(started) >= job.timeout => {
                    timed_out = true;
                    signal_group(pid, libc::SIGINT);
                    stopping = Some(now);
                }
                Some(since) if !killed && now.duration_since(since) >= job.stop_grace => {
                    signal_group(pid, libc::SIGKILL);
                    killed = true;
                }
                _ => {}
            }
            status = child
                .try_wait()
                .map_err(|err| format!("`{}` could not be watched: {err}", job.display()))?;
            if status.is_some() {
                exited_at = Some(Instant::now());
            }
        }
        if let (Some(_), Some(at)) = (status, exited_at) {
            if readers_done || at.elapsed() >= PIPE_GRACE {
                break;
            }
        }
    }
    while let Ok(event) = rx.try_recv() {
        on_event(event);
    }
    let status = status.expect("the loop ends only after the child exited");
    Ok(Ended::from_status(status, timed_out, cancelled))
}

/// SIGINT or SIGKILL to the job's process group.
fn signal_group(pid: libc::pid_t, signal: libc::c_int) {
    // SAFETY: killpg(2) on the group of our own child, which the caller has not reaped yet
    // (`try_wait` has not returned its status), so the group id is still ours.
    unsafe {
        libc::killpg(pid, signal);
    }
}

/// A thread that reads `pipe` to its end and hands every line to `on_line`.
fn spawn_reader(
    name: &str,
    mut pipe: impl Read + Send + 'static,
    mut on_line: impl FnMut(String) + Send + 'static,
) {
    let spawned = std::thread::Builder::new()
        .name(name.into())
        .spawn(move || {
            let mut lines = LineSplitter::new();
            let mut buffer = [0u8; 16 * 1024];
            loop {
                match pipe.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(n) => lines.push(&buffer[..n]).into_iter().for_each(&mut on_line),
                    Err(err) if err.kind() == std::io::ErrorKind::Interrupted => continue,
                    Err(_) => break,
                }
            }
            if let Some(rest) = lines.finish() {
                on_line(rest);
            }
        });
    if let Err(err) = spawned {
        eprintln!("tau-app: a reader thread could not start: {err}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;

    fn dir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("tau-app-runner-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir.canonicalize().unwrap()
    }

    /// A fake `tau`: a shell script.
    fn fake_tau(dir: &Path, body: &str) -> PathBuf {
        let path = dir.join("tau");
        fs::write(&path, format!("#!/bin/sh\n{body}")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        path
    }

    fn job(program: PathBuf, cwd: &Path) -> Job {
        Job {
            program,
            args: vec![
                "setup".into(),
                "run".into(),
                "guard".into(),
                "--json".into(),
            ],
            cwd: cwd.to_path_buf(),
            env: [("PATH".to_string(), "/usr/bin:/bin".to_string())].into(),
            stdin: None,
            timeout: Duration::from_secs(20),
            stop_grace: STOP_GRACE,
        }
    }

    fn collect(job: &Job, cancel: &AtomicBool) -> (Ended, Vec<Value>) {
        let mut events = Vec::new();
        let ended = run(job, cancel, |event| events.push(event)).unwrap();
        (ended, events)
    }

    #[test]
    fn streams_the_events_of_a_run_and_its_input_arrives_on_stdin() {
        let dir = dir("stream");
        let tau = fake_tau(
            &dir,
            r#"read -r input
[ "$1 $2 $3 $4" = "setup run guard --json" ] || exit 9
[ -z "$SECRET_LEAK" ] || exit 8
echo '{"event": "progress", "feature": "guard", "step": "doctor", "status": "running"}'
echo 'not json'
echo 'a warning' >&2
printf '{"event": "log", "line": "got %s"}\n' "$(printf '%s' "$input" | wc -c | tr -d ' ')"
echo '{"event": "needs_ui", "feature": "guard", "step": "setup", "command": ["guard", "setup"]}'
echo '{"event": "done", "feature": "guard", "ok": true, "pending": ["restart"]}'
"#,
        );
        let mut job = job(tau, &dir);
        let input = br#"{"steps": ["doctor", "setup"], "inputs": {}}"#;
        job.stdin = Some([&input[..], b"\n"].concat());
        let (ended, events) = collect(&job, &AtomicBool::new(false));
        assert!(ended.success(), "{ended:?}");
        let stdout: Vec<&Value> = events.iter().filter(|e| e["event"] != "stderr").collect();
        assert_eq!(stdout[0]["status"], "running");
        assert_eq!(stdout[1], &json!({"event": "text", "line": "not json"}));
        assert_eq!(stdout[2]["line"], format!("got {}", input.len()));
        assert_eq!(stdout[3]["event"], "needs_ui");
        assert_eq!(stdout[4]["event"], "done");
        assert_eq!(stdout[4]["pending"], json!(["restart"]));
        assert!(events
            .iter()
            .any(|e| e == &json!({"event": "stderr", "line": "a warning"})));
        // The input never shows up in the command line.
        assert!(!job.display().contains("steps"));
    }

    #[test]
    fn reports_the_exit_code_of_a_failed_run() {
        let dir = dir("exit");
        let tau = fake_tau(
            &dir,
            "echo '{\"event\": \"error\", \"code\": \"not_installed\", \"message\": \"no\"}'\nexit 1\n",
        );
        let (ended, events) = collect(&job(tau, &dir), &AtomicBool::new(false));
        assert_eq!(ended.code, Some(1));
        assert!(!ended.success() && !ended.cancelled && !ended.timed_out);
        assert_eq!(events[0]["code"], "not_installed");
    }

    #[test]
    fn cancel_sends_ctrl_c_and_the_job_says_goodbye() {
        let dir = dir("cancel");
        let tau = fake_tau(
            &dir,
            r#"trap 'echo "{\"event\": \"error\", \"reason\": \"cancelled\"}"; exit 130' INT
echo '{"event": "code", "code": "K7QM-X2PA"}'
while true; do sleep 0.05; done
"#,
        );
        let cancel = AtomicBool::new(false);
        let mut events = Vec::new();
        let started = Instant::now();
        let ended = run(&job(tau, &dir), &cancel, |event| {
            if event["event"] == "code" {
                cancel.store(true, Ordering::SeqCst);
            }
            events.push(event);
        })
        .unwrap();
        assert!(ended.cancelled, "{ended:?}");
        assert_eq!(ended.code, Some(130));
        assert_eq!(events.last().unwrap()["reason"], "cancelled");
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn a_job_that_ignores_ctrl_c_is_killed_after_the_grace_period() {
        let dir = dir("kill");
        let tau = fake_tau(
            &dir,
            "trap '' INT\necho '{\"event\": \"ready\"}'\nwhile true; do sleep 0.05; done\n",
        );
        let mut job = job(tau, &dir);
        job.stop_grace = Duration::from_millis(300);
        let cancel = AtomicBool::new(false);
        let started = Instant::now();
        let ended = run(&job, &cancel, |event| {
            if event["event"] == "ready" {
                cancel.store(true, Ordering::SeqCst);
            }
        })
        .unwrap();
        assert!(ended.cancelled, "{ended:?}");
        assert_eq!(ended.signal, Some(libc::SIGKILL));
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn a_job_past_its_timeout_is_stopped() {
        let dir = dir("timeout");
        let tau = fake_tau(&dir, "exec sleep 30\n");
        let mut job = job(tau, &dir);
        job.timeout = Duration::from_millis(200);
        job.stop_grace = Duration::from_millis(300);
        let started = Instant::now();
        let (ended, _) = collect(&job, &AtomicBool::new(false));
        assert!(ended.timed_out && !ended.cancelled, "{ended:?}");
        assert!(!ended.success());
        assert!(started.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn does_not_wait_for_a_grandchild_holding_the_pipes() {
        let dir = dir("grandchild");
        let tau = fake_tau(
            &dir,
            "sleep 30 &\necho $! > grandchild.pid\necho '{\"event\": \"done\", \"ok\": true}'\n",
        );
        let started = Instant::now();
        let (ended, events) = collect(&job(tau, &dir), &AtomicBool::new(false));
        assert!(ended.success());
        assert_eq!(events.last().unwrap()["event"], "done");
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "{:?}",
            started.elapsed()
        );
        let pid: libc::pid_t = fs::read_to_string(dir.join("grandchild.pid"))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
        unsafe {
            libc::kill(pid, libc::SIGKILL);
        }
    }

    #[test]
    fn the_environment_is_exactly_the_jobs() {
        let dir = dir("env");
        let tau = fake_tau(&dir, "env\n");
        let mut job = job(tau, &dir);
        job.env
            .insert("TAU_HOME".into(), "/example/home/.tau".into());
        let (ended, events) = collect(&job, &AtomicBool::new(false));
        assert!(ended.success());
        let mut lines: Vec<String> = events
            .iter()
            .map(|e| e["line"].as_str().unwrap().to_string())
            .filter(|l| !l.starts_with("PWD=") && !l.starts_with("SHLVL=") && !l.starts_with("_="))
            .collect();
        lines.sort();
        assert_eq!(lines, ["PATH=/usr/bin:/bin", "TAU_HOME=/example/home/.tau"]);
    }

    #[test]
    fn a_program_that_cannot_start_is_an_error() {
        let dir = dir("missing");
        let err = run(
            &job(dir.join("nope"), &dir),
            &AtomicBool::new(false),
            |_| {},
        )
        .unwrap_err();
        assert!(err.contains("could not start"), "{err}");
    }
}
