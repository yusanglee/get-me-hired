// Generic Lever (jobs.lever.co/<co>/<id>/apply) form filler. engine/stages.py fills in the plan and the profile placeholders.
// Questions are li.application-question blocks; EEO selects (eeo[...]) sit outside them.
// Order: resume first (Lever parses it and autofills name/email/phone/company), then "Which location" (it decides
// which demographic survey is shown), then everything else. Only VISIBLE questions are filled: a posting can carry
// several location-specific surveys and Lever shows one. Fills only. Never clicks Submit.
async (page) => {
  const plan = __PLAN__;
  const SCHOOL_PREFER = /__LEVER_SCHOOL_RE__/;  // profile forms.education.lever_school_option
  const report = [];
  const norm = (s) => (s || '').replace(/✱/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  await page.waitForSelector('li.application-question', { timeout: 15000 });

  const tag = async () => page.evaluate(() => {
    document.querySelectorAll('[data-lv-idx]').forEach(e => e.removeAttribute('data-lv-idx'));
    const lis = [...document.querySelectorAll('li.application-question')].filter(li => li.offsetParent !== null);
    lis.forEach((li, i) => li.setAttribute('data-lv-idx', i));
    return lis.map(li => (li.querySelector('.application-label .text') || li.querySelector('.application-label'))?.innerText || '');
  });
  let labels = (await tag()).map(norm);
  const used = new Set();
  const findLi = (label) => {
    const want = norm(label);
    let i = labels.findIndex((l, k) => !used.has(k) && l === want);
    if (i < 0) i = labels.findIndex((l, k) => !used.has(k) && l.length > 2 && (l.startsWith(want.slice(0, 60)) || want.startsWith(l.slice(0, 60))));
    if (i >= 0) used.add(i);
    return i;
  };

  const setSelect = async (sel, value) => {
    const r = await sel.evaluate((s, [v, preferSrc]) => {
      const opts = [...s.options];
      let o = opts.find(x => x.text.trim() === v) || opts.find(x => x.value === v);
      if (!o) { const c = opts.filter(x => x.text.trim().startsWith(v)); o = c.find(x => new RegExp(preferSrc).test(x.text.trim())) || (c.length === 1 ? c[0] : null); }
      if (!o) return null;
      s.value = o.value;
      s.dispatchEvent(new Event('change', { bubbles: true }));
      if (window.jQuery) window.jQuery(s).trigger('change');
      return o.text.trim();
    }, [value, SCHOOL_PREFER.source]);
    if (!r) throw new Error(`no option "${value}"`);
  };

  const fillOne = async (f) => {
    const name = f.label.replace(/\s+/g, ' ').slice(0, 45);
    const vals = Array.isArray(f.value) ? f.value : [f.value];
    if (/^eeo\[/.test(f.label)) {
      await setSelect(page.locator(`select[name="${f.label}"]`), vals[0]);
      return `ok    ${name}`;
    }
    const i = findLi(f.label);
    if (i < 0) return `${f.required ? 'MISS ' : 'hidden'} ${name}`;
    const li = page.locator(`[data-lv-idx="${i}"]`);
    if (f.kind === 'file') {
      await li.locator('input[type=file]').setInputFiles(f.value);
      await page.waitForTimeout(6000);  // let Lever parse the resume before other fields are filled
      return `ok    ${name}`;
    }
    if (await li.locator('input[name=location]').count()) {
      const box = li.locator('input[name=location]');
      await box.click(); await box.fill(''); await box.pressSequentially(__CITY_TYPED__, { delay: 60 });
      const opt = li.locator('.dropdown-results > div', { hasText: /__CITY_RE__/ }).first();
      await opt.waitFor({ timeout: 8000 });
      await opt.click();
      return `ok    ${name}`;
    }
    if (await li.locator('select').count()) {
      await setSelect(li.locator('select').first(), vals[0]);
      return `ok    ${name}`;
    }
    if (await li.locator('input[type=radio], input[type=checkbox]').count()) {
      for (const v of vals) {
        const inp = li.locator(`input[value="${v.replace(/"/g, '\\"')}"]`).first();
        if (await inp.count()) { if (!(await inp.isChecked())) await inp.check({ force: true }); }
        else await li.locator('label', { hasText: new RegExp('^\\s*' + esc(v.trim()) + '\\s*$') }).first().click();
      }
      return `ok    ${name}`;
    }
    const box = li.locator('input[type=text], input[type=email], input[type=tel], input[type=url], textarea').first();
    if (!(await box.count())) return `skip  ${name} (no input, e.g. the Apply-with-LinkedIn button)`;
    await box.fill(String(vals[0]));
    if ((await box.inputValue()) !== String(vals[0])) { await box.click(); await page.keyboard.press('ControlOrMeta+a'); await box.pressSequentially(String(vals[0]), { delay: 5 }); }
    return `ok    ${name}`;
  };

  const isFile = (f) => f.kind === 'file';
  const isLoc = (f) => /which location are you applying/i.test(f.label);
  const order = [...plan.filter(isFile), ...plan.filter(isLoc), ...plan.filter(f => !isFile(f) && !isLoc(f))];
  for (const f of order) {
    try { report.push(await fillOne(f)); } catch (err) { report.push(`FAIL  ${f.label.slice(0, 45)}: ${String(err.message).split('\n')[0].slice(0, 110)}`); }
    if (isLoc(f)) { await page.waitForTimeout(1500); labels = (await tag()).map(norm); used.clear(); }  // surveys may switch
  }

  // Final check: every visible question + EEO selects, required flag, and current value
  const check = await page.evaluate(() => {
    const rows = [];
    const val = (root) => {
      const file = root.querySelector('input[type=file]');
      if (file) return file.files?.[0]?.name || (root.querySelector('.filename, .resume-upload-label, [class*=filename]')?.innerText || '').trim();
      const checked = [...root.querySelectorAll('input[type=radio]:checked, input[type=checkbox]:checked')].map(c => c.value);
      if (checked.length) return checked.join('|');
      const s = root.querySelector('select');
      if (s) return s.value ? s.options[s.selectedIndex].text.trim() : '';
      const t = root.querySelector('input[type=text], input[type=email], input[type=tel], input[type=url], textarea');
      return t ? t.value : '';
    };
    for (const li of document.querySelectorAll('li.application-question')) {
      if (li.offsetParent === null) continue;
      const labEl = li.querySelector('.application-label .text') || li.querySelector('.application-label');
      const raw = labEl?.innerText || '';
      const req = /✱/.test(raw) || !!li.querySelector('[required]') ? '*' : ' ';
      const v = val(li);
      rows.push(`${v ? 'ok   ' : 'EMPTY'}${req} ${raw.replace(/✱/g, '').replace(/\s+/g, ' ').trim().slice(0, 80)} = ${String(v).slice(0, 60)}`);
    }
    for (const s of document.querySelectorAll('select[name^="eeo["]')) {
      const v = s.value ? s.options[s.selectedIndex].text.trim() : '';
      rows.push(`${v ? 'ok   ' : 'EMPTY'}  ${s.name} = ${v}`);
    }
    rows.push('captcha present: ' + (document.querySelectorAll('iframe[src*=hcaptcha]').length ? 'hCaptcha (may challenge on submit)' : 'none'));
    return rows.join('\n');
  });
  return report.join('\n') + '\n--- final field check ---\n' + check;
}
