/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Constants editor behavior: dynamic group rows. Server-rendered counts
   arrive via data-next-index so no inline script is needed. */
(function () {
    var STATUSES = ['single', 'mfj', 'mfs', 'hoh', 'qss'];

    function addConstantRow() {
        var table = document.getElementById('constant-rows');
        if (!table) return;
        var idx = parseInt(table.getAttribute('data-next-index') || '1', 10);
        var tbody = table.querySelector('tbody');
        var tr = document.createElement('tr');
        var html = '<td><input type="text" name="const_group_' + idx + '_name" placeholder="e.g. upper"></td>';
        STATUSES.forEach(function (status) {
            html += '<td><input type="text" name="const_group_' + idx + '_' + status + '" inputmode="decimal"></td>';
        });
        html += '<td class="align-right"><button type="button" class="btn btn-sm btn-danger" data-remove-closest="tr">Remove</button></td>';
        tr.innerHTML = html;
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
        if (e.target.closest('[data-add-constant-row]')) {
            addConstantRow();
        }
    });
})();
