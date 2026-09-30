//! One PTY and the TUI running in it: spawn, output, input, resize, exit and shutdown.
//!
//! Output is raw bytes from start to finish. A reader thread hands every read to a forwarder
//! that batches what arrives close together ([`forward`]) and passes each batch on untouched;
//! nothing here decodes UTF-8, so a character split across two reads (ğ, ş, a box-drawing
//! line) reaches xterm.js whole, and xterm.js's own decoder joins it.
//!
//! Output and the exit report go to the session's outlet, which a page reload hands to the new
//! page ([`Session::reattach`]): the TUI keeps running, the new terminal first gets the modes the
//! TUI had switched on ([`ModeTracker`]), and a size change makes the TUI paint everything again
//! ([`Session::repaint`]).
//!
//! The child is a session leader (portable-pty calls `setsid`), so its pid is also its process
//! group id. A waiter thread learns about the exit with `waitid(WNOWAIT)` and reaps only while
//! holding the exit lock; [`Session::shutdown`] kills the group under the same lock, so it can
//! never signal a recycled pid.

use super::launch::Launch;
use super::modes::ModeTracker;
use portable_pty::{native_pty_system, Child, MasterPty, PtySize};
use serde::Serialize;
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, TryRecvError};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

/// Ctrl+Q: the TUI's quit key. Its quit path cancels a running turn and releases a running guard
/// attempt, which a SIGHUP or SIGKILL would skip.
pub const QUIT_KEY: u8 = 0x11;
/// How long the TUI gets to quit after ctrl+q before its process group is killed.
pub const QUIT_GRACE: Duration = Duration::from_secs(1);
/// At most one output batch per this interval while output keeps coming.
pub const BATCH_WINDOW: Duration = Duration::from_millis(8);
/// The largest batch sent at once.
pub const MAX_BATCH: usize = 256 * 1024;
/// One read from the PTY.
const READ_BUFFER: usize = 64 * 1024;
/// After the TUI exits, how long to wait for the rest of its output before reporting the exit.
const DRAIN_AFTER_EXIT: Duration = Duration::from_millis(500);
/// How long a repaint keeps the PTY one row smaller, so the TUI sees two real size changes.
/// Textual reads the size when SIGWINCH arrives and ignores a size it already has, so the two
/// changes must not land in the same signal.
pub const REPAINT_NUDGE: Duration = Duration::from_millis(150);

/// How the TUI ended, for the window.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExitInfo {
    pub success: bool,
    /// The exit code; `None` when a signal ended it.
    pub code: Option<u32>,
    /// The signal that ended it, if one did.
    pub signal: Option<String>,
}

impl From<portable_pty::ExitStatus> for ExitInfo {
    fn from(status: portable_pty::ExitStatus) -> Self {
        let signal = status.signal().map(str::to_string);
        Self {
            success: status.success(),
            code: signal.is_none().then(|| status.exit_code()),
            signal,
        }
    }
}

/// What [`Session::shutdown`] had to do.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Shutdown {
    /// The TUI had already exited.
    AlreadyExited,
    /// The TUI quit on ctrl+q within the grace period.
    Quit,
    /// The TUI did not quit in time; its process group was killed.
    Killed,
}

/// The exit status, set once by the waiter thread.
struct ExitState {
    status: Mutex<Option<ExitInfo>>,
    changed: Condvar,
}

impl ExitState {
    fn wait(&self, timeout: Duration) -> Option<ExitInfo> {
        let guard = self.status.lock().unwrap_or_else(|e| e.into_inner());
        let (guard, _) = self
            .changed
            .wait_timeout_while(guard, timeout, |status| status.is_none())
            .unwrap_or_else(|e| e.into_inner());
        guard.clone()
    }
}

/// Where the output and the exit report of a session go: the page that started it, or the page
/// that took it over after a reload.
struct Outlet {
    output: Box<dyn FnMut(Vec<u8>) + Send>,
    /// Taken when the exit is reported; `None` from then on, and then no page can take over.
    exit: Option<Box<dyn FnOnce(ExitInfo) + Send>>,
    /// The terminal modes in everything sent so far, for a page that takes over.
    modes: ModeTracker,
}

