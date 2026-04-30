from collections.abc import Callable


def traverse(
    obj: object,
    /,
    visit: Callable[[object], bool | None],
    seen: set[int] | None = None,
) -> None:
    """Recursively walk an object graph, calling `visit` on each node.

    Traverse into Pydantic models, dataclasses, mappings, and collections. Track visited objects
    by identity to avoid infinite cycles.

    Args:
        obj: The root object to start traversal from.
        visit: A callback invoked for each node. Return ``False`` to stop descending into the
            node's children, or ``None`` / ``True`` to continue.
        seen: An optional set of already-visited object ids used to prevent revisiting nodes.
    """
    import dataclasses

    from pydantic import BaseModel

    from ceres.__internal__.utilities.typing import is_collection, is_mapping

    if seen is None:
        seen = set()
    if id(obj) in seen:
        return

    seen.add(id(obj))

    descend = visit(obj)
    if descend is not None:
        if not descend:
            return
    if obj is None:
        return

    undefined = object()
    if isinstance(obj, BaseModel):
        for field_name, field in obj.__class__.model_fields.items():
            element = getattr(obj, field_name, undefined)
            if element is not undefined:
                traverse(element, visit, seen)
    elif not isinstance(obj, type) and dataclasses.is_dataclass(obj):
        for field in dataclasses.fields(obj):
            element = getattr(obj, field.name, undefined)
            if element is not undefined:
                traverse(element, visit, seen)
    elif is_mapping(obj):
        for key, value in obj.items():
            traverse(key, visit, seen)
            traverse(value, visit, seen)
    elif is_collection(obj):
        for value in obj:
            traverse(value, visit, seen)
