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
