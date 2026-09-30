//! The menu bar icon and its native menu.
//!
//! A left click on the icon opens the panel (`panel.rs`); the right click shows this menu, so
//! every action stays reachable without the panel. The menu has a fixed structure; refreshing
//! only changes texts, check marks and enabled states, so it can be updated while it is open.
//! Check items for the sleep modes behave like radio items: after every click the marks are set
//! again from what is in force.
//!
//! The one exception is the guard section under the hub lines (the guard line, "Lock now",
//! "Grant camera access…"): its items exist only while the hub reports a guard, so they are
//! inserted and removed when [`GuardItems`] changes.
//!
//! [`TrayMenu::update`] runs on the main thread only ([`crate::refresh`] posts it there). Off
//! the main thread every Tauri menu call posts a task to the event loop and blocks until the
//! main thread has run it (`run_item_main_thread!` in tauri's `menu` module), so a lock held
//! across such a call from another thread deadlocks against a main-thread handler that waits
//! for the same lock: the event loop, the menu and hub supervision would freeze for good. On
//! the main thread the calls run in place, and the guard section's own lock is still never
//! held across one. No unit test can reach a Tauri menu; [`apply_guard_items`] holds the logic
//! the tests do reach.

use crate::core::Snapshot;
use crate::hub::guard::GuardMenu;
use crate::login::LoginItemStatus;
use crate::settings::SleepMode;
use crate::sleep::SleepStatus;
use std::sync::Mutex;
use tauri::image::Image;
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Rect, Runtime};

pub const TRAY_ID: &str = "taubar";
/// The guard section starts right after the three hub lines.
pub const GUARD_POSITION: usize = 3;

pub mod ids {
    pub const HUB_RUN: &str = "hub.run";
    pub const HUB_LOG: &str = "hub.log";
    pub const GUARD_LOCK: &str = "guard.lock";
    pub const GUARD_CAMERA: &str = "guard.camera";
    pub const SLEEP_NORMAL: &str = "sleep.normal";
    pub const SLEEP_AC: &str = "sleep.ac";
    pub const SLEEP_LID: &str = "sleep.lid";
    pub const LOGIN: &str = "login";
    pub const SETTINGS: &str = "settings";
    pub const OPEN_LOG: &str = "log";
    pub const QUIT: &str = "quit";
}

/// Which guard items the menu holds.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct GuardItems {
    pub line: bool,
    pub lock: bool,
    pub camera: bool,
}

/// One item of the guard section, in menu order.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GuardSlot {
    Line,
    Lock,
    Camera,
}

impl GuardSlot {
    pub const ALL: [GuardSlot; 3] = [GuardSlot::Line, GuardSlot::Lock, GuardSlot::Camera];
}

impl GuardItems {
    /// The items for `menu`: none without a guard line.
    pub fn wanted(menu: &GuardMenu) -> Self {
        let shown = menu.line.is_some();
        Self {
            line: shown,
            lock: shown && menu.lock_now,
            camera: shown && menu.grant_camera,
        }
    }

    pub fn has(&self, slot: GuardSlot) -> bool {
        match slot {
            GuardSlot::Line => self.line,
            GuardSlot::Lock => self.lock,
            GuardSlot::Camera => self.camera,
        }
    }

    fn set(&mut self, slot: GuardSlot, held: bool) {
        match slot {
            GuardSlot::Line => self.line = held,
            GuardSlot::Lock => self.lock = held,
            GuardSlot::Camera => self.camera = held,
        }
    }
}