/// A running (or finished) TUI in its PTY.
pub struct Session {
    master: Mutex<Box<dyn MasterPty + Send>>,
    /// Shared so the ctrl+q of a shutdown can be written from its own thread.
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    pid: u32,
    exit: Arc<ExitState>,
    outlet: Arc<Mutex<Outlet>>,
    closing: AtomicBool,
}

impl Session {
    /// Start `launch` in a new PTY of `size`. `on_output` gets every batch of raw bytes;
    /// `on_exit` is called once when the child has exited and its output is drained. Both can be
    /// replaced later with [`Session::reattach`].
    pub fn spawn(
        launch: &Launch,
        size: PtySize,
        on_output: impl FnMut(Vec<u8>) + Send + 'static,
        on_exit: impl FnOnce(ExitInfo) + Send + 'static,
    ) -> Result<Arc<Self>, String> {
        // portable-pty silently falls back to $HOME for a missing cwd; refuse instead.
        if !launch.cwd.is_dir() {
            return Err(format!(
                "TAU_HOME is not a folder: {}",
                launch.cwd.display()
            ));
        }
        if !launch.program.is_file() {
            return Err(format!(
                "tau's Python does not exist: {}",
                launch.program.display()
            ));
        }
        let pair = native_pty_system()
            .openpty(size)
            .map_err(|err| format!("no PTY could be opened: {err}"))?;
        let child = pair
            .slave
            .spawn_command(launch.pty_command())
            .map_err(|err| format!("`{}` could not start: {err}", launch.display()))?;
        // Only the child holds the slave now, so the reader sees EOF once the TUI is gone.
        drop(pair.slave);
        let pid = child
            .process_id()
            .ok_or("the TUI started without a process id")?;
        let reader = pair
            .master
            .try_clone_reader()
            .map_err(|err| format!("the PTY cannot be read: {err}"))?;
        let writer = pair
            .master
            .take_writer()
            .map_err(|err| format!("the PTY cannot be written: {err}"))?;

        let exit = Arc::new(ExitState {
            status: Mutex::new(None),
            changed: Condvar::new(),
        });
        let outlet = Arc::new(Mutex::new(Outlet {
            output: Box::new(on_output),
            exit: Some(Box::new(on_exit)),
            modes: ModeTracker::new(),
        }));
        let (chunks_tx, chunks_rx) = mpsc::channel::<Vec<u8>>();
        let (drained_tx, drained_rx) = mpsc::channel::<()>();
        spawn_thread("tau-chat-pty-read", move || read_loop(reader, chunks_tx))?;
        let forward_outlet = Arc::clone(&outlet);
        spawn_thread("tau-chat-pty-forward", move || {
            forward(chunks_rx, BATCH_WINDOW, MAX_BATCH, |batch| {
                // Under the outlet lock, so a page taking over gets every batch the old page
                // did not, and modes that match what the old page got.
                let mut outlet = forward_outlet.lock().unwrap_or_else(|e| e.into_inner());
                outlet.modes.feed(&batch);
                (outlet.output)(batch);
            });
            let _ = drained_tx.send(());
        })?;
        let waiter_exit = Arc::clone(&exit);
        let waiter_outlet = Arc::clone(&outlet);
        spawn_thread("tau-chat-pty-wait", move || {
            let info = wait_for_exit(pid, child, &waiter_exit);
            let _ = drained_rx.recv_timeout(DRAIN_AFTER_EXIT);
            let on_exit = waiter_outlet
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .exit
                .take();
            if let Some(on_exit) = on_exit {
                on_exit(info);
            }
        })?;

        Ok(Arc::new(Self {
            master: Mutex::new(pair.master),
            writer: Arc::new(Mutex::new(writer)),
            pid,
            exit,
            outlet,
            closing: AtomicBool::new(false),
        }))
    }

