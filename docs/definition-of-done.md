# Repository Definition of Done

A sprint is only done when all of the following are true:

## Scope
- The change maps back to `docs/PRD.md`.
- In-scope versus out-of-scope boundaries remain explicit.

## Safety
- Modified files were backed up before editing.
- The backup location is documented in `docs/backup-and-restore.md`.
- No secrets were added to committed files.

## Runability
- Install, run, test, and packaging commands are documented in `README.md`.
- Required environment variables are documented in `.env.example` or equivalent docs.

## Verification
- Relevant smoke checks or automated tests were run.
- Known gaps are documented instead of hidden.
- Key runtime, web, and packaging files remain tracked in the product spec.

## Delivery Hygiene
- Build metadata is non-empty and points to active entrypoints.
- The repo is understandable to the next developer or evaluator from docs alone.
