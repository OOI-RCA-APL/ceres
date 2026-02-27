import warnings

import pydantic.warnings

from ceres._internal.lazy import __lazy_imports__

# Suppress Pydantic warnings about unsupported field attributes. These warnings occur due to how
# FastAPI handles model-based query parameters with aliases and can be ignored.
warnings.filterwarnings(
    "ignore",
    category=pydantic.warnings.UnsupportedFieldAttributeWarning,
    module="pydantic",
)

with __lazy_imports__(__name__, export=True):
    from ceres._internal.app.main import App as App
