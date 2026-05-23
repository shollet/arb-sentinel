"""Smoke tests verifying the package and its primary dependencies load correctly."""

import arb_sentinel


def test_package_imports() -> None:
    """The arb_sentinel package can be imported."""
    assert arb_sentinel is not None


def test_package_has_main() -> None:
    """The package exposes a main entry point."""
    assert hasattr(arb_sentinel, "main")
    assert callable(arb_sentinel.main)


def test_runtime_dependencies_importable() -> None:
    """Runtime dependencies (httpx, pydantic, polars) can be imported."""
    import httpx
    import polars
    import pydantic

    assert httpx is not None
    assert pydantic is not None
    assert polars is not None
