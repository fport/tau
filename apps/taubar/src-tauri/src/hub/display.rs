//! The hub lines of the menu (and the window) and the hub rows of the panel, from a
//! [`HubView`].

use super::supervisor::{HubState, HubView};
use serde::Serialize;
use serde_json::Value;

/// The panel's hub rows: the status as a title and a detail, the Telegram poller and the last
/// crash, without the menu's `Label:` prefixes (the panel shows the labels itself).
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct HubPanel {
    pub title: String,
    pub detail: String,
    pub telegram: String,
    pub crash: String,
}

pub fn panel(view: &HubView) -> HubPanel {
    let (title, detail) = status_parts(view);
    HubPanel {
        title,
        detail,
        telegram: view
            .telegram
            .as_ref()
            .map(telegram_text)
            .unwrap_or_else(|| "–".into()),
        crash: crash_text(view),
    }
}

/// `45 s`, `12 min`, `2 h 5 min`, `3 d 4 h`.
pub fn duration(seconds: f64) -> String {
    let s = seconds.max(0.0) as u64;
    match s {
        0..=59 => format!("{s} s"),
        60..=3599 => format!("{} min", s / 60),
        3600..=86_399 => format!("{} h {} min", s / 3600, s % 3600 / 60),
        _ => format!("{} d {} h", s / 86_400, s % 86_400 / 3600),
    }
}

/// First line: is the hub up, and whose is it.
pub fn status_line(view: &HubView) -> String {
    let pid = view.pid.map(|p| format!("pid {p}")).unwrap_or_default();
    let uptime = view.uptime_s.map(duration);
    match view.state {
        HubState::NotConfigured => "Hub: not set up (Settings…)".into(),
        HubState::Off => "Hub: off".into(),
        HubState::Starting => format!("Hub: starting… ({pid})"),
        HubState::Up => match uptime {
            Some(up) => format!("Hub: up {up} · {pid}"),
            None => format!("Hub: up · {pid}"),
        },
        HubState::Stopping => format!("Hub: stopping… ({pid})"),
        HubState::Restarting => format!(
            "Hub: restarting in {} s",
            view.restart_in_s.unwrap_or(0).max(1)
        ),
        HubState::Stopped => "Hub: stopped (exited cleanly)".into(),
        HubState::Elsewhere => {
            let who = if view.launchd {
                "run by launchd"
            } else {
                "started outside TauBar"
            };
            let pid = if pid.is_empty() {
                String::new()
            } else {
                format!(" · {pid}")
            };
            match uptime {
                Some(up) => format!("Hub: up {up}{pid} · {who}"),
                None => format!("Hub: running{pid} · {who}"),
            }
        }
        HubState::LaunchdIdle => "Hub: left to launchd (com.tau.hub is loaded)".into(),
        HubState::Error => "Hub: configuration error (Settings…)".into(),
    }
}

/// The panel's status row: `("Up 2 h 5 min", "pid 1234 · started by TauBar")`.
pub fn status_parts(view: &HubView) -> (String, String) {
    let pid = view.pid.map(|p| format!("pid {p}"));
    let up = |fallback: &str| {
        view.uptime_s
            .map(|s| format!("Up {}", duration(s)))
            .unwrap_or_else(|| fallback.into())
    };
    let with_pid = |rest: &str| match &pid {
        Some(pid) => format!("{pid} · {rest}"),
        None => rest.to_string(),
    };
    match view.state {
        HubState::NotConfigured => (
            "Not set up".into(),
            "Pick the tau checkout in Settings".into(),
        ),
        HubState::Off => ("Off".into(), "Switch it on to start the hub".into()),
        HubState::Starting => (
            "Starting…".into(),
            pid.unwrap_or_else(|| "waiting for the hub".into()),
        ),
        HubState::Up => (up("Up"), with_pid("started by TauBar")),
        HubState::Stopping => ("Stopping…".into(), pid.unwrap_or_default()),
        HubState::Restarting => (
            format!("Restarting in {} s", view.restart_in_s.unwrap_or(0).max(1)),
            match view.restarts {
                0 | 1 => "after an unexpected exit".into(),
                n => format!("after {n} unexpected exits"),
            },
        ),
        HubState::Stopped => ("Stopped".into(), "It exited cleanly (tau hub stop)".into()),
        HubState::Elsewhere => (
            up("Running"),
            with_pid(if view.launchd {
                "run by launchd"
            } else {
                "started outside TauBar"
            }),
        ),
        HubState::LaunchdIdle => ("Left to launchd".into(), "com.tau.hub is loaded".into()),
        HubState::Error => ("Configuration error".into(), "See Settings".into()),
    }
}

