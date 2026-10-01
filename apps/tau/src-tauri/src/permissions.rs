//! The macOS permissions the app asks for itself, in the setup wizard (ADR 0014 §2, roadmap
//! 171): only for the features the owner chose (`permissions` in `tau setup status --json`).
//!
//! - **Camera** and **microphone**: `AVCaptureDevice` authorization. The grant belongs to the
//!   app, and macOS attributes the camera use of the app's children (the hub's guard worker,
//!   `tau guard setup` in the wizard's terminal) to it, so asking here is asking for them.
//! - **Notifications**: `UNUserNotificationCenter`. It works only inside the `tau.app` bundle
//!   (an unbundled `tauri dev` binary has no bundle id, and the framework raises then), so
//!   outside a bundle the answer is `unsupported`.
//!
//! A request shows macOS's own prompt only while the answer is "not determined"; after a no,
//! only System Settings can change it ([`settings_url`]). Nothing is ever granted by the app.

use serde::{Deserialize, Serialize};

/// A permission a feature can need (`permissions` in the catalog).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    Camera,
    Microphone,
    Notifications,
}

/// Where a permission stands.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Access {
    Granted,
    Denied,
    /// Blocked by a profile or parental controls: the owner cannot change it.
    Restricted,
    /// Never asked: a request shows macOS's prompt.
    NotDetermined,
    /// Cannot be asked here (not macOS, or not the `tau.app` bundle).
    Unsupported,
}

/// The System Settings pane where the owner changes `permission` for tau.
pub fn settings_url(permission: Permission) -> &'static str {
    match permission {
        Permission::Camera => crate::hub::guard::CAMERA_SETTINGS_URL,
        Permission::Microphone => {
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
        }
        Permission::Notifications => {
            "x-apple.systempreferences:com.apple.Notifications-Settings.extension"
        }
    }
}

/// Where `permission` stands now, without asking.
pub fn status(permission: Permission) -> Access {
    imp::status(permission)
}

/// Ask macOS for `permission` (its prompt appears while the answer is not determined) and wait
/// for the answer. Blocking: call it off the main thread.
pub fn request(permission: Permission) -> Access {
    imp::request(permission)
}

#[cfg(target_os = "macos")]
mod imp {
    use super::{Access, Permission};
    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_av_foundation::{
        AVAuthorizationStatus, AVCaptureDevice, AVMediaType, AVMediaTypeAudio, AVMediaTypeVideo,
    };
    use objc2_foundation::{NSBundle, NSError};
    use objc2_user_notifications::{
        UNAuthorizationOptions, UNAuthorizationStatus, UNNotificationSettings,
        UNUserNotificationCenter,
    };
    use std::ptr::NonNull;
    use std::sync::mpsc;
    use std::time::Duration;

    /// How long a prompt may stay open before the answer counts as the current status.
    const PROMPT_WAIT: Duration = Duration::from_secs(10 * 60);
    /// How long reading the notification settings may take.
    const STATUS_WAIT: Duration = Duration::from_secs(10);

    pub fn status(permission: Permission) -> Access {
        match media(permission) {
            Some(media) => av_status(media),
            None if bundled() => un_status(),
            None => Access::Unsupported,
        }
    }

    pub fn request(permission: Permission) -> Access {
        match media(permission) {
            Some(media) => av_request(media),
            None if bundled() => un_request(),
            None => Access::Unsupported,
        }
    }

