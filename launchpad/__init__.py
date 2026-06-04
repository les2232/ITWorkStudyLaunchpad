"""Core package for the IT Work Study Launchpad prototype."""

__all__ = ["create_app"]


def create_app(config: dict | None = None):
    from .web import create_app as _create_app

    return _create_app(config)