/// Second line: the Telegram poller, or what is wrong.
pub fn detail_line(view: &HubView) -> String {
    if let Some(problem) = &view.problem {
        return shorten(&format!("Problem: {problem}"), 72);
    }
    match &view.telegram {
        Some(telegram) => telegram_line(telegram),
        None => "Telegram: –".into(),
    }
}

/// `telegram` from `/status`: `{configured, state, bot, last_error, retry_in_s, reason}`.
pub fn telegram_line(telegram: &Value) -> String {
    shorten(&format!("Telegram: {}", telegram_text(telegram)), 72)
}

/// The poller's state without the label: `polling as @tau_bot`, `off (reason)`.
pub fn telegram_text(telegram: &Value) -> String {
    let text = |key: &str| telegram.get(key).and_then(Value::as_str);
    if telegram.get("configured").and_then(Value::as_bool) == Some(false) {
        return match text("reason") {
            Some(reason) => format!("off ({reason})"),
            None => "off".into(),
        };
    }
    match text("state") {
        Some("polling") => match text("bot") {
            Some(bot) => format!("polling as {bot}"),
            None => "polling".into(),
        },
        Some("retrying") => {
            let retry = telegram
                .get("retry_in_s")
                .and_then(Value::as_f64)
                .map(|s| format!(" in {} s", s.ceil() as u64))
                .unwrap_or_default();
            format!(
                "retrying{retry} ({})",
                text("last_error").unwrap_or("error")
            )
        }
        Some("failed") => format!("stopped ({})", text("last_error").unwrap_or("error")),
        Some(state) => state.into(),
        None => "unknown".into(),
    }
}

/// Third line: the last crash, the hub's own report first, else TauBar's record.
pub fn crash_line(view: &HubView) -> String {
    shorten(&format!("Last crash: {}", crash_text(view)), 72)
}

/// The last crash without the label: `unexpected exit (no clean shutdown), pid 99`, `none`.
pub fn crash_text(view: &HubView) -> String {
    if let Some(crash) = &view.last_crash {
        let reason = crash
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let pid = crash
            .get("pid")
            .and_then(Value::as_u64)
            .map(|p| format!(", pid {p}"))
            .unwrap_or_default();
        return format!("{reason}{pid}");
    }
    if let Some(exit) = &view.last_exit {
        let restarts = if view.restarts > 1 {
            format!(" · {} restarts", view.restarts)
        } else {
            String::new()
        };
        return format!("{} ({}){restarts}", exit.reason, exit.at);
    }
    "none".into()
}