    fn media(permission: Permission) -> Option<&'static AVMediaType> {
        // SAFETY: AVFoundation's media type constants, read once they are linked.
        unsafe {
            match permission {
                Permission::Camera => AVMediaTypeVideo,
                Permission::Microphone => AVMediaTypeAudio,
                Permission::Notifications => None,
            }
        }
    }

    fn av_status(media: &AVMediaType) -> Access {
        // SAFETY: a class method with a valid media type (video or audio).
        let status = unsafe { AVCaptureDevice::authorizationStatusForMediaType(media) };
        match status {
            AVAuthorizationStatus::Authorized => Access::Granted,
            AVAuthorizationStatus::Denied => Access::Denied,
            AVAuthorizationStatus::Restricted => Access::Restricted,
            AVAuthorizationStatus::NotDetermined => Access::NotDetermined,
            _ => Access::Unsupported,
        }
    }

    fn av_request(media: &AVMediaType) -> Access {
        let current = av_status(media);
        if current != Access::NotDetermined {
            return current;
        }
        let (tx, rx) = mpsc::channel();
        let handler = RcBlock::new(move |granted: Bool| {
            let _ = tx.send(granted.as_bool());
        });
        // SAFETY: a class method with a valid media type; the block is copied by AVFoundation
        // and called once, on a queue of its own.
        unsafe { AVCaptureDevice::requestAccessForMediaType_completionHandler(media, &handler) };
        match rx.recv_timeout(PROMPT_WAIT) {
            Ok(true) => Access::Granted,
            Ok(false) => av_status(media),
            Err(_) => av_status(media),
        }
    }

    /// Running from `tau.app` (a bundle with an id), where UserNotifications works.
    fn bundled() -> bool {
        let bundle = NSBundle::mainBundle();
        bundle.bundleIdentifier().is_some() && bundle.bundlePath().to_string().ends_with(".app")
    }

    fn un_status() -> Access {
        let center = UNUserNotificationCenter::currentNotificationCenter();
        let (tx, rx) = mpsc::channel();
        let handler = RcBlock::new(move |settings: NonNull<UNNotificationSettings>| {
            // SAFETY: the framework passes a valid settings object for the call.
            let status = unsafe { settings.as_ref() }.authorizationStatus();
            let _ = tx.send(status);
        });
        center.getNotificationSettingsWithCompletionHandler(&handler);
        match rx.recv_timeout(STATUS_WAIT) {
            Ok(UNAuthorizationStatus::NotDetermined) => Access::NotDetermined,
            Ok(UNAuthorizationStatus::Denied) => Access::Denied,
            Ok(
                UNAuthorizationStatus::Authorized
                | UNAuthorizationStatus::Provisional
                | UNAuthorizationStatus::Ephemeral,
            ) => Access::Granted,
            _ => Access::Unsupported,
        }
    }

    fn un_request() -> Access {
        let current = un_status();
        if current != Access::NotDetermined {
            return current;
        }
        let center = UNUserNotificationCenter::currentNotificationCenter();
        let (tx, rx) = mpsc::channel();
        let handler = RcBlock::new(move |granted: Bool, _error: *mut NSError| {
            let _ = tx.send(granted.as_bool());
        });
        center.requestAuthorizationWithOptions_completionHandler(
            UNAuthorizationOptions::Alert
                | UNAuthorizationOptions::Sound
                | UNAuthorizationOptions::Badge,
            &handler,
        );
        match rx.recv_timeout(PROMPT_WAIT) {
            Ok(true) => Access::Granted,
            _ => un_status(),
        }
    }
}

#[cfg(not(target_os = "macos"))]
mod imp {
    use super::{Access, Permission};

    pub fn status(_: Permission) -> Access {
        Access::Unsupported
    }

    pub fn request(_: Permission) -> Access {
        Access::Unsupported
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn permissions_have_the_catalog_s_names() {
        for (permission, name) in [
            (Permission::Camera, "camera"),
            (Permission::Microphone, "microphone"),
            (Permission::Notifications, "notifications"),
        ] {
            assert_eq!(serde_json::to_value(permission).unwrap(), name);
            let parsed: Permission = serde_json::from_value(name.into()).unwrap();
            assert_eq!(parsed, permission);
        }
        assert!(serde_json::from_value::<Permission>("location".into()).is_err());
        assert_eq!(
            serde_json::to_value(Access::NotDetermined).unwrap(),
            "not_determined"
        );
    }

    #[test]
    fn every_permission_has_its_system_settings_pane() {
        for permission in [
            Permission::Camera,
            Permission::Microphone,
            Permission::Notifications,
        ] {
            assert!(settings_url(permission).starts_with("x-apple.systempreferences:"));
        }
        assert!(settings_url(Permission::Camera).ends_with("Privacy_Camera"));
    }

    /// Reading the status never prompts; the test binary is no bundle, so notifications say
    /// `unsupported` instead of touching UserNotifications.
    #[test]
    fn the_status_never_prompts_outside_the_bundle() {
        assert_eq!(status(Permission::Notifications), Access::Unsupported);
        assert_eq!(request(Permission::Notifications), Access::Unsupported);
        let camera = status(Permission::Camera);
        assert_ne!(
            camera,
            Access::Unsupported,
            "AVFoundation answers in any process"
        );
    }
}
