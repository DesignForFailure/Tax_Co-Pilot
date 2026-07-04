/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Clipboard copy for the AI authoring assistant. The button carries
   data-copy-target (element id) and data-copy-label (resting text) so no
   inline script is needed under the CSP. */
(function () {
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-copy-target]');
        if (!btn) return;
        var el = document.getElementById(btn.getAttribute('data-copy-target'));
        if (!el) return;
        var text = 'value' in el && el.value !== undefined ? el.value : el.textContent;
        var restore = btn.getAttribute('data-copy-label') || btn.textContent;

        function done() {
            btn.textContent = 'Copied!';
            setTimeout(function () { btn.textContent = restore; }, 2000);
        }

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, function () {
                selectFallback();
            });
        } else {
            selectFallback();
        }

        function selectFallback() {
            // No clipboard permission: select the text so Ctrl+C works.
            if (el.select) {
                el.focus();
                el.select();
            }
        }
    });
})();
