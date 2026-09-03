# Security Policy

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private
addresses, or logs. Use GitHub's private vulnerability-reporting feature for
this repository. If private reporting is unavailable, open a minimal issue
asking the maintainer to establish a private channel; omit technical details.

Include the affected version/commit, prerequisites, impact, a minimal
reproduction, and suggested remediation. Remove tokens, API keys, cookies,
account identifiers, and private network details.

## Response targets

These are project targets, not an SLA: acknowledge critical/high reports in
three business days, establish severity and containment in seven, and publish
a coordinated fix/advisory as soon as safely validated. Lower-severity issues
are prioritized by exploitability and impact.

## Supported version

Only the latest published release and the default branch receive security
fixes. Operators should keep Home Assistant and the Phyn Smart Water Assistant
integration for Home Assistant updated and retain a tested rollback/backup.

## Security boundaries

The Phyn Smart Water Assistant integration for Home Assistant is a privileged
Home Assistant integration, not a sandbox. Its Phyn cloud account credentials
(username and password, exchanged for OAuth-style tokens by the `aiophyn`
client) are stored in Home Assistant's encrypted config entry storage, the
same mechanism every other core and custom integration uses; this repository
ships no separate credential store and no secrets of its own. Sensor and
control data comes from Phyn's cloud API (`iot_class: cloud_push`); the
integration does not open a listening port and does not proxy or relay data
to any third party beyond Phyn. Some devices also expose an optional local
LAN connection that this integration may use for reduced-latency device
communication where supported, in addition to the cloud channel, not as a
replacement for it; that local traffic stays on the operator's own network
and carries no internet-facing credentials.

This integration cannot prevent a malicious integration in the same Python
process from reading shared memory, the config entry store, or logs. It
cannot guarantee the security of Phyn's cloud service or Phyn's account
authentication, which are outside this project's control. Reported findings
here are inputs for the operator to act on; they are not a certification and
not a claim that no vulnerability exists.
