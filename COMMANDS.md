# TRION Reset Commands

This file lists the available commands for:
- `scripts/ops/trion_reset.sh` (factory-style reset)
- `scripts/ops/trion_live_reset.sh` (live-operation reset for tests)
- `scripts/ops/trion_restore.sh` (restore/clean-install)
- `scripts/ops/trion_live_restore.sh` (live-operation restore/clean-install)
- `scripts/ops/trion_permissions_doctor.sh` (permissions diagnostics/fix)

## 1) `scripts/ops/trion_reset.sh`

### Help
```bash
bash scripts/ops/trion_reset.sh --help
```

### Options
- `--soft` default reset (keeps blueprints)
- `--hard` include blueprint + `/trion-home` wipe
- `--reseed-blueprints` reseed defaults after `--hard`
- `--github-ready` remove cache/temp artifacts (`__pycache__`, `.pytest_cache`, `*.pyc`, `*.bak`, `*.backup-*`)
- `--dry-run` preview only
- `-h`, `--help` show usage

### Common Commands
```bash
# Soft reset
bash scripts/ops/trion_reset.sh

# Hard reset
bash scripts/ops/trion_reset.sh --hard

# Hard reset + reseed default blueprints
bash scripts/ops/trion_reset.sh --hard --reseed-blueprints

# Soft reset + github-ready cleanup
bash scripts/ops/trion_reset.sh --github-ready

# Full reset preview
bash scripts/ops/trion_reset.sh --dry-run --hard --reseed-blueprints --github-ready
```

## 2) `scripts/ops/trion_live_reset.sh`

### Help
```bash
bash scripts/ops/trion_live_reset.sh --help
```

### Options
- `--soft` default live reset
- `--hard` include blueprint + `/trion-home` wipe
- `--reseed-blueprints` reseed defaults after `--hard`
- `--github-ready` remove cache/temp artifacts
- `--dry-run` preview only
- `--keep-digest-worker` do not pause `digest-worker`
- `--keep-protocol` keep protocol files under `memory/*.md`
- `-h`, `--help` show usage

### Common Commands
```bash
# Live reset (default)
bash scripts/ops/trion_live_reset.sh

# Live reset preview
bash scripts/ops/trion_live_reset.sh --dry-run

# Live hard reset + reseed
bash scripts/ops/trion_live_reset.sh --hard --reseed-blueprints

# Live soft reset + github-ready cleanup
bash scripts/ops/trion_live_reset.sh --soft --github-ready

# Live soft reset but keep protocol files
bash scripts/ops/trion_live_reset.sh --soft --keep-protocol
```

## 3) `scripts/ops/trion_restore.sh`

### Help
```bash
bash scripts/ops/trion_restore.sh --help
```

### Options
- `--soft` restore defaults, keep user data where possible (default)
- `--hard` wipe runtime/user data first, then restore defaults
- `--reseed-blueprints` seed default blueprints (auto-enabled with `--hard`)
- `--reseed-skills` verify/seed core skills from `seed/restore_manifest.json`
- `--pull-images` pull blueprint images after reseed
- `--keep-protocol` keep `memory/*.md` + protocol status files (hard mode)
- `--keep-csv` keep `memory_speicher/*.csv` + digest state/lock files (hard mode)
- `--skip-graph` skip blueprint graph sync
- `--smoke-test` run post-restore API smoke checks
- `--skip-home-start` do not auto-start TRION home container after restore
- `--plan` print phase plan and exit
- `--dry-run` preview only
- `--yes` skip prompt
- `--non-interactive` non-prompt mode (requires `--yes`)
- `-h`, `--help` show usage

### Common Commands
```bash
# Print restore plan
bash scripts/ops/trion_restore.sh --plan

# Soft restore (safe default)
bash scripts/ops/trion_restore.sh --soft --reseed-blueprints --reseed-skills

# Hard clean install + smoke test
bash scripts/ops/trion_restore.sh --hard --reseed-skills --smoke-test

# Hard restore, keep protocol/csv, non-interactive
bash scripts/ops/trion_restore.sh --hard --keep-protocol --keep-csv --yes --non-interactive

# Full preview
bash scripts/ops/trion_restore.sh --dry-run --hard --reseed-skills --pull-images --smoke-test

# Restore but leave TRION home container stopped
bash scripts/ops/trion_restore.sh --hard --reseed-skills --skip-home-start
```

## 4) `scripts/ops/trion_live_restore.sh`

### Help
```bash
bash scripts/ops/trion_live_restore.sh --help
```

### Options
- `--soft` restore defaults while stack stays online (default)
- `--hard` wipe runtime/user data first, then restore defaults
- `--reseed-blueprints` seed default blueprints (auto-enabled with `--hard`)
- `--reseed-skills` verify/seed core skills from `seed/restore_manifest.json`
- `--pull-images` pull blueprint images after reseed
- `--keep-protocol` keep `memory/*.md` + protocol status files (hard mode)
- `--keep-csv` keep `memory_speicher/*.csv` + digest state/lock files (hard mode)
- `--skip-graph` skip blueprint graph sync
- `--smoke-test` run post-restore API smoke checks
- `--keep-digest-worker` do not pause `digest-worker` during restore
- `--pause-admin` briefly stop `jarvis-admin-api` during restore
- `--skip-home-start` do not auto-start TRION home container after restore
- `--plan` print phase plan and exit
- `--dry-run` preview only
- `--yes` skip prompt
- `--non-interactive` non-prompt mode (requires `--yes`)
- `-h`, `--help` show usage

### Common Commands
```bash
# Print live restore plan
bash scripts/ops/trion_live_restore.sh --plan

# Safe live restore (keep stack online)
bash scripts/ops/trion_live_restore.sh --soft --reseed-blueprints --reseed-skills

# Live hard restore with stricter consistency
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test

# Full live preview
bash scripts/ops/trion_live_restore.sh --dry-run --hard --reseed-skills --pull-images --smoke-test

# Live restore but keep home container stopped
bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --skip-home-start
```

### Optional ENV Overrides (Live Restore)
```bash
# If admin API is not on localhost:8200
TRION_ADMIN_API_BASE=http://localhost:8200 bash scripts/ops/trion_live_restore.sh --soft --smoke-test

# Increase smoke wait/retry for slower startup
TRION_SMOKE_MAX_WAIT_S=60 TRION_SMOKE_RETRIES=5 TRION_SMOKE_RETRY_DELAY_S=3 \
  bash scripts/ops/trion_live_restore.sh --hard --reseed-skills --pause-admin --smoke-test
```

## 5) `scripts/ops/trion_permissions_doctor.sh`

### Help
```bash
bash scripts/ops/trion_permissions_doctor.sh --help
```

### Options
- `--check` diagnostics only (default)
- `--fix-safe` apply safe local fixes in repo paths
- `--fix-docker` include Docker access diagnostics + fix hints
- `--dry-run` print fix actions only
- `--yes` skip confirmation in fix modes
- `-h`, `--help` show usage

### Common Commands
```bash
# Check permissions only
bash scripts/ops/trion_permissions_doctor.sh --check

# Safe local fixes for repo paths
bash scripts/ops/trion_permissions_doctor.sh --fix-safe

# Safe fixes + Docker diagnostics
bash scripts/ops/trion_permissions_doctor.sh --fix-safe --fix-docker

# Preview fixes without writing
bash scripts/ops/trion_permissions_doctor.sh --fix-safe --fix-docker --dry-run
```
