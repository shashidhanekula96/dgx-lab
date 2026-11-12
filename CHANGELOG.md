# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-11-12

### Added

- Multi-OS host profile detection (`dgxlab check-host`) with CPU / memory / GPU / Docker capability recording.
- Secure endpoint validation for loopback HTTP and remote HTTPS + bearer token.
- Run provenance: each run stores `operator` and `host` profile (no secrets).
- Mandatory author credits (`dgxlab credits`) and SPDX headers.
- MIT license, security policy, contributing guide, and GitHub Actions CI.

### Changed

- DGX Spark / ARM64 constraints moved into the optional Spark runtime candidate.
- Compose publish host is configurable; defaults remain loopback-only.
