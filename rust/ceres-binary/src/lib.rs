//! The binary packing layout model.
//!
//! A packing program describes how a value tree is laid out in bytes, as a tree of nodes
//! mirroring `ceres.data.binary`'s schema classes. This crate owns the layout model itself,
//! the deserializable spec, sizes, and byte-order resolution, while the engine walking
//! Python values against a spec lives with the extension module.
//!
//! Byte layout matches Python's `struct` module with an explicit byte order, standard sizes
//! and no alignment. Composite nodes concatenate their children, `Nx`-style padding becomes
//! zero bytes on pack and skipped bytes on unpack.

use serde::Deserialize;

/// One node in a compiled packing program, mirroring the Python schema classes.
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Node {
    Bytes { length: usize },
    Bool,
    Uint8,
    Int8,
    Uint16,
    Int16,
    Uint32,
    Int32,
    Uint64,
    Int64,
    Float16,
    Float32,
    Float64,
    Complex64,
    Complex128,
    Tuple { values: Vec<Spec> },
    Sequence { element: Box<Spec>, length: usize },
    Model { fields: Vec<(String, Spec)> },
}

/// A node together with its layout modifiers.
#[derive(Debug, Deserialize)]
pub struct Spec {
    #[serde(flatten)]
    pub node: Node,
    #[serde(default)]
    pub order: Option<String>,
    #[serde(default)]
    pub padding_before: usize,
    #[serde(default)]
    pub padding_after: usize,
}

impl Spec {
    /// The packed size in bytes, including padding.
    pub fn size(&self) -> usize {
        self.padding_before + self.node.size() + self.padding_after
    }
}

impl Node {
    /// The packed size in bytes of the node itself.
    pub fn size(&self) -> usize {
        match self {
            Node::Bytes { length } => *length,
            Node::Bool | Node::Uint8 | Node::Int8 => 1,
            Node::Uint16 | Node::Int16 | Node::Float16 => 2,
            Node::Uint32 | Node::Int32 | Node::Float32 => 4,
            Node::Uint64 | Node::Int64 | Node::Float64 | Node::Complex64 => 8,
            Node::Complex128 => 16,
            Node::Tuple { values } => values.iter().map(Spec::size).sum(),
            Node::Sequence { element, length } => element.size() * length,
            Node::Model { fields } => fields.iter().map(|(_, spec)| spec.size()).sum(),
        }
    }
}

/// A resolved byte order. The `=` specifier resolves to the platform's order at call time.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Endian {
    Little,
    Big,
}

impl Endian {
    /// The platform's byte order.
    pub fn native() -> Self {
        if cfg!(target_endian = "big") {
            Self::Big
        } else {
            Self::Little
        }
    }

    /// Resolve a `struct`-style byte order symbol.
    pub fn parse(symbol: &str) -> Result<Self, String> {
        match symbol {
            "<" => Ok(Self::Little),
            ">" => Ok(Self::Big),
            "=" => Ok(Self::native()),
            other => Err(format!(
                "byte order must be one of '<', '>', '=', got {other:?}"
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn leaf(node: Node) -> Spec {
        Spec {
            node,
            order: None,
            padding_before: 0,
            padding_after: 0,
        }
    }

    #[test]
    fn sizes_match_the_struct_layout() {
        let spec = Spec {
            node: Node::Tuple {
                values: vec![
                    leaf(Node::Uint8),
                    leaf(Node::Float32),
                    Spec {
                        padding_before: 2,
                        ..leaf(Node::Bytes { length: 4 })
                    },
                ],
            },
            order: None,
            padding_before: 0,
            padding_after: 1,
        };
        assert_eq!(spec.size(), 1 + 4 + 2 + 4 + 1);
    }

    #[test]
    fn sequences_multiply_their_element_size() {
        let spec = leaf(Node::Sequence {
            element: Box::new(leaf(Node::Int16)),
            length: 5,
        });
        assert_eq!(spec.size(), 10);
    }
}
