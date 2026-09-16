"""Keep local test bindings in sync with the checkout used by CI."""

import shutil

from pathlib import Path


def _copy_changed(source: str, destination: str) -> str:
    target = Path(destination)
    if not target.is_file() or Path(source).read_bytes() != target.read_bytes():
        shutil.copy2(source, destination)
    return destination


def install_test_bindings(source: Path, destination: Path) -> None:
    """Refresh a sibling checkout, or use already bundled bindings if it is absent."""
    if source.is_dir():
        # Skip identical binaries: another Blender process may have them loaded.
        shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=_copy_changed)
    elif not destination.is_dir():
        raise FileNotFoundError(f'The bindings in "{destination}" are missing. Please add them to run the tests.')
