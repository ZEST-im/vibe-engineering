# Security Policy

## Reporting

Open a [private advisory](https://github.com/ZEST-im/vibe-engineering/security/advisories/new).
Do not open a public issue for a vulnerability.

## What this project touches on your machine

`scripts/setup.py` copies runtime files into `~/.claude/skills/`, registers hooks in
`~/.claude/settings.json` and copies their scripts into `~/.claude/hooks/`, and installs an
auto-start agent (a LaunchAgent on macOS, a Scheduled Task on Windows). The full list is in the
README's Install section, and `tests/test_installer_footprint.py` holds that section to what
`setup.py` actually does.

Nothing leaves the machine unless you deliberately opt into token usage attribution
(`scripts/enroll.py` or `server.py configure-sync`) — see [PRIVACY.md](PRIVACY.md) for exactly
what that sends.

## Supported versions

Fixes land on `main`. There are no backport branches and no maintained older versions.
