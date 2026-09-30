//! The panel: a borderless, translucent window under the menu bar icon that shows the React
//! panel (`src/Panel.tsx`). A left click on the icon opens and closes it, and it hides when it
//! loses focus, as a menu does. The native menu stays on the right click (`tray.rs`), so every
//! action is still reachable when the panel is not.

use crate::webview;
use std::sync::{Mutex, MutexGuard};
use std::time::{Duration, Instant};
use tauri::window::{Effect, EffectState, EffectsBuilder};
use tauri::{
    AppHandle, LogicalPosition, LogicalSize, Manager, Rect, WebviewUrl, WebviewWindowBuilder,
    WindowEvent,
};

pub const PANEL_WINDOW: &str = "panel";
/// The panel fills the window's width, so this is the panel's width.
pub const PANEL_WIDTH: f64 = 320.0;
/// Until the page reports its height (`panel_fit`).
const INITIAL_HEIGHT: f64 = 420.0;
const MIN_HEIGHT: f64 = 80.0;
const MAX_HEIGHT: f64 = 900.0;
/// Between the menu bar and the panel, as macOS leaves under a status item's menu.
const GAP: f64 = 4.0;
/// Kept free between the panel and the edge of the screen.
const MARGIN: f64 = 8.0;
const CORNER_RADIUS: f64 = 12.0;
/// A click on the icon this soon after the panel hid on losing focus is the click that made it
/// lose focus: it closes the panel and must not open it again.
const REOPEN_GUARD: Duration = Duration::from_millis(300);

