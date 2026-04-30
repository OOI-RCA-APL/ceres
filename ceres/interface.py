from ceres.component import Component, query
from ceres.ui import Element

__all__ = [
    "Interface",
]


class Interface(Component):
    """Component that renders a user-facing UI element.

    Subclasses implement `render()` to build the tree of `Element` instances shown to the
    operator. The `render()` method is exposed as a query so the engine and other components
    can request the latest UI state.
    """

    @query
    async def render(self) -> Element:
        """Produce the current UI element tree for this interface."""
        ...
