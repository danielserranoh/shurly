# Configurar la app de Google para Shurly (login con Google Workspace)

Guía para crear, en la cuenta de Google de Griddo, lo que necesita el login con Google de Shurly
(Phase 3.13). La sigue quien administra Google Workspace en `griddo.io`. Solo hay que hacerlo **una
vez**, y al terminar tendrás dos valores para Shurly: un **client ID** y un **client secret**.

> **Estado:** el backend del login con Google (3.13) está en desarrollo y todavía no ha llegado a
> producción. Puedes crear el cliente ya: nada lo usa hasta que se despliegue. Los nombres de los
> endpoints y de las variables de entorno son los acordados para esa PR.

---

## 0. Antes de empezar

- **Cuenta:** una cuenta `@griddo.io` con permisos de administrador de Workspace y acceso a Google
  Cloud. Si la organización restringe Google Cloud, actívalo para esa cuenta en la consola de
  administración: *Aplicaciones → Servicios adicionales de Google → Google Cloud*.
- **Direcciones de Shurly** (hacen falta en el paso 5):

  | Qué | Valor |
  |---|---|
  | API (backend) | `https://s.griddo.io` |
  | Callback de Google | `https://s.griddo.io/api/v1/auth/google/callback` |
  | Callback para desarrollo local | `http://localhost:8000/api/v1/auth/google/callback` |
  | Frontend (`FRONTEND_URL`) | **pendiente**: depende del alojamiento del frontend (4.10) |

  El frontend todavía no tiene dirección pública. No afecta a Google: a Google solo se le registra
  el callback de la API, y es la API la que después redirige al frontend.

---

## 1. Crear el proyecto de Google Cloud

1. Abre <https://console.cloud.google.com/> con la cuenta `@griddo.io`.
2. Selector de proyectos (arriba) → **Proyecto nuevo**.
3. **Nombre:** `Shurly`. **Organización:** `griddo.io` (importante: si queda fuera de la
   organización, no podrás marcar la app como *Interna* en el paso 3).
4. **Crear**, y comprueba que queda seleccionado.

## 2. Google Auth Platform → Branding

Menú ☰ → **Google Auth Platform** (antes "Pantalla de consentimiento de OAuth") → **Branding**:

- **Nombre de la app:** `Shurly`
- **Correo de asistencia:** una dirección de Griddo que alguien lea (p. ej. el grupo de soporte).
- **Logo:** opcional. Si lo subes, usa el isotipo de `design/brand/png/`.
- **Dominios autorizados:** `griddo.io`
- **Contacto del desarrollador:** tu correo.

## 3. Audience (audiencia): **Interna**

**Audience → Tipo de usuario: Interno.**

Es la decisión clave, y lo que hace segura la configuración:

- Solo pueden entrar cuentas de la organización `griddo.io`. Google rechaza cualquier otra antes
  incluso de llegar a Shurly.
- Una app interna **no necesita la verificación de Google** ni pasar por el modo "en pruebas".

Shurly comprueba además, por su cuenta, que el token de Google venga del dominio `griddo.io`
(`ORGANIZATION_DOMAIN`). Son dos barreras independientes.

## 4. Data Access (permisos): solo los básicos

**Data Access → Añadir o quitar permisos**, y marca estos:

- `openid` — obligatorio
- `.../auth/userinfo.email` — obligatorio
- `.../auth/userinfo.profile` — opcional: hoy Shurly no lo pide (solo `openid email`), pero la
  Phase 3.12 querrá rellenar el nombre y la foto desde Google. Puedes añadirlo ya.

No añadas ninguno más. Ninguno de estos es sensible, así que no hace falta revisión de Google.

## 5. Clients → crear el cliente web

1. **Clients → Crear cliente**.
2. **Tipo de aplicación:** *Aplicación web*.
3. **Nombre:** `Shurly web`.
4. **Orígenes de JavaScript autorizados:** déjalo **vacío**. El flujo es de servidor (la API habla
   con Google), no desde el navegador.
5. **URIs de redirección autorizadas**, exactamente estas:
   - `https://s.griddo.io/api/v1/auth/google/callback`
   - `http://localhost:8000/api/v1/auth/google/callback` (desarrollo local; quítala si no se usa)
6. **Crear**.

### ⚠️ El client secret solo se muestra una vez

