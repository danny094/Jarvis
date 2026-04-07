# Obsidian Doc Leak Audit - 2026-04-07

Goal: audit the public repo for real documentation leaks without destroying the
technical usefulness of the notes.

## Git-Safe Definition

For Obsidian, `git-safe` means:

- no passwords
- no API keys or tokens
- no private keys or SSH keys
- no session, cookie, or authorization data
- no real host LAN or VPN addresses
- no user-specific absolute host paths unless they are necessary for the point

## Result

The priority leaks in the Obsidian area were redacted:

- real host LAN IP
- real Tailscale IP
- direct host URLs with real IPs
- user-specific absolute host paths under `$HOME/...`
- repo-absolute shell examples replaced with `<repo-root>/...`

## Redacted Notes

- `2026-03-25-docker-netzwerke.md`
- `2026-03-25-trion-dienste-ports-netzwerke.md`
- `2026-03-24-netzwerk-port-uebersicht.md`
- `2026-03-24-sunshine-pairing-gegencheck.md`
- `2026-03-24-implementationsplan.md`
- `Archiv/2026-04-gaming-station/2026-03-26-gaming-station-diagnostic-und-fixes.md`
- `Archiv/2026-04-gaming-station/2026-03-24-gaming-station-container-doc.md`
- `Archiv/2026-04-gaming-station/02-Gaming-Station-Storage-Sunshine-noVNC.md`
- `Archiv/2026-04-gaming-station/07-Gaming-Station-GitHub-Package-Prep.md`
- `Archiv/2026-04-gaming-station/18-Claude-Handoff-Gaming-Station-2026-03-24.md`

## Redaction Rules

- real host IP -> `<HOST_LAN_IP>`
- real Tailscale IP -> `<HOST_TAILSCALE_IP>`
- direct host URL -> `https://<TRION_PUBLIC_HOST>:PORT`
- user-specific host paths -> `$HOME/...`
- repo-absolute shell or file paths -> `<repo-root>/...`

## Intentionally Kept

- Docker subnets such as `172.17.0.0/16`, `172.18.0.0/16`, `172.21.0.0/16`
- virtual or technical standard paths such as `/tmp`, `/app/data`,
  `/var/run/docker.sock`
- absolute local code-reference links of the form `<repo-root>/...` in
  implementation notes

The last category is more portability and repo-link debt than an active secret
leak. It can be converted later to relative repo links or `<repo-root>`
notation.

## Residual Risk

The notes still contain technical product details, Docker topology, and
historical runtime state. That is usually acceptable for a public engineering
repo as long as there are no real credentials, private keys, live host IPs, or
personal paths.

## Additional Scan 2026-04-07

Repo-wide Obsidian scan for typical secret patterns:

- `password`, `passwd`, `passphrase`
- `secret`, `api_key`, `token`, `client_secret`
- `Authorization`, `Bearer`, `Cookie`, JWT-like strings
- `ghp_`, `github_pat_`, `sk-`, `AKIA...`
- `BEGIN ... PRIVATE KEY`, `ssh-ed25519`, `ssh-rsa`

Result:

- no embedded passwords found
- no embedded API keys or tokens found
- no private key blocks found
- no authorization, cookie, or session leaks found

Remaining matches were purely descriptive:

- architecture or security notes that use words like `secret` or `token` in
  normal prose
- Sunshine diagnostics with filenames such as `cacert.pem` or `cakey.pem`, but
  without private contents

## Follow-Up 2026-04-07

In the follow-up cleanup for the next full push, additional new Obsidian notes
were checked for user-specific host paths.

State afterwards:

- no `/home/danny/...` paths remain in `docs/obsidian`
- no real host LAN or Tailscale addresses remain in `docs/obsidian`
- technical Docker and Libvirt topology details remain only where they are
  intentionally kept as infrastructure documentation and contain no personal
  access data
