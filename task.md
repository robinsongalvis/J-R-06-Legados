# Tareas de Auditoría de Seguridad (Legados Angels)

- [x] **P1 - Eliminar defaults inseguros (`main.py`)**
  - [x] Forzar error de arranque en producción si `SECRET_KEY` falta.
  - [x] Forzar error de arranque en producción si `ADMIN_PASSWORD_HASH` falta.
  - [x] Añadir flag `ALLOW_INSECURE_DEV_AUTH` explícito para entornos de desarrollo.

- [x] **P2 - Corregir XSS en `perfil.html`**
  - [x] Reemplazar interpolación de variable en JS por `{{ cancion_favorita | tojson }}`.
  - [x] Usar APIs del DOM (`document.createElement`) en lugar de `innerHTML` para el fallback de texto y la construcción del iframe/enlace.
  - [x] Validar estrictamente la URL verificando que el hostname sea exclusivamente `youtube.com`, `www.youtube.com`, `m.youtube.com` o `youtu.be`.

- [x] **P3 - Corregir XSS/contextos peligrosos en `admin.html`**
  - [x] Corregir la función utilitaria `escapeHtml` para escapar comillas simples (`&#039;`) y dobles (`&quot;`).
  - [x] Eliminar construcciones `onclick="funcion('${variable}')"` vulnerables a inyección de comillas.
  - [x] Refactorizar la delegación de eventos usando `this.getAttribute('data-*')` y escapado seguro de HTML a nivel de atributo (`data-nombre="${escapeHtml(perfil.nombre)}"`).

- [x] **P4 - Verificación real de autorización**
  - [x] Todos los endpoints CRUD de familia están protegidos por `validar_pin_o_admin()`.
  - [x] Los endpoints de administración validan el Dependency `verificar_admin`.

- [x] **P5 - Revisar autenticación admin**
  - [x] Sincronizar parámetros de seguridad de cookies en el endpoint de logout (`httponly`, `samesite`, `secure`).

- [x] **P6 - Entregables**
  - [x] Generar `task.md` con checklist de tareas.
  - [x] Generar `walkthrough.md` con resumen del trabajo realizado.
