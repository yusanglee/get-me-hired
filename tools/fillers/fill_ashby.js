// Generic Ashby (jobs.ashbyhq.com/.../application) form filler. engine/stages.py fills in the plan and the profile placeholders.
// Each question is a .ashby-application-form-field-entry with a <label>; the control type is detected per entry.
// Fills only. Never clicks Submit. Returns a per-field report plus a final check of every entry.
async (page) => {
  const plan = __PLAN__;
  const report = [];
  const norm = (s) => (s || '').replace(/[\s*]+/g, ' ').trim().toLowerCase();
  await page.waitForSelector('[class*="_fieldEntry_"]', { timeout: 15000 });
  // Tag top-level field entries (some entries nest sub-entries, e.g. Phone + SMS consent)
  const n = await page.evaluate(() => { const all = [...document.querySelectorAll('[class*="_fieldEntry_"]')];
    const top = all.filter(e => !all.some(o => o !== e && o.contains(e))); top.forEach((e, i) => e.setAttribute('data-fill-idx', i)); return top.length; });
  const entries = { nth: (i) => page.locator(`[data-fill-idx="${i}"]`), count: async () => n };
  const labels = [];
  for (let i = 0; i < n; i++) labels.push(norm(await entries.nth(i).locator('label').first().innerText().catch(() => '')));
  const used = new Set();
  const findEntry = (label) => {
    const want = norm(label);
    let i = labels.findIndex((l, k) => !used.has(k) && l === want);
    if (i < 0) i = labels.findIndex((l, k) => !used.has(k) && (l.startsWith(want.slice(0, 60)) || want.startsWith(l.slice(0, 60))) && l.length > 2);
    if (i >= 0) used.add(i);
    return i;
  };
  for (const f of plan) {
    const i = findEntry(f.label);
    const name = f.label.replace(/\s+/g, ' ').slice(0, 45);
    if (i < 0) { report.push(`MISS  ${name}`); continue; }
    const e = entries.nth(i);
    const vals = Array.isArray(f.value) ? f.value : [f.value];
    try {
      const textBox = e.locator('input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type]), textarea').first();
      if (f.kind === 'text' && !/^(yes|no)$/i.test(String(vals[0])) && !/^i (acknowledge|agree)/i.test(String(vals[0])) && (await textBox.count()) && !(await e.locator('[role=combobox], input[placeholder="Start typing..."]').count())) {
        await textBox.fill(String(vals[0]));
      } else if (await e.locator('input[type=file]').count()) {
        await e.locator('input[type=file]').first().setInputFiles(f.value);
        await page.waitForTimeout(1500);
      } else if ((await e.locator('button', { hasText: /^Yes$/ }).count()) && (await e.locator('button', { hasText: /^No$/ }).count())) {
        const yes = /^(yes|i agree|i acknowledge|confirmed|accept)/i.test(String(vals[0]));
        const btn = e.locator('button', { hasText: yes ? /^Yes$/ : /^No$/ }).first();
        if (!/_active_/.test((await btn.getAttribute('class')) || '')) await btn.click();  // clicking an active option toggles it off
      } else if (await e.locator('input[type=radio], input[type=checkbox]').count()) {
        for (const v of vals) {
          const lab = e.locator('label').filter({ hasText: new RegExp('^\\s*' + v.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*$') });
          if (await lab.count()) await lab.first().click();
          else await e.getByLabel(v.trim(), { exact: false }).first().check();
        }
      } else if (await e.locator('[role=combobox], input[placeholder="Start typing..."]').count()) {
        const cb = e.locator('[role=combobox], input[placeholder="Start typing..."]').first();
        const typed = f.typed || (f.kind === 'location' ? __CITY_TYPED__ : vals[0]);  // f.typed: a country-only location
        await cb.click(); await cb.fill(''); await cb.pressSequentially(typed.slice(0, 30), { delay: 40 });
        await page.waitForTimeout(1500);
        const re = f.re ? new RegExp(f.re) : f.kind === 'location' ? /__CITY_RE__/ : new RegExp('^' + vals[0].trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$');
        const opt = page.getByRole('option', { name: re }).first();
        if (await opt.count()) await opt.click(); else { await page.keyboard.press('ArrowDown'); await page.keyboard.press('Enter'); }
      } else {
        const box = e.locator('input:not([type=hidden]), textarea').first();
        await box.fill(String(vals[0]));
      }
      report.push(`ok    ${name}`);
    } catch (err) {
      report.push(`FAIL  ${name}: ${String(err.message).split('\n')[0].slice(0, 110)}`);
    }
  }
  // Final check: every entry, its required flag, and what it now holds
  const check = await page.evaluate(() => [...document.querySelectorAll('[data-fill-idx]')].map(e => {
    const lab = (e.querySelector('label')?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    const req = /_required_/.test(e.querySelector('label')?.className || '') ? '*' : ' ';
    let v = '';
    const file = e.querySelector('input[type=file]');
    if (file) v = (e.innerText.match(/[\w.-]+\.pdf/) || [''])[0];
    const sel = [...e.querySelectorAll('button[aria-pressed=true], button[class*=active], button[class*=selected]')].map(b => b.innerText.trim());
    if (!v && sel.length) v = sel.join('|');
    const checked = [...e.querySelectorAll('input[type=radio]:checked, input[type=checkbox]:checked')].map(c => c.labels?.[0]?.innerText.trim() || c.value);
    if (!v && checked.length) v = checked.join('|');
    const txt = [...e.querySelectorAll('input[type=text], input[type=email], input[type=tel], input[type=url], input[type=number], input:not([type]), textarea')].map(t => t.value).filter(Boolean);
    if (!v && txt.length) v = txt.join('|');
    return `${v ? 'ok   ' : 'EMPTY'}${req} ${lab} = ${String(v).slice(0, 60)}`;
  }).join('\n'));
  return report.join('\n') + '\n--- final field check ---\n' + check;
}
