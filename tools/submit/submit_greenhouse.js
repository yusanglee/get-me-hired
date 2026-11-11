// Clicks Submit on the current Greenhouse form ONLY after the user approved this specific application in chat.
// Returns confirmation status; stops (does not retry) on validation errors or a CAPTCHA challenge.
async (page) => {
  const title = await page.title();
  await page.getByRole('button', { name: 'Submit application' }).click();
  await page.waitForTimeout(7000);
  const body = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
  const challenge = await page.locator('iframe[src*="recaptcha"][src*="bframe"]:visible, iframe[title*="challenge"]:visible').count();
  const errs = (await page.locator('[class*=error]:visible, [class*=helper-text--error]:visible').allInnerTexts()).filter(e => e.trim());
  return { title, url: page.url(), confirmed: /\/confirmation/.test(page.url()) || /thank you for applying|application has been received|application (was )?submitted/i.test(body), captcha: challenge > 0, errors: errs.slice(0, 8) };
}
