# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability, please **do not** open a public issue.

Instead, report privately by emailing: **security@tax-copilot.local**

Please include:

- A clear description of the issue and affected component(s)
- Steps to reproduce or proof-of-concept details
- Potential impact
- Suggested remediation (if known)

## Disclosure expectations

- We will acknowledge receipt as soon as possible (target: within 3 business days).
- We will investigate and provide status updates as work progresses.
- Please allow us reasonable time to validate and remediate before public disclosure.
- After a fix is available, coordinated disclosure is welcome and appreciated.

## Scope notes

This repository is a local-first tax modeling application. Potentially sensitive areas include:

- Input/import handling
- Data storage and export paths
- Database encryption and key management (SQLCipher / Fernet; see `docs/ENCRYPTION.md`)
- Password handling and key derivation (PBKDF2-HMAC-SHA256)
- Rule loading/parsing and execution pathways
- Session management and CSRF protection
