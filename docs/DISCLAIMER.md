<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Disclaimer — No Warranty & User Responsibility

## Not Tax Advice

Tax_Co-Pilot is an engineering tool for tax **modeling** and **calculation**. It
is **not** tax advice software and does not provide legal, financial, or tax
advice of any kind. The calculations, outputs, scenarios, and suggestions
produced by this software are for informational and educational purposes only.

**You should consult a qualified tax professional before making any tax-related
decisions based on the output of this software.**

## No Warranty

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.

IN NO EVENT SHALL THE AUTHORS, COPYRIGHT HOLDERS, OR CONTRIBUTORS BE LIABLE
FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

See the [AGPL-3.0 license](../LICENSE), sections 15 (Disclaimer of Warranty)
and 16 (Limitation of Liability), for the complete legal terms.

## Data Loss & Corruption

Tax_Co-Pilot is a **local-first** application. All tax data is stored
exclusively on your device in a local SQLite database. No data is transmitted
to or stored on any remote server.

**The developers and contributors of Tax_Co-Pilot are not responsible for:**

- Loss of tax data due to hardware failure, software defects, operating system
  issues, or any other cause
- Corruption of the database file from incomplete writes, power loss, disk
  errors, or software bugs
- Inability to access encrypted data due to a lost or forgotten encryption
  password
- Data loss resulting from failed migration between encrypted and unencrypted
  database formats
- Any consequences arising from incorrect tax calculations, whether due to
  software defects, incorrect rule packs, or user input errors

## Your Responsibilities

As a user of this local-first application, **you are solely responsible for:**

1. **Backups:** Maintaining regular backups of your database file
   (`data/tax_copilot.db`) and verifying that backups can be restored
   successfully.

2. **Password Security:** Safeguarding your database encryption password. There
   is no password recovery mechanism by design. If you lose your password, your
   encrypted data is permanently inaccessible.

3. **Data Accuracy:** Verifying that all input data (income, withholding,
   deductions, etc.) is accurate before relying on calculated outputs.

4. **Calculation Verification:** Cross-checking calculated results against
   official IRS publications, professional tax software, or a qualified tax
   preparer before using them for actual tax filing.

5. **Device Security:** Securing the device on which Tax_Co-Pilot runs,
   including operating system updates, malware protection, and physical access
   controls.

6. **Regulatory Compliance:** Ensuring that your use of this software,
   including its encryption features, complies with all applicable laws and
   regulations in your jurisdiction.

## Rule Pack Accuracy

Tax rules in this project are encoded as versioned YAML rule packs. While every
effort is made to ensure accuracy:

- Rule packs may contain errors or omissions
- Tax rules change annually; rule packs for a given tax year reflect the
  developers' best understanding at the time of publication
- Rule packs do not cover every possible tax situation, deduction, credit, or
  edge case
- The presence of a rule pack for a given tax year or jurisdiction does not
  constitute a guarantee of completeness or correctness

## Alpha Software Warning

Tax_Co-Pilot is currently in **alpha** status. This means:

- The software is under active development
- Breaking changes may occur between releases
- Data format changes may require migration
- Not all tax scenarios are supported
- **This software should not be used as the sole basis for filing tax returns**
