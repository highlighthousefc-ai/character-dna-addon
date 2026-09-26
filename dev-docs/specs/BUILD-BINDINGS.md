# Building Epic's `dna` and `riglogic` Python bindings

The addon needs Epic's OpenRigLogic Python bindings (`dna` = read/write DNA files, `riglogic` = rig evaluation). OpenRigLogic is MIT-licensed. **Verified** on Python 3.12 / Linux x86_64 (OpenRigLogic 13.2.9); you must repeat it for every Python version Blender ships and every OS you target.

```bash
git clone https://github.com/EpicGames/OpenRigLogic.git
cd OpenRigLogic
pip install cmake ninja "swig==4.2.1"      # NOT swig 4.5.0, see pitfall 1
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DRL_BUILD_PYTHON_WRAPPER=3.11 -DBUILD_SHARED_LIBS=OFF   # exact Python version, e.g. 3.11 or 3.13
ninja -C build py3dna py3riglogic
```

Outputs to copy together into one folder that is on the import path:
- `build/python/dna/dna.py` + `_py3dna13_2_9.so*`
- `build/python/riglogic/riglogic.py` + `_py3riglogic13_2_9.so*`
(Extension is `.pyd` on Windows, `.so` on Linux/macOS. `riglogic.py` does `import dna`, so both must be importable.)

## Pitfalls hit while verifying
1. **SWIG 4.5.0 fails** to compile the `riglogic` wrapper (`SWIG_EXPAND_AND_QUOTE_STRING was not declared`). SWIG 4.2.1 works.
2. `RL_BUILD_PYTHON_WRAPPER` uses `find_package(Python3 <ver> EXACT ...)`, so it must match the interpreter/headers you build against. Install that Python's dev headers.
3. A single-core build took roughly 10 minutes. Run long builds detached and poll them.
4. **Blender packaging:** Blender's extension validator forbids top-level modules, but the SWIG wrappers import each other by bare name (`dna`, `riglogic`). The free Poly Hammer addon works around this with a custom isolated module loader (see `bindings/__init__.py` in its repo). You will need an equivalent, or vendor the wrappers with patched imports.
5. Plan a CI matrix (Windows x64, macOS arm64, Linux x64) x (Blender's Python versions). The free addon ships builds for Python 3.11 and 3.13. **VERIFY** which Blender versions use which Python.

## Verify the build
```bash
export PYTHONPATH=/path/to/staged/folder
python spikes/spike_read_evaluate.py path/to/head.dna
python spikes/spike_roundtrip_write.py path/to/head.dna /tmp/out.dna
```
