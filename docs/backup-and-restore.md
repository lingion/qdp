# Backup and Restore Strategy

## Purpose
Before implementation work proceeds, every file that will be modified in a sprint must have a restorable copy captured inside the repository.

## Backup Convention
Store backups under:

`backups/<sprint-id>/pre-implementation-<timestamp>/`

## Sprint 1 Backups
Sprint 1 currently has two timestamped backup directories:

- `backups/sprint-1/pre-implementation-20260406-152622/` — baseline backup created before the initial Sprint 1 repository metadata and build-doc updates
- `backups/sprint-1/pre-implementation-20260406-153659/` — follow-up backup created before correcting this backup documentation

## Sprint 2 Backups
Sprint 2 currently has one timestamped backup directory:

- `backups/sprint-2/pre-implementation-20260406-160239/` — backup created before fixing plain-`pytest` collection and updating this backup record

## Files Backed Up for Sprint 1
### Baseline backup contents (`20260406-152622`)
- `README.md`
- `requirements-build.txt`
- `qdp.spec`
- `build_windows.bat`
- `build_windows.ps1`
- `build_windows.sh`

### Documentation-fix backup contents (`20260406-153659`)
- `docs/backup-and-restore.md`

## Files Backed Up for Sprint 2
### Pytest-collection fix backup contents (`20260406-160239`)
- `tests/test_stress_regression.py`
- `docs/backup-and-restore.md`
- `README.md`

## Required Workflow
1. Create the sprint backup directory before editing target files.
2. Copy each target file into that directory.
3. Only then begin implementation or documentation changes.
4. If more files are modified later, back them up before editing and note that expansion in sprint notes.

## Restore Examples
Restore the baseline Sprint 1 `README.md`:

```bash
cp backups/sprint-1/pre-implementation-20260406-152622/README.md README.md
```

Restore the baseline Sprint 1 `build_windows.sh` helper:

```bash
cp backups/sprint-1/pre-implementation-20260406-152622/build_windows.sh build_windows.sh
```

Restore this documentation file from the documentation-fix backup:

```bash
cp backups/sprint-1/pre-implementation-20260406-153659/docs/backup-and-restore.md docs/backup-and-restore.md
```

Restore the Sprint 2 plain-`pytest` regression target:

```bash
cp backups/sprint-2/pre-implementation-20260406-160239/test_stress_regression.py tests/test_stress_regression.py
```

Restore the Sprint 2 backup record before the latest update:

```bash
cp backups/sprint-2/pre-implementation-20260406-160239/backup-and-restore.md docs/backup-and-restore.md
```

## Notes
- The backup directories are intentionally visible in-repo so evaluators can confirm they exist.
- When docs mention a backup path, it must match an actual committed directory.
- Future sprints should create a new timestamped folder rather than overwriting Sprint 1 backups.
- Do not commit user secret files into backup folders.
