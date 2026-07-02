/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Rule editor behavior: type-section switching, dynamic formula-input
   rows, and dynamic bracket-table rows. Server-rendered counts arrive
   via data-next-index attributes so no inline script is needed. */
(function () {
    var typeSelect = document.getElementById('rule_type');

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
            + '<div><label>Value</label><input type="text" name="input_value_' + idx + '" placeholder="value"></div>'
            + '<button type="button" class="btn btn-sm btn-danger" data-remove-closest=".formula-input-row">Remove</button>'
            + '</div>';
        container.insertAdjacentHTML('beforeend', html);
        container.setAttribute('data-next-index', String(idx + 1));
    }

    function addBracketRow(status) {
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
        var bracketBtn = e.target.closest('[data-add-bracket-row]');
        if (bracketBtn) {
            addBracketRow(bracketBtn.getAttribute('data-add-bracket-row'));
        }
    });
})();
