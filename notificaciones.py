"""Avisos a la familia cuando alguien deja un recuerdo en el memorial.

Antes, si un visitante escribía "Papá, hoy cumplí lo que te prometí", nadie se
enteraba: el mensaje quedaba esperando a que alguien de la familia entrara a
mirar por casualidad. Este módulo cierra ese silencio.

Dos reglas que atraviesan todo el archivo:

1. **Un aviso nunca puede tumbar el memorial.** Si el correo falla, si WhatsApp
   no responde, si no hay credenciales configuradas: el recuerdo se guarda igual
   y el visitante no se entera de nada. Por eso todo va envuelto y se ejecuta
   después de responder.

2. **No se atosiga a una familia en duelo.** Si un memorial recibe veinte
   mensajes en una tarde (pasa el día del funeral, o en un aniversario), no
   mandamos veinte correos. Hay una espera mínima entre avisos por memorial.

Ambos canales son opcionales y se activan solos cuando existen sus variables de
entorno. Sin configurar, el sitio funciona exactamente como hoy.
"""

import os
import ssl
import html
import logging
import smtplib
import datetime
from email.message import EmailMessage

import httpx

# print() se queda en el buffer cuando la salida no es una terminal, y en
# Render eso significa avisos que fallan en silencio. logging sí se entrega.
log = logging.getLogger("legados.avisos")

# ==========================================
# CONFIGURACIÓN (todo por variables de entorno)
# ==========================================

# --- Correo (SMTP: sirve Gmail, Zoho, Hostinger, el que sea) ---
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PUERTO = int(os.getenv("SMTP_PORT", "587"))
SMTP_USUARIO = os.getenv("SMTP_USER", "")
SMTP_CLAVE = os.getenv("SMTP_PASSWORD", "")
SMTP_REMITENTE = os.getenv("SMTP_FROM", SMTP_USUARIO)
SMTP_NOMBRE_REMITENTE = os.getenv("SMTP_FROM_NAME", "Legados Angels")

# --- WhatsApp (API de la nube de Meta) ---
WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WA_ID_TELEFONO = os.getenv("WHATSAPP_PHONE_ID", "")
WA_PLANTILLA = os.getenv("WHATSAPP_TEMPLATE", "")
WA_IDIOMA_PLANTILLA = os.getenv("WHATSAPP_TEMPLATE_LANG", "es")

# Espera mínima entre avisos del MISMO memorial, en minutos.
ESPERA_ENTRE_AVISOS = int(os.getenv("MINUTOS_ENTRE_AVISOS", "180"))

# URL pública del sitio, para armar el enlace del memorial.
URL_BASE = os.getenv("URL_PUBLICA", "https://j-r-legados.onrender.com").rstrip("/")


def correo_configurado() -> bool:
    return bool(SMTP_HOST and SMTP_USUARIO and SMTP_CLAVE)


def whatsapp_configurado() -> bool:
    return bool(WA_TOKEN and WA_ID_TELEFONO and WA_PLANTILLA)


# ==========================================
# CANAL 1: CORREO
# ==========================================

def _cuerpo_correo(nombre_difunto: str, tipo: str, autor: str, texto: str, enlace: str) -> str:
    """Arma el HTML del correo. Sobrio y oscuro, como el memorial."""
    autor_seguro = html.escape(autor or "Alguien")
    texto_seguro = html.escape(texto or "")
    nombre_seguro = html.escape(nombre_difunto)

    return f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:0;background:#0a0f18;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0f18;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#16202f;border:1px solid rgba(255,255,255,0.08);border-radius:18px;overflow:hidden;">
        <tr><td style="padding:28px 28px 8px;">
          <p style="margin:0;color:#d4af37;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;">Legados Angels</p>
          <h1 style="margin:12px 0 0;color:#f1f5f9;font-size:21px;line-height:1.3;font-weight:600;">
            {autor_seguro} dejó {tipo} para {nombre_seguro}
          </h1>
        </td></tr>
        <tr><td style="padding:20px 28px;">
          <div style="background:rgba(255,255,255,0.04);border-left:3px solid #d4af37;border-radius:10px;padding:18px 20px;">
            <p style="margin:0;color:#e2e8f0;font-size:16px;line-height:1.65;font-style:italic;">"{texto_seguro}"</p>
          </div>
        </td></tr>
        <tr><td style="padding:8px 28px 30px;">
          <a href="{enlace}" style="display:inline-block;background:linear-gradient(135deg,#e3c15a,#b8952c);color:#14100a;text-decoration:none;font-weight:700;font-size:15px;padding:13px 26px;border-radius:12px;">
            Ver el memorial
          </a>
        </td></tr>
        <tr><td style="padding:18px 28px;border-top:1px solid rgba(255,255,255,0.07);">
          <p style="margin:0;color:#8fa0b3;font-size:12px;line-height:1.6;">
            Recibes este aviso porque tu familia administra este memorial.
            Para dejar de recibirlos, responde a este correo.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def enviar_correo(destinatario: str, asunto: str, cuerpo_html: str, texto_plano: str) -> bool:
    """Envía un correo. Devuelve True si salió; nunca lanza excepción."""
    if not correo_configurado() or not destinatario:
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = f"{SMTP_NOMBRE_REMITENTE} <{SMTP_REMITENTE}>"
        msg["To"] = destinatario
        msg.set_content(texto_plano)
        msg.add_alternative(cuerpo_html, subtype="html")

        contexto = ssl.create_default_context()
        if SMTP_PUERTO == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PUERTO, context=contexto, timeout=15) as s:
                s.login(SMTP_USUARIO, SMTP_CLAVE)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PUERTO, timeout=15) as s:
                s.starttls(context=contexto)
                s.login(SMTP_USUARIO, SMTP_CLAVE)
                s.send_message(msg)
        return True
    except Exception as e:
        log.warning("No se pudo enviar el correo a %s: %s", destinatario, e)
        return False


