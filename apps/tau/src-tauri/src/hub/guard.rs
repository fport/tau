//! The owner guard as the app shows it (ADR 0008, issue 115).
//!
//! - [`parse`] reads the `guard` block of the hub's open `/status`:
//!   `{state, enrolled, available, reason}`. Nothing else about the guard is open.
//! - [`menu`] turns it into what the menu and the window show: a guard line ("Guard: locked",
//!   "Guard: unavailable (camera denied)"), "Lock now", and "Grant camera access…" when the
//!   hub cannot use the camera. All of it is hidden without a guard block or with `off`.
//!   [`panel_text`] is the same line without its label, for the panel's guard row.
//! - [`lock`] sends `POST /guard/lock` through the signed [`ControlClient`].
//!
//! The app never unlocks: the check runs in the hub (under the app's camera grant), and no
//! route takes a verdict. The open `/status` can come from any local process that holds the
//! port, so the supervisor passes its guard block on only while the hub itself answers
//! (the app's own hub is up, or the pid that answers holds the hub lock), the state must be
//! one of [`STATES`] and the reason must have tau-core's shape, and "Lock now" trusts only a
//! proven answer.

use super::control::ControlClient;
use serde::Serialize;
use serde_json::{json, Value};
use std::time::Duration;

/// The states tau-core's `GUARD_STATES` lists.
pub const STATES: [&str; 5] = ["off", "locked", "verifying", "unlocked", "unavailable"];
/// The reasons that mean the hub cannot use the camera, so System Settings can help.
pub const CAMERA_REASONS: [&str; 2] = ["camera_denied", "camera_unavailable"];
/// System Settings → Privacy & Security → Camera.
pub const CAMERA_SETTINGS_URL: &str =
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera";
/// The audit label of the app's guard requests (`channel` in the route bodies).
pub const CHANNEL: &str = "app";
pub const LOCK_PATH: &str = "/guard/lock";
/// tau-core's `REQUEST_TIMEOUT` for guard calls.
pub const LOCK_TIMEOUT: Duration = Duration::from_secs(5);
/// Longest reason shown in the menu.
const MAX_REASON: usize = 48;

/// The `guard` block of `/status`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct GuardStatus {
    /// One of [`STATES`], or `unknown` for anything else.
    pub state: String,
    pub enrolled: bool,
    pub available: bool,
    /// A snake_case reason (`camera_denied`); anything else is dropped.
    pub reason: Option<String>,
}

/// The guard block of a `/status` payload; `None` when there is none (no guard service, an
/// older hub) or it is not an object.
pub fn parse(status: &Value) -> Option<GuardStatus> {
    let block = status.get("guard")?.as_object()?;
    let state = block
        .get("state")
        .and_then(Value::as_str)
        .filter(|state| STATES.contains(state))
        .unwrap_or("unknown")
        .to_string();
    let flag = |key: &str| block.get(key).and_then(Value::as_bool).unwrap_or(false);
    let reason = block
        .get("reason")
        .and_then(Value::as_str)
        .filter(|reason| is_reason(reason))
        .map(str::to_string);
    Some(GuardStatus {
        state,
        enrolled: flag("enrolled"),
        available: flag("available"),
        reason,
    })
}

/// A reason as tau-core writes them: 1–48 characters of `a-z`, `0-9` and `_`.
fn is_reason(text: &str) -> bool {
    (1..=MAX_REASON).contains(&text.len())
        && text
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// What the menu and the window show about the guard.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct GuardMenu {
    /// The guard line; `None` hides the whole guard section.
    pub line: Option<String>,
    /// Show "Lock now".
    pub lock_now: bool,
    /// Show "Grant camera access…".
    pub grant_camera: bool,
}

pub fn menu(guard: Option<&GuardStatus>) -> GuardMenu {
    let Some(guard) = guard.filter(|g| g.state != "off") else {
        return GuardMenu::default();
    };
    GuardMenu {
        line: Some(line(guard)),
        // Always offered while a guard runs: locking is idempotent, and the menu may lag the
        // hub by a poll.
        lock_now: true,
        grant_camera: guard
            .reason
            .as_deref()
            .is_some_and(|reason| CAMERA_REASONS.contains(&reason)),
    }
}

/// "Guard: locked", "Guard: unavailable (camera denied)", "Guard: locked (not enrolled)".
pub fn line(guard: &GuardStatus) -> String {
    format!("Guard: {}", text(guard))
}