    /// Hand the session to a new page (the old one reloaded): from now on output goes to
    /// `on_output` and the exit report to `on_exit`. `on_output` first gets the terminal modes the
    /// TUI has switched on, so a fresh terminal matches it; call [`Session::repaint`] next.
    /// Returns `false`, and changes nothing, once the exit has been reported: that TUI is over.
    pub fn reattach(
        &self,
        on_output: impl FnMut(Vec<u8>) + Send + 'static,
        on_exit: impl FnOnce(ExitInfo) + Send + 'static,
    ) -> bool {
        let mut on_output: Box<dyn FnMut(Vec<u8>) + Send> = Box::new(on_output);
        let on_exit: Box<dyn FnOnce(ExitInfo) + Send> = Box::new(on_exit);
        let (old_output, old_exit) = {
            let mut outlet = self.outlet.lock().unwrap_or_else(|e| e.into_inner());
            if outlet.exit.is_none() {
                return false;
            }
            let replay = outlet.modes.replay();
            if !replay.is_empty() {
                on_output(replay);
            }
            (
                std::mem::replace(&mut outlet.output, on_output),
                outlet.exit.replace(on_exit),
            )
        };
        // The old page's channels go away outside the lock.
        drop((old_output, old_exit));
        true
    }

    /// Make the TUI paint its whole screen again, at `cols` x `rows`. A terminal program
    /// redraws everything when its size changes, and SIGWINCH comes only with a real change: if
    /// the PTY already has this size, it is made one row smaller for [`REPAINT_NUDGE`] first.
    pub fn repaint(self: &Arc<Self>, cols: u16, rows: u16) -> Result<(), String> {
        let wanted = pty_size(cols, rows);
        if self.size().is_some_and(|size| !same_size(size, wanted)) {
            return self.resize(cols, rows);
        }
        let nudge = if wanted.rows > 1 {
            pty_size(wanted.cols, wanted.rows - 1)
        } else {
            pty_size(wanted.cols + 1, wanted.rows)
        };
        self.resize(nudge.cols, nudge.rows)?;
        let session = Arc::clone(self);
        spawn_thread("tau-chat-pty-repaint", move || {
            std::thread::sleep(REPAINT_NUDGE);
            // A resize from the page in the meantime already made the TUI repaint.
            if session.exited().is_none() && session.size().is_some_and(|s| same_size(s, nudge)) {
                let _ = session.resize(wanted.cols, wanted.rows);
            }
        })
    }

    /// The PTY's size now.
    pub fn size(&self) -> Option<PtySize> {
        self.master
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get_size()
            .ok()
    }

    /// The TUI's pid, which is also its process group id.
    pub fn pid(&self) -> u32 {
        self.pid
    }

    /// Keys, pastes and mouse reports from xterm.js, as bytes. This blocks while the PTY's
    /// input queue is full (a TUI that stopped reading), so callers keep it off the main thread.
    pub fn write(&self, bytes: &[u8]) -> std::io::Result<()> {
        write_all(&self.writer, bytes)
    }

    /// The window was resized: tell the PTY, which sends the TUI SIGWINCH.
    pub fn resize(&self, cols: u16, rows: u16) -> Result<(), String> {
        self.master
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .resize(pty_size(cols, rows))
            .map_err(|err| format!("the PTY could not be resized: {err}"))
    }

