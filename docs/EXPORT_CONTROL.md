<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Export Control Notice

> **[← Back to README](../README.md)** | [Encryption](ENCRYPTION.md) · [Rule Pack Authoring](RULE_PACK_AUTHORING.md) · [State Authoring](STATE_AUTHORING_GUIDE.md) · **Export Control** · [Disclaimer](DISCLAIMER.md) · [Notice](NOTICE.md)

## Cryptographic Functionality

This software contains cryptographic functionality and may be subject to
export control regulations in various jurisdictions.

### Algorithms Used

| Algorithm            | Purpose                             | Key Size  |
|----------------------|-------------------------------------|-----------|
| AES-256-CBC          | Database encryption at rest         | 256-bit   |
| PBKDF2-HMAC-SHA256   | Key derivation from user password   | N/A       |
| Fernet (AES-128-CBC) | Fallback field-level encryption     | 128-bit   |

### Implementation

- **Primary:** SQLCipher (C library) provides transparent AES-256 encryption of
  the SQLite database at the page level.
- **Fallback:** The Python `cryptography` library provides Fernet-based
  field-level encryption when SQLCipher is unavailable.
- **Key derivation:** PBKDF2-HMAC-SHA256 with a minimum of 100,000 iterations
  and a 16-byte random salt per database.

## U.S. Export Administration Regulations (EAR)

### Classification

This software would ordinarily be classified under **ECCN 5D002** ("Information
Security — Software") because it implements encryption using key lengths greater
than 56 bits.

### Applicable Exception

This software qualifies for the **Technology and Software Unrestricted (TSU)**
exception under **EAR §740.13(e)**, which provides that publicly available
encryption source code is not subject to the EAR, provided that:

1. The source code is publicly available (it is — this repository is hosted on
   GitHub and freely accessible).
2. A notification is sent to BIS and the ENC Encryption Request Coordinator at
   the time of, or prior to, making the source code publicly available.

### BIS Notification

Per 15 CFR §742.15(b), a notification should be sent to:

- **Bureau of Industry and Security (BIS)**
  - Email: crypt@bis.doc.gov
  - Email: enc@nsa.gov

The notification should include:

- The publicly accessible URL of the source code repository
- A brief description of the cryptographic functionality

**Project maintainers are responsible for sending this notification if they have
not already done so.** The template below may be used.

### Notification Template

```
Subject: TSU Notification — Tax_Co-Pilot Open Source Software

To: crypt@bis.doc.gov, enc@nsa.gov

This is a notification pursuant to 15 CFR §742.15(b) and EAR §740.13(e)
regarding publicly available encryption source code.

Software Name: Tax_Co-Pilot
URL: https://github.com/tax-co-pilot/Tax_Co-Pilot
License: GNU Affero General Public License v3.0 (AGPL-3.0)

Cryptographic Functionality:
- AES-256-CBC database encryption via SQLCipher
- AES-128-CBC field-level encryption via Python Fernet
- PBKDF2-HMAC-SHA256 key derivation (100,000+ iterations)

Purpose: Local-first personal tax data storage with optional
encryption at rest for privacy protection.

This source code is publicly available at the URL above at no charge.
```

## Disclaimer

This notice is provided for informational purposes only and does not constitute
legal advice. Project maintainers and contributors should consult qualified
legal counsel for specific export compliance guidance applicable to their
circumstances.
