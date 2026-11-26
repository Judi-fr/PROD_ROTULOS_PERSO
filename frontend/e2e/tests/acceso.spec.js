const { test, expect } = require("@playwright/test");

test("recuperar contraseña avisa que salió bien", async ({ page }) => {
  // Mostraba "Error de red" después de mandar el mail.
  await page.goto("/recuperar-password.html");
  await page.fill("#emailInput", "demo@rotulos.local");
  await page.click("#submitBtn");
  await expect(page.locator("#pageMessage")).toContainText("Si existe una cuenta");
  await expect(page.locator("#pageMessage")).toHaveClass(/success/);
});

test("el registro pide lo que el servidor exige", async ({ page }) => {
  await page.goto("/register.html");
  await expect(page.locator("main")).toContainText("Al menos 8 caracteres");
});

test("sin sesión las pantallas mandan a entrar", async ({ page }) => {
  await page.goto("/pedidos.html");
  await page.waitForURL(/index\.html/);
});

test("una cuenta nueva no entra hasta confirmar el email", async ({ page }) => {
  // Se creaban y usaban cuentas con emails inventados (asdfg@asdfg.com).
  const fs = require("fs");
  const path = require("path");
  const email = `nueva${Date.now()}@example.com`;
  await page.goto("/register.html");
  await page.fill("#fullName", "Ana Paz");
  await page.fill("#email", email);
  await page.fill("#password", "Rotulos2026");
  await page.fill("#confirmPassword", "Rotulos2026");
  await page.click('#register-form button[type="submit"]');
  await page.waitForURL(/confirmar_email\.html/);
  await expect(page.locator("#confirmEmail")).toHaveText(email);

  // Sin confirmar, el panel la manda de vuelta.
  await page.goto("/dashboard.html");
  await page.waitForURL(/confirmar_email\.html/);

  // El mail sale por la consola de la API (backend.log): se abre su enlace.
  const log = fs.readFileSync(path.join(__dirname, "..", "backend.log"), "utf8").replace(/=\r?\n/g, "").replace(/=3D/g, "=");
  const tail = log.slice(log.lastIndexOf(email));
  const token = tail.match(/verify-email\.html\?token=([\w-]+)/)[1];
  await page.goto(`/verify-email.html?token=${token}`);
  await expect(page.locator("#verifyMsg")).toHaveClass(/success/);
  await page.goto("/dashboard.html");
  await page.waitForURL(/comercio_inicio\.html/);
});

test("sin 'mantener la sesión' la cookie es de sesión, y cerrar las demás deja afuera a ese navegador", async ({ browser }) => {
  // Otra computadora entra SIN marcar "Mantener la sesión iniciada".
  const otherContext = await browser.newContext({ baseURL: "http://localhost:8101" });
  const other = await otherContext.newPage();
  await other.goto("/index.html");
  await expect(other.locator("#rememberMe")).not.toBeChecked();
  await other.fill("#user", "demo@rotulos.local");
  await other.fill("#password", "Demo2026");
  await other.click('button[type="submit"]');
  await other.waitForURL(/dashboard\.html/);
  const refresh = (await otherContext.cookies()).find((cookie) => cookie.name === "rotulos_refresh");
  expect(refresh.expires).toBe(-1); // cookie de sesión: se borra al cerrar el navegador

  // Desde la sesión de siempre del comerciante, "Cerrar todas las demás".
  const mineContext = await browser.newContext({ baseURL: "http://localhost:8101", storageState: ".auth-comerciante.json" });
  const mine = await mineContext.newPage();
  await mine.goto("/seguridad.html");
  await expect(mine.locator(".session-item")).toHaveCount(2);
  await expect(mine.locator(".session-item.is-current")).toHaveCount(1);
  await mine.click("#revokeOthersBtn");
  await mine.getByRole("button", { name: "Cerrar las demás" }).click();
  await expect(mine.locator("#pageMessage")).toContainText("Cerramos 1 sesión");
  await expect(mine.locator(".session-item")).toHaveCount(1);

  // La otra computadora queda afuera en su próximo paso.
  await other.goto("/pedidos.html");
  await other.waitForURL(/index\.html/);

  await otherContext.close();
  await mineContext.close();
});

// TOTP (RFC 6238) como la app autenticadora: SHA1, 6 dígitos, 30 s.
function totp(secretBase32, at = Date.now()) {
  const crypto = require("crypto");
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const char of secretBase32.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(char).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g).map((byte) => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const digest = crypto.createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const number = (digest.readUInt32BE(offset) & 0x7fffffff) % 1000000;
  return String(number).padStart(6, "0");
}

test("verificación en dos pasos: se activa con la app, pide el código al entrar y un código de recuperación sirve una vez", async ({ browser }) => {
  const email = "e2e-2pasos@rotulos.local";
  const password = "E2eRotulos2026";
  async function login(page) {
    await page.goto("/index.html");
    await page.fill("#user", email);
    await page.fill("#password", password);
    await page.click('#login-form button[type="submit"]');
  }

  // Entrar y activarla con la app autenticadora.
  const context = await browser.newContext({ baseURL: "http://localhost:8101" });
  const page = await context.newPage();
  await login(page);
  await page.waitForURL(/(dashboard|comercio_inicio)\.html/);
  await page.goto("/seguridad.html");
  await page.fill("#mfaReauthPassword", password);
  await page.click('[data-mfa-method="totp"]');
  await expect(page.locator("#mfaQr")).toHaveAttribute("src", /^data:image\/png;base64,/);
  const secret = (await page.locator("#mfaSecret").textContent()).trim();
  await page.fill("#mfaSetupCode", totp(secret));
  await page.click('#mfaSetup button[type="submit"]');
  await expect(page.locator(".mfa-code-grid li")).toHaveCount(10);
  const recovery = (await page.locator(".mfa-code-grid li").first().textContent()).trim();
  await page.click("#codesDone");
  await expect(page.locator("#mfaBadge")).toBeVisible();
  await context.close();

  // Otro navegador: después de la contraseña pide el código.
  const second = await browser.newContext({ baseURL: "http://localhost:8101" });
  const page2 = await second.newPage();
  await login(page2);
  await page2.waitForURL(/verificar_ingreso\.html/);
  await page2.click("#useRecovery");
  await page2.fill("#mfaCode", recovery);
  await page2.click('#mfaForm button[type="submit"]');
  await page2.waitForURL(/(dashboard|comercio_inicio)\.html/);

  // El mismo código de recuperación no sirve dos veces.
  await page2.context().clearCookies();
  await login(page2);
  await page2.waitForURL(/verificar_ingreso\.html/);
  await page2.click("#useRecovery");
  await page2.fill("#mfaCode", recovery);
  await page2.click('#mfaForm button[type="submit"]');
  await expect(page2.locator("#pageMessage")).toContainText("no es correcto");
  await second.close();
});
