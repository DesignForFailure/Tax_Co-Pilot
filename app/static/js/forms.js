/* SPDX-License-Identifier: AGPL-3.0-or-later */
/* Dynamic income-form rows shared by the Calculate and What-If pages.
   Buttons declare data-add-row="<section>"; rows are removed via the
   .remove-btn inside each .dynamic-row. Spouse toggling and state-option
   refresh only activate when the page has the matching elements. */
(function () {
    var counters = {
        p_w2: 1, p_1099int: 0, p_1099div: 0, p_1099b: 0, p_1099nec: 0,
        s_w2: 0, s_1099int: 0, s_1099div: 0, s_1099b: 0, s_1099nec: 0,
        edu: 0
    };

    function getTemplate(section, idx) {
        var prefix = section + '_' + idx;
        if (section.endsWith('_w2')) {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div><label>Employer</label><input type="text" name="' + prefix + '_employer" placeholder="Employer name"></div>'
                + '<div class="form-row">'
                + '<div><label>Wages (Box 1)</label><input type="text" name="' + prefix + '_wages" placeholder="85000"></div>'
                + '<div><label>Federal Withheld (Box 2)</label><input type="text" name="' + prefix + '_federal_withheld" placeholder="12000"></div>'
                + '</div>'
                + '<div class="form-row-3">'
                + '<div><label>State (Box 15)</label><input type="text" name="' + prefix + '_state" placeholder="GA" maxlength="2"></div>'
                + '<div><label>State Wages (Box 16)</label><input type="text" name="' + prefix + '_state_wages" placeholder="85000"></div>'
                + '<div><label>State Withheld (Box 17)</label><input type="text" name="' + prefix + '_state_withheld" placeholder="4000"></div>'
                + '</div></div>';
        }
        if (section.endsWith('_1099int')) {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div><label>Payer Name</label><input type="text" name="' + prefix + '_payer" placeholder="Bank name"></div>'
                + '<div class="form-row">'
                + '<div><label>Interest Income (Box 1)</label><input type="text" name="' + prefix + '_interest" placeholder="500"></div>'
                + '<div><label>Federal Withheld</label><input type="text" name="' + prefix + '_federal_withheld" placeholder="0"></div>'
                + '</div></div>';
        }
        if (section.endsWith('_1099div')) {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div><label>Payer Name</label><input type="text" name="' + prefix + '_payer" placeholder="Brokerage name"></div>'
                + '<div class="form-row-3">'
                + '<div><label>Ordinary Dividends (Box 1a)</label><input type="text" name="' + prefix + '_ordinary" placeholder="1000"></div>'
                + '<div><label>Qualified Dividends (Box 1b)</label><input type="text" name="' + prefix + '_qualified" placeholder="800"></div>'
                + '<div><label>Federal Withheld</label><input type="text" name="' + prefix + '_federal_withheld" placeholder="0"></div>'
                + '</div></div>';
        }
        if (section.endsWith('_1099nec')) {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div><label>Payer Name</label><input type="text" name="' + prefix + '_payer" placeholder="Client name"></div>'
                + '<div class="form-row">'
                + '<div><label>Nonemployee Compensation (Box 1)</label><input type="text" name="' + prefix + '_compensation" placeholder="30000"></div>'
                + '<div><label>Federal Withheld (Box 4)</label><input type="text" name="' + prefix + '_federal_withheld" placeholder="0"></div>'
                + '</div></div>';
        }
        if (section === 'edu') {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div class="form-row">'
                + '<div><label>Student Name</label><input type="text" name="' + prefix + '_student" placeholder="Student name"></div>'
                + '<div><label>Qualified Expenses</label><input type="text" name="' + prefix + '_expenses" placeholder="4000"></div>'
                + '</div></div>';
        }
        if (section.endsWith('_1099b')) {
            return '<div class="dynamic-row" data-section="' + section + '" data-index="' + idx + '">'
                + '<button type="button" class="remove-btn">Remove</button>'
                + '<div><label>Description</label><input type="text" name="' + prefix + '_desc" placeholder="AAPL sale"></div>'
                + '<div class="form-row">'
                + '<div><label>Proceeds</label><input type="text" name="' + prefix + '_proceeds" placeholder="900"></div>'
                + '<div><label>Cost Basis</label><input type="text" name="' + prefix + '_basis" placeholder="200"></div>'
                + '</div>'
                + '<div class="form-row">'
                + '<div><label>Federal Withheld</label><input type="text" name="' + prefix + '_federal_withheld" placeholder="0"></div>'
                + '<div class="checkbox-row"><input type="checkbox" name="' + prefix + '_long_term" value="1"><label class="u-mb-0">Long-term (held &gt; 1 year)</label></div>'
                + '</div></div>';
        }
        return '';
    }

    function addRow(section) {
        var idx = counters[section];
        counters[section] = idx + 1;
        var container = document.getElementById(section + '_container');
        if (!container) return;
        var div = document.createElement('div');
        div.innerHTML = getTemplate(section, idx);
        container.appendChild(div.firstChild);
    }

    document.addEventListener('click', function (e) {
        var addBtn = e.target.closest('[data-add-row]');
        if (addBtn) {
            addRow(addBtn.getAttribute('data-add-row'));
            return;
        }
        var removeBtn = e.target.closest('.remove-btn');
        if (removeBtn) {
            var row = removeBtn.closest('.dynamic-row');
            if (row) {
                row.parentElement.removeChild(row);
            }
        }
    });

    var filingSelect = document.getElementById('filing_status');
    var spouseSection = document.getElementById('spouse_section');

    function toggleSpouse() {
        if (!filingSelect || !spouseSection) return;
        if (filingSelect.value === 'mfj') {
            spouseSection.classList.add('visible');
        } else {
            spouseSection.classList.remove('visible');
        }
    }

    if (filingSelect && spouseSection) {
        filingSelect.addEventListener('change', toggleSpouse);
    }

    var yearSelect = document.getElementById('tax_year');
    var stateSelect = document.getElementById('state_of_residence');
    var availableStatesByYear = {};
    if (yearSelect && yearSelect.getAttribute('data-states-by-year')) {
        try {
            availableStatesByYear = JSON.parse(yearSelect.getAttribute('data-states-by-year'));
        } catch (err) {
            availableStatesByYear = {};
        }
    }

    function refreshStateOptions() {
        if (!yearSelect || !stateSelect) return;
        var previous = stateSelect.value;
        var states = availableStatesByYear[yearSelect.value] || [];

        stateSelect.innerHTML = '<option value="">— None —</option>';
        states.forEach(function (stateCode) {
            var opt = document.createElement('option');
            opt.value = stateCode;
            opt.textContent = stateCode;
            stateSelect.appendChild(opt);
        });

        if (states.indexOf(previous) !== -1) {
            stateSelect.value = previous;
        }
    }

    if (yearSelect && stateSelect) {
        yearSelect.addEventListener('change', refreshStateOptions);
    }

    function init() {
        refreshStateOptions();
        toggleSpouse();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