#[derive(Default)]
pub struct PanelState {
    hidden_on_blur: Mutex<Option<Instant>>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// A rectangle in logical points, top-left origin.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Area {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// The panel's top-left corner: under the icon with its left edge on the icon's left edge
/// (where macOS puts a status item's menu), moved left as far as it must to stay on the screen.
pub fn origin(icon: Area, width: f64, screen: Option<Area>) -> (f64, f64) {
    let mut x = icon.x;
    if let Some(screen) = screen {
        let right = screen.x + screen.width - MARGIN;
        if x + width > right {
            x = right - width;
        }
        x = x.max(screen.x + MARGIN);
    }
    (x, icon.y + icon.height + GAP)
}

/// Create the panel hidden, so the first click shows it at once.
pub fn build(app: &AppHandle) -> tauri::Result<()> {
    let window = WebviewWindowBuilder::new(
        app,
        PANEL_WINDOW,
        WebviewUrl::App("index.html#panel".into()),
    )
    .title("tau")
    .inner_size(PANEL_WIDTH, INITIAL_HEIGHT)
    .decorations(false)
    .transparent(true)
    .effects(
        EffectsBuilder::new()
            .effect(Effect::Popover)
            .state(EffectState::Active)
            .radius(CORNER_RADIUS)
            .build(),
    )
    .shadow(true)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .always_on_top(true)
    .visible_on_all_workspaces(true)
    .skip_taskbar(true)
    .accept_first_mouse(true)
    .focused(false)
    .visible(false)
    // The app holds the camera grant for its hub; the panel may not use it (ADR 0008).
    .on_permission_request(|_, kind| webview::permission(kind))
    .build()?;
    let handle = app.clone();
    window.on_window_event(move |event| match event {
        WindowEvent::Focused(false) => hide_on_blur(&handle),
        // No close button, but keep the window for the next click if something asks.
        WindowEvent::CloseRequested { api, .. } => {
            api.prevent_close();
            hide(&handle);
        }
        _ => {}
    });
    Ok(())
}

/// A left click on the icon: open the panel under it, or close it.
pub fn toggle(app: &AppHandle, icon: Rect) {
    let Some(window) = app.get_webview_window(PANEL_WINDOW) else {
        return;
    };
    if window.is_visible().unwrap_or(false) {
        hide(app);
        return;
    }
    let just_hidden = lock(&app.state::<PanelState>().hidden_on_blur)
        .take()
        .is_some_and(|at| at.elapsed() < REOPEN_GUARD);
    if just_hidden {
        return;
    }
    let _ = window.set_position(place(app, icon));
    let _ = window.show();
    let _ = window.set_focus();
    highlight(app, true);
}

pub fn hide(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(PANEL_WINDOW) {
        let _ = window.hide();
    }
    highlight(app, false);
}

fn hide_on_blur(app: &AppHandle) {
    let visible = app
        .get_webview_window(PANEL_WINDOW)
        .is_some_and(|w| w.is_visible().unwrap_or(false));
    if visible {
        *lock(&app.state::<PanelState>().hidden_on_blur) = Some(Instant::now());
        hide(app);
    }
}

/// The page's height, so the window fits the panel exactly.
pub fn fit(app: &AppHandle, height: f64) {
    if let Some(window) = app.get_webview_window(PANEL_WINDOW) {
        let height = height.clamp(MIN_HEIGHT, MAX_HEIGHT);
        let _ = window.set_size(LogicalSize::new(PANEL_WIDTH, height));
    }
}

/// Where the panel goes for an icon at `icon` (physical pixels, as the tray reports it), in the
/// logical points of the screen the icon is on.
fn place(app: &AppHandle, icon: Rect) -> LogicalPosition<f64> {
    let at = icon.position.to_physical::<f64>(1.0);
    let monitor = app
        .monitor_from_point(at.x, at.y)
        .ok()
        .flatten()
        .or_else(|| app.primary_monitor().ok().flatten());
    let scale = monitor.as_ref().map_or(1.0, |m| m.scale_factor());
    let position = icon.position.to_logical::<f64>(scale);
    let size = icon.size.to_logical::<f64>(scale);
    let screen = monitor.map(|m| {
        let work = m.work_area();
        let position = work.position.to_logical::<f64>(scale);
        let size = work.size.to_logical::<f64>(scale);
        Area {
            x: position.x,
            y: position.y,
            width: size.width,
            height: size.height,
        }
    });
    let icon = Area {
        x: position.x,
        y: position.y,
        width: size.width,
        height: size.height,
    };
    let (x, y) = origin(icon, PANEL_WIDTH, screen);
    LogicalPosition::new(x, y)
}

/// Keep the menu bar icon pressed while the panel is open, as it is while a menu is open.
#[cfg(target_os = "macos")]
fn highlight(app: &AppHandle, on: bool) {
    let Some(tray) = app.tray_by_id(crate::tray::TRAY_ID) else {
        return;
    };
    let _ = tray.with_inner_tray_icon(move |inner| {
        let Some(mtm) = objc2::MainThreadMarker::new() else {
            return;
        };
        if let Some(button) = inner.ns_status_item().and_then(|item| item.button(mtm)) {
            button.highlight(on);
        }
    });
}

#[cfg(not(target_os = "macos"))]
fn highlight(_app: &AppHandle, _on: bool) {}

#[cfg(test)]
mod tests {
    use super::*;

    const SCREEN: Area = Area {
        x: 0.0,
        y: 32.0,
        width: 1512.0,
        height: 950.0,
    };

    fn icon(x: f64) -> Area {
        Area {
            x,
            y: 0.0,
            width: 30.0,
            height: 32.0,
        }
    }

    #[test]
    fn panel_hangs_under_the_icon() {
        assert_eq!(origin(icon(900.0), 320.0, Some(SCREEN)), (900.0, 36.0));
    }

    #[test]
    fn panel_stays_on_the_screen() {
        // An icon near the right edge: the panel moves left and keeps its margin.
        assert_eq!(
            origin(icon(1400.0), 320.0, Some(SCREEN)),
            (1512.0 - 8.0 - 320.0, 36.0)
        );
        // A second screen to the left of the main one.
        let left = Area {
            x: -1920.0,
            ..SCREEN
        };
        assert_eq!(origin(icon(-1930.0), 320.0, Some(left)).0, -1912.0);
    }

    #[test]
    fn without_a_screen_the_icon_decides() {
        assert_eq!(origin(icon(1400.0), 320.0, None), (1400.0, 36.0));
    }
}
