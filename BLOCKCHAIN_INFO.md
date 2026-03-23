# FusionCore_Stack Integrity Notes

This package uses a simple release integrity workflow:

- canonical source files are hashed with SHA-256
- the resulting manifest is stored in `SIGNATURE.sha256`
- the release narrative is recorded in `PHAM_BLOCKCHAIN_LOG.md`

The hash manifest is intended as a lightweight integrity check for release review.
It is not a distributed blockchain or consensus system.
