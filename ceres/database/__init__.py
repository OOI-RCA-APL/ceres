from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__, export=True):
    from ceres.database.database import Database as Database