/// Change the guard section from `shown` to `wanted`: take every shown item out, then put the
/// wanted ones back in menu order from [`GUARD_POSITION`]. `remove` and `insert` do the menu
/// calls and say whether they worked. Returns what the menu holds afterwards, so an item whose
/// removal or insertion failed is tried again at the next update instead of being recorded as
/// done. An item that could not be removed keeps its place, and the others are put around it.
pub fn apply_guard_items(
    shown: GuardItems,
    wanted: GuardItems,
    mut remove: impl FnMut(GuardSlot) -> bool,
    mut insert: impl FnMut(GuardSlot, usize) -> bool,
) -> GuardItems {
    let mut held = shown;
    if shown == wanted {
        return held;
    }
    for slot in GuardSlot::ALL {
        if held.has(slot) && remove(slot) {
            held.set(slot, false);
        }
    }
    let mut position = GUARD_POSITION;
    for slot in GuardSlot::ALL {
        if held.has(slot) {
            position += 1;
        } else if wanted.has(slot) && insert(slot, position) {
            held.set(slot, true);
            position += 1;
        }
    }
    held
}

pub struct TrayMenu<R: Runtime> {
    menu: Menu<R>,
    hub_lines: [MenuItem<R>; 3],
    guard_line: MenuItem<R>,
    guard_lock: MenuItem<R>,
    guard_camera: MenuItem<R>,
    /// What the guard section holds. Only the main thread touches it (see the module
    /// docs); the `Mutex` is there because the tray menu is shared app state (`Sync`).
    guard_shown: Mutex<GuardItems>,
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
        let guard_line = MenuItem::with_id(app, "guard.status", "Guard", false, none)?;
        let guard_lock = MenuItem::with_id(app, ids::GUARD_LOCK, "Lock now", true, none)?;
        let guard_camera =
            MenuItem::with_id(app, ids::GUARD_CAMERA, "Grant camera access…", true, none)?;
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
            menu,
            hub_lines,
            guard_line,
            guard_lock,
            guard_camera,
            guard_shown: Mutex::new(GuardItems::default()),
            hub_run,
            sleep_header,
            sleep_normal,
            sleep_ac,
            sleep_lid,
            login,
        })
    }

    /// Show `snapshot`. Call it on the main thread only: [`crate::refresh`] posts it there.
    pub fn update(&self, app: &AppHandle<R>, snapshot: &Snapshot) {
        for (item, line) in self.hub_lines.iter().zip(&snapshot.hub.lines) {
            let _ = item.set_text(line);
        }
        self.update_guard(&snapshot.hub.guard_menu);
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

impl<R: Runtime> TrayMenu<R> {
    /// Show the guard section `menu` asks for: set the line, and insert or remove items only
    /// when the set changes. The lock on `guard_shown` is taken twice, briefly, and never held
    /// across a menu call (see the module docs).
    fn update_guard(&self, menu: &GuardMenu) {
        if let Some(line) = &menu.line {
            let _ = self.guard_line.set_text(line);
        }
        let wanted = GuardItems::wanted(menu);
        let shown = *self.guard_shown.lock().unwrap_or_else(|e| e.into_inner());
        if shown == wanted {
            return;
        }
        let item = |slot: GuardSlot| match slot {
            GuardSlot::Line => &self.guard_line,
            GuardSlot::Lock => &self.guard_lock,
            GuardSlot::Camera => &self.guard_camera,
        };
        let held = apply_guard_items(
            shown,
            wanted,
            |slot| self.menu.remove(item(slot)).is_ok(),
            |slot, position| self.menu.insert(item(slot), position).is_ok(),
        );
        *self.guard_shown.lock().unwrap_or_else(|e| e.into_inner()) = held;
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
    fn guard_items_follow_the_guard_menu() {
        assert_eq!(
            GuardItems::wanted(&GuardMenu::default()),
            GuardItems::default()
        );
        let locked = GuardMenu {
            line: Some("Guard: locked".into()),
            lock_now: true,
            grant_camera: false,
        };
        assert_eq!(
            GuardItems::wanted(&locked),
            GuardItems {
                line: true,
                lock: true,
                camera: false
            }
        );
        let denied = GuardMenu {
            line: Some("Guard: unavailable (camera denied)".into()),
            lock_now: true,
            grant_camera: true,
        };
        assert_eq!(
            GuardItems::wanted(&denied),
            GuardItems {
                line: true,
                lock: true,
                camera: true
            }
        );
        // Actions never show without the line.
        let orphan = GuardMenu {
            line: None,
            lock_now: true,
            grant_camera: true,
        };
        assert_eq!(GuardItems::wanted(&orphan), GuardItems::default());
    }

    #[test]
    fn guard_items_from_canned_status_bodies() {
        use crate::hub::guard::{menu, parse};
        use serde_json::json;
        let items = |status: serde_json::Value| GuardItems::wanted(&menu(parse(&status).as_ref()));
        let none = GuardItems::default();
        let lock_only = GuardItems {
            line: true,
            lock: true,
            camera: false,
        };
        assert_eq!(items(json!({"pid": 1})), none);
        assert_eq!(items(json!({"guard": {"state": "off"}})), none);
        assert_eq!(
            items(json!({"guard": {"state": "locked", "enrolled": true}})),
            lock_only
        );
        assert_eq!(
            items(json!({"guard": {"state": "unlocked", "enrolled": true}})),
            lock_only
        );
        assert_eq!(
            items(json!({"guard": {"state": "unavailable", "enrolled": true,
                "available": false, "reason": "camera_denied"}})),
            GuardItems {
                line: true,
                lock: true,
                camera: true
            }
        );
    }

    /// A stand-in for the tray menu: the items in order, with removals and insertions that
    /// fail on request, driven the way `update_guard` drives the real one.
    struct FakeMenu {
        items: Vec<String>,
        fail_remove: Vec<GuardSlot>,
        fail_insert: Vec<GuardSlot>,
    }

    impl FakeMenu {
        fn new() -> Self {
            Self {
                items: [
                    "hub.status",
                    "hub.detail",
                    "hub.crash",
                    "hub.run",
                    "hub.log",
                ]
                .map(String::from)
                .to_vec(),
                fail_remove: vec![],
                fail_insert: vec![],
            }
        }

        fn name(slot: GuardSlot) -> String {
            format!("{slot:?}")
        }

        fn apply(&mut self, shown: GuardItems, wanted: GuardItems) -> GuardItems {
            let menu = std::cell::RefCell::new(self);
            apply_guard_items(
                shown,
                wanted,
                |slot| {
                    let mut menu = menu.borrow_mut();
                    if menu.fail_remove.contains(&slot) {
                        return false;
                    }
                    let name = Self::name(slot);
                    let before = menu.items.len();
                    menu.items.retain(|item| *item != name);
                    menu.items.len() < before
                },
                |slot, position| {
                    let mut menu = menu.borrow_mut();
                    if menu.fail_insert.contains(&slot) || position > menu.items.len() {
                        return false;
                    }
                    let name = Self::name(slot);
                    assert!(!menu.items.contains(&name), "{name} inserted twice");
                    menu.items.insert(position, name);
                    true
                },
            )
        }

        fn guard_section(&self) -> Vec<&str> {
            self.items[GUARD_POSITION..]
                .iter()
                .map(String::as_str)
                .take_while(|item| !item.starts_with("hub."))
                .collect()
        }
    }

    const ALL: GuardItems = GuardItems {
        line: true,
        lock: true,
        camera: true,
    };
    const LINE_LOCK: GuardItems = GuardItems {
        line: true,
        lock: true,
        camera: false,
    };
    const NONE: GuardItems = GuardItems {
        line: false,
        lock: false,
        camera: false,
    };

    #[test]
    fn the_guard_section_is_inserted_in_order_and_removed() {
        let mut menu = FakeMenu::new();
        let held = menu.apply(NONE, LINE_LOCK);
        assert_eq!(held, LINE_LOCK);
        assert_eq!(menu.guard_section(), ["Line", "Lock"]);
        assert_eq!(
            menu.items[5], "hub.run",
            "the hub switch follows the section"
        );
        let held = menu.apply(held, ALL);
        assert_eq!(held, ALL);
        assert_eq!(menu.guard_section(), ["Line", "Lock", "Camera"]);
        let held = menu.apply(held, NONE);
        assert_eq!(held, NONE);
        assert_eq!(menu.items, FakeMenu::new().items);
        // Nothing to change, no menu call.
        assert_eq!(
            apply_guard_items(ALL, ALL, |_| panic!("remove"), |_, _| panic!("insert")),
            ALL
        );
    }

    #[test]
    fn a_failed_insert_is_not_recorded_and_is_tried_again() {
        let mut menu = FakeMenu::new();
        menu.fail_insert = vec![GuardSlot::Lock];
        let held = menu.apply(NONE, ALL);
        assert_eq!(
            held,
            GuardItems {
                line: true,
                lock: false,
                camera: true
            },
            "only what went in is recorded"
        );
        assert_eq!(menu.guard_section(), ["Line", "Camera"]);
        menu.fail_insert.clear();
        let held = menu.apply(held, ALL);
        assert_eq!(held, ALL);
        assert_eq!(menu.guard_section(), ["Line", "Lock", "Camera"]);
    }

    #[test]
    fn a_failed_removal_keeps_its_place_and_is_tried_again() {
        let mut menu = FakeMenu::new();
        let held = menu.apply(NONE, ALL);
        menu.fail_remove = vec![GuardSlot::Lock];
        let held = menu.apply(held, NONE);
        assert_eq!(
            held,
            GuardItems {
                line: false,
                lock: true,
                camera: false
            }
        );
        assert_eq!(menu.guard_section(), ["Lock"]);
        // The next wanted set is put around the item that stayed, in menu order.
        let held = menu.apply(held, ALL);
        assert_eq!(held, ALL);
        assert_eq!(menu.guard_section(), ["Line", "Lock", "Camera"]);
        menu.fail_remove.clear();
        assert_eq!(menu.apply(held, NONE), NONE);
        assert_eq!(menu.items, FakeMenu::new().items);
    }

    /// The menu is changed on the main thread only: `refresh` posts `TrayMenu::update` with a
    /// non-blocking `run_on_main_thread`, and nothing else calls it. A menu call from another
    /// thread blocks until the main thread runs it, so a lock held across one can deadlock the
    /// event loop (see the module docs); a unit test cannot reach a Tauri menu, so this pins
    /// the structure instead.
    #[test]
    fn the_menu_is_only_updated_on_the_main_thread() {
        let src = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let lib = std::fs::read_to_string(src.join("lib.rs")).unwrap();
        let start = lib.find("pub fn refresh(").expect("refresh in lib.rs");
        let end = start + lib[start..].find("\n}\n").expect("end of refresh");
        let refresh = &lib[start..end];
        let posted = refresh
            .find("run_on_main_thread(move ||")
            .expect("refresh posts the menu update to the main thread");
        let update = refresh.find(".update(").expect("refresh updates the menu");
        assert!(posted < update, "the update runs inside the posted task");
        let mut calls = 0;
        let mut stack = vec![src];
        while let Some(dir) = stack.pop() {
            for entry in std::fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                if path.is_dir() {
                    stack.push(path);
                } else if path.extension().is_some_and(|ext| ext == "rs") {
                    let text = std::fs::read_to_string(&path).unwrap();
                    // Split so this test's own source does not count.
                    calls += text.matches(concat!("menu", ".update(")).count();
                    assert!(
                        !text.contains("update_guard(") || path.ends_with("tray.rs"),
                        "{} calls update_guard",
                        path.display()
                    );
                }
            }
        }
        assert_eq!(calls, 1, "TrayMenu::update is called from refresh only");
    }

    #[test]
    fn labels() {
        assert!(lid_label(false).ends_with("(needs setup)"));
        assert_eq!(lid_label(true), "Keep awake with the lid closed");
        assert_eq!(login_label(LoginItemStatus::Enabled), "Launch at login");
        assert!(login_label(LoginItemStatus::RequiresApproval).contains("System Settings"));
    }
}