    /// The exit status, once the TUI has exited.
    pub fn exited(&self) -> Option<ExitInfo> {
        self.exit
            .status
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    /// Mark the session as closing; `true` only for the first caller.
    pub fn begin_closing(&self) -> bool {
        !self.closing.swap(true, Ordering::SeqCst)
    }

    /// Whether the window is closing this session.
    pub fn is_closing(&self) -> bool {
        self.closing.load(Ordering::SeqCst)
    }

    /// Quit the TUI the way a person would: ctrl+q, then up to `grace` for it to exit. If it is
    /// still there, kill its whole process group, so nothing it started stays behind.
    pub fn shutdown(&self, grace: Duration) -> Shutdown {
        if self.exited().is_some() {
            return Shutdown::AlreadyExited;
        }
        // From its own thread: a hung TUI with a full input queue must not stall the kill.
        let writer = Arc::clone(&self.writer);
        let _ = spawn_thread("tau-chat-pty-quit", move || {
            let _ = write_all(&writer, &[QUIT_KEY]);
        });
        if self.exit.wait(grace).is_some() {
            return Shutdown::Quit;
        }
        {
            // Reaping happens only under this lock, so while the status is unset the pid (and
            // the group id) still belongs to our child, alive or a zombie.
            let status = self.exit.status.lock().unwrap_or_else(|e| e.into_inner());
            if status.is_none() {
                // SAFETY: killpg(2) on our own child's process group, see above.
                unsafe {
                    libc::killpg(self.pid as libc::pid_t, libc::SIGKILL);
                }
            }
        }
        self.exit.wait(Duration::from_secs(2));
        Shutdown::Killed
    }
}

fn same_size(a: PtySize, b: PtySize) -> bool {
    (a.cols, a.rows) == (b.cols, b.rows)
}

/// A PTY size from xterm.js's grid, clamped to something every terminal program survives.
pub fn pty_size(cols: u16, rows: u16) -> PtySize {
    PtySize {
        cols: cols.clamp(2, 1000),
        rows: rows.clamp(1, 1000),
        pixel_width: 0,
        pixel_height: 0,
    }
}

fn write_all(writer: &Mutex<Box<dyn Write + Send>>, bytes: &[u8]) -> std::io::Result<()> {
    let mut writer = writer.lock().unwrap_or_else(|e| e.into_inner());
    writer.write_all(bytes)?;
    writer.flush()
}

fn spawn_thread(name: &str, f: impl FnOnce() + Send + 'static) -> Result<(), String> {
    std::thread::Builder::new()
        .name(name.into())
        .spawn(f)
        .map(|_| ())
        .map_err(|err| format!("{name} could not start: {err}"))
}

fn read_loop(mut reader: Box<dyn Read + Send>, chunks: mpsc::Sender<Vec<u8>>) {
    let mut buf = vec![0u8; READ_BUFFER];
    loop {
        match reader.read(&mut buf) {
            // EOF (portable-pty maps the EIO of a closed slave to 0).
            Ok(0) => return,
            Ok(n) => {
                if chunks.send(buf[..n].to_vec()).is_err() {
                    return;
                }
            }
            Err(err) if err.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return,
        }
    }
}

/// Pass chunks from `chunks` to `sink`, in order and byte for byte, in batches: a chunk that
/// arrives after a quiet spell goes out at once (a key's echo is not delayed), while output that
/// keeps coming is gathered into at most one batch per `window`, each at most `max_batch` bytes
/// (unless a single chunk is bigger). Returns when the sender is gone and everything is sent.
pub fn forward(
    chunks: Receiver<Vec<u8>>,
    window: Duration,
    max_batch: usize,
    mut sink: impl FnMut(Vec<u8>),
) {
    let mut last_sent: Option<Instant> = None;
    let mut carry: Option<Vec<u8>> = None;
    loop {
        let mut batch = match carry.take() {
            Some(chunk) => chunk,
            None => match chunks.recv() {
                Ok(chunk) => chunk,
                Err(_) => return,
            },
        };
        let deadline = match last_sent {
            Some(sent) if sent.elapsed() < window => sent + window,
            _ => Instant::now(),
        };
        let mut open = true;
        while batch.len() < max_batch {
            let next = match chunks.try_recv() {
                Ok(chunk) => Some(chunk),
                Err(TryRecvError::Disconnected) => {
                    open = false;
                    None
                }
                Err(TryRecvError::Empty) => {
                    let now = Instant::now();
                    if now >= deadline {
                        None
                    } else {
                        match chunks.recv_timeout(deadline - now) {
                            Ok(chunk) => Some(chunk),
                            Err(RecvTimeoutError::Timeout) => None,
                            Err(RecvTimeoutError::Disconnected) => {
                                open = false;
                                None
                            }
                        }
                    }
                }
            };
            let Some(chunk) = next else { break };
            if batch.len() + chunk.len() > max_batch {
                carry = Some(chunk);
                break;
            }
            batch.extend_from_slice(&chunk);
        }
        sink(batch);
        last_sent = Some(Instant::now());
        if !open && carry.is_none() {
            // Anything still queued arrived before the disconnect was seen.
            while let Ok(chunk) = chunks.try_recv() {
                sink(chunk);
            }
            return;
        }
    }
}

/// Block until the child exits, then reap it under the exit lock and publish the status.
fn wait_for_exit(pid: u32, mut child: Box<dyn Child + Send + Sync>, exit: &ExitState) -> ExitInfo {
    wait_without_reaping(pid);
    let mut status = exit.status.lock().unwrap_or_else(|e| e.into_inner());
    let info = match child.wait() {
        Ok(code) => ExitInfo::from(code),
        Err(_) => ExitInfo {
            success: false,
            code: None,
            signal: None,
        },
    };
    *status = Some(info.clone());
    exit.changed.notify_all();
    info
}

/// `waitid(WEXITED | WNOWAIT)`: returns once `pid` has exited, leaving it a zombie.
fn wait_without_reaping(pid: u32) {
    loop {
        // SAFETY: a zeroed siginfo_t is a valid out-parameter for waitid(2).
        let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
        let rc = unsafe {
            libc::waitid(
                libc::P_PID,
                pid as libc::id_t,
                &mut info,
                libc::WEXITED | libc::WNOWAIT,
            )
        };
        if rc == 0 {
            return;
        }
        if std::io::Error::last_os_error().kind() != std::io::ErrorKind::Interrupted {
            // ECHILD and friends: nothing to wait for; `child.wait()` reports what it can.
            return;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::path::PathBuf;
    use std::sync::mpsc::Sender;

    const TURKISH: &str = "ğüşıöç ĞÜŞİÖÇ ─│┌┐└┘";

    // --- forward: the output batcher -----------------------------------------------------

    fn collect(window: Duration, max: usize, feed: impl FnOnce(Sender<Vec<u8>>)) -> Vec<Vec<u8>> {
        let (tx, rx) = mpsc::channel();
        let (out_tx, out_rx) = mpsc::channel();
        let handle = std::thread::spawn(move || {
            forward(rx, window, max, move |batch| out_tx.send(batch).unwrap())
        });
        feed(tx);
        handle.join().unwrap();
        out_rx.iter().collect()
    }

    #[test]
    fn split_utf8_passes_through_byte_for_byte() {
        let bytes = TURKISH.as_bytes().to_vec();
        // Cut inside multi-byte characters: 1-byte chunks and odd offsets.
        for cut in [1usize, 3, 5, 7] {
            let chunks: Vec<Vec<u8>> = bytes.chunks(cut).map(<[u8]>::to_vec).collect();
            let batches = collect(BATCH_WINDOW, MAX_BATCH, |tx| {
                for chunk in chunks {
                    tx.send(chunk).unwrap();
                }
            });
            let joined: Vec<u8> = batches.concat();
            assert_eq!(joined, bytes, "cut {cut}");
            assert_eq!(String::from_utf8(joined).unwrap(), TURKISH);
        }
    }

    #[test]
    fn a_chunk_after_a_quiet_spell_goes_out_at_once() {
        let (tx, rx) = mpsc::channel();
        let (out_tx, out_rx) = mpsc::channel();
        let handle = std::thread::spawn(move || {
            forward(rx, Duration::from_secs(5), MAX_BATCH, move |b| {
                out_tx.send(b).unwrap()
            })
        });
        let started = Instant::now();
        tx.send(b"a".to_vec()).unwrap();
        let first = out_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert_eq!(first, b"a");
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "the echo waited"
        );
        drop(tx);
        handle.join().unwrap();
    }

    #[test]
    fn output_that_keeps_coming_is_batched_per_window() {
        let (tx, rx) = mpsc::channel();
        let (out_tx, out_rx) = mpsc::channel();
        let handle = std::thread::spawn(move || {
            forward(rx, Duration::from_millis(200), MAX_BATCH, move |b| {
                out_tx.send(b).unwrap()
            })
        });
        tx.send(b"first".to_vec()).unwrap();
        assert_eq!(
            out_rx.recv_timeout(Duration::from_secs(2)).unwrap(),
            b"first"
        );
        // Inside the window of the last send: these three leave together.
        for part in [&b"a"[..], b"b", b"c"] {
            tx.send(part.to_vec()).unwrap();
        }
        assert_eq!(out_rx.recv_timeout(Duration::from_secs(2)).unwrap(), b"abc");
        drop(tx);
        handle.join().unwrap();
        assert!(out_rx.try_recv().is_err());
    }

    #[test]
    fn batches_stay_under_the_cap_and_keep_the_order() {
        let batches = collect(Duration::from_millis(50), 4, |tx| {
            for part in [&b"ab"[..], b"cd", b"ef", b"g", b"hijkl"] {
                tx.send(part.to_vec()).unwrap();
            }
        });
        assert_eq!(batches.concat(), b"abcdefghijkl");
        // The 5-byte chunk goes alone; nothing else exceeds the cap.
        assert!(batches.iter().all(|b| b.len() <= 4 || b == b"hijkl"));
    }

    // --- Session: a real PTY with /bin/sh as a stand-in TUI ---------------------------

    fn sh(script: &str) -> Launch {
        let mut env = BTreeMap::new();
        env.insert("PATH".to_string(), "/usr/bin:/bin".to_string());
        env.insert("TERM".to_string(), "xterm-256color".to_string());
        env.insert("LANG".to_string(), "en_US.UTF-8".to_string());
        Launch {
            program: PathBuf::from("/bin/sh"),
            args: vec!["-c".into(), script.into()],
            cwd: std::env::temp_dir(),
            env,
        }
    }

    struct Running {
        session: Arc<Session>,
        output: Arc<Mutex<Vec<u8>>>,
        exits: Receiver<ExitInfo>,
    }

    impl Running {
        fn start(launch: Launch) -> Self {
            let output = Arc::new(Mutex::new(Vec::new()));
            let sink = Arc::clone(&output);
            let (exit_tx, exits) = mpsc::channel();
            let session = Session::spawn(
                &launch,
                pty_size(80, 24),
                move |batch| sink.lock().unwrap().extend(batch),
                move |info| exit_tx.send(info).unwrap(),
            )
            .unwrap();
            Self {
                session,
                output,
                exits,
            }
        }

        fn text(&self) -> String {
            String::from_utf8_lossy(&self.output.lock().unwrap()).into_owned()
        }

        fn wait_for(&self, needle: &str) -> String {
            self.wait_for_after(0, needle)
        }

        /// Wait for `needle` in the output after its first `start` bytes.
        fn wait_for_after(&self, start: usize, needle: &str) -> String {
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                let text = self.text();
                if text.get(start..).is_some_and(|tail| tail.contains(needle)) {
                    return text;
                }
                assert!(Instant::now() < deadline, "no {needle:?} in {text:?}");
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }

    fn alive(pid: i32) -> bool {
        unsafe { libc::kill(pid, 0) == 0 }
    }

    fn wait_gone(pid: i32) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while alive(pid) {
            assert!(Instant::now() < deadline, "pid {pid} survived");
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    #[test]
    fn runs_in_a_pty_with_exactly_the_given_environment() {
        let run = Running::start(sh("[ -t 0 ] && echo tty-yes; env; echo done-env"));
        let text = run.wait_for("done-env");
        assert!(text.contains("tty-yes"), "{text}");
        assert!(text.contains("TERM=xterm-256color"), "{text}");
        assert!(text.contains("LANG=en_US.UTF-8"), "{text}");
        // Nothing from the test process's environment leaks in (portable-pty adds SHELL).
        let names: Vec<&str> = text
            .lines()
            .filter_map(|l| l.split_once('=').map(|(k, _)| k.trim()))
            .collect();
        for name in names {
            assert!(
                ["PATH", "TERM", "LANG", "SHELL", "PWD", "SHLVL", "_", "OLDPWD"].contains(&name),
                "unexpected variable {name} in {text}"
            );
        }
        let info = run.exits.recv_timeout(Duration::from_secs(10)).unwrap();
        assert_eq!(
            info,
            ExitInfo {
                success: true,
                code: Some(0),
                signal: None
            }
        );
    }

    #[test]
    fn turkish_output_survives_the_pty_and_the_batcher() {
        let run = Running::start(sh(&format!("printf '%s' '{TURKISH}'; printf ' END'")));
        let text = run.wait_for(" END");
        assert!(text.contains(TURKISH), "{text}");
        assert!(!text.contains('\u{FFFD}'), "{text}");
    }

    #[test]
    fn typed_turkish_reaches_the_child() {
        let run = Running::start(sh("echo ready; read line; echo \"got:$line\""));
        run.wait_for("ready");
        run.session
            .write(format!("{TURKISH}\n").as_bytes())
            .unwrap();
        run.wait_for(&format!("got:{TURKISH}"));
    }

    #[test]
    fn resize_reaches_the_child() {
        let run = Running::start(sh("echo ready; read line; stty size"));
        run.wait_for("ready");
        run.session.resize(120, 40).unwrap();
        run.session.write(b"\n").unwrap();
        run.wait_for("40 120");
    }

    #[test]
    fn shutdown_sends_ctrl_q_and_the_tui_quits() {
        // Raw mode like Textual's, then quit on the first byte, as the TUI does on ctrl+q.
        // It exits 0 only when the byte it reads is ctrl+q (0x11).
        let run = Running::start(sh("stty raw -echo; echo ready; \
             key=$(dd bs=1 count=1 2>/dev/null | od -An -tx1 | tr -d ' \\n'); \
             stty sane; [ \"$key\" = 11 ] && exit 0; exit 3"));
        run.wait_for("ready");
        let started = Instant::now();
        assert_eq!(run.session.shutdown(Duration::from_secs(5)), Shutdown::Quit);
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(run.session.exited().unwrap().success);
        assert_eq!(run.session.shutdown(QUIT_GRACE), Shutdown::AlreadyExited);
        wait_gone(run.session.pid() as i32);
    }

    #[test]
    fn shutdown_kills_the_group_when_ctrl_q_is_ignored() {
        // A TUI that never quits, with a child of its own in the same process group.
        let run = Running::start(sh(
            "trap '' HUP INT TERM; sleep 60 & echo \"child:$!:\"; while :; do sleep 1; done",
        ));
        let text = run.wait_for(":\r\n");
        let child: i32 = text
            .split("child:")
            .nth(1)
            .and_then(|rest| rest.split(':').next())
            .and_then(|pid| pid.trim().parse().ok())
            .unwrap_or_else(|| panic!("no child pid in {text:?}"));
        let leader = run.session.pid() as i32;
        assert!(alive(leader) && alive(child));
        let started = Instant::now();
        assert_eq!(
            run.session.shutdown(Duration::from_millis(300)),
            Shutdown::Killed
        );
        assert!(started.elapsed() >= Duration::from_millis(300));
        let info = run.exits.recv_timeout(Duration::from_secs(10)).unwrap();
        assert!(info.signal.is_some() && !info.success, "{info:?}");
        wait_gone(leader);
        wait_gone(child);
    }

    /// What a second page sees of a session: its own output buffer and exit channel.
    type Page = (Arc<Mutex<Vec<u8>>>, Receiver<ExitInfo>);

    fn attach(session: &Session) -> Option<Page> {
        let output = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&output);
        let (exit_tx, exits) = mpsc::channel();
        session
            .reattach(
                move |batch| sink.lock().unwrap().extend(batch),
                move |info| exit_tx.send(info).unwrap(),
            )
            .then_some((output, exits))
    }

    fn wait_in(buffer: &Mutex<Vec<u8>>, needle: &str) -> String {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let text = String::from_utf8_lossy(&buffer.lock().unwrap()).into_owned();
            if text.contains(needle) {
                return text;
            }
            assert!(Instant::now() < deadline, "no {needle:?} in {text:?}");
            std::thread::sleep(Duration::from_millis(10));
        }
    }

    #[test]
    fn a_reloaded_page_takes_over_the_running_tui() {
        // Switches modes like Textual, then waits for two lines of input.
        let run = Running::start(sh(
            "printf '\\033[?1049h\\033[?1000;1006h\\033[?25l'; echo first; \
             read a; echo \"second:$a\"; read b; exit 0",
        ));
        run.wait_for("first");
        let (output, exits) = attach(&run.session).expect("the TUI is running");
        // The new terminal is put into the TUI's modes before anything else reaches it.
        assert!(
            output
                .lock()
                .unwrap()
                .starts_with(b"\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1006h"),
            "{:?}",
            String::from_utf8_lossy(&output.lock().unwrap())
        );
        run.session.write(b"hello\n").unwrap();
        wait_in(&output, "second:hello");
        assert!(!run.text().contains("second:"), "{}", run.text());
        // The exit report goes to the new page, and nobody can take over a finished TUI.
        run.session.write(b"\n").unwrap();
        let info = exits.recv_timeout(Duration::from_secs(10)).unwrap();
        assert!(info.success, "{info:?}");
        assert!(run.exits.try_recv().is_err());
        assert!(attach(&run.session).is_none());
    }

    #[test]
    fn repaint_gives_the_tui_a_real_size_change() {
        let run = Running::start(sh(
            "trap 'echo \"size:$(stty size)\"' WINCH; echo ready; while :; do sleep 0.02; done",
        ));
        run.wait_for("ready");
        // A new size: one change, no nudge.
        run.session.repaint(100, 30).unwrap();
        run.wait_for("size:30 100");
        std::thread::sleep(REPAINT_NUDGE * 2);
        let before = run.text().len();
        assert_eq!(run.text().matches("size:").count(), 1, "{}", run.text());
        // The same size: one row smaller for a moment, then back.
        run.session.repaint(100, 30).unwrap();
        let text = run.wait_for_after(before, "size:30 100");
        let tail = &text[before..];
        let smaller = tail.find("size:29 100").expect(tail);
        assert!(smaller < tail.find("size:30 100").unwrap(), "{tail}");
        let size = run.session.size().unwrap();
        assert_eq!((size.cols, size.rows), (100, 30));
        run.session.shutdown(Duration::from_millis(100));
    }

    #[test]
    fn closing_is_claimed_once() {
        let run = Running::start(sh("sleep 5"));
        assert!(!run.session.is_closing());
        assert!(run.session.begin_closing());
        assert!(!run.session.begin_closing());
        assert!(run.session.is_closing());
        run.session.shutdown(Duration::from_millis(100));
    }

    #[test]
    fn refuses_a_missing_home_or_python() {
        let mut launch = sh("true");
        launch.cwd = PathBuf::from("/nonexistent/tau");
        let err = Session::spawn(&launch, pty_size(80, 24), |_| {}, |_| {})
            .err()
            .unwrap();
        assert!(err.contains("TAU_HOME is not a folder"), "{err}");
        let mut launch = sh("true");
        launch.program = PathBuf::from("/nonexistent/tau/.venv/bin/python");
        let err = Session::spawn(&launch, pty_size(80, 24), |_| {}, |_| {})
            .err()
            .unwrap();
        assert!(err.contains("Python does not exist"), "{err}");
    }

    #[test]
    fn sizes_are_clamped() {
        let size = pty_size(0, 0);
        assert_eq!((size.cols, size.rows), (2, 1));
        let size = pty_size(5000, 5000);
        assert_eq!((size.cols, size.rows), (1000, 1000));
    }
}
