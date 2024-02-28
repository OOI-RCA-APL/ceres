from typing import TYPE_CHECKING

from ceres.internal.lazy import LazyExport

__export = LazyExport(__name__)

if TYPE_CHECKING:
    from ceres.internal.app.main import App as App

__export("ceres.internal.app.main", "App")
