# Avisos a la familia

Cuando alguien deja un recuerdo, enciende una vela o comenta una foto, la familia
recibe un aviso. Sin esto, un mensaje hermoso puede quedarse meses sin que nadie
de la familia se entere.

Todo es **opcional**: si no configuras nada, el sitio funciona igual que siempre
y simplemente no se envían avisos.

---

## 1. Guardar el contacto de cada familia

En el panel de administración, en cada memorial → botón **Gestión** → escribe el
teléfono y/o el correo del responsable de la familia.

Estos datos **nunca aparecen en la página pública** del memorial: solo se ven
desde el panel con sesión de administrador.

---

## 2. Activar el correo

En Render → tu servicio → **Environment**, agrega:

| Variable | Ejemplo | Obligatoria |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | sí |
| `SMTP_USER` | `avisos@tudominio.com` | sí |
| `SMTP_PASSWORD` | *(contraseña de aplicación)* | sí |
| `SMTP_PORT` | `587` | no (587 por defecto) |
| `SMTP_FROM` | `avisos@tudominio.com` | no (usa `SMTP_USER`) |
| `SMTP_FROM_NAME` | `Legados Angels` | no |

**Con Gmail no sirve tu contraseña normal.** Hay que activar la verificación en
dos pasos y generar una *contraseña de aplicación* de 16 caracteres en
https://myaccount.google.com/apppasswords, y usar esa.

Si tu proveedor usa el puerto 465 (SSL directo), pon `SMTP_PORT=465`; el código
lo detecta y cambia de modo solo.

---

## 3. Activar WhatsApp (opcional)

Usa la **API de la nube de Meta**. Requiere una cuenta de WhatsApp Business y
que Meta apruebe una plantilla de mensaje antes de poder escribir primero.

| Variable | Qué es |
|---|---|
| `WHATSAPP_TOKEN` | Token de acceso permanente de la app de Meta |
| `WHATSAPP_PHONE_ID` | ID del número emisor (no el número: el ID) |
| `WHATSAPP_TEMPLATE` | Nombre de la plantilla aprobada |
| `WHATSAPP_TEMPLATE_LANG` | Código de idioma, `es` por defecto |

La plantilla debe tener **cuatro variables**, en este orden:

```
{{1}} quién dejó el recuerdo
{{2}} nombre de la persona recordada
{{3}} el texto del recuerdo
{{4}} enlace al memorial
```

Ejemplo de cuerpo para enviar a aprobación:

> {{1}} dejó un recuerdo para {{2}}:
> "{{3}}"
> Puedes verlo aquí: {{4}}

Los teléfonos se normalizan solos: `320 357 4674`, `+57 320-3574674` y
`(320) 3574674` terminan todos como `573203574674`. Si el número no es
colombiano, escríbelo con su indicativo.

---

## 4. Otras variables

| Variable | Para qué | Por defecto |
|---|---|---|
| `URL_PUBLICA` | Dominio que va en los enlaces del aviso | `https://j-r-legados.onrender.com` |
| `MINUTOS_ENTRE_AVISOS` | Espera mínima entre avisos del mismo memorial | `180` (3 horas) |

**Sobre la espera:** el día de un funeral un memorial puede recibir decenas de
mensajes. Sin este freno la familia recibiría decenas de avisos en una tarde, y
un gesto de cariño se volvería una molestia. Con el valor por defecto reciben
como mucho un aviso cada 3 horas.

---

## 5. Comprobar que funciona

En el panel → **Gestión** de cualquier memorial que tenga contacto guardado →
botón **Enviar prueba**.

- Si sale bien, dice por dónde se envió.
- Si falla, dice exactamente qué canal falló para que revises las credenciales.

Debajo del botón se indica siempre qué canales están activos en el servidor.

---

## Cómo se comporta ante fallos

Un aviso **nunca** puede afectar al memorial:

- Se envía **después** de responderle al visitante, así que la página no se
  queda esperando al servidor de correo.
- Si el envío falla, queda registrado en los logs de Render y ya: el recuerdo se
  guardó igual y el visitante no ve ningún error.
- Si no hay credenciales configuradas, la función sale de inmediato sin hacer nada.
