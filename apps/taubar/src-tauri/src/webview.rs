//! Webview permissions: every request is denied.
//!
//! TauBar holds the camera (and later the microphone) grant for the hub it runs (ADR 0008
//! decision 16). wry answers a page's `getUserMedia` with "grant" when no handler is set
//! (`requestMediaCapturePermissionForOrigin` in its WKWebView UI delegate), so without this any
//! page in a TauBar webview could open the camera or the microphone without a prompt. The
//! window needs no permission at all: the guard runs in the hub, never in a webview.
//!
//! [`permission`] is installed twice: on the app builder, for every webview, and on each
//! `WebviewWindowBuilder`, so a webview's own handler never falls back to `Default` (which wry
//! turns into WebKit's prompt). With both, `navigator.mediaDevices.getUserMedia(...)` in the
//! window rejects with `NotAllowedError`.

use tauri::webview::{PermissionKind, PermissionResponse};

/// The answer to every webview permission request: deny, whatever the kind.
pub fn permission(_kind: PermissionKind) -> PermissionResponse {
    PermissionResponse::Deny
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn every_media_and_other_permission_is_denied() {
        for kind in [
            PermissionKind::Camera,
            PermissionKind::Microphone,
            PermissionKind::DisplayCapture,
            PermissionKind::Geolocation,
            PermissionKind::Notifications,
            PermissionKind::ClipboardRead,
            PermissionKind::Midi,
            PermissionKind::Sensors,
            PermissionKind::MediaKeySystemAccess,
            PermissionKind::LocalFonts,
            PermissionKind::WindowManagement,
            PermissionKind::PointerLock,
            PermissionKind::AutomaticDownloads,
            PermissionKind::FileSystemAccess,
            PermissionKind::Autoplay,
            PermissionKind::Other,
        ] {
            assert_eq!(permission(kind), PermissionResponse::Deny, "{kind}");
        }
    }

    /// Every webview TauBar builds gets the handler: the app builder once, and each
    /// `WebviewWindowBuilder::new` (a future window must not forget it).
    #[test]
    fn every_webview_builder_installs_the_deny_handler() {
        let src = Path::new(env!("CARGO_MANIFEST_DIR")).join("src");
        let mut builders = 0;
        let mut handlers = 0;
        let mut app_handler = false;
        let mut stack = vec![src];
        while let Some(dir) = stack.pop() {
            for entry in std::fs::read_dir(&dir).unwrap() {
                let path = entry.unwrap().path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                if path.extension().is_none_or(|ext| ext != "rs") || path.ends_with("webview.rs") {
                    continue;
                }
                let text = std::fs::read_to_string(&path).unwrap();
                // Two distinct names: "WebviewBuilder" is not a substring of the other.
                builders += text.matches("WebviewWindowBuilder::new(").count()
                    + text.matches("WebviewBuilder::new(").count();
                handlers += text
                    .matches(".on_permission_request(|_, kind| webview::permission(kind))")
                    .count();
                app_handler |= text.contains("tauri::Builder::default()")
                    && text.contains(".on_permission_request(|_, kind| webview::permission(kind))");
            }
        }
        assert!(app_handler, "the app builder installs webview::permission");
        assert!(builders >= 1, "the settings window is built somewhere");
        assert_eq!(
            handlers,
            builders + 1,
            "each WebviewWindowBuilder (and the app builder) installs webview::permission"
        );
    }
}
