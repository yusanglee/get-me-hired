// Generic Greenhouse (job-boards.greenhouse.io) form filler. engine/stages.py fills in the plan and the profile placeholders.
// Fills only. Never clicks Submit. Returns a per-field report; anything not "ok" needs a look.
async (page) => {
  const plan = __PLAN__;
  const report = [];
  const key = (s) => s.replace(/\s+/g, ' ').trim().slice(0, 45);
  const seenLabel = {};
  // A react-select dropdown by accessible name; else (EEO boxes whose page label differs from the API's) by its <label for> text.
  // nth: a form that repeats a block of questions (same labels, other question ids) gets the nth box for the nth answer.
  const combo = async (name, labelRe, nth = 0) => {
    const byName = page.getByRole('combobox', { name }).nth(nth);
    if ((await byName.count()) || !labelRe) return byName;
    let k = 0;
    for (const c of await page.getByRole('combobox').all()) {
      const id = await c.getAttribute('id');
      if (id && labelRe.test(await page.locator(`label[for="${id}"]`).innerText().catch(() => '')) && k++ === nth) return c;
    }
    return byName;
  };
  // Pick each value (exact option text, else typed), then check the box shows exactly those values
  const choose = async (cb, values) => {
    const shown = () => cb.evaluate(el => { let n = el, t = ''; for (let i = 0; i < 6 && n && !t; i++) { n = n.parentElement;
      t = [...(n?.querySelectorAll('[class*=singleValue],[class*=single-value],[class*=multiValue__label],[class*=multi-value__label]') || [])].map(x => x.innerText.trim()).join(' | '); } return t; });
    for (const v of values) {
      await cb.click();
      const opt = page.getByRole('option', { name: v.trim(), exact: true });
      if (await opt.count()) await opt.first().click();
      else { await cb.pressSequentially(v.trim().slice(0, 40), { delay: 20 }); await page.getByRole('option', { name: v.trim(), exact: true }).first().click({ timeout: 4000 }).catch(() => page.keyboard.press('Enter')); }
    }
    const now = await shown();
    const got = now.split(' | ').filter(Boolean), want = values.map(v => v.trim());
    if (want.some(v => !got.includes(v)) || got.some(g => !want.includes(g))) throw new Error(`selected "${now}" but wanted "${want.join(' | ')}"`);
  };
  for (const f of plan) {
    const name = key(f.label);
    const nth = seenLabel[f.label] = (seenLabel[f.label] ?? -1) + 1;  // repeated labels ("If you answered Yes...") map to successive fields
    try {
      if (f.kind === 'text') {
        const exact = page.getByRole('textbox', { name: f.label.replace(/\s+/g, ' ').trim(), exact: true });
        const box = (await exact.count()) ? exact.nth(nth) : page.getByRole('textbox', { name }).nth(nth);
        await box.fill(f.value);
        if ((await box.inputValue()) !== f.value) {  // React-controlled or pre-filled field: replace via keyboard
          await box.click(); await page.keyboard.press('ControlOrMeta+A'); await page.keyboard.press('Backspace');
          await box.pressSequentially(f.value, { delay: 5 });
        }
        if ((await box.inputValue()) !== f.value) throw new Error('value mismatch after fill: ' + (await box.inputValue()).slice(0, 40));
      } else if (f.kind === 'file') {
        // On some embed pages Greenhouse's upload script isn't ready when the form renders: a file set too early
        // shows "Cannot read properties of undefined (reading 'uploadFile')" and attaches nothing. Wait for the page
        // to settle, check the file name shows, and set it once more after a pause if it doesn't.
        const grp = page.getByRole('group', { name }).nth(nth);
        const fname = f.value.split('/').pop();
        const shows = async () => { for (let i = 0; i < 10; i++) { if ((await grp.innerText().catch(() => '')).includes(fname)) return true; await page.waitForTimeout(500); } return false; };
        await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
        await grp.locator('input[type=file]').setInputFiles(f.value);
        if (!(await shows())) {
          await page.waitForTimeout(3000);
          await grp.locator('input[type=file]').setInputFiles(f.value);
          if (!(await shows())) throw new Error(`${fname} not shown after two tries: reload the page and upload it`);
        }
      } else if (f.kind === 'location') {
        const cb = page.getByRole('combobox', { name: 'Location (City)' }).first();
        await cb.pressSequentially(f.value, { delay: 30 });
        await page.getByRole('option', { name: /__GH_LOCATION_RE__/ }).first().click({ timeout: 8000 });
      } else if (f.kind === 'choice') {
        const grp = page.getByRole('group', { name }).nth(nth);
        const boxes = (await grp.count()) ? grp.getByRole('checkbox') : null;
        if (boxes && (await boxes.count())) {
          for (const v of f.value) await grp.getByRole('checkbox', { name: v.trim() }).first().check();
        } else {
          const alias = { VeteranStatus: 'Veteran Status', DisabilityStatus: 'Disability Status' }[f.label];
          const eeoRe = { Race: /\brace\b/i, VeteranStatus: /veteran/i, DisabilityStatus: /disabilit/i }[f.label];
          if (f.hispanic) {  // Greenhouse EEO: "Are you Hispanic/Latino?" comes first; the race box appears only after "No"
            const h = await combo('Hispanic', /hispanic/i);
            if (await h.count()) { await choose(h, [f.hispanic]); await page.waitForTimeout(500); }
          }
          const cb = await combo(alias || name, eeoRe, nth);
          if (!(await cb.count()) && f.hispanic === 'Yes') { report.push(`ok    ${f.kind.padEnd(8)} ${name} (not asked after Hispanic/Latino: Yes)`); continue; }
          await choose(cb, f.value);
        }
      }
      report.push(`ok    ${f.kind.padEnd(8)} ${name}`);
    } catch (e) {
      report.push(`FAIL  ${f.kind.padEnd(8)} ${name}: ${String(e.message).split('\n')[0].slice(0, 120)}`);
    }
  }
  // --- Education block (Greenhouse school--0 / degree--0 / discipline--0 / dates). Values: profile forms.education.
  const edu = [];
  const pick = async (cb, typed, re) => {
    await cb.click(); if (typed) await cb.pressSequentially(typed, { delay: 40 });
    await page.waitForTimeout(1200);
    const o = page.getByRole('option', { name: re }).first();
    if (await o.count()) { await o.click(); return true; }
    await page.keyboard.press('Escape'); return false;
  };
  const val = (el) => el.evaluate(e => { let n = e, v = ''; for (let i = 0; i < 6 && n && !v; i++) { n = n.parentElement; v = [...n.querySelectorAll('[class*=single-value]')].map(x => x.innerText).join('|'); } return v || e.value; });
  const school = page.locator('#school--0');
  if (__EDU_ON__ && await school.count()) {
    if (!(await val(school))) edu.push('school ' + await pick(school, __SCHOOL_TYPED__, /__SCHOOL_RE__/i));
    const degree = page.locator('#degree--0');
    if ((await degree.count()) && !(await val(degree)))  // the profile's option, else the same degree spelled another way ("Bachelors")
      edu.push('degree ' + (await pick(degree, '', /__DEGREE_RE__/i) || await pick(degree, '', /__DEGREE_LOOSE_RE__/i)));
    const disc = page.locator('#discipline--0');
    if ((await disc.count()) && !(await val(disc))) edu.push('discipline ' + (await pick(disc, __DISC_TYPED__, /__DISC_RE__/i) || await pick(disc, 'Other', /^Other$/i)));  // exact discipline, else Other (never a near-miss)
    const hasEmployment = (await page.locator('#company-name-0').count()) > 0;  // employment block uses start-date-month-0 etc.
    for (const [lab, v, idre] of [['Start date month', __EDU_START_MONTH__, 'start'], ['Start date year', __EDU_START_YEAR__, 'start'], ['End date month', __EDU_END_MONTH__, 'end'], ['End date year', __EDU_END_YEAR__, 'end']]) {
      const kind = lab.endsWith('month') ? 'month' : 'year';
      let f = page.locator(`[id^="${idre}"][id*="${kind}"][id$="--0"]`).first();  // education ids end in --0
      if (!(await f.count())) { if (hasEmployment) continue; f = page.getByLabel(lab, { exact: false }).first(); }
      if (!(await f.count())) continue;
      if ((await f.getAttribute('role')) === 'combobox') { let ok = false; for (const x of v) { if (await pick(f, x, new RegExp('^' + x + '$', 'i'))) { ok = true; break; } } edu.push(lab + ' ' + ok); }
      else { await f.fill(v[v.length === 1 ? 0 : 1]); edu.push(lab + ' ' + await f.inputValue()); }
    }
    report.push('edu   ' + edu.join(', ') + ' => ' + [await val(school), await val(page.locator('#degree--0'))].join(' | '));
  }


  // --- Employment block (company-name-0 / title-0 / dates): most recent role, profile forms.employment
  if (__EMP_ON__ && await page.locator('#company-name-0').count()) {
    const pickId = async (id, text) => { const cb = page.locator('#' + id); await cb.click(); await page.waitForTimeout(400);
      const o = page.getByRole('option', { name: text, exact: true }).first(); if (await o.count()) await o.click();
      else { await cb.pressSequentially(text, { delay: 30 }); await page.waitForTimeout(800); await page.getByRole('option', { name: text, exact: true }).first().click(); } };
    try {
      if (!(await page.locator('#company-name-0').inputValue())) await page.locator('#company-name-0').fill(__EMP_COMPANY__);
      if ((await page.locator('#title-0').count()) && !(await page.locator('#title-0').inputValue())) await page.locator('#title-0').fill(__EMP_TITLE__);
      if (await page.locator('#start-date-month-0').count()) await pickId('start-date-month-0', __EMP_START_MONTH__);
      if (await page.locator('#start-date-year-0').count()) await page.locator('#start-date-year-0').fill(__EMP_START_YEAR__);
      if (await page.locator('#end-date-month-0').count()) await pickId('end-date-month-0', __EMP_END_MONTH__);
      if (await page.locator('#end-date-year-0').count()) await page.locator('#end-date-year-0').fill(__EMP_END_YEAR__);
      const cur = page.locator('#current-role-0_1'); if ((await cur.count()) && (await cur.isChecked())) await cur.uncheck();
      report.push('ok    employ   ' + __EMP_SUMMARY__);
    } catch (e) { report.push('FAIL  employ   ' + String(e.message).split('\n')[0].slice(0, 100)); }
  }
  // Phone country defaults to US when present and unset
  try {
    const c = page.getByRole('combobox', { name: 'Country' }).first();
    if (await c.count()) { await c.click(); await c.pressSequentially('United States', { delay: 20 }); await page.keyboard.press('Enter'); }
  } catch (e) {}
  // Demographic-data consent (required to submit the EEO answers the user chose to give; approved as a privacy acknowledgement)
  for (const c of await page.locator('input[type=checkbox][id^=gdpr_demographic_data_consent]').all()) { if (!(await c.isChecked())) { await c.check(); report.push('ok    consent  demographic-data consent box'); } }
  const check = await page.evaluate(__CHECK__);
  return report.join('\n') + '\n--- final field check ---\n' + check;
}
