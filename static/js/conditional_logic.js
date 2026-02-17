(function () {
  function evaluateCondition(condition, values) {
    const actual = values[condition.field];
    const op = (condition.operator || 'equals').toLowerCase();
    if (op === 'equals') return actual == condition.value;
    if (op === 'not_equals') return actual != condition.value;
    if (op === 'contains') {
      if (Array.isArray(actual)) return actual.includes(condition.value);
      return String(actual || '').includes(String(condition.value));
    }
    if (op === 'gt') return Number(actual) > Number(condition.value);
    if (op === 'lt') return Number(actual) < Number(condition.value);
    return false;
  }

  function evaluateLogic(logic, values) {
    if (!logic || !logic.conditions) return true;
    const op = (logic.operator || 'AND').toUpperCase();
    const checks = logic.conditions.map((c) => evaluateCondition(c, values));
    return op === 'OR' ? checks.some(Boolean) : checks.every(Boolean);
  }

  function collectValues(form) {
    const values = {};
    form.querySelectorAll('input,select,textarea').forEach((el) => {
      if (!el.name) return;
      if (el.type === 'checkbox') {
        values[el.name] = el.checked;
      } else if (el.multiple) {
        values[el.name] = Array.from(el.selectedOptions).map((o) => o.value);
      } else {
        values[el.name] = el.value;
      }
    });
    return values;
  }

  function apply(form) {
    const values = collectValues(form);
    form.querySelectorAll('[data-conditional-logic]').forEach((field) => {
      let logic = field.getAttribute('data-conditional-logic');
      try { logic = JSON.parse(logic); } catch (e) { logic = {}; }
      const wrapper = field.closest('.dynamic-custom-field') || field.parentElement;
      const visible = evaluateLogic(logic, values);
      if (wrapper) wrapper.style.display = visible ? '' : 'none';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    const form = document.querySelector('form');
    if (!form) return;
    form.addEventListener('change', function () { apply(form); });
    form.addEventListener('input', function () { apply(form); });
    apply(form);
  });
})();
