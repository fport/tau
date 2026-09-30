//! The terminal modes a TUI has switched on, so a new page can pick up a running TUI.
//!
//! A page that reloads (a crashed web content process, which Tauri reloads by itself, or a Vite
//! reload in `bun run tauri dev`) comes back with a fresh xterm.js, while `tau tui` keeps running in
//! the PTY. Textual sets its modes once, at start-up: the alternate screen, mouse reporting,
//! focus events, bracketed paste and a hidden cursor. A repaint does not send them again, so
//! [`ModeTracker`] watches the output for DEC private mode sets and resets (`CSI ? n h`,
//! `CSI ? n l`) and [`ModeTracker::replay`] writes the current state for the new terminal.
//!
//! The parser is a small state machine that keeps its state between chunks, so a sequence split
//! across two reads is still seen. It only looks at bytes; nothing is decoded.

/// The modes worth restoring on a fresh terminal, in the order they are replayed: the screen
/// buffer first (switching to the alternate screen clears it), then the cursor, keys, mouse,
/// focus and paste. Synchronized output (2026) is left out on purpose: a replayed set without
/// its reset would stop the terminal from drawing.
pub const TRACKED: &[u16] = &[
    1049, // alternate screen, saving the cursor
    1047, // alternate screen
    47,   // alternate screen (legacy)
    1,    // application cursor keys
    7,    // auto-wrap
    25,   // cursor visible
    1000, // mouse: press and release
    1002, // mouse: drag
    1003, // mouse: any motion
    1005, // mouse: UTF-8 coordinates
    1006, // mouse: SGR coordinates
    1015, // mouse: urxvt coordinates
    1016, // mouse: SGR pixel coordinates
    1004, // focus in and out
    2004, // bracketed paste
];

/// Parameters longer than this are not a mode anyone tracks.
const MAX_PARAMS: usize = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State {
    Ground,
    /// After ESC.
    Escape,
    /// After ESC [.
    CsiEntry,
    /// After ESC [ ?, collecting numbers.
    Private,
}

/// Follows the DEC private modes in a byte stream.
#[derive(Clone, Debug)]
pub struct ModeTracker {
    state: State,
    params: Vec<u32>,
    current: Option<u32>,
    /// The last value seen for each tracked mode, indexed like [`TRACKED`].
    modes: [Option<bool>; TRACKED.len()],
}

impl Default for ModeTracker {
    fn default() -> Self {
        Self::new()
    }
}

impl ModeTracker {
    pub fn new() -> Self {
        Self {
            state: State::Ground,
            params: Vec::new(),
            current: None,
            modes: [None; TRACKED.len()],
        }
    }

