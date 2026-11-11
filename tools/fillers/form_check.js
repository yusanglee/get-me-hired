// Paste into browser_evaluate before handing a form to the user: lists every visible field and its value,
// flagging EMPTY ones (required or not), so nothing in application-notes.md is skipped.
() => {
  const rows = [];
  const label = el => (el.labels?.[0]?.innerText || el.getAttribute('aria-label') || el.closest('[class*=field], [class*=question], fieldset')?.querySelector('label, legend')?.innerText || el.name || '').trim().replace(/\s+/g, ' ').slice(0, 90);
  document.querySelectorAll('input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]):not([aria-hidden=true]), textarea').forEach(el => {
    if (!el.offsetParent) return;
    const sel = el.getAttribute('role') === 'combobox';
    let val = el.value;
    if (sel) {  // react-select: the chosen value renders in a sibling node a few levels up
      let n = el, found = '';
      for (let i = 0; i < 6 && n && !found; i++) { n = n.parentElement; found = n?.querySelector('[class*=singleValue], [class*=single-value], [class*=multiValue__label], [class*=multi-value__label]')?.innerText || ''; }
      val = found;
    }
    rows.push(`${val ? 'ok   ' : 'EMPTY'} ${label(el)} = ${String(val).slice(0, 50)}`);
  });
  document.querySelectorAll('fieldset, [role=group]').forEach(g => {
    const boxes = g.querySelectorAll('input[type=checkbox], input[type=radio]');
    if (boxes.length) rows.push(`${[...boxes].some(b => b.checked) ? 'ok   ' : 'EMPTY'} [choice] ${(g.querySelector('legend, label')?.innerText || '').slice(0, 90)}`);
  });
  const files = [...document.querySelectorAll('[class*=file] p, [class*=filename]')].map(e => e.innerText);
  rows.push('files: ' + [...new Set(files)].join(', '));
  return rows.join('\n');
}
