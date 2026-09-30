//! The hub lines of the menu (and the window), from a [`HubView`].

use super::supervisor::{HubState, HubView};
use serde_json::Value;

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
    let text = |key: &str| telegram.get(key).and_then(Value::as_str);
    if telegram.get("configured").and_then(Value::as_bool) == Some(false) {
        return match text("reason") {
            Some(reason) => shorten(&format!("Telegram: off ({reason})"), 72),
            None => "Telegram: off".into(),
        };
    }
    let line = match text("state") {
        Some("polling") => match text("bot") {
            Some(bot) => format!("Telegram: polling as {bot}"),
            None => "Telegram: polling".into(),
        },
        Some("retrying") => {
            let retry = telegram
                .get("retry_in_s")
                .and_then(Value::as_f64)
                .map(|s| format!(" in {} s", s.ceil() as u64))
                .unwrap_or_default();
            format!(
                "Telegram: retrying{retry} ({})",
                text("last_error").unwrap_or("error")
            )
        }
        Some("failed") => format!(
            "Telegram: stopped ({})",
            text("last_error").unwrap_or("error")
        ),
        Some(state) => format!("Telegram: {state}"),
        None => "Telegram: unknown".into(),
    };
    shorten(&line, 72)
}

/// Third line: the last crash, the hub's own report first, else TauBar's record.
pub fn crash_line(view: &HubView) -> String {
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
        return shorten(&format!("Last crash: {reason}{pid}"), 72);
    }
    if let Some(exit) = &view.last_exit {
        let restarts = if view.restarts > 1 {
            format!(" · {} restarts", view.restarts)
        } else {
            String::new()
        };
        return shorten(
            &format!("Last crash: {} ({}){restarts}", exit.reason, exit.at),
            72,
        );
    }
    "Last crash: none".into()
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
            guard: None,
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
