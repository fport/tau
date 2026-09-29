//! "Launch at login": TauBar registers itself as a login item with `SMAppService.mainApp`
//! (macOS 13+), the API behind System Settings → General → Login Items → "Open at Login".
//!
//! Not a LaunchAgent with `RunAtLoad`: on the Mac this was built on, launchd pended every
//! non-demand spawn of user agents (roadmap 057, 052), and `tauri-plugin-autostart` offers only
//! a LaunchAgent or an AppleScript login item. The registration belongs to the system, so the
//! checkbox reads its state from `SMAppService` instead of TauBar's settings file.
//!
//! `SMAppService.mainApp` registers the bundle at its current path, so install TauBar.app
//! where it will stay (`/Applications`) before ticking the box.

use serde::Serialize;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LoginItemStatus {
    /// Registered and allowed: TauBar opens at login.
    Enabled,
    NotRegistered,
    /// Registered, but the user has to allow it in System Settings → Login Items.
    RequiresApproval,
    /// What `SMAppService.mainApp` reports before the app was ever registered (and for a
    /// binary outside an app bundle).
    NotFound,
    /// Not macOS.
    Unsupported,
}

impl LoginItemStatus {
    /// The checkbox is ticked when TauBar is registered, even while approval is pending.
    pub fn checked(self) -> bool {
        matches!(self, Self::Enabled | Self::RequiresApproval)
    }
}

#[cfg(target_os = "macos")]
mod imp {
    use super::LoginItemStatus;
    use objc2_service_management::{SMAppService, SMAppServiceStatus};

    pub fn status() -> LoginItemStatus {
        // SAFETY: plain ServiceManagement calls on the main app service.
        let status = unsafe { SMAppService::mainAppService().status() };
        match status {
            SMAppServiceStatus::Enabled => LoginItemStatus::Enabled,
            SMAppServiceStatus::NotRegistered => LoginItemStatus::NotRegistered,
            SMAppServiceStatus::RequiresApproval => LoginItemStatus::RequiresApproval,
            _ => LoginItemStatus::NotFound,
        }
    }

    pub fn set(enabled: bool) -> Result<LoginItemStatus, String> {
        let current = status();
        if current.checked() == enabled {
            return Ok(current);
        }
        // SAFETY: as above; errors come back as NSError.
        let service = unsafe { SMAppService::mainAppService() };
        let result = unsafe {
            if enabled {
                service.registerAndReturnError()
            } else {
                service.unregisterAndReturnError()
            }
        };
        result.map_err(|err| err.localizedDescription().to_string())?;
        Ok(status())
    }

    pub fn open_system_settings() {
        // SAFETY: opens System Settings → Login Items; no arguments.
        unsafe { SMAppService::openSystemSettingsLoginItems() }
    }
}

#[cfg(not(target_os = "macos"))]
mod imp {
    use super::LoginItemStatus;

    pub fn status() -> LoginItemStatus {
        LoginItemStatus::Unsupported
    }

    pub fn set(_enabled: bool) -> Result<LoginItemStatus, String> {
        Err("launch at login is only available on macOS".into())
    }

    pub fn open_system_settings() {}
}

pub use imp::{open_system_settings, set, status};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checkbox_state() {
        assert!(LoginItemStatus::Enabled.checked());
        assert!(LoginItemStatus::RequiresApproval.checked());
        assert!(!LoginItemStatus::NotRegistered.checked());
        assert!(!LoginItemStatus::NotFound.checked());
        assert!(!LoginItemStatus::Unsupported.checked());
    }
}
