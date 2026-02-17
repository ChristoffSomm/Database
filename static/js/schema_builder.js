(function () {
  let dragged = null;
  document.addEventListener('dragstart', (e) => {
    const item = e.target.closest('.schema-field-item');
    if (!item) return;
    dragged = item;
    item.classList.add('opacity-50');
  });
  document.addEventListener('dragend', (e) => {
    const item = e.target.closest('.schema-field-item');
    if (item) item.classList.remove('opacity-50');
  });
  document.addEventListener('dragover', (e) => {
    if (!dragged) return;
    const target = e.target.closest('.schema-field-item');
    if (!target || target === dragged) return;
    e.preventDefault();
    target.parentNode.insertBefore(dragged, target.nextSibling);
  });

  async function saveOrdering() {
    const items = [];
    document.querySelectorAll('[data-group-id]').forEach((group) => {
      const groupId = group.getAttribute('data-group-id');
      group.querySelectorAll('.schema-field-item').forEach((item, index) => {
        items.push({id: Number(item.getAttribute('data-field-id')), order: index, group_id: Number(groupId)});
      });
    });
    const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    await fetch('/custom-fields/reorder/', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf || ''},
      body: JSON.stringify({ordering: items}),
    });
  }

  document.addEventListener('drop', () => { saveOrdering(); });
})();
