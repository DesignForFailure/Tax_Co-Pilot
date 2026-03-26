<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Database Encryption Guide

> **[← Back to README](../README.md)** | **Encryption** · [Rule Pack Authoring](RULE_PACK_AUTHORING.md) · [State Authoring](STATE_AUTHORING_GUIDE.md) · [Export Control](EXPORT_CONTROL.md) · [Disclaimer](DISCLAIMER.md) · [Notice](NOTICE.md)

Tax Co-Pilot supports optional encryption-at-rest for the SQLite database to protect your sensitive tax data.

## Overview

- **Encryption Algorithm**: AES-256 (via SQLCipher)
- **Key Derivation**: PBKDF2-HMAC-SHA256 with 100,000+ iterations
- **Password Management**: Environment variable, OS keyring, or web UI prompt
- **Migration**: Seamless migration from unencrypted to encrypted databases

## Why Encryption?

Your tax database contains highly sensitive information:
- Social Security Numbers (SSNs)
- Income data (W-2s, 1099s)
- Employer information
- Tax calculations and financial details

Encryption at rest protects this data if:
- Your device is stolen or compromised
- Malware attempts to read database files
- You need to back up to cloud storage
- Multiple users have access to your filesystem

## Quick Start

### 1. Enable Encryption

Set the environment variable:

```bash
export TAX_COPILOT_ENCRYPTION_ENABLED=true
```

Or add to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
echo 'export TAX_COPILOT_ENCRYPTION_ENABLED=true' >> ~/.bashrc
source ~/.bashrc
```

### 2. Set Your Password

**Option A: Environment Variable (Development)**

```bash
export TAX_COPILOT_DB_PASSWORD="your-secure-password-here"
```

**Option B: OS Keyring (Recommended for Production)**

The password will be automatically stored in your system keyring after first unlock:
- **Linux**: GNOME Keyring / Secret Service
- **macOS**: Keychain
- **Windows**: Windows Credential Locker

**Option C: Web UI Prompt**

If no password is found, the app will prompt you on startup.

### 3. Start the Application

```bash
./run.sh
```

## First-Time Setup

### New Installation

1. Start the app with encryption enabled
2. You'll be prompted to set a database password
3. Password is stored in your system keyring
4. Database is created with encryption enabled
5. Access the app normally

### Migrating Existing Database

If you already have an unencrypted database:

1. **Backup your data first**:
   ```bash
   cp data/tax_copilot.db data/tax_copilot.db.manual_backup
   ```

2. Enable encryption:
   ```bash
   export TAX_COPILOT_ENCRYPTION_ENABLED=true
   ```

3. Start the app - you'll see a migration prompt

4. Set your encryption password

5. Migration runs automatically:
   - Creates encrypted copy
   - Verifies data integrity (row counts, checksums)
   - Original backed up to `tax_copilot.db.unencrypted.backup`
   - Encrypted database becomes active

6. **After successful migration**:
   - Test that you can access your data
   - Keep the `.unencrypted.backup` file until confirmed working
   - Securely delete backup when ready:
     ```bash
     shred -u data/tax_copilot.db.unencrypted.backup  # Linux
     # or
     rm -P data/tax_copilot.db.unencrypted.backup     # macOS
     ```

## Password Requirements

- **Minimum length**: 12 characters
- **Recommended**: 16+ characters with mix of letters, numbers, symbols
- **No recovery mechanism**: If you lose your password, your data is permanently inaccessible

### Password Best Practices

✅ **DO:**
- Use a strong, unique password
- Store in a password manager
- Use a passphrase (e.g., "correct horse battery staple")
- Keep encrypted backups of your database

❌ **DON'T:**
- Reuse passwords from other services
- Use easily guessable passwords
- Store password in plaintext files
- Share your password

## Configuration

### Environment Variables

```bash
# Enable/disable encryption (default: false)
export TAX_COPILOT_ENCRYPTION_ENABLED=true

# Database password (optional, will prompt if not set)
export TAX_COPILOT_DB_PASSWORD="your-password"

# Encryption provider: "sqlcipher" | "auto" (default: auto)
export TAX_COPILOT_ENCRYPTION_PROVIDER=auto

# Password source: "env" | "keyring" | "prompt" | "auto" (default: auto)
export TAX_COPILOT_PASSWORD_SOURCE=auto

# Key derivation iterations (default: 100000, minimum: 100000)
export TAX_COPILOT_KEY_ITERATIONS=100000
```

### Encryption Providers

**SQLCipher (Primary)**
- Native SQLite encryption at page level
- AES-256 encryption
- Minimal performance overhead (~5-15%)
- Transparent to application
- Requires `pysqlcipher3` library

Python-layer fallback encryption is currently disabled at runtime because
transparent decode/encode hooks are not implemented in persistence reads/writes.

## System Requirements

### Linux

Install SQLCipher development libraries:

```bash
# Debian/Ubuntu
sudo apt-get install libsqlcipher-dev build-essential python3-dev

# Fedora/RHEL
sudo dnf install sqlcipher-devel gcc python3-devel

