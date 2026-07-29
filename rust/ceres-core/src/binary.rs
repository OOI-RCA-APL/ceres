//! The native binary packing engine.
//!
//! `ceres.data.binary` describes wire formats as trees of packing schemas. A schema tree
//! compiles once into a [`PackingProgram`], a self-contained description the engine executes
//! natively, packing a whole value tree into one buffer and unpacking a whole buffer into
//! one Python value tree in a single call. Pydantic validation stays on the Python side,
//! applied once to the assembled value.
//!
//! Byte layout matches Python's `struct` module with an explicit byte order, standard sizes
//! and no alignment. Composite nodes concatenate their children, `Nx`-style padding becomes
//! zero bytes on pack and skipped bytes on unpack.

use ceres_binary::{Endian, Node, Spec};
use half::f16;
use pyo3::exceptions::{PyOverflowError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyComplex, PyDict, PyTuple};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

/// Append a fixed-width value in the requested byte order.
fn write<const N: usize>(out: &mut Vec<u8>, little: [u8; N], big: [u8; N], endian: Endian) {
    match endian {
        Endian::Little => out.extend_from_slice(&little),
        Endian::Big => out.extend_from_slice(&big),
    }
}

/// Read a fixed-width chunk in the requested byte order, returned as little-endian bytes.
fn read<const N: usize>(data: &[u8], endian: Endian) -> [u8; N] {
    let mut bytes: [u8; N] = data[..N].try_into().expect("the caller checked bounds");
    if endian == Endian::Big {
        bytes.reverse();
    }

    bytes
}

/// Extract an integer and check it against the width's valid range.
fn int_in_range(value: &Bound<'_, PyAny>, low: i128, high: i128, name: &str) -> PyResult<i128> {
    let number: i128 = value
        .extract()
        .map_err(|_| PyTypeError::new_err(format!("{name} requires an integer")))?;
    if number < low || number > high {
        return Err(PyValueError::new_err(format!(
            "{name} requires {low} <= number <= {high}, got {number}"
        )));
    }

    Ok(number)
}

/// Extract a float, mirroring `struct`'s acceptance of any number with a `__float__`.
fn as_float(value: &Bound<'_, PyAny>, name: &str) -> PyResult<f64> {
    value
        .extract()
        .map_err(|_| PyTypeError::new_err(format!("{name} requires a number")))
}

/// Extract a complex value, accepting a real number as a zero-imaginary complex.
fn as_complex(value: &Bound<'_, PyAny>) -> PyResult<(f64, f64)> {
    if let Ok(complex) = value.cast::<PyComplex>() {
        return Ok((complex.real(), complex.imag()));
    }

    let real: f64 = value
        .extract()
        .map_err(|_| PyTypeError::new_err("complex format requires a complex number"))?;
    Ok((real, 0.0))
}

/// Narrow a float, mirroring `struct`'s overflow error when a finite value cannot fit.
fn narrow<T>(value: f64, narrowed: T, is_infinite: bool, name: &str) -> PyResult<T> {
    if value.is_finite() && is_infinite {
        return Err(PyOverflowError::new_err(format!(
            "float too large to pack with {name} format"
        )));
    }

    Ok(narrowed)
}

