// Dialog forms: buttons with data-dialog open a <dialog>; data-fill (JSON) pre-fills its fields.
document.querySelectorAll('[data-dialog]').forEach(btn => {
  btn.addEventListener('click', () => {
    const dlg = document.getElementById(btn.dataset.dialog);
    const form = dlg.querySelector('form');
    form.reset();
    form.querySelectorAll('input[type=hidden]:not([name=csrf_token])').forEach(i => (i.value = ''));
    const data = btn.dataset.fill ? JSON.parse(btn.dataset.fill) : {};
    Object.entries(data).forEach(([k, v]) => {
      const el = form.elements[k];
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = v == null ? '' : v;
    });
    const title = dlg.querySelector('[data-title]');
    if (title) title.textContent = data.id ? title.dataset.edit : title.dataset.add;
    dlg.showModal();
  });
});
document.querySelectorAll('dialog [data-close]').forEach(b =>
  b.addEventListener('click', () => b.closest('dialog').close()));

// Confirm destructive actions
document.querySelectorAll('form[data-confirm]').forEach(f =>
  f.addEventListener('submit', e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

// Auto-submit selects
document.querySelectorAll('select[data-autosubmit]').forEach(s =>
  s.addEventListener('change', () => s.form.submit()));

// New booking: find an existing guest as you type
const box = document.getElementById('guest-search');
if (box) {
  const list = document.getElementById('guest-results');
  const picked = document.getElementById('guest-picked');
  const idField = document.getElementById('guest-id');
  const newFields = document.getElementById('new-guest');
  let timer;
  const pick = (g) => {
    idField.value = g.id;
    picked.hidden = false;
    picked.querySelector('span').textContent = g.name + (g.detail ? ' (' + g.detail + ')' : '');
    newFields.hidden = true;
    newFields.querySelectorAll('input').forEach(i => (i.required = false));
    list.innerHTML = ''; box.value = '';
  };
  document.getElementById('guest-clear')?.addEventListener('click', () => {
    idField.value = ''; picked.hidden = true; newFields.hidden = false;
    newFields.querySelectorAll('[data-req]').forEach(i => (i.required = true));
  });
  box.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (box.value.trim().length < 2) { list.innerHTML = ''; return; }
      const res = await fetch('/guests/search?q=' + encodeURIComponent(box.value.trim()));
      if (!res.ok) return;
      const items = await res.json();
      list.innerHTML = '';
      if (!items.length) { list.innerHTML = '<div class="empty">No match. Enter new guest details below.</div>'; return; }
      items.forEach(g => {
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = g.name + (g.detail ? ' · ' + g.detail : '');
        b.addEventListener('click', () => pick(g));
        list.appendChild(b);
      });
    }, 250);
  });
  if (idField.value) newFields.hidden = true;
}