fn shorten(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let cut: String = text.chars().take(max - 1).collect();
    format!("{cut}…")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hub::supervisor::ExitRecord;
    use serde_json::json;

    fn view(state: HubState) -> HubView {
        HubView {
            switch_on: true,
            state,
            pid: Some(1234),
            by_taubar: true,
            launchd: false,
            uptime_s: None,
            restart_in_s: None,
            restarts: 0,
            last_exit: None,
            last_crash: None,
            telegram: None,
            control_url: Some("http://127.0.0.1:7877".into()),
            hub_log: None,
            command: None,
            problem: None,
        }
    }

    #[test]
    fn durations() {
        assert_eq!(duration(4.2), "4 s");
        assert_eq!(duration(125.0), "2 min");
        assert_eq!(duration(7_500.0), "2 h 5 min");
        assert_eq!(duration(3.0 * 86_400.0 + 4.0 * 3600.0), "3 d 4 h");
    }

    #[test]
    fn status_lines() {
        let mut up = view(HubState::Up);
        up.uptime_s = Some(7_500.0);
        assert_eq!(status_line(&up), "Hub: up 2 h 5 min · pid 1234");
        assert_eq!(status_line(&view(HubState::Off)), "Hub: off");
        assert_eq!(
            status_line(&view(HubState::Starting)),
            "Hub: starting… (pid 1234)"
        );
        let mut restarting = view(HubState::Restarting);
        restarting.restart_in_s = Some(2);
        assert_eq!(status_line(&restarting), "Hub: restarting in 2 s");
        let mut elsewhere = view(HubState::Elsewhere);
        elsewhere.uptime_s = Some(30.0);
        assert_eq!(
            status_line(&elsewhere),
            "Hub: up 30 s · pid 1234 · started outside TauBar"
        );
        elsewhere.launchd = true;
        assert!(status_line(&elsewhere).ends_with("run by launchd"));
        assert!(status_line(&view(HubState::NotConfigured)).contains("Settings"));
    }

    #[test]
    fn telegram_lines() {
        assert_eq!(
            telegram_line(&json!({"configured": false, "reason": "TELEGRAM_BOT_TOKEN is not set"})),
            "Telegram: off (TELEGRAM_BOT_TOKEN is not set)"
        );
        assert_eq!(
            telegram_line(&json!({"configured": true, "state": "polling", "bot": "@tau_bot"})),
            "Telegram: polling as @tau_bot"
        );
        assert_eq!(
            telegram_line(
                &json!({"configured": true, "state": "retrying", "retry_in_s": 4.2,
                "last_error": "timeout"})
            ),
            "Telegram: retrying in 5 s (timeout)"
        );
        assert_eq!(
            telegram_line(&json!({"configured": true, "state": "failed", "last_error": "401"})),
            "Telegram: stopped (401)"
        );
    }

    #[test]
    fn detail_prefers_a_problem() {
        let mut v = view(HubState::NotConfigured);
        v.problem = Some("the hub's Python is not set".into());
        assert_eq!(detail_line(&v), "Problem: the hub's Python is not set");
        v.problem = Some("x".repeat(200));
        assert_eq!(detail_line(&v).chars().count(), 72);
        assert_eq!(detail_line(&view(HubState::Off)), "Telegram: –");
    }

    #[test]
    fn panel_status_parts() {
        let mut up = view(HubState::Up);
        up.uptime_s = Some(7_500.0);
        assert_eq!(
            status_parts(&up),
            ("Up 2 h 5 min".into(), "pid 1234 · started by TauBar".into())
        );
        assert_eq!(status_parts(&view(HubState::Off)).0, "Off");
        let mut elsewhere = view(HubState::Elsewhere);
        elsewhere.launchd = true;
        assert_eq!(
            status_parts(&elsewhere),
            ("Running".into(), "pid 1234 · run by launchd".into())
        );
        let mut restarting = view(HubState::Restarting);
        restarting.restart_in_s = Some(4);
        restarting.restarts = 3;
        assert_eq!(
            status_parts(&restarting),
            (
                "Restarting in 4 s".into(),
                "after 3 unexpected exits".into()
            )
        );
        let mut starting = view(HubState::Starting);
        starting.pid = None;
        assert_eq!(status_parts(&starting).1, "waiting for the hub");
    }

    #[test]
    fn panel_rows_drop_the_labels() {
        let mut v = view(HubState::Up);
        assert_eq!(panel(&v).telegram, "–");
        assert_eq!(panel(&v).crash, "none");
        v.telegram = Some(json!({"configured": true, "state": "polling", "bot": "@tau_bot"}));
        v.last_crash = Some(json!({"pid": 99, "reason": "unexpected exit (no clean shutdown)"}));
        let rows = panel(&v);
        assert_eq!(rows.telegram, "polling as @tau_bot");
        assert_eq!(rows.crash, "unexpected exit (no clean shutdown), pid 99");
        // The menu keeps its labelled lines.
        assert_eq!(detail_line(&v), "Telegram: polling as @tau_bot");
        assert_eq!(crash_line(&v), format!("Last crash: {}", rows.crash));
    }

    #[test]
    fn crash_lines() {
        assert_eq!(crash_line(&view(HubState::Up)), "Last crash: none");
        let mut v = view(HubState::Up);
        v.last_exit = Some(ExitRecord {
            at: "2026-09-30 12:00:00".into(),
            pid: 1,
            reason: "killed by SIGKILL".into(),
        });
        v.restarts = 3;
        assert_eq!(
            crash_line(&v),
            "Last crash: killed by SIGKILL (2026-09-30 12:00:00) · 3 restarts"
        );
        v.last_crash = Some(json!({"pid": 99, "reason": "unexpected exit (no clean shutdown)"}));
        assert_eq!(
            crash_line(&v),
            "Last crash: unexpected exit (no clean shutdown), pid 99"
        );
    }
}
