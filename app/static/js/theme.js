/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Theme persistence. Loaded in <head> (no defer) so the saved theme is
   applied before first paint — deferring it would flash the wrong theme. */
(function () {
    try {
        var savedTheme = localStorage.getItem('tcp-theme');
        if (savedTheme === 'light' || savedTheme === 'dark') {
            document.documentElement.dataset.theme = savedTheme;
        }
    } catch (err) {
        /* Theme preference is optional; ignore storage errors. */
    }
})();

document.addEventListener('DOMContentLoaded', function () {
    var order = ['system', 'light', 'dark'];
    var button = document.getElementById('theme-toggle');

    function currentTheme() {
        var saved = null;
        try {
            saved = localStorage.getItem('tcp-theme');
        } catch (err) {
            saved = null;
        }
        return saved === 'light' || saved === 'dark' ? saved : 'system';
    }

    function applyTheme(theme) {
        if (theme === 'system') {
            document.documentElement.removeAttribute('data-theme');
            try {
                localStorage.removeItem('tcp-theme');
            } catch (err) {
                /* Ignore storage failures. */
            }
        } else {
            document.documentElement.dataset.theme = theme;
            try {
                localStorage.setItem('tcp-theme', theme);
            } catch (err) {
                /* Ignore storage failures. */
            }
        }
        if (button) {
            button.textContent = 'Theme: ' + (theme === 'system' ? 'Auto' : theme[0].toUpperCase() + theme.slice(1));
        }
    }

    if (button) {
        applyTheme(currentTheme());
        button.addEventListener('click', function () {
            var next = order[(order.indexOf(currentTheme()) + 1) % order.length];
            applyTheme(next);
        });
    }
});
