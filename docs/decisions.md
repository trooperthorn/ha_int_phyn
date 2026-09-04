# Decisions

Dated decisions with the alternative rejected and why.

## 2026-09-04: runtime objects live on `entry.runtime_data`

The client and coordinator moved from `hass.data[DOMAIN]` into a
`PhynRuntimeData` dataclass on the config entry (`PhynConfigEntry`). Platforms,
the options flow, diagnostics, and services read them from the entry, and the
services helper finds the loaded entry through
`hass.config_entries.async_loaded_entries`. Rejected: keeping the module-level
dictionary, which the manifest's claimed platinum quality scale forbids
(`runtime-data` rule) and which could not distinguish entries. The integration
still runs one primary entry per account; redundant entries remove themselves.

## 2026-09-04: the options flow no longer stores the entry itself

`PhynOptionsFlow.__init__` took and stored the config entry; the base class
provides `config_entry`, and explicit storage is the deprecated pattern
(`docs/core/integration/options_flow.md`). Rejected: keeping the private copy.

## 2026-09-04: `aiophyn` is pinned exactly

`aiophyn==2026.6.4` replaces the `>=` floor so installs are reproducible. The
test install still passes `--no-deps` because the library's own `pycognito`
pin conflicts with `hass-nabucasa`; see `docs/operations.md`.

## 2026-09-04: percentage units use `UnitOfRatio.PERCENTAGE`

The bare `PERCENTAGE` constant as a unit is deprecated since core 2026.7
(developer blog 2026-06-30).

## 2026-09-04: minimum Home Assistant is 2026.9.0

The suite runs on `pytest-homeassistant-custom-component` 0.13.363, which pins
core 2026.9.0; that is the only version the tests prove. Rejected: keeping the
2026.6.4 floor.

## 2026-09-04: DHCP discovery logs a shortened identifier, not the host

CodeQL flagged two discovery log lines (`py/clear-text-logging-sensitive-data`)
that printed the device MAC and its LAN address. Neither is a secret on its
own, but debug logs are pasted into issues, and a MAC plus address pair
identifies a household device. The lines now log no device identifier at
all (the info line names the account entry instead); the address is still
stored on the entry where the integration needs it. A shortened identifier
was tried first and still flagged, because CodeQL treats anything derived
from the discovery MAC as private data. Rejected: dismissing the alert, because the
log-sharing case is the realistic one.

## 2026-09-04: The platinum quality scale claim is dropped

`manifest.json` carried `quality_scale: platinum` inherited from upstream with
no `quality_scale.yaml` ledger behind it. The claim is removed rather than
backed by a ledger written in a hurry; the rules this fork demonstrably meets
(runtime data, reauth and reconfigure flows, diagnostics, translations) are
listed in `docs/design.md`, and a ledger can be added when the remaining
rules are audited one by one. Rejected: keeping an unverified claim, which
contradicts the house rule of never asserting what has not been checked.

