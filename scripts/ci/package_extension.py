"""Build one platform's extension zip with ``blender --command extension build --split-platforms``.

Usage:
    python scripts/ci/package_extension.py --blender <blender executable> --platform macos-arm64 --out dist

Blender's ``--split-platforms`` only filters *wheels* by platform; every other file (including the
compiled bindings in ``bindings/<os>/``) goes into every platform's zip. So the source tree must
hold only the target platform's bindings. This script checks that, builds all platform zips, keeps
the target platform's zip, and verifies its contents.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile

from pathlib import Path, PurePosixPath


ADDON = Path(__file__).resolve().parents[2] / "src" / "addons" / "character_dna"
BINDINGS_FOLDERS = {"windows-x64": "bindings/windows/x64/py313", "macos-arm64": "bindings/macos/arm64/py313"}
BINDING_FILES = {
    "windows-x64": ("dna.py", "riglogic.py", "_py3dna13_2_9.pyd", "_py3riglogic13_2_9.pyd"),
    "macos-arm64": ("dna.py", "riglogic.py", "_py3dna13_2_9.so", "_py3riglogic13_2_9.so"),
}
WHEEL_TAGS = {"windows-x64": "win_amd64", "macos-arm64": "macosx_11_0_arm64"}


def check_source_tree(platform: str) -> None:
    for other, folder in BINDINGS_FOLDERS.items():
        present = (ADDON / folder).is_dir()
        if other == platform and not present:
            raise SystemExit(f"Missing {folder} for {platform}; stage the bindings first.")
        if other != platform and (ADDON / folder.split("/")[0] / folder.split("/")[1]).exists():
            raise SystemExit(f"{folder} is present; it would be packed into the {platform} zip too.")


def build(blender: Path, output: Path) -> None:
    command = [
        str(blender),
        "--factory-startup",
        "--command",
        "extension",
        "build",
        "--source-dir",
        str(ADDON),
        "--output-dir",
        str(output),
        "--split-platforms",
    ]
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)  # noqa: S603 (fixed Blender CLI invocation)


def verify(zip_path: Path, platform: str) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        infos = archive.infolist()
    generated = manifest.get("build", {}).get("generated", {})
    print(f"{zip_path.name}: {zip_path.stat().st_size / 1e6:.2f} MB, {len(names)} files")
    print(f"  manifest platforms: {manifest.get('platforms')}  generated platforms: {generated.get('platforms')}")
    print(f"  generated wheels: {generated.get('wheels')}")
    top_level: dict[str, int] = {}
    for info in infos:
        top = PurePosixPath(info.filename).parts[0]
        top_level[top] = top_level.get(top, 0) + info.file_size
    for top, size in sorted(top_level.items(), key=lambda item: -item[1])[:12]:
        print(f"  {top:<32} {size / 1e6:8.2f} MB uncompressed")
    bindings = sorted(name for name in names if name.startswith("bindings/") and name.count("/") > 1)
    print("  bindings:", *bindings, sep="\n    ")

    problems = []
    if generated.get("platforms") != [platform]:
        problems.append(f"generated platforms is {generated.get('platforms')}, expected [{platform!r}]")
    wheels = [name for name in names if name.endswith(".whl")]
    if not wheels or any(WHEEL_TAGS[platform] not in wheel for wheel in wheels):
        problems.append(f"unexpected wheels for {platform}: {wheels}")
    expected = {f"{BINDINGS_FOLDERS[platform]}/{name}" for name in BINDING_FILES[platform]}
    if set(bindings) != expected:
        problems.append(f"bindings are {bindings}, expected {sorted(expected)}")
    problems.extend(
        f"zip contains {pattern!r} entries"
        for pattern in ("__pycache__/", ".pyc", "tests/")
        if any(pattern in name for name in names)
    )
    if problems:
        raise SystemExit("Package check failed:\n  " + "\n  ".join(problems))
    print("  package check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--platform", choices=sorted(BINDINGS_FOLDERS), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    check_source_tree(args.platform)
    for cache in ADDON.rglob("__pycache__"):
        shutil.rmtree(cache)
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        build(args.blender, Path(temp))
        built = sorted(Path(temp).glob("*.zip"))
        print("built:", *(path.name for path in built))
        suffix = args.platform.replace("-", "_")
        target = next(path for path in built if path.stem.endswith(suffix))
        destination = args.out / target.name
        shutil.move(target, destination)
    verify(destination, args.platform)
    print(f"Package: {destination}")


if __name__ == "__main__":
    sys.exit(main())
