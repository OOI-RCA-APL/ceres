from typing import TYPE_CHECKING

from ceres._internal.lazy import LazyExport

__export = LazyExport(__name__)

if TYPE_CHECKING:
    from ceres._internal.app.main import App as App

__export("ceres._internal.app.main", "App")