    /// Read the next chunk of output.
    pub fn feed(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            self.step(byte);
        }
    }

    fn step(&mut self, byte: u8) {
        // ESC starts a new sequence wherever it appears (and aborts an unfinished one).
        if byte == 0x1b {
            self.state = State::Escape;
            return;
        }
        self.state = match (self.state, byte) {
            (State::Ground, _) => State::Ground,
            (State::Escape, b'[') => State::CsiEntry,
            // RIS: a full reset puts every mode back to its default.
            (State::Escape, b'c') => {
                self.modes = [None; TRACKED.len()];
                State::Ground
            }
            (State::Escape, _) => State::Ground,
            (State::CsiEntry, b'?') => {
                self.params.clear();
                self.current = None;
                State::Private
            }
            (State::CsiEntry, _) => State::Ground,
            (State::Private, b'0'..=b'9') => {
                let digit = u32::from(byte - b'0');
                self.current = Some(
                    self.current
                        .unwrap_or(0)
                        .saturating_mul(10)
                        .saturating_add(digit),
                );
                State::Private
            }
            (State::Private, b';') => {
                self.push_param();
                State::Private
            }
            (State::Private, b'h' | b'l') => {
                self.push_param();
                let on = byte == b'h';
                for i in 0..self.params.len() {
                    self.set(self.params[i], on);
                }
                State::Ground
            }
            // Anything else (a `$` of a mode query, an intermediate byte): not a mode change.
            (State::Private, _) => State::Ground,
        };
    }

    fn push_param(&mut self) {
        if self.params.len() < MAX_PARAMS {
            self.params.push(self.current.unwrap_or(0));
        }
        self.current = None;
    }

    fn set(&mut self, mode: u32, on: bool) {
        if let Some(i) = TRACKED.iter().position(|&m| u32::from(m) == mode) {
            self.modes[i] = Some(on);
        }
    }

    /// Whether `mode` was last set (`Some(true)`), reset (`Some(false)`) or never touched.
    pub fn get(&self, mode: u16) -> Option<bool> {
        TRACKED
            .iter()
            .position(|&m| m == mode)
            .and_then(|i| self.modes[i])
    }

    /// The sequences that put a fresh terminal into the same modes; empty if none were touched.
    pub fn replay(&self) -> Vec<u8> {
        let mut out = Vec::new();
        for (mode, value) in TRACKED.iter().zip(self.modes) {
            if let Some(on) = value {
                out.extend_from_slice(
                    format!("\x1b[?{mode}{}", if on { 'h' } else { 'l' }).as_bytes(),
                );
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// What Textual writes when it starts (textual/drivers/linux_driver.py), mixed with a frame.
    const TEXTUAL_START: &[u8] = b"\x1b[?1049h\x1b[?1000h\x1b[?1003h\x1b[?1015h\x1b[?1006h\
\x1b[?25l\x1b[?1004h\x1b[>7u\x1b[?2026$p\x1b[?2048$p\x1b[?2004h\
\x1b[?2026h\x1b[1;1H\x1b[38;2;255;122;61m\xe2\x94\x8c\xe2\x94\x80 \xc4\x9f\xc3\xbc\x1b[0m\x1b[?2026l";

    const TEXTUAL_REPLAY: &[u8] = b"\x1b[?1049h\x1b[?25l\x1b[?1000h\x1b[?1003h\x1b[?1006h\
\x1b[?1015h\x1b[?1004h\x1b[?2004h";

    #[test]
    fn replays_what_textual_switched_on() {
        let mut modes = ModeTracker::new();
        modes.feed(TEXTUAL_START);
        assert_eq!(modes.replay(), TEXTUAL_REPLAY);
        // Synchronized output and the mode queries are never replayed.
        assert_eq!(modes.get(2026), None);
    }

    #[test]
    fn a_sequence_split_anywhere_is_still_seen() {
        for cut in 1..TEXTUAL_START.len() {
            let mut modes = ModeTracker::new();
            let (a, b) = TEXTUAL_START.split_at(cut);
            modes.feed(a);
            modes.feed(b);
            assert_eq!(modes.replay(), TEXTUAL_REPLAY, "cut at {cut}");
        }
        let mut modes = ModeTracker::new();
        for byte in TEXTUAL_START {
            modes.feed(&[*byte]);
        }
        assert_eq!(modes.replay(), TEXTUAL_REPLAY);
    }

    #[test]
    fn the_last_value_wins_and_resets_are_replayed() {
        let mut modes = ModeTracker::new();
        modes.feed(b"\x1b[?1049h\x1b[?1000;1006h\x1b[?25l");
        // Textual leaving: mouse off, cursor back, normal screen.
        modes.feed(b"\x1b[?1000l\x1b[?1006l\x1b[?25h\x1b[?1049l");
        assert_eq!(modes.get(1049), Some(false));
        assert_eq!(modes.get(1000), Some(false));
        assert_eq!(
            modes.replay(),
            b"\x1b[?1049l\x1b[?25h\x1b[?1000l\x1b[?1006l".to_vec()
        );
    }

    #[test]
    fn ignores_what_is_not_a_private_mode_change() {
        let mut modes = ModeTracker::new();
        // Plain CSI (no `?`), a mode query, an unknown mode, an aborted sequence, text.
        modes.feed(b"\x1b[25h\x1b[?25$p\x1b[?9999h\x1b[?10\x1b[0m?1000h 1049h");
        assert_eq!(modes.replay(), b"");
        // An oversized number saturates instead of wrapping onto a tracked mode.
        modes.feed(b"\x1b[?4294968345h");
        assert_eq!(modes.replay(), b"");
    }

    #[test]
    fn a_full_reset_forgets_the_modes() {
        let mut modes = ModeTracker::new();
        modes.feed(b"\x1b[?1049h\x1b[?1000h");
        modes.feed(b"\x1bc");
        assert_eq!(modes.replay(), b"");
    }
}
