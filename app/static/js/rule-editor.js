/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Rule editor behavior: type-section switching, dynamic formula-input
   rows, dynamic bracket-table rows, bracket copy-from-single, and the
   matrix_lookup grid. Server-rendered counts arrive via data-* attributes
   so no inline script is needed. */
(function () {
    var typeSelect = document.getElementById('rule_type');
    // Filing statuses used in generated field names. Values read from the
    // DOM are looked up here first so only these constant strings are ever
    // concatenated into markup.
    var STATUSES = ['single', 'mfj', 'mfs', 'hoh', 'qss'];

    function switchType(type) {
        document.querySelectorAll('.type-section').forEach(function (section) {
            section.hidden = true;
        });
        var sec = document.getElementById('section-' + type);
        if (sec) {
            sec.hidden = false;
        }
    }

    if (typeSelect) {
        typeSelect.addEventListener('change', function () {
            switchType(this.value);
        });
    }

    function addFormulaInput() {
        var container = document.getElementById('formula-inputs');
        if (!container) return;
        var idx = parseInt(container.getAttribute('data-next-index') || '0', 10);
        var html = '<div class="form-grid-4 formula-input-row">'
            + '<div><label>Variable Name</label><input type="text" name="input_name_' + idx + '" placeholder="variable name"></div>'
            + '<div><label>Source Type</label><select name="input_type_' + idx + '"><option value="ref">ref</option><option value="literal">literal</option></select></div>'
            + '<div><label>Value</label><input type="text" name="input_value_' + idx + '" list="ref-options" placeholder="value"></div>'
            + '<button type="button" class="btn btn-sm btn-danger" data-remove-closest=".formula-input-row">Remove</button>'
            + '</div>';
        container.insertAdjacentHTML('beforeend', html);
        container.setAttribute('data-next-index', String(idx + 1));
    }

    function addSumItem() {
        var container = document.getElementById('sum-items');
        if (!container) return;
        var idx = parseInt(container.getAttribute('data-next-index') || '1', 10);
        var html = '<div class="form-grid-4 sum-item-row">'
            + '<div><label>Item Reference</label><input type="text" name="sum_item_' + idx + '" list="ref-options" placeholder="e.g. input.w2.wages"></div>'
            + '<button type="button" class="btn btn-sm btn-danger" data-remove-closest=".sum-item-row">Remove</button>'
            + '</div>';
        container.insertAdjacentHTML('beforeend', html);
        container.setAttribute('data-next-index', String(idx + 1));
    }

    function addBracketRow(rawStatus) {
        var statusIdx = STATUSES.indexOf(rawStatus);
        if (statusIdx === -1) return;
        var status = STATUSES[statusIdx];
        var table = document.getElementById('bracket-table-' + status);
        if (!table) return;
        var idx = parseInt(table.getAttribute('data-next-index') || '1', 10);
        var tbody = table.querySelector('tbody');
        var tr = document.createElement('tr');
        tr.innerHTML = '<td><input type="text" name="bracket_' + status + '_' + idx + '_lower"></td>'
            + '<td><input type="text" name="bracket_' + status + '_' + idx + '_upper"></td>'
            + '<td><input type="text" name="bracket_' + status + '_' + idx + '_rate"></td>'
            + '<td class="align-right"><button type="button" class="btn btn-sm btn-danger" data-remove-closest="tr">Remove</button></td>';
        tbody.appendChild(tr);
        table.setAttribute('data-next-index', String(idx + 1));
    }

    function copyBracketsFromSingle(rawStatus) {
        // Replace the target status's rows with SINGLE's current values —
        // a starting point for the common "same shape, tweaked bounds" case.
        var statusIdx = STATUSES.indexOf(rawStatus);
        if (statusIdx === -1) return;
        var status = STATUSES[statusIdx];
        var source = document.getElementById('bracket-table-single');
        var target = document.getElementById('bracket-table-' + status);
        if (!source || !target || status === 'single') return;
        var rows = [];
        source.querySelectorAll('tbody tr').forEach(function (tr) {
            var lower = tr.querySelector('input[name$="_lower"]');
            var upper = tr.querySelector('input[name$="_upper"]');
            var rate = tr.querySelector('input[name$="_rate"]');
            if (lower && upper && rate) {
                rows.push({ lower: lower.value, upper: upper.value, rate: rate.value });
            }
        });
        var tbody = target.querySelector('tbody');
        tbody.innerHTML = '';
        rows.forEach(function (row, idx) {
            var tr = document.createElement('tr');
            tr.innerHTML = '<td><input type="text" name="bracket_' + status + '_' + idx + '_lower"></td>'
                + '<td><input type="text" name="bracket_' + status + '_' + idx + '_upper"></td>'
                + '<td><input type="text" name="bracket_' + status + '_' + idx + '_rate"></td>'
                + '<td class="align-right"><button type="button" class="btn btn-sm btn-danger" data-remove-closest="tr">Remove</button></td>';
            tr.querySelector('input[name$="_lower"]').value = row.lower;
            tr.querySelector('input[name$="_upper"]').value = row.upper;
            tr.querySelector('input[name$="_rate"]').value = row.rate;
            tbody.appendChild(tr);
        });
        target.setAttribute('data-next-index', String(rows.length));
    }

    function addMatrixRow() {
        var table = document.getElementById('matrix-table');
        if (!table) return;
        var rowIdx = parseInt(table.getAttribute('data-next-row-index') || '0', 10);
        var tbody = table.querySelector('tbody');
        var colInputs = table.querySelectorAll('thead input[name^="matrix_col_"]');
        var html = '<td><input type="text" name="matrix_row_' + rowIdx + '_key" placeholder="row key"></td>';
        colInputs.forEach(function (input) {
            // parseInt so only a number is ever concatenated into markup.
            var colIdx = parseInt(input.name.replace('matrix_col_', ''), 10);
            if (isNaN(colIdx)) return;
            html += '<td><input type="text" name="matrix_cell_' + rowIdx + '_' + colIdx + '" inputmode="decimal"></td>';
        });
        html += '<td class="align-right"><button type="button" class="btn btn-sm btn-danger" data-remove-closest="tr">Remove</button></td>';
        var tr = document.createElement('tr');
        tr.setAttribute('data-row-index', String(rowIdx));
        tr.innerHTML = html;
        tbody.appendChild(tr);
        table.setAttribute('data-next-row-index', String(rowIdx + 1));
    }

    function addMatrixColumn() {
        var table = document.getElementById('matrix-table');
        if (!table) return;
        var colIdx = parseInt(table.getAttribute('data-next-col-index') || '0', 10);
        var headRow = table.querySelector('thead tr');
        var th = document.createElement('th');
        th.innerHTML = '<input type="text" name="matrix_col_' + colIdx + '" placeholder="column key">';
        // Keep the Actions header (when present) as the last column.
        var actionsTh = headRow.querySelector('th.align-right');
        headRow.insertBefore(th, actionsTh);
        table.querySelectorAll('tbody tr').forEach(function (tr) {
            // parseInt so only a number is ever concatenated into markup.
            var rowIdx = parseInt(tr.getAttribute('data-row-index') || '', 10);
            if (isNaN(rowIdx)) return;
            var td = document.createElement('td');
            td.innerHTML = '<input type="text" name="matrix_cell_' + rowIdx + '_' + colIdx + '" inputmode="decimal">';
            var actionsTd = tr.querySelector('td.align-right');
            tr.insertBefore(td, actionsTd);
        });
        table.setAttribute('data-next-col-index', String(colIdx + 1));
    }

    document.addEventListener('click', function (e) {
        var removeBtn = e.target.closest('[data-remove-closest]');
        if (removeBtn) {
            var target = removeBtn.closest(removeBtn.getAttribute('data-remove-closest'));
            if (target) {
                target.remove();
            }
            return;
        }
        if (e.target.closest('[data-add-formula-input]')) {
            addFormulaInput();
            return;
        }
        if (e.target.closest('[data-add-sum-item]')) {
            addSumItem();
            return;
        }
        var bracketBtn = e.target.closest('[data-add-bracket-row]');
        if (bracketBtn) {
            addBracketRow(bracketBtn.getAttribute('data-add-bracket-row'));
            return;
        }
        var copyBtn = e.target.closest('[data-copy-brackets]');
        if (copyBtn) {
            copyBracketsFromSingle(copyBtn.getAttribute('data-copy-brackets'));
            return;
        }
        if (e.target.closest('[data-add-matrix-row]')) {
            addMatrixRow();
            return;
        }
        if (e.target.closest('[data-add-matrix-column]')) {
            addMatrixColumn();
        }
    });
})();
