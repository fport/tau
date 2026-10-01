//! The first-launch wizard (ADR 0014 §2 and §5, roadmap 171): the app's front door to
//! `tau setup`, over its JSON protocol (`docs/reference/setup.md`).
//!
//! - **The window** (`wizard`, `index.html#wizard`, `capabilities/wizard.json`) opens on the
//!   app's first start, while tau is not set up, and from "Set up tau…" in the menus, the panel
//!   and the settings window.
//! - **Discovery** (`discover.rs`) finds tau (a `uv tool install`, a checkout, a `tau` command)
//!   and writes it into the hub settings and the chat windows' `chat.json`; without one the
//!   wizard installs uv and tau (`jobs.rs`).
//! - **Jobs** (`jobs.rs`, `runner.rs`): `tau setup status|install|run --json`, `tau telegram
//!   pair --json` and `tau net spine deploy --json`, one at a time, input on stdin, events
//!   streamed to the page over a channel.
//! - **Interactive steps** that need a terminal (the guard's enrolment, which holds the camera
//!   through the app) run in the wizard's own PTY, the chat windows' machinery.
//! - **Permissions** (`crate::permissions`): asked only for the chosen features.

pub mod commands;
pub mod discover;
pub mod jobs;
pub mod jsonl;
pub mod runner;

use crate::chat::pty::QUIT_GRACE;
use crate::chat::Chats;
use crate::webview;
use discover::Found;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent};

/// The wizard window's label (`capabilities/wizard.json`).
pub const WINDOW: &str = "wizard";
/// The page it shows (`src/main.tsx` picks the wizard by the hash).
const PAGE: &str = "index.html#wizard";

/// The wizard's state in the app: the tau discovery found, uv, and the running job.
#[derive(Default)]
pub struct Wizard {
    tau: Mutex<Option<Found>>,
    uv: Mutex<Option<PathBuf>>,
    /// The cancel flag of the job that runs now; one job at a time.
    job: Mutex<Option<Arc<AtomicBool>>>,
}

impl Wizard {
    pub fn tau(&self) -> Option<Found> {
        self.tau.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn set_found(&self, tau: Option<Found>, uv: Option<PathBuf>) {
        *self.tau.lock().unwrap_or_else(|e| e.into_inner()) = tau;
        *self.uv.lock().unwrap_or_else(|e| e.into_inner()) = uv;
    }

    pub fn uv(&self) -> Option<PathBuf> {
        self.uv.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Claim the job slot; `Err` while another job runs. The flag cancels the new job.
    fn begin_job(&self) -> Result<JobSlot<'_>, String> {
        let mut job = self.job.lock().unwrap_or_else(|e| e.into_inner());
        if job.is_some() {
            return Err("Another step is still running.".into());
        }
        let cancel = Arc::new(AtomicBool::new(false));
        *job = Some(cancel.clone());
        Ok(JobSlot {
            wizard: self,
            cancel,
        })
    }

    /// Stop the running job, if any (SIGINT, then SIGKILL).
    pub fn cancel(&self) {
        if let Some(cancel) = self.job.lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
            cancel.store(true, Ordering::SeqCst);
        }
    }
}

/// The running job's place: freed when dropped, whatever way the job ended.
struct JobSlot<'a> {
    wizard: &'a Wizard,
    cancel: Arc<AtomicBool>,
}

impl Drop for JobSlot<'_> {
    fn drop(&mut self) {
        *self.wizard.job.lock().unwrap_or_else(|e| e.into_inner()) = None;
    }
}

/// Show the wizard (a new window, or the open one in front).
pub fn open(app: &AppHandle) {
    crate::panel::hide(app);
    if let Some(window) = app.get_webview_window(WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }
    let built = WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::App(PAGE.into()))
        .title("Set up tau")
        .inner_size(880.0, 640.0)
        .min_inner_size(700.0, 520.0)
        .center()
        .focused(true)
        // The app holds the camera grant; the wizard's page may not use it (ADR 0008).
        .on_permission_request(|_, kind| webview::permission(kind))
        .on_navigation(crate::chat::is_app_url)
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .disable_drag_drop_handler()
        .build();
    match built {
        Ok(window) => {
            let _ = window.set_focus();
            crate::log(app, "setup wizard opened");
        }
        Err(err) => crate::log(app, format!("the setup wizard could not open: {err}")),
    }
}

/// The wizard window's events: closing it stops its job and its terminal.
pub fn on_window_event(window: &tauri::Window, event: &WindowEvent) {
    if window.label() != WINDOW || !matches!(event, WindowEvent::Destroyed) {
        return;
    }
    let app = window.app_handle();
    app.state::<Wizard>().cancel();
    if let Some(session) = app.state::<Chats>().remove_session(WINDOW) {
        if session.exited().is_none() {
            std::thread::spawn(move || {
                session.begin_closing();
                session.shutdown(QUIT_GRACE);
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_job_at_a_time_and_the_slot_frees_itself() {
        let wizard = Wizard::default();
        let slot = wizard.begin_job().unwrap();
        assert!(wizard.begin_job().is_err());
        wizard.cancel();
        assert!(slot.cancel.load(Ordering::SeqCst));
        drop(slot);
        let again = wizard.begin_job().unwrap();
        assert!(
            !again.cancel.load(Ordering::SeqCst),
            "a new job starts uncancelled"
        );
    }

    /// The capability that grants the wizard's commands names exactly its window.
    #[test]
    fn the_wizard_capability_matches_the_window_label() {
        let path =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("capabilities/wizard.json");
        let text = std::fs::read_to_string(path).unwrap();
        let capability: serde_json::Value = serde_json::from_str(&text).unwrap();
        assert_eq!(capability["windows"], serde_json::json!([WINDOW]));
        let permissions = capability["permissions"].as_array().unwrap();
        // It never gets the settings window's free-form hub settings, nor a shell or dialog.
        for denied in [
            "allow-save-hub-settings",
            "dialog:allow-open",
            "core:default",
        ] {
            assert!(
                !permissions.iter().any(|p| p == denied),
                "the wizard must not have {denied}"
            );
        }
    }
}
