//! Stub generation driver for the `ceres_core` extension module.
//!
//! The generation itself runs in this crate's build script, which links `ceres-core` as a
//! build dependency and rewrites `ceres/__internal__/core.pyi` whenever the module's
//! sources change.
//! Building the workspace is enough to keep the stubs current. This library only hosts the
//! polish pass shared with the build script, so its tests run under `cargo test`.

pub mod polish;
