//! The app runs and supervises the hub (`tau hub run`) when "Run the hub" is on.
//!
//! - [`control`]: signed requests to the hub's protected control routes (token, nonce, proof);
//! - [`guard`]: the owner guard's `/status` block, its menu line and "Lock now";
//! - [`launch`]: the command and environment, and importing them from a launchd agent;
//! - [`policy`]: which exits are restarted, and the backoff;
//! - [`probe`]: read-only looks at a hub (lock, control API, `tau hub status --json`, launchd);
//! - [`supervisor`]: the state machine around the child process;
//! - [`display`]: the menu lines.

pub mod control;
pub mod display;
pub mod guard;
pub mod launch;
pub mod policy;
pub mod probe;
pub mod supervisor;
