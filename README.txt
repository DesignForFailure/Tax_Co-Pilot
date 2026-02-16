Tax_Co-Pilot: Install, Setup, and Run Guide
==========================================

Prerequisites
-------------
- Python 3.11+ (3.12 is also supported)
- pip
- macOS, Linux, or WSL

1) Install Dependencies
-----------------------
From the repository root:

    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

(Optional for development tools/tests):

    python -m pip install -r requirements-dev.txt

2) Setup
--------
No additional environment variables are required for the MVP.

The app uses:
- SQLite for local persistence (database file is created on first run)
- Optional AES-256 encryption at rest via SQLCipher (see docs/ENCRYPTION.md)
- YAML rule packs under:
  - rule_packs/federal/2024/
  - rule_packs/state/GA/2024/

3) Run the Web App (Canonical)
------------------------------
Start the local server with the provided launcher script:

    ./run.sh

`run.sh` starts Uvicorn with ASGI import target:

    main:app

Expected local URL:

    http://127.0.0.1:8000

(Direct alternative command, same ASGI target):

    python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

4) Run Tests
------------
Execute the test suite with:

    pytest -q

Notes
-----
- This project is licensed under the GNU AGPL v3. See the LICENSE file.
- This project is local-first and intended to run on your own machine.
- It is an engineering system for tax modeling and reproducible calculations,
  not legal or tax advice.
