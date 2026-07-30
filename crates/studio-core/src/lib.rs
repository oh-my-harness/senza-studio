//! studio-core — Core business logic for Senza Studio.
//!
//! No web dependencies. Contains:
//! - Spec data structures and validation
//! - Project management (filesystem CRUD)
//! - Meta-agent definitions (Converser + Coding Agent)
//! - Python subprocess runner with fd 3 frame protocol
//! - Built-in example library

pub mod error;
pub mod events;
pub mod examples;
pub mod frame;
pub mod project;
pub mod runner;
pub mod spec;
