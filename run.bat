@echo off
REM SPDX-License-Identifier: AGPL-3.0-or-later
REM Tax_Co-Pilot - Local-first personal tax software system
REM Copyright (C) 2026  Tax_Co-Pilot Contributors
REM
REM This program is free software: you can redistribute it and/or modify
REM it under the terms of the GNU Affero General Public License as published
REM by the Free Software Foundation, either version 3 of the License, or
REM (at your option) any later version.
REM
REM This program is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
REM GNU Affero General Public License for more details.
REM
REM You should have received a copy of the GNU Affero General Public License
REM along with this program.  If not, see <https://www.gnu.org/licenses/>.

REM Tax Copilot - Run the application (Windows launcher, mirrors run.sh)
setlocal

cd /d "%~dp0"

echo Tax Copilot - Starting...
echo    URL: http://127.0.0.1:8000
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

endlocal
