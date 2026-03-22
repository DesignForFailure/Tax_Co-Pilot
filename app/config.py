# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Configuration management for Tax Copilot.

Handles encryption settings, password sources, and feature flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class EncryptionConfig:
    """Configuration for database encryption.

    Attributes:
        enabled: Whether encryption is enabled (default: False for MVP, True for production)
        provider: Which encryption provider to use ('auto' resolves to SQLCipher)
        password_source: Where to get the password from ('env' | 'keyring' | 'prompt')
        key_derivation_iterations: PBKDF2 iterations for key derivation (100k minimum)
        allow_unencrypted: Safety flag - if False, refuse to create unencrypted DBs
    """

    enabled: bool = False  # Start disabled, enable after full implementation
    provider: Literal["sqlcipher", "auto"] = "auto"
    password_source: Literal["env", "keyring", "prompt", "auto"] = "auto"
    key_derivation_iterations: int = 100_000
    allow_unencrypted: bool = True  # Allow unencrypted during migration period

    @classmethod
    def from_environment(cls) -> EncryptionConfig:
        """Load configuration from environment variables.

        Environment variables:
            TAX_COPILOT_ENCRYPTION_ENABLED: "true" or "false" (default: false)
            TAX_COPILOT_ENCRYPTION_PROVIDER: "sqlcipher" or "auto" (default: auto)
            TAX_COPILOT_PASSWORD_SOURCE: "env", "keyring", "prompt", or "auto" (default: auto)
            TAX_COPILOT_KEY_ITERATIONS: integer (default: 100000)
        """
        enabled = os.getenv("TAX_COPILOT_ENCRYPTION_ENABLED", "false").lower() == "true"
        provider = os.getenv("TAX_COPILOT_ENCRYPTION_PROVIDER", "auto")
        password_source = os.getenv("TAX_COPILOT_PASSWORD_SOURCE", "auto")
        iterations = int(os.getenv("TAX_COPILOT_KEY_ITERATIONS", "100000"))

        # Validate provider
        if provider not in ("sqlcipher", "auto"):
            provider = "auto"

        # Validate password_source
        if password_source not in ("env", "keyring", "prompt", "auto"):
            password_source = "auto"

        # Enforce minimum iterations
        if iterations < 100_000:
            iterations = 100_000

        return cls(
            enabled=enabled,
            provider=provider,  # type: ignore
            password_source=password_source,  # type: ignore
            key_derivation_iterations=iterations,
        )


# Global configuration instance
config = EncryptionConfig.from_environment()
