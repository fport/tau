//! "Launch at login": TauBar registers itself as a login item with `SMAppService.mainApp`
//! (macOS 13+), the API behind System Settings → General → Login Items → "Open at Login".
//!
//! Not a LaunchAgent with `RunAtLoad`: on the Mac this was built on, launchd pended every
//! non-demand spawn of user agents (roadmap 057, 052), and `tauri-plugin-autostart` offers only
//! a LaunchAgent or an AppleScript login item. The registration belongs to the system, so the
//! checkbox reads its state from `SMAppService` instead of TauBar's settings file.
//!
//! `SMAppService.mainApp` registers the bundle at its current path, so TauBar refuses to turn
//! the login item on unless it runs from `/Applications` or `~/Applications`: a login item that
//! points at the build folder of a checkout breaks when the folder is rebuilt (roadmap 091).

use serde::Serialize;
use std::path::{Path, PathBuf};

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

pub use imp::{open_system_settings, status};

/// Turn the login item on or off. Turning it on needs TauBar to run from an installed copy
/// (see [`installed_bundle`]); turning it off always works.
pub fn set(enabled: bool) -> Result<LoginItemStatus, String> {
    if enabled {
        let exe = std::env::current_exe().map_err(|err| err.to_string())?;
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        installed_bundle(&exe, &home)?;
    }
    imp::set(enabled)
}

/// The app bundle `exe` belongs to, when that bundle is installed directly in `/Applications`
/// or `<home>/Applications`; otherwise the message the user sees.
pub fn installed_bundle(exe: &Path, home: &Path) -> Result<PathBuf, String> {
    let bundle = exe
        .ancestors()
        .find(|path| path.extension().is_some_and(|ext| ext == "app"))
        .ok_or_else(|| {
            format!(
                "Launch at login needs TauBar.app installed in /Applications; this TauBar is not \
                 an app bundle ({}).",
                exe.display()
            )
        })?;
    let folder = bundle.parent().unwrap_or(Path::new(""));
    if folder == Path::new("/Applications") || folder == home.join("Applications") {
        return Ok(bundle.to_path_buf());
    }
    Err(format!(
        "Launch at login needs TauBar.app installed in /Applications; this copy runs from {}. \
         Quit it, install TauBar.app in /Applications and open that one.",
        bundle.display()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_an_installed_bundle_may_register_for_login() {
        let home = Path::new("/Users/someone");
        let installed = Path::new("/Applications/TauBar.app/Contents/MacOS/taubar");
        assert_eq!(
            installed_bundle(installed, home),
            Ok(PathBuf::from("/Applications/TauBar.app"))
        );
        let per_user = Path::new("/Users/someone/Applications/TauBar.app/Contents/MacOS/taubar");
        assert_eq!(
            installed_bundle(per_user, home),
            Ok(PathBuf::from("/Users/someone/Applications/TauBar.app"))
        );
        for elsewhere in [
            "/path/to/tau/apps/taubar/src-tauri/target/release/bundle/macos/TauBar.app/Contents/MacOS/taubar",
            "/Applications/Tools/TauBar.app/Contents/MacOS/taubar",
            "/Users/someone/Downloads/TauBar.app/Contents/MacOS/taubar",
        ] {
            let err = installed_bundle(Path::new(elsewhere), home).unwrap_err();
            assert!(err.contains("needs TauBar.app installed in /Applications"), "{err}");
            assert!(err.contains("TauBar.app"), "{err}");
        }
        let bare = installed_bundle(Path::new("/path/to/target/debug/taubar"), home).unwrap_err();
        assert!(bare.contains("not an app bundle"), "{bare}");
    }

    #[test]
    fn checkbox_state() {
        assert!(LoginItemStatus::Enabled.checked());
        assert!(LoginItemStatus::RequiresApproval.checked());
        assert!(!LoginItemStatus::NotRegistered.checked());
        assert!(!LoginItemStatus::NotFound.checked());
        assert!(!LoginItemStatus::Unsupported.checked());
    }
}
