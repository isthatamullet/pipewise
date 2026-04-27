"""Smoke test — confirms the package imports and CI harness works."""

import pipewise


def test_version_present() -> None:
    assert isinstance(pipewise.__version__, str)
    assert pipewise.__version__
