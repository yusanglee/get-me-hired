// Ashby submit. Run only after the user approves this specific application in chat.
// Clicks "Submit Application" and reports confirmation (success text) or any validation errors / captcha.
async (page) => {
  const btn = page.getByRole('button', { name: /^Submit Application$/i }).first();
  if (!(await btn.count())) return 'NO SUBMIT BUTTON on ' + page.url();
  // Ashby sometimes shows a Yes/No button as active without registering it in form state.
  // Re-assert each active choice: click the other option, then the intended one again.
  const yn = page.locator('[class*="_fieldEntry_"]').filter({ has: page.locator('button.ashby-application-form-input-yesno-option') });
  for (let i = 0; i < await yn.count(); i++) {
    const e = yn.nth(i);
    const act = e.locator('button.ashby-application-form-input-yesno-option[aria-pressed=true]');
    if (!(await act.count())) continue;
    const want = (await act.first().innerText()).trim();
    const other = want === 'Yes' ? 'No' : 'Yes';
    await e.locator('button.ashby-application-form-input-yesno-option', { hasText: new RegExp('^' + other + '$') }).click();
    await page.waitForTimeout(200);
    await e.locator('button.ashby-application-form-input-yesno-option', { hasText: new RegExp('^' + want + '$') }).click();
    await page.waitForTimeout(200);
    if ((await e.locator('button[aria-pressed=true]').innerText()).trim() !== want) return 'ABORT: Yes/No re-assert failed, nothing submitted';
  }
  // Same desync on single-choice radios: click another option, then the checked one again.
  const radios = page.locator('[class*="_fieldEntry_"]').filter({ has: page.locator('input[type=radio]:checked') });
  for (let i = 0; i < await radios.count(); i++) {
    const e = radios.nth(i);
    const labs = e.locator('label:has(input[type=radio])');
    if ((await labs.count()) < 2) continue;
    const wantText = (await e.locator('label:has(input[type=radio]:checked)').first().innerText()).trim();
    const other = (await labs.nth(0).innerText()).trim() === wantText ? labs.nth(1) : labs.nth(0);
    await other.click(); await page.waitForTimeout(200);
    await e.locator('label:has(input[type=radio])', { hasText: wantText }).first().click(); await page.waitForTimeout(200);
    if ((await e.locator('label:has(input[type=radio]:checked)').first().innerText()).trim() !== wantText) return 'ABORT: radio re-assert failed, nothing submitted';
  }
  await btn.scrollIntoViewIfNeeded();
  await btn.click();
  const ok = /application was successfully submitted|thank(s| you)( so much)? for (applying|your application)|\bSuccess\b\s+Thank|we('ve| have) received your application/i;
  for (let t = 0; t < 30; t++) {
    await page.waitForTimeout(1000);
    const body = await page.locator('body').innerText().catch(() => '');
    if (ok.test(body)) return 'CONFIRMED  ' + page.url() + '  | ' + (body.match(ok) || [''])[0];
    if (await page.locator('iframe[src*="captcha"], iframe[title*="captcha" i]').count()) {
      const visible = await page.locator('iframe[src*="captcha"], iframe[title*="captcha" i]').first().isVisible().catch(() => false);
      if (visible && t > 3) return 'CAPTCHA  — the user must complete it on ' + page.url();
    }
    const errs = await page.locator('[class*="_error_"], [role=alert]').allInnerTexts().catch(() => []);
    const real = errs.map(s => s.trim()).filter(Boolean);
    if (real.length && t > 2) return 'ERRORS  ' + page.url() + '\n' + real.join('\n').slice(0, 800);
  }
  return 'UNCONFIRMED after 30s  ' + page.url() + '\n' + (await page.locator('body').innerText()).slice(0, 600);
}