/// The panel's guard row (the panel shows the label itself): `None` without a guard block or
/// with `off`, like the menu's guard section.
pub fn panel_text(guard: Option<&GuardStatus>) -> Option<String> {
    guard.filter(|g| g.state != "off").map(text)
}

/// The guard's state without the label: "locked", "unavailable (camera denied)".
pub fn text(guard: &GuardStatus) -> String {
    let state = match guard.state.as_str() {
        "locked" => "locked",
        "verifying" => "checking…",
        "unlocked" => "unlocked",
        "unavailable" => "unavailable",
        "off" => "off",
        _ => "unknown state",
    };
    let detail = match &guard.reason {
        Some(reason) => Some(reason.replace('_', " ")),
        None if !guard.enrolled && guard.state != "unlocked" => Some("not enrolled".into()),
        None if !guard.available && guard.state != "unavailable" => Some("cannot check now".into()),
        None => None,
    };
    match detail {
        Some(detail) => format!("{state} ({detail})"),
        None => state.to_string(),
    }
}

/// The body of `POST /guard/lock` from the app.
pub fn lock_body(client_id: &str) -> Value {
    json!({"channel": CHANNEL, "client_id": client_id, "trigger": "command"})
}

/// Ask the hub to lock. `Ok` only for a proven `{"state": "locked"}`.
pub fn lock(client: &ControlClient, client_id: &str) -> Result<(), String> {
    let answer = client
        .post(LOCK_PATH, &lock_body(client_id))
        .map_err(|err| err.to_string())?;
    if answer.get("state").and_then(Value::as_str) == Some("locked") {
        return Ok(());
    }
    let text = answer.to_string();
    let text: String = text.chars().take(120).collect();
    Err(format!(
        "the hub did not confirm the lock (it answered {text})"
    ))
}

/// A random id for this app process: an audit label, never a claim (like tau-core's
/// `process_client_id`).
pub fn new_client_id() -> String {
    super::control::random_hex(8).unwrap_or_else(|_| format!("pid{}", std::process::id()))
}

#[cfg(test)]
mod tests {
    use super::super::control::tests::{authorized, signed, tmpdir, FakeHub};
    use super::super::control::TOKEN_FILE;
    use super::*;

    fn guard(state: &str, reason: Option<&str>) -> Value {
        json!({"pid": 1, "guard": {"state": state, "enrolled": true, "available": true,
            "reason": reason}})
    }

    fn menu_for(status: &Value) -> GuardMenu {
        menu(parse(status).as_ref())
    }

    #[test]
    fn no_guard_block_hides_everything() {
        for status in [
            json!({"pid": 1, "telegram": {}}),
            json!({"guard": null}),
            json!({"guard": "locked"}),
            json!({"guard": []}),
        ] {
            assert_eq!(parse(&status), None, "{status}");
            assert_eq!(menu_for(&status), GuardMenu::default());
        }
    }

    #[test]
    fn off_hides_everything() {
        let status = guard("off", None);
        assert_eq!(parse(&status).unwrap().state, "off");
        assert_eq!(menu_for(&status), GuardMenu::default());
    }

    #[test]
    fn locked_and_unlocked_show_the_line_and_lock_now() {
        let locked = menu_for(&guard("locked", None));
        assert_eq!(locked.line.as_deref(), Some("Guard: locked"));
        assert!(locked.lock_now && !locked.grant_camera);
        let unlocked = menu_for(&guard("unlocked", None));
        assert_eq!(unlocked.line.as_deref(), Some("Guard: unlocked"));
        assert!(unlocked.lock_now && !unlocked.grant_camera);
        let verifying = menu_for(&guard("verifying", None));
        assert_eq!(verifying.line.as_deref(), Some("Guard: checking…"));
    }

    #[test]
    fn unavailable_names_its_reason_and_offers_the_camera_pane() {
        let denied = menu_for(&json!({"guard": {"state": "unavailable", "enrolled": true,
            "available": false, "reason": "camera_denied"}}));
        assert_eq!(
            denied.line.as_deref(),
            Some("Guard: unavailable (camera denied)")
        );
        assert!(denied.lock_now && denied.grant_camera);
        let missing = menu_for(&guard("unavailable", Some("camera_unavailable")));
        assert_eq!(
            missing.line.as_deref(),
            Some("Guard: unavailable (camera unavailable)")
        );
        assert!(missing.grant_camera);
        let config = menu_for(&guard("unavailable", Some("bad_config")));
        assert_eq!(
            config.line.as_deref(),
            Some("Guard: unavailable (bad config)")
        );
        assert!(!config.grant_camera);
        // A locked guard whose camera is denied offers the pane too.
        assert!(menu_for(&guard("locked", Some("camera_denied"))).grant_camera);
        let bare = menu_for(&guard("unavailable", None));
        assert_eq!(bare.line.as_deref(), Some("Guard: unavailable"));
    }

