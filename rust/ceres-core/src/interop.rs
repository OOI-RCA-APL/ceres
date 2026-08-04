//! Conversions between configuration values and Python objects.
//!
//! The `python_config!` macro leans on two traits here. [`PyFieldType`] maps a raw field type
//! to the Python-facing types of its constructor argument and getter, and [`ToPyValue`]
//! converts a validated field value into its Python-facing form.

use std::path::PathBuf;
use std::time::Duration;

use ceres_config::{ByteSize, Name, Secret, TimeDelta};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pythonize::{depythonize, pythonize};
use serde::Serialize;
use serde::de::DeserializeOwned;

/// Convert validation problems into a Python `ValueError`.
pub fn problems_to_error(problems: ceres_config::Problems) -> PyErr {
    PyValueError::new_err(problems.to_string())
}

/// Convert a serializable value into a Python object.
pub fn to_python<T: Serialize>(py: Python<'_>, value: &T) -> PyResult<Py<PyAny>> {
    Ok(pythonize(py, value)?.unbind())
}

/// Convert a Python object into a deserializable value.
pub fn from_python<T: DeserializeOwned>(value: &Bound<'_, PyAny>) -> PyResult<T> {
    depythonize(value).map_err(|error| PyValueError::new_err(error.to_string()))
}

/// Convert a validated value back into the raw form of another type.
///
/// Nested configuration values arrive at a constructor already validated, while the parent's
/// raw form holds raw sections. The round trip through serde is lossless.
pub fn reraw<Value: Serialize, Raw: DeserializeOwned>(value: &Value) -> PyResult<Raw> {
    let serialized =
        serde_json::to_value(value).map_err(|error| PyValueError::new_err(error.to_string()))?;
    serde_json::from_value(serialized).map_err(|error| PyValueError::new_err(error.to_string()))
}

/// Map a validated field type to the types it crosses the Python boundary with.
pub trait PyFieldType: Sized {
    /// The constructor argument type.
    type Input;

    /// The getter return type.
    type Py;

    /// The raw form's field type the constructor argument converts into.
    type Raw;

    /// Convert a constructor argument into the raw field value.
    fn from_input(input: Self::Input) -> PyResult<Self::Raw>;
}

/// Convert a validated field value into its Python-facing form.
pub trait ToPyValue<T> {
    fn to_py_value(&self) -> T;
}

/// Implement the identity conversions for types that cross the boundary unchanged.
macro_rules! identity_field {
    ($($ty:ty),* $(,)?) => {
        $(
            impl PyFieldType for $ty {
                type Input = $ty;
                type Py = $ty;
                type Raw = $ty;

                fn from_input(input: $ty) -> PyResult<$ty> {
                    Ok(input)
                }
            }

            impl ToPyValue<$ty> for $ty {
                fn to_py_value(&self) -> $ty {
                    self.clone()
                }
            }
        )*
    };
}

identity_field!(String, PathBuf, bool, u16, u64, i64, Vec<String>);

impl<T: PyFieldType> PyFieldType for Option<T> {
    type Input = Option<T::Input>;
    type Py = Option<T::Py>;
    type Raw = Option<T::Raw>;

    fn from_input(input: Self::Input) -> PyResult<Self::Raw> {
        input.map(T::from_input).transpose()
    }
}

impl<T: ToPyValue<U>, U> ToPyValue<Option<U>> for Option<T> {
    fn to_py_value(&self) -> Option<U> {
        self.as_ref().map(ToPyValue::to_py_value)
    }
}

impl PyFieldType for Name {
    type Input = String;
    type Py = String;
    type Raw = String;

    fn from_input(input: String) -> PyResult<String> {
        Ok(input)
    }
}

impl ToPyValue<String> for Name {
    fn to_py_value(&self) -> String {
        self.to_string()
    }
}

/// A secret constructor argument, accepting a string or a wrapper like Pydantic's
/// `SecretStr` that exposes its value through `get_secret_value`.
pub struct SecretInput(Secret);

impl FromPyObject<'_, '_> for SecretInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(text) = value.extract::<String>() {
            return Ok(Self(Secret::new(text)));
        }

        let exposed: String = value.call_method0("get_secret_value")?.extract()?;
        Ok(Self(Secret::new(exposed)))
    }
}

impl pyo3_stub_gen::PyStubType for SecretInput {
    fn type_output() -> pyo3_stub_gen::TypeInfo {
        pyo3_stub_gen::TypeInfo::with_module("str | pydantic.SecretStr", "pydantic".into())
    }
}

impl PyFieldType for Secret {
    type Input = SecretInput;
    type Py = String;
    type Raw = Secret;

    fn from_input(input: SecretInput) -> PyResult<Secret> {
        Ok(input.0)
    }
}

impl ToPyValue<String> for Secret {
    fn to_py_value(&self) -> String {
        self.expose().to_string()
    }
}

/// A duration constructor argument, accepting `timedelta`, seconds, or ISO 8601 text.
pub struct TimeDeltaInput(TimeDelta);

impl FromPyObject<'_, '_> for TimeDeltaInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(duration) = value.extract::<Duration>() {
            return Ok(Self(TimeDelta::from_duration(duration)));
        }

        if let Ok(seconds) = value.extract::<f64>() {
            return TimeDelta::parse(&seconds.to_string())
                .map(Self)
                .map_err(PyValueError::new_err);
        }

        let text: String = value.extract()?;
        TimeDelta::parse(&text)
            .map(Self)
            .map_err(PyValueError::new_err)
    }
}

impl pyo3_stub_gen::PyStubType for TimeDeltaInput {
    fn type_output() -> pyo3_stub_gen::TypeInfo {
        pyo3_stub_gen::TypeInfo::with_module(
            "datetime.timedelta | int | float | str",
            "datetime".into(),
        )
    }
}

impl PyFieldType for TimeDelta {
    type Input = TimeDeltaInput;
    type Py = Duration;
    type Raw = TimeDelta;

    fn from_input(input: TimeDeltaInput) -> PyResult<Self> {
        Ok(input.0)
    }
}

impl ToPyValue<Duration> for TimeDelta {
    fn to_py_value(&self) -> Duration {
        self.duration()
    }
}

/// A byte size constructor argument, accepting a count or unit-suffixed text.
pub struct ByteSizeInput(ByteSize);

impl FromPyObject<'_, '_> for ByteSizeInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(bytes) = value.extract::<u64>() {
            return Ok(Self(ByteSize::new(bytes)));
        }

        let text: String = value.extract()?;
        ByteSize::parse(&text)
            .map(Self)
            .map_err(PyValueError::new_err)
    }
}

impl pyo3_stub_gen::PyStubType for ByteSizeInput {
    fn type_output() -> pyo3_stub_gen::TypeInfo {
        pyo3_stub_gen::TypeInfo::builtin("int | str")
    }
}

impl PyFieldType for ByteSize {
    type Input = ByteSizeInput;
    type Py = u64;
    type Raw = ByteSize;

    fn from_input(input: ByteSizeInput) -> PyResult<Self> {
        Ok(input.0)
    }
}

impl ToPyValue<u64> for ByteSize {
    fn to_py_value(&self) -> u64 {
        self.bytes()
    }
}
