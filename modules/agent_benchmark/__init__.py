"""Load the canonical package when repository modules/ is on sys.path."""

from importlib.util import spec_from_file_location as _spec_from_file_location
from pathlib import Path as _Path
import sys as _sys

_package = _Path(__file__).parent / "agent_benchmark"
_spec = _spec_from_file_location(__name__, _package / "__init__.py", submodule_search_locations=[str(_package)])
assert _spec is not None and _spec.loader is not None
__path__ = [str(_package)]
__file__ = str(_package / "__init__.py")
__spec__ = _spec
_spec.loader.exec_module(_sys.modules[__name__])