# ==========================================
# CANAL 2: WHATSAPP
# ==========================================

def normalizar_telefono(numero: str) -> str:
    """Deja solo dígitos y antepone 57 (Colombia) si viene sin indicativo.

    Las familias escriben el teléfono como les sale: '320 357 4674',
    '+57 320-3574674', '(320) 3574674'. Meta lo exige en dígitos corridos.
    """
    if not numero:
        return ""
    digitos = "".join(c for c in str(numero) if c.isdigit())
    if not digitos:
        return ""
    # 10 dígitos que arrancan en 3 = celular colombiano sin indicativo
    if len(digitos) == 10 and digitos.startswith("3"):
        return "57" + digitos
    return digitos


def enviar_whatsapp(telefono: str, parametros: list) -> bool:
    """Manda una plantilla aprobada por WhatsApp. Devuelve True si salió.

    Meta solo permite escribir primero con plantillas aprobadas de antemano; no
    se puede mandar texto libre a alguien que no te escribió en las últimas 24h.
    Por eso van parámetros y no un mensaje armado aquí.
    """
    destino = normalizar_telefono(telefono)
    if not whatsapp_configurado() or not destino:
        return False

    try:
        respuesta = httpx.post(
            f"https://graph.facebook.com/v21.0/{WA_ID_TELEFONO}/messages",
            headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "to": destino,
                "type": "template",
                "template": {
                    "name": WA_PLANTILLA,
                    "language": {"code": WA_IDIOMA_PLANTILLA},
                    "components": [{
                        "type": "body",
                        "parameters": [{"type": "text", "text": str(p)[:200]} for p in parametros],
                    }],
                },
            },
            timeout=15,
        )
        if respuesta.status_code >= 400:
            log.warning("WhatsApp respondió %s: %s", respuesta.status_code, respuesta.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("No se pudo enviar el WhatsApp a %s: %s", destino, e)
        return False


# ==========================================
# ORQUESTADOR
# ==========================================

ETIQUETAS = {
    "mensaje": ("un recuerdo", "Nuevo recuerdo en el memorial de"),
    "vela": ("una vela", "Encendieron una vela por"),
    "comentario": ("un comentario en una foto", "Nuevo comentario en el memorial de"),
}


def _toca_avisar(perfil) -> bool:
    """Evita la avalancha: un aviso por memorial cada ESPERA_ENTRE_AVISOS minutos.

    El día del funeral un memorial puede recibir decenas de mensajes. Avisar de
    cada uno convertiría un gesto de cariño en una molestia.
    """
    ultimo = getattr(perfil, "ultimo_aviso", None)
    if not ultimo:
        return True
    transcurrido = datetime.datetime.utcnow() - ultimo
    return transcurrido.total_seconds() >= ESPERA_ENTRE_AVISOS * 60


def avisar_nuevo_recuerdo(perfil_id: int, tipo: str, autor: str, texto: str):
    """Avisa a la familia por los canales que estén configurados.

    Recibe el ID y abre su propia sesión de base de datos porque corre DESPUÉS de
    haber respondido al visitante: para entonces la sesión del request ya se cerró.
    """
    if not (correo_configurado() or whatsapp_configurado()):
        return

    import database

    db = database.SessionLocal()
    try:
        perfil = db.query(database.PerfilDifunto).filter(
            database.PerfilDifunto.id == perfil_id
        ).first()
        if not perfil:
            return

        destinatario_correo = (perfil.contacto_email or "").strip()
        destinatario_wa = (perfil.contacto_telefono or "").strip()
        if not destinatario_correo and not destinatario_wa:
            return  # La familia no dejó forma de contacto

        if not _toca_avisar(perfil):
            return

        que_dejo, encabezado = ETIQUETAS.get(tipo, ETIQUETAS["mensaje"])
        autor = (autor or "Alguien").strip()[:60]
        texto = (texto or "").strip()[:200]
        enlace = f"{URL_BASE}/perfil/{perfil.identificador}"
        asunto = f"{encabezado} {perfil.nombre}"

        enviado = False

        if destinatario_correo:
            texto_plano = (
                f"{autor} dejó {que_dejo} para {perfil.nombre}.\n\n"
                f'"{texto}"\n\n'
                f"Ver el memorial: {enlace}"
            )
            cuerpo = _cuerpo_correo(perfil.nombre, que_dejo, autor, texto, enlace)
            enviado = enviar_correo(destinatario_correo, asunto, cuerpo, texto_plano) or enviado

        if destinatario_wa:
            # Orden de los parámetros de la plantilla: {{1}} autor, {{2}} difunto,
            # {{3}} el texto del recuerdo, {{4}} el enlace.
            enviado = enviar_whatsapp(destinatario_wa, [autor, perfil.nombre, texto, enlace]) or enviado

        if enviado:
            perfil.ultimo_aviso = datetime.datetime.utcnow()
            db.commit()

    except Exception as e:
        log.exception("Falló el aviso del perfil %s: %s", perfil_id, e)
    finally:
        db.close()
