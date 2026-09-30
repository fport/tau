//! The bundle metadata TauBar needs to hold the camera and microphone grant for the hub it
//! runs (ADR 0008 decision 16, roadmap 115). The built app is checked by hand (see the README:
//! `plutil` and `codesign -d --entitlements -`); these tests keep the sources right.

use serde_json::Value;
use std::path::{Path, PathBuf};

fn file(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(name)
}

fn plist(name: &str) -> plist::Dictionary {
    plist::Value::from_file(file(name))
        .unwrap_or_else(|e| panic!("{name}: {e}"))
        .into_dictionary()
        .unwrap_or_else(|| panic!("{name} is not a dictionary"))
}

fn config() -> Value {
    let text = std::fs::read_to_string(file("tauri.conf.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}

#[test]
fn info_plist_describes_camera_and_microphone_use_in_english() {
    let info = plist("Info.plist");
    assert_eq!(
        info.get("LSUIElement").and_then(|v| v.as_boolean()),
        Some(true)
    );
    for key in ["NSCameraUsageDescription", "NSMicrophoneUsageDescription"] {
        let text = info
            .get(key)
            .and_then(|v| v.as_string())
            .unwrap_or_else(|| panic!("Info.plist has no {key}"));
        assert!(text.contains("hub that TauBar runs"), "{key}: {text}");
        assert!(
            text.is_ascii(),
            "{key} is English until roadmap 086: {text}"
        );
    }
}

#[test]
fn entitlements_allow_the_camera_and_audio_input_and_nothing_else() {
    let entitlements = plist("Entitlements.plist");
    let mut keys: Vec<&str> = entitlements.keys().map(String::as_str).collect();
    keys.sort();
    assert_eq!(
        keys,
        [
            "com.apple.security.device.audio-input",
            "com.apple.security.device.camera"
        ]
    );
    assert!(entitlements.values().all(|v| v.as_boolean() == Some(true)));
}

#[test]
fn the_bundle_is_signed_with_the_entitlements_and_no_personal_identity() {
    let config = config();
    let macos = &config["bundle"]["macOS"];
    let entitlements = macos["entitlements"]
        .as_str()
        .expect("bundle.macOS.entitlements");
    assert!(file(entitlements).is_file(), "{entitlements} exists");
    assert_eq!(
        macos["signingIdentity"], "-",
        "the committed identity stays ad hoc; a stable one comes from APPLE_SIGNING_IDENTITY"
    );
    assert_ne!(
        macos["hardenedRuntime"],
        Value::Bool(false),
        "the hardened runtime stays on"
    );
    assert_eq!(config["identifier"], "com.tau.taubar");
}
