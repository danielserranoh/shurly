# Conectar Claude a Shurly (el MCP)

Guía para conectar Claude a Shurly y pedirle cosas como «acorta este enlace y etiquétalo para la
campaña Q4» o «¿cuántos clics tuvo la propuesta de Acme esta semana?». Claude actúa como tú: ve y
cambia lo mismo que tu cuenta.

La dirección del MCP es, **exactamente así, con la barra final**:

```
https://shurly.griddo.io/mcp/
```

Hay dos formas de entrar:

| | Con Google (recomendada) | Con una API key |
|---|---|---|
| Qué necesitas | Tu cuenta `@griddo.io` | Una API key de Shurly |
| Dónde funciona | claude.ai, Claude Desktop y Claude Code | Solo Claude Code |
| Estado | Activo en producción desde el 28-09-2026 | Funciona, pero hoy no hay dónde generar la key (ver más abajo) |

---

## 1. claude.ai (y Claude Desktop)

Claude Desktop usa los conectores de tu cuenta de claude.ai: si lo añades en claude.ai, aparece
también en Desktop. No hay que configurar nada más en Desktop.

1. En <https://claude.ai>, abre **Settings → Connectors** (en algunas versiones, **Settings →
   Customize → Connectors**).
2. **Add custom connector**.
   - **Name:** `Shurly`
   - **URL:** `https://shurly.griddo.io/mcp/` (con la barra final)
   - No rellenes nada en "Advanced settings" (client ID ni secret): Shurly registra el conector solo.
3. **Add**, y luego **Connect**.
4. Se abre la **página de consentimiento de Shurly**. Dice qué aplicación pide acceso (claude.ai) y
   adónde te devuelve. Acepta.
5. Te lleva a **Google**. Entra con tu cuenta `@griddo.io`.
6. Vuelves a claude.ai con el conector en estado **Connected**.

> **Plan Team o Enterprise:** un owner de la organización de claude.ai tiene que añadir el conector
> primero en **Organization settings → Connectors**. Después cada persona lo conecta desde sus
> Settings con los pasos 3–6.

**Probarlo:** en una conversación nueva, activa Shurly en el menú de herramientas (el icono de
conectores) y pregunta: «¿Qué enlaces tengo en Shurly?». Claude usará `list_urls`.

---

## 2. Claude Code

### Con Google

```bash
claude mcp add --transport http --scope user shurly https://shurly.griddo.io/mcp/
```

Después, dentro de Claude Code:

1. Escribe `/mcp`.
2. Elige **shurly** → **Authenticate**.
3. Se abre el navegador: la página de consentimiento de Shurly (dirá Claude Code y una dirección
   `http://localhost:…`) y luego Google. Entra con tu cuenta `@griddo.io`.
4. Vuelve a Claude Code: `/mcp` debe mostrar `shurly` como **connected**.

`--scope user` lo deja disponible en todos tus proyectos. Sin él, solo en la carpeta actual.

### Con una API key

```bash
claude mcp add --transport http --scope user shurly https://shurly.griddo.io/mcp/ \
    --header "Authorization: Bearer <tu API key>"
```

La API key se genera en **Settings → API & MCP** de la web de Shurly, y **solo se muestra una vez,
al generarla**: cópiala en ese momento. Hoy la web todavía no está publicada (tarea 4.10), así que
usa Google. Cuando la web esté en `https://shurly.griddo.io`, esta opción queda disponible.

Quien tenga la key puede gestionar tus enlaces: trátala como una contraseña y no la pegues en
chats, issues ni commits.

---

## 3. Qué puede hacer Claude

Unas 40 herramientas: crear y editar enlaces (normales, personalizados y de campaña), etiquetas,
reglas de redirección, analíticas de un enlace, de una campaña o generales, y tu perfil (por
ejemplo, «pon mi zona horaria en Atlantic/Canary»).

Lo que **no** puede hacer, a propósito: cambiar roles o miembros de la organización, cambiar tu
contraseña, iniciar sesión por ti, ni generar o revocar API keys. Son acciones que solo debe hacer
la persona, porque un texto malicioso (el título de un enlace, una página leída) podría intentar
convencer a Claude de hacerlas.

---

## 4. Si algo falla

| Qué ves | Qué pasa | Qué hacer |
|---|---|---|
| Google rechaza tu cuenta | Solo entran cuentas del Workspace de `griddo.io` | Entra con tu cuenta de trabajo |
| Shurly rechaza tu cuenta tras Google | Tu cuenta de Shurly está cerrada (por ejemplo, te quitaron de la organización) | Pide a un owner que lo revise |
| El conector no llega a abrir la página de consentimiento, o da error de "resource" | La dirección no es exacta | Usa `https://shurly.griddo.io/mcp/`, con la barra final y ese host |
| "Too many attempts" / error 429 | Se superó el límite de intentos de inicio de sesión desde tu IP | Espera un minuto y reintenta |
| Claude dice que Shurly respondió 401 con tu API key | La key ya no vale: se regeneró o revocó, o te quitaron de la organización | Genera otra, `claude mcp remove shurly` y añádelo de nuevo |
| En claude.ai pide reconectar | La sesión de Google caducó o se revocó | **Connect** otra vez |

Si nada de esto encaja, anota la hora aproximada y el mensaje exacto: con eso se busca en los logs
del servicio (`/aws/ecs/default/shurly-api-5fdb`).

---

## Referencias

- Detalle técnico del MCP: [`mcp_server/README.md`](../mcp_server/README.md)
- La misma guía, para el equipo, dentro de la app: `/manual/install-mcp/` (cuando la web esté publicada)
- Configuración del cliente de Google: [`docs/setup_google_app.md`](setup_google_app.md)
