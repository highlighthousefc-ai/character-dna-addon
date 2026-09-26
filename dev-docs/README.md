# Developer notes

Not part of the user documentation site (`docs/`, built by mkdocs).

- `FINDINGS.md`: the running log of verified facts and dead ends, newest sections last.
- `02-fork-and-windows.md`: the fork decision and the Windows / bindings plan (September 2026).
- `specs/`: feature specs, starting with `00-overview.md`. `08-character-assembly.md` covers importing a
  Poly Hammer Interchange "Export Character For DCC" folder. `BUILD-BINDINGS.md` covers building Epic's
  OpenRigLogic Python bindings.

Some specs mention `spikes/` and `CLAUDE.md`. Those live in the maintainer's local project folder and
aren't in this repository; the bindings build itself is now in `bindings-build/`.

Never commit a real MetaHuman export or DNA here; see `.gitignore`.