fn pack_into(
    spec: &Spec,
    value: &Bound<'_, PyAny>,
    endian: Endian,
    out: &mut Vec<u8>,
) -> PyResult<()> {
    out.resize(out.len() + spec.padding_before, 0);

    match &spec.node {
        Node::Bytes { length } => {
            let bytes: &[u8] = value
                .extract()
                .map_err(|_| PyTypeError::new_err("bytes format requires a bytes object"))?;
            let copied = bytes.len().min(*length);
            out.extend_from_slice(&bytes[..copied]);
            out.resize(out.len() + (length - copied), 0);
        }
        Node::Bool => out.push(value.is_truthy()? as u8),
        Node::Uint8 => out.push(int_in_range(value, 0, 0xff, "uint8")? as u8),
        Node::Int8 => out.push(int_in_range(value, -0x80, 0x7f, "int8")? as u8),
        Node::Uint16 => {
            let number = int_in_range(value, 0, 0xffff, "uint16")? as u16;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Int16 => {
            let number = int_in_range(value, -0x8000, 0x7fff, "int16")? as i16;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Uint32 => {
            let number = int_in_range(value, 0, 0xffff_ffff, "uint32")? as u32;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Int32 => {
            let number = int_in_range(value, -0x8000_0000, 0x7fff_ffff, "int32")? as i32;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Uint64 => {
            let number = int_in_range(value, 0, u64::MAX as i128, "uint64")? as u64;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Int64 => {
            let number = int_in_range(value, i64::MIN as i128, i64::MAX as i128, "int64")? as i64;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Float16 => {
            let number = as_float(value, "float16")?;
            let converted = f16::from_f64(number);
            let narrowed = narrow(number, converted, converted.is_infinite(), "e")?;
            write(out, narrowed.to_le_bytes(), narrowed.to_be_bytes(), endian);
        }
        Node::Float32 => {
            let number = as_float(value, "float32")?;
            let narrowed = narrow(number, number as f32, (number as f32).is_infinite(), "f")?;
            write(out, narrowed.to_le_bytes(), narrowed.to_be_bytes(), endian);
        }
        Node::Float64 => {
            let number = as_float(value, "float64")?;
            write(out, number.to_le_bytes(), number.to_be_bytes(), endian);
        }
        Node::Complex64 => {
            let (real, imaginary) = as_complex(value)?;
            let real = narrow(real, real as f32, (real as f32).is_infinite(), "F")?;
            let imaginary = narrow(
                imaginary,
                imaginary as f32,
                (imaginary as f32).is_infinite(),
                "F",
            )?;
            write(out, real.to_le_bytes(), real.to_be_bytes(), endian);
            write(
                out,
                imaginary.to_le_bytes(),
                imaginary.to_be_bytes(),
                endian,
            );
        }
        Node::Complex128 => {
            let (real, imaginary) = as_complex(value)?;
            write(out, real.to_le_bytes(), real.to_be_bytes(), endian);
            write(
                out,
                imaginary.to_le_bytes(),
                imaginary.to_be_bytes(),
                endian,
            );
        }
        Node::Tuple { values } => {
            // Like Python's `zip`, packing stops at the shorter of the value and the schemas.
            let mut items = value.try_iter()?;
            for child in values {
                let Some(item) = items.next() else {
                    break;
                };
                pack_into(child, &item?, endian, out)?;
            }
        }
        Node::Sequence { element, .. } => {
            // The declared length only constrains unpacking, packing writes every element.
            for item in value.try_iter()? {
                pack_into(element, &item?, endian, out)?;
            }
        }
        Node::Model { fields } => {
            for (name, child) in fields {
                pack_into(child, &value.getattr(name.as_str())?, endian, out)?;
            }
        }
    }

    out.resize(out.len() + spec.padding_after, 0);
    Ok(())
}

fn unpack_from<'py>(
    spec: &Spec,
    py: Python<'py>,
    data: &[u8],
    offset: &mut usize,
    endian: Endian,
) -> PyResult<Bound<'py, PyAny>> {
    *offset += spec.padding_before;

    let need = spec.node.size();
    if data.len() < *offset + need {
        return Err(PyValueError::new_err(format!(
            "unpack requires a buffer of at least {} bytes, got {}",
            *offset + need,
            data.len()
        )));
    }

    let at = &data[*offset..];
    let value: Bound<'py, PyAny> = match &spec.node {
        Node::Bytes { length } => PyBytes::new(py, &at[..*length]).into_any(),
        Node::Bool => (at[0] != 0).into_pyobject(py)?.to_owned().into_any(),
        Node::Uint8 => at[0].into_pyobject(py)?.into_any(),
        Node::Int8 => (at[0] as i8).into_pyobject(py)?.into_any(),
        Node::Uint16 => u16::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Int16 => i16::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Uint32 => u32::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Int32 => i32::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Uint64 => u64::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Int64 => i64::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Float16 => f16::from_le_bytes(read(at, endian))
            .to_f64()
            .into_pyobject(py)?
            .into_any(),
        Node::Float32 => (f32::from_le_bytes(read(at, endian)) as f64)
            .into_pyobject(py)?
            .into_any(),
        Node::Float64 => f64::from_le_bytes(read(at, endian))
            .into_pyobject(py)?
            .into_any(),
        Node::Complex64 => {
            let real = f32::from_le_bytes(read(at, endian)) as f64;
            let imaginary = f32::from_le_bytes(read(&at[4..], endian)) as f64;
            PyComplex::from_doubles(py, real, imaginary).into_any()
        }
        Node::Complex128 => {
            let real = f64::from_le_bytes(read(at, endian));
            let imaginary = f64::from_le_bytes(read(&at[8..], endian));
            PyComplex::from_doubles(py, real, imaginary).into_any()
        }
        Node::Tuple { values } => {
            let mut items = Vec::with_capacity(values.len());
            for child in values {
                items.push(unpack_from(child, py, data, offset, endian)?);
            }

            *offset += spec.padding_after;
            return Ok(PyTuple::new(py, items)?.into_any());
        }
        Node::Sequence { element, length } => {
            let mut items = Vec::with_capacity(*length);
            for _ in 0..*length {
                items.push(unpack_from(element, py, data, offset, endian)?);
            }

            *offset += spec.padding_after;
            return Ok(PyTuple::new(py, items)?.into_any());
        }
        Node::Model { fields } => {
            let arguments = PyDict::new(py);
            for (name, child) in fields {
                arguments.set_item(name, unpack_from(child, py, data, offset, endian)?)?;
            }

            *offset += spec.padding_after;
            return Ok(arguments.into_any());
        }
    };

    *offset += spec.node.size() + spec.padding_after;
    Ok(value)
}

/// A compiled binary packing program.
///
/// Built by `ceres.data.binary` from a packing schema tree and executed natively, packing a
/// whole value into one buffer and unpacking a whole buffer into one value tree per call.
/// Models unpack to plain dictionaries, validation and model construction stay with the
/// caller.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct PackingProgram {
    spec: Spec,
    size: usize,
}

#[gen_stub_pymethods]
#[pymethods]
impl PackingProgram {
    #[new]
    fn new(
        #[gen_stub(override_type(type_repr = "dict[str, typing.Any]"))] spec: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        let spec: Spec = crate::interop::from_python(spec)?;
        let size = spec.size();
        Ok(Self { spec, size })
    }

    /// The packed size in bytes.
    #[getter]
    fn size(&self) -> usize {
        self.size
    }

    /// Pack a value into its binary representation.
    #[pyo3(signature = (value, order=None))]
    fn pack<'py>(
        &self,
        py: Python<'py>,
        value: &Bound<'_, PyAny>,
        order: Option<&str>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let endian = self.resolve_order(order)?;
        let mut out = Vec::with_capacity(self.size);
        pack_into(&self.spec, value, endian, &mut out)?;
        Ok(PyBytes::new(py, &out))
    }

    /// Unpack a value tree from binary data.
    #[pyo3(signature = (data, offset=0, order=None))]
    fn unpack<'py>(
        &self,
        py: Python<'py>,
        #[gen_stub(override_type(type_repr = "bytes"))] data: &[u8],
        offset: usize,
        order: Option<&str>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let endian = self.resolve_order(order)?;
        let mut offset = offset;
        unpack_from(&self.spec, py, data, &mut offset, endian)
    }
}

impl PackingProgram {
    fn resolve_order(&self, order: Option<&str>) -> PyResult<Endian> {
        match order.or(self.spec.order.as_deref()) {
            Some(symbol) => Endian::parse(symbol).map_err(PyValueError::new_err),
            None => Ok(Endian::Little),
        }
    }
}
