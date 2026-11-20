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

test("en Auditoría, Ver cambios muestra el detalle a la vista", async ({ page }) => {
  // El 2026-11-19 se fue el estilo de esa ventana y el detalle quedaba
  // dibujado al pie de la página: el botón parecía no hacer nada.
  // Un alta de usuario deja una fila con detalle (la base de prueba no trae ninguna).
  await page.goto("/gestionuser.html");
  await page.click("#openCreatePanel");
  await page.fill("#fullNameInput", "Auditoría de Prueba");
  await page.fill("#emailInput", "auditoria-e2e@rotulos.local");
  await page.selectOption("#roleSelect", { label: "Comerciante" });
  await page.selectOption("#statusSelect", "active");
  // Con contraseña: sin ella el alta depende de la configuración del servidor (en el CI da 400).
  await page.fill("#passwordInput", "E2eRotulos2026");
  await page.locator("#createUserForm button[type=submit]").click();
  await expect(page.locator("tbody")).toContainText("auditoria-e2e@rotulos.local");

  // Pantalla baja: con la lista larga del servidor el detalle quedaba fuera de vista.
  await page.setViewportSize({ width: 1280, height: 420 });
  await page.goto("/auditoria.html");
  await page.selectOption("#auditCategoryFilter", { label: "Usuarios" });
  await page.getByRole("button", { name: "Aplicar" }).click();
  await page.getByRole("button", { name: "Ver cambios" }).first().click();
  const detail = page.getByRole("dialog", { name: "Detalle del cambio" });
  await expect(detail).toBeInViewport();
  await expect(detail).toContainText("auditoria-e2e@rotulos.local");
});
