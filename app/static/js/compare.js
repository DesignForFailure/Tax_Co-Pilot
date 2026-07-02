/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Run-comparison checkbox logic for the Runs page: cap the selection at
   two runs, keep the hint text current, and open the comparison view. */
(function () {
    function updateCompare() {
        var boxes = document.querySelectorAll('.compare-cb:checked');
        var hint = document.getElementById('compare-hint');
        if (hint) {
            if (boxes.length === 0) {
                hint.textContent = 'Check exactly two runs, then open the comparison view.';
            } else if (boxes.length === 1) {
                hint.textContent = 'Select one more run to enable a side-by-side comparison.';
            } else {
                hint.textContent = 'Two runs selected. Open the comparison view when ready.';
            }
        }
    }

    document.addEventListener('change', function (e) {
        if (!e.target.classList.contains('compare-cb')) return;
        var boxes = document.querySelectorAll('.compare-cb:checked');
        if (boxes.length > 2) {
            e.target.checked = false;
        }
        updateCompare();
    });

    function compareSelected() {
        var boxes = document.querySelectorAll('.compare-cb:checked');
        if (boxes.length !== 2) {
            alert('Please select exactly two runs to compare.');
            return;
        }
        var a = boxes[0].value;
        var b = boxes[1].value;
        window.location.href = '/runs/compare?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b);
    }

    document.addEventListener('click', function (e) {
        if (e.target.closest('[data-compare-selected]')) {
            compareSelected();
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateCompare);
    } else {
        updateCompare();
    }
})();
