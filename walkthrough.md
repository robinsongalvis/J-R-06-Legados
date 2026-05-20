# Auditoría y Correcciones de Seguridad - Legados Angels

He finalizado la auditoría estricta de seguridad y aplicado las correcciones definitivas sobre el código fuente del proyecto (`J-R-06-Legados`), solucionando fallas críticas que se habían pasado por alto.

## Cambios Realizados

### 1. Eliminación de Defaults Inseguros (`main.py`)
El sistema anteriormente definía contraseñas y secretos por defecto (ej. `admin123`) si las variables de entorno no estaban configuradas, lo cual es altamente peligroso en producción.
*   **Corrección:** Se implementó una política estricta de arranque (Fail-Safe). Ahora, si `SECRET_KEY` o `ADMIN_PASSWORD_HASH` están ausentes, la aplicación lanza una excepción `ValueError` y **se niega a iniciar**.
*   **Modo de Desarrollo:** Se añadió una bandera explícita `ALLOW_INSECURE_DEV_AUTH=true`. Solo si esta variable de entorno se provee, la aplicación permitirá usar las contraseñas de desarrollo para pruebas locales, evitando errores accidentales en despliegues como Render.

### 2. Remediación de XSS (Cross-Site Scripting) en Perfiles (`perfil.html`)
Se identificó una vulnerabilidad crítica de XSS en la forma en que se manejaba la variable `cancion_favorita`.
*   **Ataque Previo:** La inyección era posible a través de la interpolación directa en JavaScript: `const CANCION_RAW = "{{ cancion_favorita }}";` y el uso posterior de `innerHTML`. Si el usuario ingresaba comillas o etiquetas HTML, estas se ejecutaban.
*   **Corrección (Contexto de Script):** Se migró a la serialización segura de Jinja2 `{{ cancion_favorita | tojson }}`, que garantiza que cualquier entrada sea tratada como un string válido en JavaScript, codificando las comillas automáticamente.
*   **Corrección (Contexto HTML):** Se reemplazó el uso de `innerHTML` por APIs seguras del DOM (`document.createElement()`, `appendChild()`, `textContent`). Adicionalmente, el enlace externo que se genera cuando falla la expresión regular ahora es validado estrictamente verificando que el host pertenezca exclusivamente a YouTube (`youtube.com`, `www.youtube.com`, `m.youtube.com`, `youtu.be`).

### 3. Remediación de XSS en Panel de Administración (`admin.html`)
El panel de control generaba código HTML con eventos `onclick` dinámicos (ej. `onclick="eliminar('${nombre}')"`). Aunque se usaba una función `escapeHtml()`, esta no escapaba las comillas simples, permitiendo romper el string en JavaScript y ejecutar código arbitrario al inyectar un nombre como `O'Brian`.
*   **Fortalecimiento de Utilidad:** Se mejoró la función `escapeHtml()` para que escape rigurosamente comillas simples (`&#039;`) y dobles (`&quot;`).
*   **Refactorización de Eventos:** Se eliminó la inyección directa de argumentos en JavaScript. Ahora los botones almacenan los datos sensibles de forma segura usando atributos HTML `data-*` (ej. `data-nombre`). El evento `onclick` se modificó para leer el propio atributo (ej. `onclick="eliminar(this.getAttribute('data-nombre'))"`). De esta manera, el navegador procesa la cadena de forma segura y el motor JavaScript solo recibe un string literal sin evaluarlo como código.

### 4. Seguridad de Sesión Mejorada
*   **Limpieza de Cookies:** El endpoint `POST /api/admin/logout` se actualizó para incluir exactamente los mismos flags de seguridad (`httponly=True`, `samesite="lax"`, `secure=...`) al momento de invalidar la cookie `admin_session`. Anteriormente solo se llamaba a `delete_cookie("admin_session")`, lo cual podía fallar en borrar la cookie si el flag de `Secure` o dominio difería, dejando la sesión abierta.

### 5. Validación de Autorización Confirmada
Se revisaron manualmente los roles de los endpoints. La estrategia de defensa en profundidad está implementada correctamente:
*   Todos los endpoints de administración están protegidos por el dependency `verificar_admin`.
*   Todos los endpoints mutables referentes a la familia (`subir_fotos`, `cambiar_foto_perfil`, etc.) validan que exista un PIN válido o que sea un administrador a través de `validar_pin_o_admin()`.

## Estado Actual
El código base ahora es resistente a ataques de Cross-Site Scripting (XSS) y fallas de configuración (Insecure Defaults), cumpliendo con los estándares de seguridad web modernos. La estrategia de "falla segura" protegerá la aplicación al momento del despliegue en la nube.
