"""Resolve the OpenRigLogic ``dna`` module lazily, inside or outside the addon."""

from types import ModuleType


def dna_module() -> ModuleType:
    """Return Epic's ``dna`` bindings module.

    Inside the addon this is the isolated copy loaded by ``character_dna.bindings``. Outside it
    (tests, tooling) a bare ``dna`` module must be importable from ``sys.path``.
    """
    try:
        from ..bindings import dna  # pyright: ignore[reportAttributeAccessIssue]
    except ImportError:
        import dna  # pyright: ignore[reportMissingImports]

    return dna


def riglogic_module() -> ModuleType:
    """Return Epic's ``riglogic`` bindings module (resolved like :func:`dna_module`)."""
    dna_module()  # riglogic's wrapper needs dna loaded first
    try:
        from ..bindings import riglogic  # pyright: ignore[reportAttributeAccessIssue]
    except ImportError:
        import riglogic  # pyright: ignore[reportMissingImports]

    return riglogic
