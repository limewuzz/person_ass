
import importlib.util, pathlib
_spec = importlib.util.spec_from_file_location(
    "dbpg_repository", pathlib.Path(__file__).resolve().parents[1] / "dbpg" / "repository.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class PgRepoProbe(_mod.PgTaskRepo):
    """证明蓝本显式 NotImplementedError（PG_RUNTIME NOT RUN）。"""
