const { test, expect } = require("@playwright/test");

test.use({ storageState: ".auth-admin.json" });

test("el botón Actualizar de Usuarios vuelve a pedir la lista", async ({ page }) => {
  // No tenía nada conectado.
  await page.goto("/gestionuser.html");
  await expect(page.locator("tbody tr").first()).toContainText("@");
  const request = page.waitForRequest((r) => /\/api\/v1\/users\//.test(r.url()) && r.method() === "GET");
  await page.click("#refreshUsersBtn");
  await request;
});

test("en celular el admin tiene menú", async ({ page }) => {
  // Desde el 2026-11-19 el admin usa la barra lateral de toda la app: en celular
  // queda fuera de la pantalla hasta que se abre con el botón de la barra superior.
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/gestionuser.html");
  const menu = page.getByRole("navigation", { name: "Menú principal" });
  const users = menu.getByRole("link", { name: "Usuarios", exact: true });
  await expect(users).not.toBeInViewport();
  await page.getByRole("button", { name: "Abrir el menú" }).click();
  await expect(users).toBeInViewport();
  await expect(menu.getByRole("link", { name: "Roles y permisos" })).toBeInViewport();
});

test("no ve el usuario interno de los comercios", async ({ page }) => {
  await page.goto("/gestionuser.html");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await expect(page.locator("main")).not.toContainText("datos.invalid");
});
