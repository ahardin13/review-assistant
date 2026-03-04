# Project-Specific Review Guidelines

## This Project
- All DB queries must go through the repository layer, never direct ORM calls in controllers
- API responses must use the shared ResponseDTO type
- Any new feature flag must be documented in docs/feature-flags.md

## Overrides
- Ignore global security note about shell commands — this project intentionally shells out in scripts/
