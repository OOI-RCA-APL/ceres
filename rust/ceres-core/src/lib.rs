//! The `ceres_core` Python extension module.
//!
//! Exposes the native configuration types to Python. Validation and semantics live in the
//! `ceres-config` crate, this module only carries them across the boundary. The classes
//! integrate with Pydantic on the Python side through thin subclasses in `ceres.config`.
//!
//! The type stubs in `ceres_core.pyi` are generated from these definitions by the `stub_gen`
//! binary. Regenerate them after changing the module's surface.

use std::path::PathBuf;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::define_stub_info_gatherer;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use pythonize::pythonize;

/// Convert validation problems into a Python `ValueError`.
fn problems_to_error(problems: ceres_config::Problems) -> PyErr {
    PyValueError::new_err(problems.to_string())
}

/// Define the shared surface of a Python class wrapping a validated configuration type.
///
/// Generates `to_dict`, `json_schema`, equality, and `repr`. Constructors and getters are
/// written by hand per class, so their signatures stay fully typed in the generated stubs.
macro_rules! config_class {
    (
        $(#[doc = $doc:literal])*
        $name:ident wraps $inner:ty, raw $raw:ty
    ) => {
        $(#[doc = $doc])*
        #[gen_stub_pyclass]
        #[pyclass(subclass, module = "ceres_core")]
        #[derive(Debug, Clone)]
        pub struct $name {
            inner: $inner,
        }

        #[gen_stub_pymethods]
        #[pymethods]
        impl $name {
            /// Return the configuration as a plain dictionary of JSON-compatible values.
            #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
            fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
                let value = serde_json::to_value(&self.inner)
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                Ok(pythonize(py, &value)?.unbind())
            }

            /// Return the JSON Schema describing this configuration section.
            #[staticmethod]
            #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
            fn json_schema(py: Python<'_>) -> PyResult<Py<PyAny>> {
                let schema = schemars::schema_for!($raw);
                Ok(pythonize(py, &schema)?.unbind())
            }

            fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
                match other.cast::<$name>() {
                    Ok(other) => self.inner == other.borrow().inner,
                    Err(_) => false,
                }
            }

            fn __repr__(&self) -> String {
                format!("{:?}", self.inner)
            }
        }
    };
}

config_class! {
    /// Process-level options applied when running the engine as a system service.
    ServiceConfig wraps ceres_config::ServiceConfig, raw ceres_config::RawServiceConfig
}

#[gen_stub_pymethods]
#[pymethods]
impl ServiceConfig {
    #[new]
    #[pyo3(signature = (*, name=None, user=None, stdout=None, stderr=None))]
    fn new(
        name: Option<String>,
        user: Option<String>,
        stdout: Option<PathBuf>,
        stderr: Option<PathBuf>,
    ) -> PyResult<Self> {
        let raw = ceres_config::RawServiceConfig {
            name,
            user,
            stdout,
            stderr,
        };
        let inner = ceres_config::ServiceConfig::try_from(raw).map_err(problems_to_error)?;
        Ok(Self { inner })
    }

    /// Service name registered with the operating system.
    #[getter]
    fn name(&self) -> Option<String> {
        self.inner.name.as_ref().map(ToString::to_string)
    }

    /// User the service runs as.
    #[getter]
    fn user(&self) -> Option<String> {
        self.inner.user.as_ref().map(ToString::to_string)
    }

    /// Optional path to redirect standard output to.
    #[getter]
    fn stdout(&self) -> Option<PathBuf> {
        self.inner.stdout.clone()
    }

    /// Optional path to redirect standard error to.
    #[getter]
    fn stderr(&self) -> Option<PathBuf> {
        self.inner.stderr.clone()
    }
}

config_class! {
    /// Branding and layout options for the engine's web console.
    ConsoleConfig wraps ceres_config::ConsoleConfig, raw ceres_config::RawConsoleConfig
}

#[gen_stub_pymethods]
#[pymethods]
impl ConsoleConfig {
    #[new]
    #[pyo3(signature = (*, title=None, favicon=None))]
    fn new(title: Option<String>, favicon: Option<PathBuf>) -> PyResult<Self> {
        let raw = ceres_config::RawConsoleConfig { title, favicon };
        let inner = ceres_config::ConsoleConfig::try_from(raw).map_err(problems_to_error)?;
        Ok(Self { inner })
    }

    /// Title shown in the console's browser tab and header.
    #[getter]
    fn title(&self) -> Option<String> {
        self.inner.title.clone()
    }

    /// Path to a favicon image served by the console.
    #[getter]
    fn favicon(&self) -> Option<PathBuf> {
        self.inner.favicon.clone()
    }
}

#[pymodule(gil_used = false)]
fn ceres_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<ServiceConfig>()?;
    module.add_class::<ConsoleConfig>()?;
    Ok(())
}

define_stub_info_gatherer!(stub_info);