    #[test]
    fn missing_fields_fail_towards_saying_less() {
        let status = json!({"guard": {"state": "locked"}});
        let parsed = parse(&status).unwrap();
        assert!(!parsed.enrolled && !parsed.available && parsed.reason.is_none());
        assert_eq!(line(&parsed), "Guard: locked (not enrolled)");
        let cannot = json!({"guard": {"state": "locked", "enrolled": true, "available": false}});
        assert_eq!(
            menu_for(&cannot).line.as_deref(),
            Some("Guard: locked (cannot check now)")
        );
    }

    #[test]
    fn text_from_the_open_status_is_filtered() {
        // Any local process can answer /status on a free port: no free text reaches the menu.
        let status = json!({"guard": {"state": "unlocked\nGuard: fine", "enrolled": true,
            "available": true, "reason": "Click here: http://evil"}});
        let parsed = parse(&status).unwrap();
        assert_eq!(parsed.state, "unknown");
        assert_eq!(parsed.reason, None);
        assert_eq!(
            menu_for(&status).line.as_deref(),
            Some("Guard: unknown state")
        );
        let long = "a".repeat(MAX_REASON + 1);
        assert_eq!(parse(&guard("locked", Some(&long))).unwrap().reason, None);
        assert_eq!(
            parse(&json!({"guard": {"state": 3, "reason": 7}}))
                .unwrap()
                .state,
            "unknown"
        );
    }

    #[test]
    fn the_panel_row_is_the_line_without_its_label() {
        assert_eq!(panel_text(None), None);
        assert_eq!(panel_text(parse(&guard("off", None)).as_ref()), None);
        let denied = parse(&guard("unavailable", Some("camera_denied")));
        assert_eq!(
            panel_text(denied.as_ref()).as_deref(),
            Some("unavailable (camera denied)")
        );
        let locked = parse(&guard("locked", None)).unwrap();
        assert_eq!(panel_text(Some(&locked)).as_deref(), Some("locked"));
        assert_eq!(line(&locked), "Guard: locked");
    }

    #[test]
    fn the_camera_pane_url_is_the_privacy_camera_pane() {
        assert_eq!(
            CAMERA_SETTINGS_URL,
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"
        );
    }

    #[test]
    fn lock_posts_the_signed_body_and_needs_a_proven_locked_answer() {
        let dir = tmpdir("guard-lock");
        std::fs::write(dir.join(TOKEN_FILE), "hub-token").unwrap();
        let mut hub = FakeHub::start(1, |_, seen| {
            if authorized("hub-token", seen) && seen.path == LOCK_PATH {
                signed("hub-token", seen, 200, br#"{"state": "locked"}"#)
            } else {
                (403, vec![], b"{}".to_vec())
            }
        });
        let client = ControlClient::new(hub.port, &dir, LOCK_TIMEOUT);
        assert_eq!(lock(&client, "0123456789abcdef"), Ok(()));
        let seen = hub.requests();
        assert_eq!(seen.len(), 1);
        assert_eq!(
            serde_json::from_slice::<Value>(&seen[0].body).unwrap(),
            json!({"channel": "app", "client_id": "0123456789abcdef", "trigger": "command"})
        );

        let mut hub = FakeHub::start(1, |_, seen| {
            signed("hub-token", seen, 200, br#"{"state": "unlocked"}"#)
        });
        let client = ControlClient::new(hub.port, &dir, LOCK_TIMEOUT);
        let err = lock(&client, "id").unwrap_err();
        assert!(err.contains("did not confirm the lock"), "{err}");
        hub.requests();

        let mut hub = FakeHub::start(1, |_, _| (200, vec![], br#"{"state": "locked"}"#.to_vec()));
        let client = ControlClient::new(hub.port, &dir, LOCK_TIMEOUT);
        let err = lock(&client, "id").unwrap_err();
        assert!(err.contains("no valid proof"), "{err}");
        hub.requests();
    }

    #[test]
    fn client_ids_are_random_hex() {
        let id = new_client_id();
        assert_eq!(id.len(), 16);
        assert!(id.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(id, new_client_id());
    }
}
