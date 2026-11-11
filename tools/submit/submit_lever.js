// Lever submit. Run only after the user approves this specific application in chat.
// Pre-check: resume attached and name/email filled (guards against a reloaded, empty tab). Then clicks
// #btn-submit and reports confirmation (/thanks URL or "application submitted" text), validation errors,
// or a visible hCaptcha challenge (the user solves it; this script never touches captchas).
async (page) => {
  // Already past the form (e.g. after the user solved a captcha): just report.
  if (/\/thanks/.test(page.url())) return 'CONFIRMED  ' + page.url();
  const pre = await page.evaluate(() => ({
    resume: !!document.querySelector('input[name=resume]')?.files?.length,
    name: document.querySelector('input[name=name]')?.value || '',
    email: document.querySelector('input[name=email]')?.value || '',
  }));
  if (!pre.resume || !pre.name || !pre.email) return 'ABORT (form not filled, nothing submitted): ' + JSON.stringify(pre);
  await page.locator('#btn-submit').click();
  const ok = /application (was )?submitted|thanks for applying|thank you for applying|we('ve| have) received your application/i;
  for (let t = 0; t < 45; t++) {
    await page.waitForTimeout(1000);
    const body = await page.locator('body').innerText().catch(() => '');
    if (/\/thanks/.test(page.url()) || ok.test(body)) return 'CONFIRMED  ' + page.url() + '  | ' + ((body.match(ok) || [''])[0]);
    const challenge = page.locator('iframe[src*="hcaptcha"][title*="challenge" i], iframe[src*="hcaptcha"][src*="frame=challenge"]');
    if (t > 1 && (await challenge.count()) && (await challenge.first().isVisible().catch(() => false)))
      return 'CAPTCHA  hCaptcha challenge is showing on ' + page.url() + ' (the user solves it; Lever submits after)';
    const errs = (await page.locator('.error-message, .application-error, [class*=error]:visible').allInnerTexts().catch(() => [])).map(s => s.trim()).filter(s => s && !/maximum upload size/i.test(s));  // that one is static template text
    if (t > 4 && errs.length) return 'ERRORS  ' + page.url() + '\n' + [...new Set(errs)].join('\n').slice(0, 800);
  }
  return 'UNCONFIRMED after 45s  ' + page.url() + '\n' + (await page.locator('body').innerText()).slice(0, 500);
}