Al crear el cliente, Google enseña el **client ID** y el **client secret**. **El secret solo se
puede ver y descargar en ese momento**; después la consola solo muestra sus últimos 4 caracteres.

- Pulsa **Descargar JSON** en ese mismo instante.
- Guárdalo en tu gestor de contraseñas.
- **No lo pegues en ningún chat** (tampoco en esta conversación), en un issue ni en un commit. El
  repositorio es público.

Si lo pierdes, no se recupera: en el cliente, **Añadir secret** crea uno nuevo, y luego borras el
antiguo.

## 6. Consola de administración de Workspace

En <https://admin.google.com/>: **Seguridad → Acceso y control de datos → Controles de API →
Gestionar el acceso de aplicaciones de terceros**.

- Comprueba que las **apps internas** tengan acceso. Lo más sencillo es activar **"Confiar en
  las aplicaciones internas propiedad del dominio"**. Si tu organización restringe las apps,
  busca `Shurly` en la lista y márcala como **De confianza**.
- Un administrador de Workspace puede bloquear **cualquier** app, también las internas. Si
  alguien de Griddo ve un aviso de "app bloqueada" al entrar, el motivo está aquí.

## 7. Pasarle los valores a Shurly

Shurly lee esta configuración de variables de entorno (servicio `shurly-api`, ECS, `eu-south-2`):

| Variable | Valor |
|---|---|
| `GOOGLE_CLIENT_ID` | el client ID (`…apps.googleusercontent.com`) |
| `GOOGLE_CLIENT_SECRET` | el client secret |
| `GOOGLE_REDIRECT_URI` | `https://s.griddo.io/api/v1/auth/google/callback` |
| `FRONTEND_URL` | la dirección del frontend, cuando exista (4.10) |
| `ORGANIZATION_DOMAIN` | `griddo.io` (ya es el valor por defecto) |

Si falta cualquiera de ellas, Shurly arranca igualmente y el login con Google responde "no
disponible". Nada se rompe.

**Cómo entregar el secret** sin exponerlo:

- **Opción A (recomendada):** déjalo en `_exchange/google_oauth.json`, que git ignora, y avisa.
  Lo paso a la configuración de ECS sin que se muestre en pantalla, igual que hicimos con la
  contraseña de la base de datos.
- **Opción B:** añádelo tú en la consola de ECS. Cambiar la configuración lanza un despliegue de
  unos 12 minutos.

El workflow de deploy ya oculta en sus logs cualquier variable con `SECRET` en el nombre. A medio
plazo el secret irá a Secrets Manager (6.3) en vez de a una variable de entorno.

## 8. Comprobar que funciona

Cuando el backend de la 3.13 esté desplegado y las variables configuradas:

1. Abre `https://s.griddo.io/api/v1/auth/google/start` en el navegador.
2. Google te pide elegir una cuenta. Con una `@griddo.io` → te devuelve a
   `FRONTEND_URL/login/#code=…` y entras en Shurly.
3. Con una cuenta que no sea de Griddo, Google la rechaza ("app interna"). Es lo que tiene que pasar.

Si ves `#error=google_unavailable`, falta alguna variable del paso 7.

## 9. Más adelante: el MCP (5.8)

El login por OAuth del MCP (5.8) usará **este mismo proyecto y este mismo cliente**, pero
necesitará una **URI de redirección más** en el paso 5. La URI exacta la dará la PR de la 5.8; ahora
no hace falta añadir nada.

---

## Resumen

- [ ] Proyecto `Shurly` dentro de la organización `griddo.io`
- [ ] Branding: nombre, correo de asistencia, dominio autorizado `griddo.io`
- [ ] Audience: **Interna**
- [ ] Permisos: `openid` y `email` (más `profile`, opcional)
- [ ] Cliente web con las dos URIs de redirección, y el JSON **descargado al crearlo**
- [ ] Workspace: las apps internas tienen acceso (o `Shurly` marcada como de confianza)
- [ ] Client ID y secret entregados (opción A u opción B del paso 7)

Referencias: [Gestionar clientes OAuth](https://support.google.com/cloud/answer/15549257) ·
[Controlar qué apps acceden a los datos de Workspace](https://knowledge.workspace.google.com/admin/apps/control-which-third-party-and-internal-apps-access-google-workspace-data)
