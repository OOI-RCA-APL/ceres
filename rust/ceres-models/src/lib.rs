//! Model generation driver for the Python entity modules.
//!
//! The generation itself runs in this crate's build script, which reads the table
//! schemas through `ceres-database` as a build dependency and rewrites the modules
//! under `ceres/__internal__/models/` whenever the entity definitions change. Building
//! the workspace is enough to keep the models current, and CI fails when a committed
//! module drifts.
