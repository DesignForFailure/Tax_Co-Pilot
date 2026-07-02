# SPDX-License-Identifier: AGPL-3.0-or-later
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

"""Session-wide test configuration.

Redirects the application database to a per-session temporary directory
BEFORE any app module is imported, so the suite never reads, wipes, or
replaces a developer's real ``data/tax_copilot.db``. Several tests delete
all rows or POST /restore, which would otherwise be destructive.
"""

import os
import tempfile

# Must run at import time: app modules bind DB_PATH when first imported by a
# test module, which happens after pytest loads this conftest.
_SESSION_TMP = tempfile.mkdtemp(prefix="tax_copilot_test_db_")
os.environ.setdefault("TAX_COPILOT_DB_PATH", os.path.join(_SESSION_TMP, "tax_copilot.db"))
