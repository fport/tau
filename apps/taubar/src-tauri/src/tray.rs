//! The menu bar icon and its native menu.
//!
//! A left click on the icon opens the panel (`panel.rs`); the right click shows this menu, so
//! every action stays reachable without the panel. The menu has a fixed structure; refreshing
//! only changes texts, check marks and enabled states, so it can be updated while it is open.
//! Check items for the sleep modes behave like radio items: after every click the marks are set
//! again from what is in force.

use crate::core::Snapshot;
use crate::login::LoginItemStatus;
use crate::settings::SleepMode;
use crate::sleep::SleepStatus;
use tauri::image::Image;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Rect, Runtime};

pub const TRAY_ID: &str = "taubar";

pub mod ids {
    pub const HUB_RUN: &str = "hub.run";
    pub const HUB_LOG: &str = "hub.log";
    pub const SLEEP_NORMAL: &str = "sleep.normal";
    pub const SLEEP_AC: &str = "sleep.ac";
    pub const SLEEP_LID: &str = "sleep.lid";
    pub const LOGIN: &str = "login";
    pub const SETTINGS: &str = "settings";
    pub const OPEN_LOG: &str = "log";
    pub const QUIT: &str = "quit";
}

pub struct TrayMenu<R: Runtime> {
    hub_lines: [MenuItem<R>; 3],
    hub_run: CheckMenuItem<R>,
    sleep_header: MenuItem<R>,
    sleep_normal: CheckMenuItem<R>,
    sleep_ac: CheckMenuItem<R>,
    sleep_lid: CheckMenuItem<R>,
    login: CheckMenuItem<R>,
}

impl<R: Runtime> TrayMenu<R> {
    /// Create the tray icon and its menu. `on_menu` receives the id of the clicked item,
    /// `on_left_click` the icon's position and size when a left click ends.
    pub fn build<F, G>(app: &AppHandle<R>, on_menu: F, on_left_click: G) -> tauri::Result<Self>
    where
        F: Fn(&AppHandle<R>, &str) + Send + Sync + 'static,
        G: Fn(&AppHandle<R>, Rect) + Send + Sync + 'static,
    {
        let none = None::<&str>;
        let hub_lines = [
            MenuItem::with_id(app, "hub.status", "Hub", false, none)?,
            MenuItem::with_id(app, "hub.detail", "Telegram: –", false, none)?,
            MenuItem::with_id(app, "hub.crash", "Last crash: none", false, none)?,
        ];
        let hub_run = CheckMenuItem::with_id(app, ids::HUB_RUN, "Run the hub", true, false, none)?;
        let hub_log = MenuItem::with_id(app, ids::HUB_LOG, "Open Hub Log", true, none)?;
        let sleep_header = MenuItem::with_id(app, "sleep.header", "Sleep", false, none)?;
        let sleep_normal = CheckMenuItem::with_id(
            app,
            ids::SLEEP_NORMAL,
            SleepMode::Normal.label(),
            true,
            false,
            none,
        )?;
        let sleep_ac = CheckMenuItem::with_id(
            app,
            ids::SLEEP_AC,
            SleepMode::KeepAwakeOnAc.label(),
            true,
            false,
            none,
        )?;
        let sleep_lid =
            CheckMenuItem::with_id(app, ids::SLEEP_LID, lid_label(false), false, false, none)?;
        let login = CheckMenuItem::with_id(app, ids::LOGIN, "Launch at login", true, false, none)?;
        let settings =
            MenuItem::with_id(app, ids::SETTINGS, "Settings…", true, Some("CmdOrCtrl+,"))?;
        let open_log = MenuItem::with_id(app, ids::OPEN_LOG, "Open TauBar Log", true, none)?;
        let quit = MenuItem::with_id(app, ids::QUIT, "Quit TauBar", true, Some("CmdOrCtrl+Q"))?;

        let menu = Menu::with_items(
            app,
            &[
                &hub_lines[0],
                &hub_lines[1],
                &hub_lines[2],
                &hub_run,
                &hub_log,
                &PredefinedMenuItem::separator(app)?,
                &sleep_header,
                &sleep_normal,
                &sleep_ac,
                &sleep_lid,
                &PredefinedMenuItem::separator(app)?,
                &login,
                &settings,
                &open_log,
                &PredefinedMenuItem::separator(app)?,
                &quit,
            ],
        )?;

        TrayIconBuilder::with_id(TRAY_ID)
            .icon(Image::from_bytes(include_bytes!(
                "../icons/tray-template.png"
            ))?)
            .icon_as_template(true)
            .tooltip("TauBar")
            .menu(&menu)
            .show_menu_on_left_click(false)
            .on_menu_event(move |app, event| on_menu(app, event.id().as_ref()))
            .on_tray_icon_event(move |tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    rect,
                    ..
                } = event
                {
                    on_left_click(tray.app_handle(), rect);
                }
            })
            .build(app)?;

        Ok(Self {
            hub_lines,
            hub_run,
            sleep_header,
            sleep_normal,
            sleep_ac,
            sleep_lid,
            login,
        })
    }

    pub fn update(&self, app: &AppHandle<R>, snapshot: &Snapshot) {
        for (item, line) in self.hub_lines.iter().zip(&snapshot.hub.lines) {
            let _ = item.set_text(line);
        }
        let _ = self.hub_run.set_checked(snapshot.hub.view.switch_on);
        let sleep = &snapshot.sleep;
        let header = sleep_header(sleep);
        let _ = self.sleep_header.set_text(&header);
        let _ = self
            .sleep_normal
            .set_checked(sleep.effective == SleepMode::Normal);
        let _ = self
            .sleep_ac
            .set_checked(sleep.effective == SleepMode::KeepAwakeOnAc);
        let _ = self
            .sleep_lid
            .set_checked(sleep.effective == SleepMode::KeepAwakeLidClosed);
        let _ = self.sleep_lid.set_enabled(sleep.lid_available);
        let _ = self.sleep_lid.set_text(lid_label(sleep.lid_available));
        let _ = self.login.set_checked(snapshot.login.status.checked());
        let _ = self.login.set_text(login_label(snapshot.login.status));
        if let Some(tray) = app.tray_by_id(TRAY_ID) {
            let _ = tray.set_tooltip(Some(format!(
                "TauBar · {} · {header}",
                snapshot.hub.lines[0]
            )));
        }
    }
}

