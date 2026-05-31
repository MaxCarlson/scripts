class _TmpPathFactoryStub:
    """Stub that satisfies pytest-asyncio 1.3.0 monkeypatch undo after cleanup."""
    _basetemp = None


def pytest_sessionfinish(session, exitstatus):
    # pytest-asyncio 1.3.0 bug: --continue-on-collection-errors causes pytest to remove
    # _tmp_path_factory before asyncio's monkeypatch undo fires in _ensure_unconfigure.
    # Restoring a stub prevents the AttributeError/'NoneType'._basetemp cascade.
    if not hasattr(session.config, "_tmp_path_factory"):
        session.config._tmp_path_factory = _TmpPathFactoryStub()
