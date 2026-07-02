/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Form submission guards, applied to every page via the base layout:
   - data-confirm="...": ask for confirmation before destructive submits
     (replaces former inline onsubmit/onclick confirm() handlers).
   - Double-submit prevention: disable the submit button once a form is
     actually being submitted. */
document.addEventListener('submit', function (e) {
    var form = e.target;
    var message = form.getAttribute('data-confirm');
    if (message && !window.confirm(message)) {
        e.preventDefault();
        return;
    }
    var btn = form.querySelector('button[type="submit"]:not([disabled]), .btn[type="submit"]:not([disabled])');
    if (btn) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = 'Working…';
    }
});
