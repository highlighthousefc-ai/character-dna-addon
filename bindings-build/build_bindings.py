"""Build Epic's OpenRigLogic ``dna`` / ``riglogic`` Python bindings for Blender and stage them.

Usage:
    python bindings-build/build_bindings.py --source <OpenRigLogic checkout> --out <folder>

Run it with the Python 3.13 interpreter whose headers/import library the bindings should be
built against. The output is laid out the way ``character_dna/bindings/__init__.py`` expects:

    <out>/<os>/<arch>/py313/dna.py, riglogic.py, _py3dna13_2_9.<ext>, _py3riglogic13_2_9.<ext>

``<ext>`` is ``.pyd`` on Windows and ``.so`` on macOS. The source checkout must already have
``openriglogic-blender.patch`` applied (see README.md).

Windows: MSVC (Visual Studio generator), static C++ runtime (``/MT``), links ``python313.lib``.
macOS: Ninja + Apple clang, ``.dylib`` renamed to ``.so``, ``@rpath`` rewritten to
``@loader_path``, ad-hoc re-signed.
"""

# This build script only runs fixed toolchain commands (cmake, otool, install_name_tool, codesign).
# ruff: noqa: S603, S607

import argparse
import platform
import shutil
import subprocess
import sys

from pathlib import Path


VERSION = "13_2_9"
MODULES = ("dna", "riglogic")
# DLL name prefixes that mean the MSVC C/C++ runtime was linked dynamically (/MD) instead of
# statically (/MT). Blender users may not have the matching VC++ redistributable installed.
WINDOWS_CRT_PREFIXES = ("vcruntime", "msvcp", "ucrtbase", "api-ms-win-crt-", "concrt", "vccorlib")
PYTHON_DLL = f"python3{sys.version_info.minor}.dll"


def run(*command: str | Path) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True)


def target_folder(out: Path) -> Path:
    os_name = {"win32": "windows", "darwin": "macos"}[sys.platform]
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return out / os_name / arch / f"py3{sys.version_info.minor}"


def configure_and_build(source: Path, build: Path) -> None:
    common = [
        f"-DRL_BUILD_PYTHON_WRAPPER=3.{sys.version_info.minor}",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DRL_BUILD_TESTS=OFF",
        "-DRL_BUILD_BENCHMARKS=OFF",
        "-DREAD_ONLY_SOURCE_TREE=ON",
        f"-DPython3_EXECUTABLE={sys.executable}",
    ]
    if sys.platform == "win32":
        platform_args = ["-A", "x64", "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded"]
    else:
        platform_args = [
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_OSX_ARCHITECTURES=arm64",
            "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0",
        ]
    run("cmake", "-S", source, "-B", build, *platform_args, *common)
    run("cmake", "--build", build, "--config", "Release", "--parallel", "--target", "py3dna", "py3riglogic")


def find_one(folder: Path, pattern: str) -> Path:
    matches = sorted(folder.rglob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {pattern} under {folder}, found {matches}")
    return matches[0]


def wrapper_source(folder: Path, module: str) -> Path:
    """SWIG writes ``<module>.py`` next to the target, or into the config folder (multi-config)."""
    direct = folder / f"{module}.py"
    return direct if direct.is_file() else find_one(folder, f"{module}.py")


def stage_windows(build: Path, target: Path) -> None:
    for module in MODULES:
        folder = build / "python" / module
        shutil.copy2(wrapper_source(folder, module), target)
        shutil.copy2(find_one(folder, f"_py3{module}{VERSION}.pyd"), target)


def stage_macos(build: Path, target: Path) -> None:
    for module in MODULES:
        folder = build / "python" / module
        shutil.copy2(folder / f"{module}.py", target)
        shutil.copy2(folder / f"_py3{module}{VERSION}.13.2.9.dylib", target / f"_py3{module}{VERSION}.so")
    dna_lib, rl_lib = target / f"_py3dna{VERSION}.so", target / f"_py3riglogic{VERSION}.so"
    run("install_name_tool", "-id", f"@loader_path/{dna_lib.name}", dna_lib)
    run("install_name_tool", "-id", f"@loader_path/{rl_lib.name}", rl_lib)
    run("install_name_tool", "-change", f"@rpath/_py3dna{VERSION}.13.dylib", f"@loader_path/{dna_lib.name}", rl_lib)
    load_commands = subprocess.run(["otool", "-l", str(rl_lib)], check=True, capture_output=True, text=True).stdout
    lines = load_commands.splitlines()
    for index, line in enumerate(lines):
        if "LC_RPATH" in line:
            rpath = lines[index + 2].split()[1]
            run("install_name_tool", "-delete_rpath", rpath, rl_lib)
    run("codesign", "--force", "-s", "-", dna_lib, rl_lib)


def check_windows_imports(target: Path) -> None:
    import pefile  # only needed on Windows

    for library in sorted(target.glob("*.pyd")):
        pe = pefile.PE(str(library), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        imports = sorted(entry.dll.decode().lower() for entry in pe.DIRECTORY_ENTRY_IMPORT)
        print(f"{library.name} imports: {', '.join(imports)}")
        crt = [name for name in imports if name.startswith(WINDOWS_CRT_PREFIXES)]
        if crt:
            raise RuntimeError(f"{library.name} depends on the dynamic MSVC runtime: {crt}")
        if PYTHON_DLL not in imports:
            raise RuntimeError(f"{library.name} does not import {PYTHON_DLL}")


def check_macos_links(target: Path) -> None:
    for library in sorted(target.glob("*.so")):
        output = subprocess.run(["otool", "-L", str(library)], check=True, capture_output=True, text=True).stdout
        print(output)
        # The first line is the library's own path; only the linked libraries matter.
        links = [line.split(" (")[0].strip() for line in output.splitlines()[1:] if line.strip()]
        if any(link.startswith("@rpath") or link.startswith("/Users/") for link in links):
            raise RuntimeError(f"{library.name} still links through an rpath or absolute build path")


def smoke_import(target: Path) -> None:
    """Import both modules from the staged folder in a fresh interpreter."""
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); import dna, riglogic; "
        "print('imported', dna.__name__, riglogic.__name__, 'from', sys.argv[1])"
    )
    run(sys.executable, "-B", "-c", script, target)  # -B: no __pycache__ in the staged folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="patched OpenRigLogic checkout")
    parser.add_argument("--build", type=Path, default=Path("build/openriglogic"), help="CMake build folder")
    parser.add_argument("--out", type=Path, required=True, help="root of the staged bindings tree")
    args = parser.parse_args()

    if sys.version_info[:2] != (3, 13):
        raise SystemExit(f"Build with Python 3.13 (Blender 5.x); this is {sys.version.split()[0]}")

    configure_and_build(args.source.resolve(), args.build.resolve())
    target = target_folder(args.out.resolve())
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    if sys.platform == "win32":
        stage_windows(args.build.resolve(), target)
        check_windows_imports(target)
    else:
        stage_macos(args.build.resolve(), target)
        check_macos_links(target)
    smoke_import(target)
    print(f"Staged bindings in {target}")


if __name__ == "__main__":
    main()
