# Backlog

Dated open items.

- 2026-09-04: mypy reports four pre-existing errors (a read-only
  `update_interval` assignment in `__init__.py`, a `JsonValueType` mismatch in
  `services.py`, and two `PhynEntity` attribute and overload errors in
  `devices/pw.py`). The CI mypy job passes because it runs an unpinned mypy
  against an unpinned core; pin both and fix the four.
- 2026-09-04: ruff is not in the gate; a first run with the house rule set
  reports 39 fixable findings. Add `pyproject.toml` and the Lint step as the
  other repositories have.
- 2026-09-04: install the release GitHub App on this repository and set
  `RELEASE_AUTOMATION_PRIVATE_KEY` (the client ID variable is set); until then
  version bumps are manual.
- 2026-09-04: the manifest claims `quality_scale: platinum`, inherited from
  upstream; no `quality_scale.yaml` backs it. Either add the ledger or drop the
  claim.
