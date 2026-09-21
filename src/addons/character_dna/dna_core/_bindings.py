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
