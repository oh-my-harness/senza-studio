//! Meta-agent layer: 2 AgentHarness instances (Converser + Coding Agent).
//!
//! These are the "meta agents" that help users build Senza projects.
//! They are NOT the user's agents — those run as Python subprocesses.

pub mod coding_agent;
pub mod converser;
pub mod diff_engine;
pub mod studio_tool;

pub use coding_agent::build_coding_agent;
pub use converser::build_converser;
pub use diff_engine::compute_affected_files;
pub use studio_tool::StudioTool;