# Arch Linux
sudo pacman -S sqlcipher base-devel
```

### macOS

```bash
brew install sqlcipher
```

### Windows

Pre-built wheels for `pysqlcipher3` are available for Windows. Runtime encrypted
operation requires SQLCipher support.

## Security Considerations

### What's Protected

✅ Database files on disk are encrypted
✅ JSON blobs containing tax data are unreadable without password
✅ Backups of encrypted databases remain encrypted
✅ Password stored securely in OS keyring

### What's NOT Protected

❌ Data in memory during application runtime
❌ Network traffic (app is localhost-only by design)
❌ Screen contents / UI display
❌ Temporary files (none created by Tax Co-Pilot)

### Threat Model

**Protects Against:**
- Physical device theft
- Filesystem-level access by malware
- Unauthorized file copying
- Unencrypted backups

**Does NOT Protect Against:**
- Keyloggers capturing your password
- Screen recording/screenshots
- Memory dumps while app is running
- Compromised OS with root/admin access

## Backup Strategy

### Encrypted Backups (Recommended)

```bash
# Backup encrypted database (password still required to restore)
cp data/tax_copilot.db ~/Backups/tax_copilot_$(date +%Y%m%d).db
```

Encrypted backups can be safely stored on:
- Cloud storage (Dropbox, Google Drive, etc.)
- External hard drives
- Network attached storage (NAS)
- USB flash drives

### Unencrypted Backups (Use with Caution)

If you need an unencrypted backup:

1. Temporarily disable encryption:
   ```bash
   export TAX_COPILOT_ENCRYPTION_ENABLED=false
   ```

2. Export your data (future feature)

3. Store in a secure, encrypted location (e.g., encrypted USB drive)

## Troubleshooting

### "Incorrect password or corrupted database"

**Possible causes:**
- Wrong password entered
- Database file corrupted
- Keyring returned wrong password

**Solutions:**
1. Try entering password manually (ignore keyring)
2. Check for `.unencrypted.backup` file from migration
3. Restore from backup if available

### "Database is encrypted but no password provided"

**Cause**: Encryption is enabled but password not found in env/keyring

**Solution**: The app will redirect to unlock page. Enter your password.

### "pysqlcipher3 is required for SQLCipher encryption"

**Cause**: SQLCipher library not installed

**Solutions:**
1. Install dependencies: `pip install -e .`
2. Install system libraries (see System Requirements above)
3. Configure SQLCipher support; runtime encrypted operation requires SQLCipher

### Performance Issues

**Symptoms**: Slow database operations

**Solutions:**
1. Check that SQLCipher is installed and in use
2. Increase `TAX_COPILOT_KEY_ITERATIONS` affects initial unlock time only
3. Consider hardware: SSD vs HDD makes significant difference

## Password Recovery

**There is no password recovery mechanism by design.**

This is a privacy-first application. No master keys, no backdoors, no recovery questions.

**If you lose your password:**
- Your encrypted data is permanently inaccessible
- You must start fresh with a new database
- Restore from an unencrypted backup (if available)

**Prevention:**
- Store password in a password manager
- Keep the original `.unencrypted.backup` file until fully confident
- Test password recovery from keyring before deleting backups
- Consider keeping an unencrypted backup in a secure physical location

## Advanced Topics

### Manual Migration

If automatic migration fails:

```python
from pathlib import Path
from app.services.encryption import migrate_to_encrypted

db_path = Path("data/tax_copilot.db")
password = "your-secure-password"

migrate_to_encrypted(
    db_path=db_path,
    password=password,
    provider_type="sqlcipher",
    kdf_iterations=100_000,
    backup_suffix=".unencrypted.backup"
)
```

### Changing Password

To change your encryption password:

1. Export your data (future feature)
2. Disable encryption
3. Delete encrypted database
4. Re-enable encryption with new password
5. Re-import data

(A dedicated password change feature is planned for a future release)

### Inspecting Encryption State

```python
from pathlib import Path
from app.services.encryption import detect_encryption_state, DatabaseState

db_path = Path("data/tax_copilot.db")
state = detect_encryption_state(db_path)

print(f"Database state: {state}")
# Possible values:
# - DatabaseState.NONE (doesn't exist)
# - DatabaseState.UNENCRYPTED
# - DatabaseState.ENCRYPTED_SQLCIPHER
# - DatabaseState.ENCRYPTED_PYTHON (legacy; runtime unsupported)
```

## FAQ

**Q: Will encryption slow down my tax calculations?**
A: No. Encryption only affects database read/write operations. Tax calculation engine performance is unaffected. Overhead is 5-15% for SQLCipher, barely noticeable in practice.

**Q: Can I disable encryption after enabling it?**
A: Yes, but you'll need to manually migrate back to unencrypted format. Future releases will include a migration tool.

**Q: Is my password stored anywhere?**
A: Your password is stored in your OS keyring (encrypted by your OS). It's never written to config files, logs, or plaintext files.

**Q: Can I use a different password per database?**
A: Currently, one password per installation. Multi-database support is planned for future releases.

**Q: What happens if I forget to set a password?**
A: The app will prompt you to enter one when you try to access an encrypted database.

**Q: Is this compliant with [regulation]?**
A: Tax Co-Pilot implements industry-standard encryption (AES-256, PBKDF2). Compliance depends on your specific regulatory requirements. Consult with your compliance team.

## Support

For issues or questions:
- GitHub Issues: https://github.com/tax-co-pilot/Tax_Co-Pilot/issues
- Security concerns: See SECURITY.md in the project root

## Technical Details

- **Encryption Algorithm**: AES-256-CBC (SQLCipher) or Fernet/AES-128-CBC (Python)
- **Key Derivation**: PBKDF2-HMAC-SHA256
- **Default Iterations**: 100,000 (configurable)
- **Salt**: 16 bytes random (per database)
- **SQLCipher Version**: 4.x
- **Python Cryptography**: `cryptography` library (Fernet)
- **Keyring Support**: `keyring` library (SecretService, Keychain, WinCred)
