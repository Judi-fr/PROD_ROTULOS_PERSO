# Variables del `.env` de producción — `rotulos.human-log.org`

Lo que está entre `<...>` hay que completarlo. Lo demás va tal cual.

> **Importante:** la API, el worker (`run_integrations_worker`) y el monitor (`run_monitor`)
> tienen que tener **las mismas variables**. Si el worker no tiene las mismas claves que la API,
> no puede leer los tokens de las tiendas ni registrar webhooks.

---

## 1. Dominio y Django

```env
DEBUG=False
SECRET_KEY=<la que ya tienen; NO cambiarla si ya hay datos>
ALLOWED_HOSTS=rotulos.human-log.org
CORS_ALLOWED_ORIGINS=https://rotulos.human-log.org
TRUSTED_PROXIES=1
```

- `TRUSTED_PROXIES=1` es por el balanceador de AWS. Si además hay una CDN adelante, va `2`.

## 2. URLs públicas (las que usan las tiendas)

```env
FRONTEND_URL=https://rotulos.human-log.org
PASSWORD_RESET_URL=https://rotulos.human-log.org/reset-password.html
EMAIL_VERIFICATION_URL=https://rotulos.human-log.org/verify-email.html
INTEGRATIONS_PUBLIC_BASE_URL=https://rotulos.human-log.org
```

- `INTEGRATIONS_PUBLIC_BASE_URL` es **la más importante para las tiendas**. Va con `https`,
  sin barra al final y sin `/api/v1`. Si falta, la tienda se conecta pero nunca llegan los
  pedidos solos.

## 3. Clave que cifra los tokens de las tiendas

```env
INTEGRATIONS_ENCRYPTION_KEY=<generar>
```

Para generarla:

```bash
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

- Se genera **una sola vez** y se guarda en un gestor de contraseñas.
- Si en producción **ya hay tiendas conectadas** y esta variable no estaba puesta,
  **no la agreguen ahora**: los tokens guardados dejan de poder leerse y cada tienda se
  tendría que volver a conectar. En ese caso, consultar antes.

## 4. Tiendanube (Portal de Partners → la app)

```env
TIENDANUBE_APP_ID=<app id del Portal de Partners>
TIENDANUBE_CLIENT_SECRET=<client secret del Portal de Partners>
TIENDANUBE_USER_AGENT=Rotulos (<email de contacto>)
```

- `TIENDANUBE_USER_AGENT` es obligatoria: sin ella Tiendanube contesta error 400 a todo.

## 5. Shopify (Dev Dashboard → la app)

```env
SHOPIFY_CLIENT_ID=<client id>
SHOPIFY_CLIENT_SECRET=<client secret>
```

## 6. WooCommerce, VTEX, Magento

No llevan variables. Cada tienda carga sus propias credenciales desde la pantalla Tiendas de la app.

## 7. Correo (registro, recuperar contraseña, invitaciones)

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<smtp del proveedor>
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<casilla>
EMAIL_HOST_PASSWORD=<contraseña de aplicación>
DEFAULT_FROM_EMAIL=Human Log · Rótulos <casilla>
```

## 8. Login con Google

```env
GOOGLE_CLIENT_ID=<el mismo que está en frontend/index.html>
GOOGLE_CLIENT_SECRET=<secreto>
```

## 9. Opcionales recomendadas

```env
MONITORING_ALERT_EMAILS=<mails que reciben las alertas de caída>
# ANTHROPIC_API_KEY=<solo si se quiere la importación de rótulos por foto>
```

---

# Después de cargar el `.env`

1. **Reiniciar la API, el worker y el monitor.** Sin el worker corriendo no entran pedidos.
2. **Verificar** que `https://rotulos.human-log.org/api/v1/health/system/` responda 200.
3. **Cargar las URLs nuevas en los paneles** de cada plataforma (abajo).
4. **Si ya había tiendas conectadas**, correr en el contenedor de la API:

   ```bash
   python manage.py update_store_urls --dry-run
   python manage.py update_store_urls
   ```

## URLs para cargar en cada plataforma

> **Estado (2026-11-26):** Tiendanube y Shopify **ya están hechos** (Shopify publicado como
> `rotulos-perso-9`). Falta solo **Google**.

### Tiendanube (Portal de Partners → la app)

| Campo | URL |
|---|---|
| URL de redirección | `https://rotulos.human-log.org/api/v1/integrations/tiendanube/callback/` |
| Acción masiva "Imprimir rótulos" | `https://rotulos.human-log.org/imprimir_tiendanube.html` |
| Acción masiva "Planilla de retiro" | `https://rotulos.human-log.org/planilla_tiendanube.html` |
| Acción masiva "Despachar con tu transportista" | `https://rotulos.human-log.org/despachar_tiendanube.html` |
| Webhooks de privacidad | `https://rotulos.human-log.org/api/v1/integrations/tiendanube/webhooks/` |
| Política de privacidad | `https://rotulos.human-log.org/privacidad.html` |
| Términos | `https://rotulos.human-log.org/terminos.html` |

### Shopify

En `rotulos-extension/shopify.app.rotulos-perso.toml` cambiar el dominio en `application_url`,
en los `uri` de los webhooks (también los de privacidad) y en `redirect_urls`. Después, desde
`rotulos-extension/`, correr `shopify app deploy` y publicar la versión nueva.

| Campo | URL |
|---|---|
| App URL | `https://rotulos.human-log.org/api/v1/integrations/shopify/launch/` |
| Redirect URL | `https://rotulos.human-log.org/api/v1/integrations/shopify/callback/` |

### Google Cloud Console (login con Google)

- Entrar con la cuenta de Google dueña del cliente `639018151961-c7mc5vsqfhpv3i208ok7a93647tlh1mf.apps.googleusercontent.com`
  (el que usa `frontend/index.html`; no es el del proyecto "My Project 81875").
- Cliente OAuth → **Orígenes de JavaScript autorizados**: `https://rotulos.human-log.org`
- Pantalla de consentimiento: dominio autorizado `human-log.org`, privacidad
  `https://rotulos.human-log.org/privacidad.html`, términos `https://rotulos.human-log.org/terminos.html`

### WooCommerce, Magento, VTEX

No hay que tocar nada a mano: se actualizan solos (o con el paso 4 de arriba).
