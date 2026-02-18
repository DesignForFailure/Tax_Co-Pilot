<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# NOTICE — Third-Party Software Attribution

**Tax_Co-Pilot**
Copyright (C) 2026 Tax Co-Pilot Contributors

This product is licensed under the GNU Affero General Public License v3.0 or
later (AGPL-3.0-or-later). See the [LICENSE](../LICENSE) file for the full
license text.

This product includes and/or depends on third-party software components listed
below, each governed by its own license. Their inclusion does not imply any
endorsement by the respective authors or organizations.

---

## Table of Contents

1. [Encryption Engine — SQLCipher](#1-encryption-engine--sqlcipher)
2. [Encryption Engine — OpenSSL](#2-encryption-engine--openssl)
3. [Web Framework — FastAPI & Starlette](#3-web-framework--fastapi--starlette)
4. [ASGI Server — Uvicorn](#4-asgi-server--uvicorn)
5. [Data Validation — Pydantic](#5-data-validation--pydantic)
6. [Template Engine — Jinja2 & MarkupSafe](#6-template-engine--jinja2--markupsafe)
7. [YAML Parser — PyYAML](#7-yaml-parser--pyyaml)
8. [Multipart Form Parsing — python-multipart](#8-multipart-form-parsing--python-multipart)
9. [SQLCipher Python Binding — pysqlcipher3](#9-sqlcipher-python-binding--pysqlcipher3)
10. [Cryptography Library](#10-cryptography-library)
11. [Credential Storage — keyring](#11-credential-storage--keyring)
12. [Frontend — htmx](#12-frontend--htmx)
13. [Transitive Dependencies](#13-transitive-dependencies)

---

## 1. Encryption Engine — SQLCipher

SQLCipher is the primary encryption engine for Tax_Co-Pilot's database
encryption at rest (AES-256).

```
Copyright (c) 2008-2024, ZETETIC LLC
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from this
   software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY ZETETIC LLC ''AS IS'' AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN
NO EVENT SHALL ZETETIC LLC BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

- **License:** BSD-3-Clause
- **Website:** https://www.zetetic.net/sqlcipher/
- **Source:** https://github.com/sqlcipher/sqlcipher

SQLCipher is built on top of SQLite, which is in the **public domain**.

---

## 2. Encryption Engine — OpenSSL

OpenSSL is used transitively via the `cryptography` Python package.

```
Copyright 1995-2024 The OpenSSL Project Authors. All Rights Reserved.

Licensed under the Apache License 2.0 (the "License"). You may not use
this file except in compliance with the License. You can obtain a copy
in the file LICENSE in the source distribution or at
https://www.openssl.org/source/license.html
```

- **License:** Apache-2.0 (OpenSSL 3.x)
- **Website:** https://www.openssl.org/
- **Source:** https://github.com/openssl/openssl

---

## 3. Web Framework — FastAPI & Starlette

```
The MIT License (MIT)

Copyright (c) 2018 Sebastian Ramirez

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

- **License:** MIT
- **Website:** https://fastapi.tiangolo.com/
- **Source:** https://github.com/fastapi/fastapi

Starlette (the ASGI toolkit underlying FastAPI):

```
Copyright (c) 2018, Encode OSS Ltd. All rights reserved.
```

- **License:** BSD-3-Clause
- **Source:** https://github.com/encode/starlette

---

## 4. ASGI Server — Uvicorn

```
Copyright (c) 2017-present, Encode OSS Ltd. All rights reserved.
```

- **License:** BSD-3-Clause
- **Source:** https://github.com/encode/uvicorn

---

## 5. Data Validation — Pydantic

```
The MIT License (MIT)

Copyright (c) 2017 to present Pydantic Services Inc. and individual
contributors.
```

- **License:** MIT
- **Source:** https://github.com/pydantic/pydantic

---

## 6. Template Engine — Jinja2 & MarkupSafe

```
Copyright 2007 Pallets
```

- **License:** BSD-3-Clause
- **Source (Jinja2):** https://github.com/pallets/jinja
- **Source (MarkupSafe):** https://github.com/pallets/markupsafe

MarkupSafe:

```
Copyright 2010 Pallets
```

- **License:** BSD-3-Clause

---

## 7. YAML Parser — PyYAML

```
Copyright (c) 2017-2021 Ingy dot Net
Copyright (c) 2006-2016 Kirill Simonov
```

- **License:** MIT
- **Source:** https://github.com/yaml/pyyaml

---

## 8. Multipart Form Parsing — python-multipart

```
Copyright 2012, Andrew Dunham
```

- **License:** Apache-2.0
- **Source:** https://github.com/Kludex/python-multipart

---

## 9. SQLCipher Python Binding — pysqlcipher3

```
Copyright (c) 2015 David Riggleman
Copyright (c) 2013-2014 Kali Kaneko
Copyright (c) 2004-2007 Gerhard Haring
```

- **License:** zlib/libpng
- **Source:** https://github.com/rigglemania/pysqlcipher3

---

## 10. Cryptography Library

```
Copyright (c) Individual contributors.
All rights reserved.
```

- **License:** Apache-2.0 OR BSD-3-Clause (dual-licensed; this project uses it
  under the BSD-3-Clause terms)
- **Source:** https://github.com/pyca/cryptography

---

## 11. Credential Storage — keyring

```
Copyright Jason R. Coombs
```

- **License:** MIT
- **Source:** https://github.com/jaraco/keyring

---

## 12. Frontend — htmx

```
Copyright Big Sky Software
```

- **License:** 0BSD (Zero-Clause BSD)
- **Website:** https://htmx.org/
- **Source:** https://github.com/bigskysoftware/htmx

The 0BSD license imposes no attribution or redistribution requirements.

---

## 13. Transitive Dependencies

The following packages are pulled in as transitive dependencies of the above
libraries:

| Package   | License       | Copyright                                    |
|-----------|---------------|----------------------------------------------|
| anyio     | MIT           | Copyright (c) 2018 Alex Gronholm             |
| click     | BSD-3-Clause  | Copyright 2014 Pallets                       |
| h11       | MIT           | Copyright (c) 2016 Nathaniel J. Smith et al. |

---

## License Compatibility Summary

All third-party licenses used in this project are **permissive** and compatible
with the project's AGPL-3.0-or-later license:

| License (SPDX)             | AGPL-3.0 Compatible | Packages                                                     |
|----------------------------|----------------------|--------------------------------------------------------------|
| MIT                        | Yes                  | FastAPI, Pydantic, PyYAML, keyring, anyio, h11               |
| BSD-3-Clause               | Yes                  | Uvicorn, Starlette, Jinja2, MarkupSafe, Click, SQLCipher     |
| Apache-2.0                 | Yes                  | python-multipart, OpenSSL 3.x                                |
| Apache-2.0 OR BSD-3-Clause | Yes                  | cryptography                                                 |
| zlib/libpng                | Yes                  | pysqlcipher3                                                 |
| 0BSD                       | Yes                  | htmx                                                         |
| Public Domain              | Yes                  | SQLite                                                       |

**No license incompatibilities were found.**

---

## Keeping This File Current

This NOTICE file should be updated whenever:

- A new production dependency is added to `pyproject.toml`
- A system-level library is added to the CI workflow
- A CDN-hosted or vendored front-end library is added to the templates
- Any dependency changes its license terms in a version upgrade