/// The disabled header line above the sleep modes: what is in force, and why it differs
/// from the choice.
pub fn sleep_header(status: &SleepStatus) -> String {
    if status.disabled_elsewhere {
        return "Sleep: disabled outside TauBar (pmset disablesleep 1)".into();
    }
    let what = match status.effective {
        SleepMode::Normal => "Sleep: as usual",
        SleepMode::KeepAwakeOnAc => "Sleep: kept awake on AC power",
        SleepMode::KeepAwakeLidClosed => "Sleep: kept awake, even with the lid closed",
    };
    if status.wanted != status.effective {
        format!("{what} (lid-closed mode unavailable)")
    } else if status.problem.is_some() {
        format!("{what} (see the TauBar log)")
    } else {
        what.into()
    }
}

pub fn lid_label(available: bool) -> &'static str {
    if available {
        "Keep awake with the lid closed"
    } else {
        "Keep awake with the lid closed (needs setup)"
    }
}

pub fn login_label(status: LoginItemStatus) -> &'static str {
    match status {
        LoginItemStatus::RequiresApproval => "Launch at login (allow it in System Settings)",
        _ => "Launch at login",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn status(wanted: SleepMode, effective: SleepMode) -> SleepStatus {
        SleepStatus {
            wanted,
            effective,
            lid_available: false,
            disabled_elsewhere: false,
            problem: None,
        }
    }

    #[test]
    fn header_names_the_mode_in_force() {
        assert_eq!(
            sleep_header(&status(SleepMode::Normal, SleepMode::Normal)),
            "Sleep: as usual"
        );
        assert_eq!(
            sleep_header(&status(SleepMode::KeepAwakeOnAc, SleepMode::KeepAwakeOnAc)),
            "Sleep: kept awake on AC power"
        );
    }

    #[test]
    fn header_explains_a_fallback_and_problems() {
        let mut fallback = status(SleepMode::KeepAwakeLidClosed, SleepMode::KeepAwakeOnAc);
        fallback.problem = Some("needs the rule".into());
        assert_eq!(
            sleep_header(&fallback),
            "Sleep: kept awake on AC power (lid-closed mode unavailable)"
        );
        let mut failed = status(SleepMode::Normal, SleepMode::Normal);
        failed.problem = Some("boom".into());
        assert_eq!(
            sleep_header(&failed),
            "Sleep: as usual (see the TauBar log)"
        );
        let mut elsewhere = status(SleepMode::Normal, SleepMode::Normal);
        elsewhere.disabled_elsewhere = true;
        assert!(sleep_header(&elsewhere).contains("outside TauBar"));
    }

    #[test]
    fn labels() {
        assert!(lid_label(false).ends_with("(needs setup)"));
        assert_eq!(lid_label(true), "Keep awake with the lid closed");
        assert_eq!(login_label(LoginItemStatus::Enabled), "Launch at login");
        assert!(login_label(LoginItemStatus::RequiresApproval).contains("System Settings"));
    }
}
