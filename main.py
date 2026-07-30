from fastapi import FastAPI, Request, Depends, HTTPException, File, UploadFile, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import io # <-- LA PIEZA CLAVE PARA QUE CLOUDINARY ACEPTE LOS ARCHIVOS
from sqlalchemy.orm import Session, selectinload
from pydantic import BaseModel
import datetime
import os
import socket
from typing import List
import re
import hashlib
import hmac
import json
import base64
import time
from collections import defaultdict
import httpx

# ==========================================
# HORA DE COLOMBIA
# ==========================================
# En la base todo se guarda en UTC, que es lo correcto: una fecha sin zona no
# significa nada cuando el servidor vive en otro continente. Pero la familia lee
# el memorial desde Colombia, así que el día hay que traducirlo al mostrarlo.
#
# Sin esto, un mensaje escrito a las 8 de la noche del 14 de febrero se guardaba
# como 01:00 UTC del 15 y se mostraba con la fecha del día siguiente. Cinco de
# cada veinticuatro horas caían en el día equivocado, y justo en la franja de la
# noche, que es cuando más se visita un memorial.
#
# Offset fijo en vez de zoneinfo a propósito: Colombia no tiene horario de verano
# desde 1993, así que -05:00 vale todo el año, y así no dependemos de que la
# imagen del servidor traiga la base de datos de zonas horarias instalada.
ZONA_COLOMBIA = datetime.timezone(datetime.timedelta(hours=-5))

def a_hora_colombia(fecha):
    """Convierte un datetime UTC sin zona (los que guarda la base) a hora local."""
    if fecha is None:
        return None
    return fecha.replace(tzinfo=datetime.timezone.utc).astimezone(ZONA_COLOMBIA)

def ahora_colombia():
    """El instante actual en Colombia. Úsalo para saber en qué día estamos."""
    return datetime.datetime.now(ZONA_COLOMBIA)

def fecha_colombia_str(fecha, formato="%d/%m/%Y", vacio=""):
    """Formatea una fecha guardada en UTC con el día que le corresponde acá."""
    local = a_hora_colombia(fecha)
    return local.strftime(formato) if local else vacio

def parse_date_for_sorting(date_str):
    if not date_str: return (9999, 12, 31)
    date_str = str(date_str).lower()
    match_year = re.search(r'\b(18|19|20)\d{2}\b', date_str)
    year = int(match_year.group()) if match_year else 9999
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    month = 12
    for i, m in enumerate(meses):
        if m in date_str:
            month = i + 1
            break
    match_day = re.search(r'\b([1-9]|[12]\d|3[01])\b', date_str)
    day = int(match_day.group()) if match_day else 31
    return (year, month, day)

# ==========================================
# EFEMÉRIDES: "UN DÍA COMO HOY, HACE X AÑOS"
# ==========================================
MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

def _dia_valido(anio, mes, dia):
    try:
        datetime.date(anio, mes, dia)
        return True
    except ValueError:
        return False

def partes_fecha_momento(texto):
    """Saca (año, mes, día) del campo libre de un momento. mes y día pueden ser None.

    Devolver None cuando no se sabe es TODA la gracia de esta función.
    parse_date_for_sorting rellena con mes 12 y día 31 cuando no encuentra nada,
    que sirve para ordenar pero es veneno para una efeméride: publicaría
    aniversarios inventados cada 31 de diciembre. Y su regex de día agarra
    cualquier número de dos cifras, así que "Cumplió 15 años en 1985" le saldría
    como día 15.

    Regla firme: nunca se devuelve un día sin mes. Un día suelto no identifica
    ninguna fecha, y el campo lo llena el dueño a mano escribiendo frases.
    """
    if not texto:
        return (None, None, None)
    t = str(texto).strip().lower()

    # El año va aparte: puede estar en cualquier parte de la frase.
    m_anio = re.search(r'\b(?:18|19|20)\d{2}\b', t)
    anio = int(m_anio.group()) if m_anio else None

    # 15/08/1972 · 15-8-1972 (día primero, como se escribe en Colombia)
    m = re.search(r'\b(\d{1,2})[/\-.](\d{1,2})[/\-.](?:18|19|20)(\d{2})\b', t)
    if m and _dia_valido(anio or 2000, int(m.group(2)), int(m.group(1))):
        return (anio, int(m.group(2)), int(m.group(1)))

    # 1972-08-15 (ISO)
    m = re.search(r'\b(?:18|19|20)\d{2}[/\-.](\d{1,2})[/\-.](\d{1,2})\b', t)
    if m and _dia_valido(anio or 2000, int(m.group(1)), int(m.group(2))):
        return (anio, int(m.group(1)), int(m.group(2)))

    nombres = "|".join(MESES_ES)

    # "15 de agosto" · "15 agosto"
    m = re.search(rf'\b(\d{{1,2}})\s+(?:de\s+)?({nombres})\b', t)
    if m and _dia_valido(anio or 2000, MESES_ES[m.group(2)], int(m.group(1))):
        return (anio, MESES_ES[m.group(2)], int(m.group(1)))

    # "agosto de 1972" · "en agosto": mes sí, día no
    m = re.search(rf'\b({nombres})\b', t)
    if m:
        return (anio, MESES_ES[m.group(1)], None)

    return (anio, None, None)

def efemeride_del_dia(momentos, hoy):
    """Elige el momento cuyo aniversario cae hoy, o None si no hay ninguno.

    Tres niveles de precisión, y se prefiere siempre el más exacto:
      dia  -> el texto trae día y mes, y coinciden con hoy
      mes  -> trae el mes, y es el mes en curso
      anio -> todo lo demás: se cumplen años este año, aunque el día ya pasó o
              está por venir. Rota uno por día para no repetir lo mismo siempre.

    El último nivel es un cajón de sastre A PROPÓSITO. Antes solo recibía los
    momentos SIN mes, y eso dejaba fuera a los que tenían fecha completa de otro
    mes: en un memorial con tres momentos bien fechados el bloque salía 91 días
    al año y los otros 274 no aparecía nada, cuando bien podía decir "este año se
    cumplen 61 años de su nacimiento". Un aniversario no deja de serlo porque
    hoy no sea el día.

    `momentos` son los diccionarios que ya arma la vista, con 'anio' como texto.
    """
    exactos, del_mes, del_anio = [], [], []

    for mo in momentos:
        anio, mes, dia = partes_fecha_momento(mo.get("anio"))
        if not anio:
            continue
        cumple = hoy.year - anio
        if cumple < 1:  # todavía no hay aniversario que celebrar
            continue
        candidato = {**mo, "hace_anios": cumple}
        if mes and dia and (mes, dia) == (hoy.month, hoy.day):
            exactos.append(candidato)
        elif mes and mes == hoy.month:
            del_mes.append(candidato)
        else:
            del_anio.append(candidato)

    if exactos:
        return {**max(exactos, key=lambda c: c["hace_anios"]), "precision": "dia"}
    if del_mes:
        return {**max(del_mes, key=lambda c: c["hace_anios"]), "precision": "mes"}
    if del_anio:
        # Rotación por día, igual que el recuerdo de hoy: sin esto el bloque
        # diría lo mismo todo el año y se vuelve parte del decorado.
        elegido = del_anio[hoy.toordinal() % len(del_anio)]
        return {**elegido, "precision": "anio"}
    return None

def obtener_icono_momento(titulo):
    t = str(titulo).lower()
    if any(x in t for x in ["nace", "nacimiento", "bebe", "hijo", "hija", "nieto", "nieta"]): return "fa-baby"
    if any(x in t for x in ["boda", "matrimonio", "esposo", "esposa", "casaron"]): return "fa-ring"
    if any(x in t for x in ["viaje", "conoció", "viajó", "paseo", "vacaciones"]): return "fa-plane"
    if any(x in t for x in ["grado", "graduacion", "estudio", "universidad", "colegio"]): return "fa-graduation-cap"
    if any(x in t for x in ["trabajo", "empresa", "negocio", "fundo"]): return "fa-briefcase"
    if any(x in t for x in ["fallece", "adios", "muerte", "partida", "cielo"]): return "fa-dove"
    return "fa-star"

import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps
from dotenv import load_dotenv

load_dotenv() 

API_KEY_GEMINI = os.getenv("GEMINI_API_KEY")

cloudinary.config( 
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"), 
  api_key = os.getenv("CLOUDINARY_API_KEY"), 
  api_secret = os.getenv("CLOUDINARY_API_SECRET"),
  secure = True
)

import database

app = FastAPI(title="Memorial Digital QR")

# ==========================================
# 🛡️ SEGURIDAD: AUTENTICACIÓN Y PROTECCIÓN
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")
ALLOW_INSECURE_DEV_AUTH = os.getenv("ALLOW_INSECURE_DEV_AUTH", "false").lower() == "true"
# IMPORTANTE: ALLOW_INSECURE_DEV_AUTH=true JAMAS debe usarse en Render o en cualquier entorno de Produccion.
# Es exclusivamente para pruebas locales donde no se disponga de variables de entorno configuradas.

if not SECRET_KEY:
    if ALLOW_INSECURE_DEV_AUTH:
        SECRET_KEY = "dev-inseguro-cambiar-en-produccion"
    else:
        raise ValueError("FATAL ERROR: SECRET_KEY env var missing. Refusing to start.")

if not ADMIN_PASSWORD_HASH:
    if ALLOW_INSECURE_DEV_AUTH:
        ADMIN_PASSWORD_HASH = hashlib.sha256("admin123".encode()).hexdigest()
    else:
        raise ValueError("FATAL ERROR: ADMIN_PASSWORD_HASH env var missing. Refusing to start.")

def _firmar_cookie(data: dict) -> str:
    """Crea una cookie firmada con HMAC-SHA256"""
    data["t"] = int(time.time())
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"

def _verificar_cookie(cookie_val: str, max_age: int = 86400):
    """Verifica una cookie firmada. Retorna dict o None."""
    try:
        payload, sig = cookie_val.rsplit(".", 1)
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload))
        if time.time() - data.get("t", 0) > max_age:
            return None
        return data
    except Exception:
        return None

def verificar_admin(request: Request):
    """Dependency: Verifica que el request venga de un admin autenticado via cookie."""
    cookie = request.cookies.get("admin_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="No autorizado")
    data = _verificar_cookie(cookie)
    if not data or data.get("role") != "admin":
        raise HTTPException(status_code=401, detail="Sesión expirada o inválida")
    return True

def _es_admin(request: Request) -> bool:
    """Verifica si el request viene de un admin, sin lanzar excepción."""
    cookie = request.cookies.get("admin_session")
    if not cookie:
        return False
    data = _verificar_cookie(cookie)
    return data is not None and data.get("role") == "admin"

def validar_pin_o_admin(request: Request, perfil):
    """Permite acceso si es admin autenticado O si tiene el PIN familiar correcto."""
    if _es_admin(request):
        return  # Admin autenticado, acceso permitido
    pin = request.headers.get("x-family-pin", "")
    if not pin or not hmac.compare_digest(str(pin), str(perfil.pin_familia)):
        raise HTTPException(status_code=403, detail="PIN familiar requerido o incorrecto")


def exigir_pin_o_admin(request: Request, perfil):
    """Igual que validar_pin_o_admin, pero para elementos sueltos (una foto, un
    mensaje) a los que se llega por su id numérico.

    Antes se escribía `if foto.perfil: validar_pin_o_admin(...)`, así que un
    elemento sin perfil asociado se podía borrar SIN ninguna credencial. Aquí la
    ausencia de perfil deniega en vez de permitir: solo el admin puede tocar
    huérfanos.
    """
    if _es_admin(request):
        return
    if perfil is None:
        raise HTTPException(status_code=403, detail="Elemento sin memorial asociado: solo el administrador puede modificarlo.")
    validar_pin_o_admin(request, perfil)

# ==========================================
# ⏱️ RATE LIMITER IN-MEMORY (MVP)
# Para producción multi-instancia usar Redis.
# ==========================================
_rate_store = defaultdict(list)

def _ip_cliente(request: Request) -> str:
    """IP real del visitante. Render entrega la original en X-Forwarded-For;
    sin esto todas las peticiones parecerían venir del proxy y compartirían cupo."""
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_check(request: Request, endpoint: str, max_calls: int = 10, window: int = 60):
    """Limita las llamadas por IP a un endpoint específico."""
    key = f"{_ip_cliente(request)}:{endpoint}"
    now = time.time()
    _rate_store[key] = [t for t in _rate_store[key] if now - t < window]
    if len(_rate_store[key]) >= max_calls:
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta más tarde.")
    _rate_store[key].append(now)


# ==========================================
# 🔒 FRENO A LA FUERZA BRUTA (PIN Y ADMIN)
#
# El PIN familiar son 4 dígitos: 10.000 combinaciones. Sin freno, un script las
# prueba todas en minutos y entra a editar o borrar el memorial. Aquí contamos
# los INTENTOS FALLIDOS y bloqueamos temporalmente; los aciertos no gastan cupo.
# El contador es por proceso y se reinicia al desplegar (limitación conocida del
# almacenamiento en memoria), pero convierte un ataque de minutos en uno de días.
# ==========================================
_intentos_fallidos = defaultdict(list)
MAX_INTENTOS = 6
VENTANA_BLOQUEO = 900  # 15 minutos


def _clave_intentos(request: Request, alcance: str) -> str:
    return f"{_ip_cliente(request)}:{alcance}"


def verificar_bloqueo(request: Request, alcance: str):
    """Corta el paso si esta IP ya falló demasiadas veces. Llamar ANTES de comparar."""
    clave = _clave_intentos(request, alcance)
    ahora = time.time()
    _intentos_fallidos[clave] = [t for t in _intentos_fallidos[clave] if ahora - t < VENTANA_BLOQUEO]
    if len(_intentos_fallidos[clave]) >= MAX_INTENTOS:
        espera = int((VENTANA_BLOQUEO - (ahora - _intentos_fallidos[clave][0])) / 60) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Vuelve a intentarlo en {espera} minutos."
        )


def registrar_fallo(request: Request, alcance: str):
    """Anota un intento fallido para esta IP."""
    _intentos_fallidos[_clave_intentos(request, alcance)].append(time.time())


def limpiar_intentos(request: Request, alcance: str):
    """Borra el historial tras un acceso correcto."""
    _intentos_fallidos.pop(_clave_intentos(request, alcance), None)


os.makedirs("static", exist_ok=True) 
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


def miniatura(url: str, ancho: int = 400) -> str:
    """Devuelve una versión ligera de la imagen para las cuadrículas.

    En Cloudinary inserta transformaciones (formato y calidad automáticos + recorte),
    lo que baja una foto de ~2MB a ~30KB. Con 50 fotos eso es la diferencia entre
    un scroll fluido y uno que se traba en el celular. URLs de otros orígenes se
    devuelven intactas.
    """
    if not url or "/upload/" not in url or "res.cloudinary.com" not in url:
        return url
    return url.replace("/upload/", f"/upload/f_auto,q_auto,w_{ancho},c_fill,g_auto/", 1)


def liviano(url: str, ancho: int = 720) -> str:
    """Sirve una portada o un retrato al tamaño en que se va a ver, no al que se subió.

    Vale para imagen y para video, y en video es donde cambia todo: las portadas y
    los retratos se suben desde el celular sin comprimir, y se estaban sirviendo
    crudos. Medido en el memorial de referencia, con los dos videos que llevan
    autoplay y por lo tanto se descargan solos al abrir:

        portada  16.58 MB -> 1.06 MB   (f_auto,q_auto,w_720)
        retrato   7.75 MB -> 0.60 MB   (f_auto,q_auto,w_320)

    Son 23.5 MB que bajaban antes de que se viera nada. En 3G eso es más de ocho
    minutos mirando una pantalla vacía, de pie frente a una lápida. No se cambia
    el contenido que eligió la familia: el video sigue siendo video, transcodificado.

    A diferencia de miniatura(), no recorta (sin c_fill): la portada y el retrato
    tienen su propio encuadre y recortarlos les cambiaría la composición.
    """
    if not url or "/upload/" not in url or "res.cloudinary.com" not in url:
        return url
    liviana = url.replace("/upload/", f"/upload/f_auto,q_auto,w_{ancho}/", 1)
    # A los .mov hay que pedirles un contenedor que el navegador sepa reproducir;
    # f_auto entrega mp4 o webm según quien pida, pero la extensión debe cambiar.
    if liviana.lower().endswith((".mov", ".m4v")):
        liviana = liviana[:liviana.rfind(".")] + ".mp4"
    return liviana

def audio_web(url: str) -> str:
    """Sirve la nota de voz como audio y no como video.

    Se graba desde el celular y Cloudinary la guarda con extensión de video (.mov,
    .mp4): es un contenedor de video cargando solo audio. Medido en el memorial de
    referencia: 0.51 MB en .mov contra 0.05 MB en mp3, un 89% menos.

    No parece mucho al lado de las portadas, pero es la voz de él: en 3G son diez
    segundos de espera antes de oírlo, contra uno.
    """
    url = str(url or "").strip()
    if not url or "res.cloudinary.com" not in url or "/upload/" not in url:
        return url
    convertida = url.replace("/upload/", "/upload/f_mp3,q_auto/", 1)
    punto = convertida.rfind(".")
    barra = convertida.rfind("/")
    if punto > barra:                     # tiene extensión: se cambia
        convertida = convertida[:punto]
    return convertida + ".mp3"

templates.env.filters["miniatura"] = miniatura
templates.env.filters["liviano"] = liviano
templates.env.filters["audio_web"] = audio_web


# ==========================================
# VISTA PREVIA DEL ENLACE (WhatsApp y redes)
# ==========================================
# 1200x630 es la medida que esperan WhatsApp, Facebook y compañía.
# f_jpg y no f_auto a propósito: f_auto negocia el formato con quien pide (WebP,
# AVIF), y los robots que arman la vista previa no siempre saben leerlos. Un JPG
# lo entiende todo el mundo. g_auto centra en las caras, que es lo que importa acá.
OG_ANCHO, OG_ALTO = 1200, 630
_OG_TRANSFORMACION = f"f_jpg,q_auto,w_{OG_ANCHO},h_{OG_ALTO},c_fill,g_auto"

def _es_video(url) -> bool:
    return str(url or "").lower().endswith((".mp4", ".mov", ".webm", ".m4v"))

def imagen_compartible(url) -> str:
    """Convierte una URL de Cloudinary en una imagen apta para la vista previa.

    Si le entra un video le saca un fotograma; si es imagen, la reencuadra. En
    ambos casos sale un JPG del tamaño correcto. Devuelve "" cuando la URL no
    sirve, para que quien llame siga probando con la siguiente candidata.
    """
    url = str(url or "").strip()
    if not url or "res.cloudinary.com" not in url or "/upload/" not in url:
        return ""
    if _es_video(url):
        # so_0 = el fotograma del segundo cero, y se cambia la extensión a .jpg
        sin_extension = url[:url.rfind(".")]
        return sin_extension.replace("/upload/", f"/upload/so_0,{_OG_TRANSFORMACION}/", 1) + ".jpg"
    return url.replace("/upload/", f"/upload/{_OG_TRANSFORMACION}/", 1)

_RUTA_IMAGEN_DEFECTO = "static/fotos/portada-compartir.jpg"

def _medidas_imagen_defecto():
    """Mide la imagen genérica del sitio una sola vez, al arrancar.

    Hace falta porque og:image:width/height tienen que decir la verdad: si
    declaramos 1200x630 para una imagen que mide otra cosa, algunos lectores de
    vista previa la renderizan mal o la descartan. Las de Cloudinary sí salen
    exactas porque nosotros pedimos el tamaño; esta es un archivo que el dueño
    puede cambiar cuando quiera, así que se pregunta en vez de suponer.
    """
    try:
        with Image.open(_RUTA_IMAGEN_DEFECTO) as img:
            return img.size
    except Exception:
        return (OG_ANCHO, OG_ALTO)

OG_DEFECTO_ANCHO, OG_DEFECTO_ALTO = _medidas_imagen_defecto()

def imagen_para_compartir(perfil, lista_portadas, fotos_feed, url_base) -> dict:
    """La foto que verá quien reciba el enlace del memorial.

    Antes se mandaba la primera portada sin mirar qué era. En los memoriales con
    portada en video eso significaba apuntar el og:image a un .mov de 16 MB:
    WhatsApp lo pedía, se encontraba un QuickTime y mostraba la tarjeta pelada,
    sin la cara de la persona. Justo el enlace que la familia va a repartir.

    Se prueba en orden y la primera que dé una imagen gana: la portada que eligió
    el dueño, la foto del perfil, la primera de la galería, y si nada sirve la
    imagen genérica del sitio. Las URL que no son de Cloudinary (como el avatar
    en blanco por defecto) se saltan solas, que es lo que queremos: mejor la
    imagen del sitio que un muñeco gris.
    """
    candidatas = []
    if lista_portadas:
        candidatas.append(lista_portadas[0].get("url"))
    candidatas.append(getattr(perfil, "foto_perfil", ""))
    if fotos_feed:
        candidatas.append(fotos_feed[0].get("url"))

    for candidata in candidatas:
        lista = imagen_compartible(candidata)
        if lista:
            return {"url": lista, "ancho": OG_ANCHO, "alto": OG_ALTO}
    return {
        "url": url_base.rstrip("/") + "/" + _RUTA_IMAGEN_DEFECTO,
        "ancho": OG_DEFECTO_ANCHO, "alto": OG_DEFECTO_ALTO,
    }

def _resumir_para_vista_previa(texto, limite: int = 190) -> str:
    """Deja un texto listo para una etiqueta de vista previa.

    El epitafio lo escribe la familia a mano: puede traer saltos de línea y
    espacios de más (que en una tarjeta se ven como un renglón roto) y puede ser
    más largo de lo que muestra WhatsApp. Se colapsa el espaciado y, si hay que
    cortar, se corta en una palabra completa y no a la mitad.
    """
    limpio = " ".join(str(texto or "").split())
    if len(limpio) <= limite:
        return limpio
    recortado = limpio[:limite]
    if " " in recortado:
        recortado = recortado[:recortado.rfind(" ")]
    return recortado.rstrip(" ,;:.") + "…"

def url_publica(request: Request) -> str:
    """La URL de esta página, sin parámetros y en https.

    Render termina el TLS en su proxy, así que la petición puede llegar como http
    y una vista previa con og:url en http sobre una página https se ve sospechosa.
    """
    url = str(request.url).split("?")[0]
    if url.startswith("http://") and not any(h in url for h in ("localhost", "127.0.0.1")):
        url = "https://" + url[len("http://"):]
    return url


@app.get("/", response_class=HTMLResponse)
async def inicio(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
# --- MODELOS DE DATOS ---
class PerfilDatos(BaseModel):
    identificador: str
    nombre: str
    fechas: str
    biografia: str
    en_memoria_de: str = ""
    esposa: str = ""
    hijos: str = ""
    cancion_favorita: str = ""
    juego_favorito: str = ""
    pin_familia: str = "0000"
    # Datos de gestión: los usa /crear_perfil/ (solo admin). editar_perfil/
    # comparte este modelo pero NO los copia, porque ahí entra la familia con
    # su PIN y no debe poder tocar el estado de pago ni las notas internas.
    contacto_nombre: str = ""
    contacto_telefono: str = ""
    contacto_email: str = ""
    estado_pago: str = "pendiente"
    notas_internas: str = ""

class GestionUpdate(BaseModel):
    contacto_nombre: str = ""
    contacto_telefono: str = ""
    contacto_email: str = ""
    estado_pago: str = "pendiente"
    notas_internas: str = ""

class MensajeNuevo(BaseModel):
    autor: str
    texto: str

class MomentoNuevo(BaseModel):
    anio: str
    titulo: str
    descripcion: str

class PinRequest(BaseModel):
    pin: str

class DatosIA(BaseModel):
    datos_clave: str

class DatosHomenaje(BaseModel):
    perfil_nombre: str
    parentezco_o_anecdota: str

class ComentarioNuevo(BaseModel):
    texto: str

class AdminLogin(BaseModel):
    password: str

class PinUpdate(BaseModel):
    nuevo_pin: str

class TemaUpdate(BaseModel):
    tema: str

class VelaRequest(BaseModel):
    nombre: str = "Visitante Anónimo"
    mensaje: str = ""
    duracion_horas: int = 24

class MapaUpdate(BaseModel):
    lat: str
    lng: str
    direccion: str = ""
    descripcion: str = ""
    privacidad: str = "publico"

class FamiliarRequest(BaseModel):
    nombre: str
    relacion: str
    foto_url: str = ""
    memorial_id: str = ""
    orden: int = 0

def get_db():
    db = database.SessionLocal()
    try: yield db
    finally: db.close()

# --- COMPRESOR MÁGICO REPARADO PARA CLOUDINARY ---
def comprimir_imagen(file_content):
    try:
        img = Image.open(io.BytesIO(file_content))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((1600, 1600)) 
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=80)
        buffer.seek(0)
        return buffer # Empaque perfecto para Cloudinary
    except Exception as e:
        print(f"Aviso en compresión: {e}")
        return io.BytesIO(file_content)

def registrar_interaccion(perfil, db):
    # El día se corta a la medianoche de Colombia, no a las 7 de la noche, que
    # es cuando cambia la fecha en UTC.
    hoy_str = ahora_colombia().strftime("%Y-%m-%d")
    if perfil.dia_interacciones != hoy_str:
        perfil.interacciones_hoy = 1
        perfil.dia_interacciones = hoy_str
    else:
        perfil.interacciones_hoy += 1
    db.commit()

# ==========================================
# 🔐 AUTENTICACIÓN ADMIN: LOGIN / LOGOUT
# ==========================================
@app.post("/api/admin/login")
def admin_login(datos: AdminLogin, request: Request):
    verificar_bloqueo(request, "admin_login")

    hash_input = hashlib.sha256(datos.password.encode()).hexdigest()
    if not hmac.compare_digest(hash_input, ADMIN_PASSWORD_HASH):
        registrar_fallo(request, "admin_login")
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    limpiar_intentos(request, "admin_login")
    token = _firmar_cookie({"role": "admin"})
    response = JSONResponse(content={"mensaje": "Acceso concedido"})
    response.set_cookie(
        key="admin_session", value=token,
        httponly=True, samesite="lax",
        max_age=86400,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )
    return response

@app.post("/api/admin/logout")
def admin_logout():
    response = JSONResponse(content={"mensaje": "Sesión cerrada"})
    response.delete_cookie(
        key="admin_session",
        httponly=True,
        samesite="lax",
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )
    return response

# --- RUTAS DE IA (ASYNC CON HTTPX) ---
@app.post("/api/generar_biografia")
async def generar_biografia(datos: DatosIA, request: Request):
    rate_limit_check(request, "generar_ia", max_calls=5, window=60)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url_modelos = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_GEMINI}"
            res_modelos = await client.get(url_modelos)
            if res_modelos.status_code != 200: raise HTTPException(status_code=500, detail="Error API Key")
            lista_modelos = res_modelos.json().get("models", [])
            modelo_elegido = next((m.get("name") for m in lista_modelos if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "").lower()), None)
            if not modelo_elegido: raise HTTPException(status_code=500, detail="Sin modelos")
            instruccion = f"Actúa como un escritor profesional especializado en homenajes y obituarios. Redacta una biografía breve, respetuosa, poética y muy emotiva para un memorial digital basada en estos datos: '{datos.datos_clave}'. No uses lenguaje robótico ni frases cliché. Hazlo sonar humano, reconfortante y divide el texto en 2 o 3 párrafos cortos. No pongas título."
            url_generar = f"https://generativelanguage.googleapis.com/v1beta/{modelo_elegido}:generateContent?key={API_KEY_GEMINI}"
            respuesta = await client.post(url_generar, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": instruccion}]}]})
            if respuesta.status_code != 200: raise HTTPException(status_code=500, detail="Error de Google")
            return {"biografia": respuesta.json()['candidates'][0]['content']['parts'][0]['text']}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error general de la IA")

@app.post("/api/generar_homenaje")
async def generar_homenaje(datos: DatosHomenaje, request: Request):
    rate_limit_check(request, "generar_ia", max_calls=5, window=60)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            url_modelos = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_GEMINI}"
            res_modelos = await client.get(url_modelos)
            if res_modelos.status_code != 200: raise HTTPException(status_code=500, detail="Error API Key")
            lista_modelos = res_modelos.json().get("models", [])
            modelo_elegido = next((m.get("name") for m in lista_modelos if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "").lower()), None)
            if not modelo_elegido: raise HTTPException(status_code=500, detail="Sin modelos")
            instruccion = f"Escribe o redacta un hermoso y breve mensaje de condolencia o recuerdo para la persona fallecida '{datos.perfil_nombre}'. Mi relación o anécdota con él/ella es la siguiente: '{datos.parentezco_o_anecdota}'. Quiero publicarlo en su libro de recuerdos (Guestbook). Que el mensaje sea corto (máximo 40 palabras), poético, profundamente empático y cálido, en primera persona hacia él o ella. Omite saludos o despedidas largas. Entrega sólo el texto final sin comillas ni aclaraciones."
            url_generar = f"https://generativelanguage.googleapis.com/v1beta/{modelo_elegido}:generateContent?key={API_KEY_GEMINI}"
            respuesta = await client.post(url_generar, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": instruccion}]}]})
            if respuesta.status_code != 200: raise HTTPException(status_code=500, detail="Error de Google")
            texto_generado = respuesta.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '')
            return {"homenaje": texto_generado[:150]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error general de la IA")

@app.post("/api/verificar_pin/{identificador}")
def verificar_pin(identificador: str, req: PinRequest, request: Request, db: Session = Depends(get_db)):
    alcance = f"pin:{identificador}"
    verificar_bloqueo(request, alcance)

    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)

    if hmac.compare_digest(str(perfil.pin_familia), str(req.pin)):
        limpiar_intentos(request, alcance)
        return {"success": True}

    registrar_fallo(request, alcance)
    raise HTTPException(status_code=401, detail="PIN incorrecto")

ESTADOS_PAGO = ("pendiente", "pagado", "cortesia")

def _estado_pago_valido(valor: str) -> str:
    """Solo deja pasar los tres estados conocidos; cualquier otra cosa es 'pendiente'.

    Así el semáforo del panel nunca queda en un estado que no sabe pintar.
    """
    limpio = (valor or "").strip().lower()
    return limpio if limpio in ESTADOS_PAGO else "pendiente"

# --- CRUD PROTEGIDO POR ADMIN ---
@app.post("/crear_perfil/")
def crear_perfil(perfil: PerfilDatos, request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    existente = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == perfil.identificador).first()
    if existente: raise HTTPException(status_code=400, detail="Ese identificador ya existe.")
    nuevo_difunto = database.PerfilDifunto(identificador=perfil.identificador, nombre=perfil.nombre, fechas=perfil.fechas, biografia=perfil.biografia, foto_perfil="https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_1280.png", foto_portada="https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop", en_memoria_de=perfil.en_memoria_de, esposa=perfil.esposa, hijos=perfil.hijos, cancion_favorita=perfil.cancion_favorita, juego_favorito=perfil.juego_favorito, pin_familia=perfil.pin_familia,
        fecha_creacion=datetime.datetime.utcnow(),
        contacto_nombre=perfil.contacto_nombre.strip(), contacto_telefono=perfil.contacto_telefono.strip(),
        contacto_email=perfil.contacto_email.strip(), estado_pago=_estado_pago_valido(perfil.estado_pago),
        notas_internas=perfil.notas_internas.strip())
    db.add(nuevo_difunto)
    db.commit()
    return {"mensaje": f"Perfil creado."}

# --- CRUD PROTEGIDO POR PIN FAMILIAR (o Admin) ---
@app.put("/editar_perfil/{identificador}")
def editar_perfil(identificador: str, datos_nuevos: PerfilDatos, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    perfil.nombre = datos_nuevos.nombre
    perfil.fechas = datos_nuevos.fechas
    perfil.biografia = datos_nuevos.biografia
    perfil.en_memoria_de = datos_nuevos.en_memoria_de
    perfil.cancion_favorita = datos_nuevos.cancion_favorita
    # esposa, hijos y juego_favorito YA NO SE ESCRIBEN (Fase 2).
    #
    # El formulario dejó de pedirlos, así que llegarían siempre vacíos por el
    # valor por defecto del modelo — y esta línea borraría el texto original
    # apenas la familia guardara cualquier otro cambio. Esas columnas son el
    # respaldo de lo que se mudó al Árbol Familiar: se leen, no se pisan.
    db.commit()
    return {"mensaje": "Perfil actualizado"}

# --- SUBIDAS CLOUDINARY 100% REPARADAS (PROTEGIDAS POR PIN) ---
@app.post("/cambiar_foto_perfil/{identificador}")
async def cambiar_foto_perfil(identificador: str, request: Request, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    try:
        contenido = await archivo.read()
        es_video = archivo.content_type.startswith('video/')
        if es_video: 
            file_obj = io.BytesIO(contenido)
            respuesta_cloud = cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/perfiles", resource_type="video")
        else: 
            file_obj = comprimir_imagen(contenido)
            respuesta_cloud = cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/perfiles", resource_type="image")
        
        perfil.foto_perfil = respuesta_cloud['secure_url']
        db.commit()
        return {"mensaje": "Medio de perfil actualizado", "url": respuesta_cloud['secure_url']}
    except Exception as e:
        print(f"Error en Cloudinary Perfil: {e}")
        raise HTTPException(status_code=500, detail="Fallo la subida a la nube.")

@app.post("/cambiar_foto_portada/{identificador}")
async def cambiar_foto_portada(identificador: str, request: Request, archivos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    urls_guardadas = []
    try:
        for archivo in archivos[:4]: 
            contenido = await archivo.read()
            if archivo.content_type.startswith('video/'): 
                file_obj = io.BytesIO(contenido)
                urls_guardadas.append(cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/portadas", resource_type="video")['secure_url'])
            else: 
                file_obj = comprimir_imagen(contenido)
                urls_guardadas.append(cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/portadas", resource_type="image")['secure_url'])
        perfil.foto_portada = ",".join(urls_guardadas)
        db.commit()
        return {"mensaje": "Portadas actualizadas", "urls": urls_guardadas}
    except Exception as e:
        print(f"Error en Cloudinary Portada: {e}")
        raise HTTPException(status_code=500, detail="Fallo la subida a la nube.")

@app.post("/subir_fotos/{identificador}")
async def subir_fotos(identificador: str, request: Request, archivos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    fotos_guardadas = []
    try:
        for archivo in archivos:
            contenido = await archivo.read()
            file_obj = comprimir_imagen(contenido)
            respuesta_cloud = cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/galeria", resource_type="image")
            
            nueva_foto = database.FotoGaleria(url_foto=respuesta_cloud['secure_url'], perfil_id=perfil.id)
            db.add(nueva_foto)
            db.commit()
            db.refresh(nueva_foto)
            fotos_guardadas.append({"id": nueva_foto.id, "url": respuesta_cloud['secure_url']})
        
        registrar_interaccion(perfil, db)
        return {"fotos": fotos_guardadas}
    except Exception as e:
        print(f"Error en Cloudinary Galería: {e}")
        raise HTTPException(status_code=500, detail="Fallo la subida a la nube.")

@app.post("/subir_audio_voz/{identificador}")
async def subir_audio_voz(identificador: str, request: Request, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    try:
        contenido = await archivo.read()
        file_obj = io.BytesIO(contenido)
        respuesta_cloud = cloudinary.uploader.upload(file_obj, folder=f"memoriales/{identificador}/audio", resource_type="video") # Cloudinary procesa audio como video
        perfil.audio_voz = respuesta_cloud['secure_url']
        db.commit()
        return {"mensaje": "Audio subido correctamente", "url": respuesta_cloud['secure_url']}
    except Exception as e:
        print(f"Error en Audio: {e}")
        raise HTTPException(status_code=500, detail="Fallo la subida de audio.")

@app.delete("/eliminar_foto/{foto_id}")
def eliminar_foto(foto_id: int, request: Request, db: Session = Depends(get_db)):
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, foto.perfil)
    try:
        url_partes = foto.url_foto.split('/')
        cloudinary.uploader.destroy("/".join(url_partes[url_partes.index("memoriales"):]).split('.')[0], resource_type="image")
    except: pass
    db.delete(foto)
    db.commit()
    return {"mensaje": "Foto eliminada"}

# --- RUTAS DE RECUERDOS Y MOMENTOS ---
@app.post("/dejar_mensaje/{identificador}")
def dejar_mensaje(identificador: str, mensaje: MensajeNuevo, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "dejar_mensaje", max_calls=10, window=60)
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    nuevo_msj = database.MensajeRecuerdo(autor=mensaje.autor, texto=mensaje.texto[:150], perfil_id=perfil.id)
    db.add(nuevo_msj)
    registrar_interaccion(perfil, db)
    return {"mensaje": "Recuerdo guardado"}

@app.post("/likear_mensaje/{mensaje_id}")
def likear_mensaje(mensaje_id: int, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "likear", max_calls=30, window=60)
    mensaje = db.query(database.MensajeRecuerdo).filter(database.MensajeRecuerdo.id == mensaje_id).first()
    if not mensaje: raise HTTPException(status_code=404)
    mensaje.likes += 1
    if mensaje.perfil: registrar_interaccion(mensaje.perfil, db)
    return {"likes": mensaje.likes}

@app.delete("/eliminar_mensaje/{mensaje_id}")
def eliminar_mensaje(mensaje_id: int, request: Request, db: Session = Depends(get_db)):
    mensaje = db.query(database.MensajeRecuerdo).filter(database.MensajeRecuerdo.id == mensaje_id).first()
    if not mensaje: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, mensaje.perfil)
    db.delete(mensaje)
    db.commit()
    return {"mensaje": "Mensaje eliminado"}

@app.post("/agregar_momento/{identificador}")
def agregar_momento(identificador: str, momento: MomentoNuevo, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    nuevo_momento = database.MomentoInolvidable(anio=momento.anio, titulo=momento.titulo, descripcion=momento.descripcion, perfil_id=perfil.id)
    db.add(nuevo_momento)
    db.commit()
    return {"mensaje": "Momento agregado"}

@app.put("/editar_momento/{momento_id}")
def editar_momento(momento_id: int, momento: MomentoNuevo, request: Request, db: Session = Depends(get_db)):
    momento_db = db.query(database.MomentoInolvidable).filter(database.MomentoInolvidable.id == momento_id).first()
    if not momento_db: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, momento_db.perfil)
    momento_db.anio = momento.anio; momento_db.titulo = momento.titulo; momento_db.descripcion = momento.descripcion
    db.commit()
    return {"mensaje": "Momento actualizado"}

@app.delete("/eliminar_momento/{momento_id}")
def eliminar_momento(momento_id: int, request: Request, db: Session = Depends(get_db)):
    momento = db.query(database.MomentoInolvidable).filter(database.MomentoInolvidable.id == momento_id).first()
    if not momento: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, momento.perfil)
    db.delete(momento)
    db.commit()
    return {"mensaje": "Momento eliminado"}

@app.post("/api/encender_vela/{identificador}")
def encender_vela(identificador: str, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "vela", max_calls=5, window=60)
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if perfil.velas is None: perfil.velas = 0
    perfil.velas += 1

    # Además del contador, dejamos rastro de CUÁNDO se encendió. Antes esta vela
    # solo sumaba un número: quedaba constancia de que alguien pasó, pero no del
    # día, así que ese recuerdo no se podía devolver nunca.
    #
    # duracion_horas=0 la mantiene fuera del muro de dedicatorias (el muro filtra
    # por horas restantes, y con 0 nunca entra). El muro es para velas con nombre
    # y mensaje; esta es anónima y llenaría ese espacio de tarjetas vacías.
    db.add(database.VelaEncendida(
        nombre="Visitante Anónimo",
        mensaje="",
        duracion_horas=0,
        perfil_id=perfil.id
    ))

    registrar_interaccion(perfil, db)
    return {"velas": perfil.velas}

@app.post("/api/likear_foto/{foto_id}")
def likear_foto(foto_id: int, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "likear", max_calls=30, window=60)
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    if foto.likes is None: foto.likes = 0
    foto.likes += 1
    db.commit() 
    if foto.perfil: registrar_interaccion(foto.perfil, db)
    return {"likes": foto.likes}

@app.post("/api/comentar_foto/{foto_id}")
def comentar_foto(foto_id: int, comentario: ComentarioNuevo, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "comentar", max_calls=10, window=60)
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    nuevo_comentario = database.ComentarioFoto(texto=comentario.texto[:120], foto_id=foto.id)
    db.add(nuevo_comentario)
    db.commit()
    if foto.perfil: registrar_interaccion(foto.perfil, db)
    return {"mensaje": "Comentario agregado"}

# --- ADMIN: GESTIÓN DE PERFILES (PROTEGIDO) ---
@app.put("/api/admin/reset_pin/{identificador}")
def reset_pin_perfil(identificador: str, datos: PinUpdate, request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    perfil.pin_familia = datos.nuevo_pin
    db.commit()
    return {"mensaje": "PIN actualizado correctamente"}

@app.delete("/api/admin/eliminar_perfil/{identificador}")
def eliminar_perfil_completo(identificador: str, request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    try: cloudinary.api.delete_resources_by_prefix(f"memoriales/{identificador}/"); cloudinary.api.delete_folder(f"memoriales/{identificador}")
    except: pass
    for foto in perfil.fotos_galeria: db.delete(foto)
    for msj in perfil.mensajes: db.delete(msj)
    for mom in perfil.momentos: db.delete(mom)
    db.delete(perfil)
    db.commit()
    return {"mensaje": "Perfil eliminado."}

def _mapa_context(perfil, request: Request) -> dict:
    """Devuelve las claves de mapa para el template respetando mapa_privacidad."""
    lat = getattr(perfil, 'mapa_lat', '') or ''
    lng = getattr(perfil, 'mapa_lng', '') or ''
    privacidad = getattr(perfil, 'mapa_privacidad', 'publico') or 'publico'
    tiene_mapa = bool(lat and lng)
    puede_ver = privacidad == 'publico' or _es_admin(request)
    return {
        "mapa_lat": lat if puede_ver else '',
        "mapa_lng": lng if puede_ver else '',
        "mapa_direccion": (getattr(perfil, 'mapa_direccion', '') or '') if puede_ver else '',
        "mapa_descripcion": (getattr(perfil, 'mapa_descripcion', '') or '') if puede_ver else '',
        "mapa_privacidad": privacidad,
        "tiene_mapa": tiene_mapa,
    }

# 🗺️ API: COORDENADAS AUTORIZADAS (para familia con PIN)
@app.get("/api/mapa_coords/{identificador}")
def obtener_mapa_coords(identificador: str, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    privacidad = getattr(perfil, 'mapa_privacidad', 'publico') or 'publico'
    if privacidad in ('privado', 'invitados'):
        if not _es_admin(request):
            pin = request.headers.get("x-family-pin", "")
            if not pin or pin != perfil.pin_familia:
                raise HTTPException(status_code=403, detail="PIN familiar requerido")
    return {
        "lat": getattr(perfil, 'mapa_lat', '') or '',
        "lng": getattr(perfil, 'mapa_lng', '') or '',
        "direccion": getattr(perfil, 'mapa_direccion', '') or '',
        "descripcion": getattr(perfil, 'mapa_descripcion', '') or '',
    }

# 🎬 CONSTRUCCIÓN DE LA VISTA PRINCIPAL 🎬
@app.get("/perfil/{identificador}", response_class=HTMLResponse)
def ver_perfil(request: Request, identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).options(
        selectinload(database.PerfilDifunto.fotos_galeria).selectinload(database.FotoGaleria.comentarios),
        selectinload(database.PerfilDifunto.mensajes),
        selectinload(database.PerfilDifunto.momentos),
        selectinload(database.PerfilDifunto.familiares_arbol)
    ).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: return HTMLResponse(content="<h1>Error 404: Perfil no encontrado</h1>", status_code=404)

    hoy_str = ahora_colombia().strftime("%Y-%m-%d")
    if getattr(perfil, 'dia_interacciones', '') != hoy_str:
        perfil.interacciones_hoy = 0
        perfil.dia_interacciones = hoy_str
        db.commit()

    nombre_cookie = f"visita_{identificador}"
    if not request.cookies.get(nombre_cookie):
        perfil.visitas += 1
        perfil.ultima_visita = datetime.datetime.utcnow()
        registrar_interaccion(perfil, db) 

    fotos_db = list(reversed(perfil.fotos_galeria))
    
    fotos_feed = []
    total_corazones_galeria = 0
    for foto in fotos_db:
        corazones = foto.likes or 0
        total_corazones_galeria += corazones
        comentarios_feed = [{"texto": c.texto} for c in list(foto.comentarios)[-3:]]
        fotos_feed.append({"id": foto.id, "url": foto.url_foto, "likes": corazones, "comentarios": comentarios_feed})

    # El bloque se llama "Recuerdo de hoy", así que tiene que ser el de hoy: antes
    # era un random.choice sin semilla y sacaba una foto distinta en cada recarga.
    #
    # Rotación y no azar sembrado: con azar salían tres días seguidos con la misma
    # foto, que parece que estuviera fallando. Así avanza una foto por día y pasa
    # por todas antes de repetir. El desplazamiento por identificador evita que
    # todos los memoriales muestren la misma posición el mismo día.
    if fotos_feed:
        dia_absoluto = ahora_colombia().date().toordinal()
        desplazamiento = int(hashlib.sha256(identificador.encode()).hexdigest()[:8], 16)
        foto_aleatoria = fotos_feed[(dia_absoluto + desplazamiento) % len(fotos_feed)]
    else:
        foto_aleatoria = None
    foto_mas_recordada = max(fotos_feed, key=lambda f: f["likes"]) if fotos_feed and total_corazones_galeria > 0 else None

    mensajes_feed = [{"id": m.id, "autor": m.autor, "texto": m.texto, "fecha": fecha_colombia_str(m.fecha_creacion), "likes": m.likes} for m in reversed(perfil.mensajes)]
    momentos_feed = [{"id": m.id, "anio": m.anio, "titulo": m.titulo, "descripcion": m.descripcion, "icono": obtener_icono_momento(m.titulo)} for m in perfil.momentos]
    momentos_feed.sort(key=lambda x: parse_date_for_sorting(x["anio"])) # ✅ CRONOLOGÍA AUTOMÁTICA

    # Aniversario que cae hoy, si hay alguno. Sale de los momentos que ya tenemos:
    # son el único contenido con fechas de hace décadas, así que es lo único que
    # puede decir "hace 40 años" en una plataforma que lleva meses en pie.
    efemeride = efemeride_del_dia(momentos_feed, ahora_colombia().date())

    es_video_perfil = perfil.foto_perfil.endswith(('.mp4', '.mov', '.webm'))
    
    portadas_raw = perfil.foto_portada.split(',') if perfil.foto_portada else ["https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop"]
    lista_portadas = [{"url": p.strip(), "es_video": p.endswith(('.mp4', '.mov', '.webm'))} for p in portadas_raw if p.strip()]
    
    # El nombre y las fechas se limpian acá: venían con espacios de sobra del
    # formulario y salían en la vista previa del enlace como "Javier Galvis ."
    nombre_limpio = (perfil.nombre or "").strip()
    fechas_limpias = (perfil.fechas or "").strip()

    # La descripción de la vista previa: si la familia escribió su dedicatoria,
    # esa dice mucho más que cualquier frase que pongamos nosotros.
    compartible = imagen_para_compartir(perfil, lista_portadas, fotos_feed, str(request.base_url))

    epitafio = (perfil.en_memoria_de or "").strip()
    og_descripcion = _resumir_para_vista_previa(epitafio) or (
        f"Un espacio para recordar a {nombre_limpio}: sus fotos, su historia y "
        "los mensajes de quienes lo quisieron."
    )

    datos_diccionario = {
        "identificador": perfil.identificador, "nombre": nombre_limpio, "fechas": fechas_limpias,
        "og_titulo": f"En memoria de {nombre_limpio}" + (f" ({fechas_limpias})" if fechas_limpias else ""),
        "og_descripcion": og_descripcion,
        "og_imagen": compartible["url"],
        "og_ancho": compartible["ancho"], "og_alto": compartible["alto"],
        "og_url": url_publica(request),
        "biografia": perfil.biografia, "foto_perfil": perfil.foto_perfil,
        "portadas": lista_portadas,
        "es_video_perfil": es_video_perfil, "visitas": perfil.visitas, "ultima_visita": fecha_colombia_str(perfil.ultima_visita),
        "en_memoria_de": perfil.en_memoria_de, "esposa": perfil.esposa, "hijos": perfil.hijos, 
        "cancion_favorita": perfil.cancion_favorita, "juego_favorito": perfil.juego_favorito, 
        "fotos": fotos_feed, "mensajes": mensajes_feed, "momentos": momentos_feed, "velas": perfil.velas or 0,
        "efemeride": efemeride,
        "interacciones_hoy": perfil.interacciones_hoy,
        "total_corazones_galeria": total_corazones_galeria,
        "foto_aleatoria": foto_aleatoria,
        "foto_mas_recordada": foto_mas_recordada,
        "audio_voz": getattr(perfil, 'audio_voz', ''),
        "tema_visual": getattr(perfil, 'tema_visual', 'noche') or 'noche',
        **_mapa_context(perfil, request),
        "familiares": [
            {"id": f.id, "nombre": f.nombre, "relacion": f.relacion,
             "foto_url": f.foto_url or '', "memorial_id": f.memorial_id or ''}
            for f in sorted(getattr(perfil, 'familiares_arbol', []), key=lambda x: x.orden)
        ],
    }

    pagina_html = templates.TemplateResponse("perfil.html", {"request": request, **datos_diccionario})
    if not request.cookies.get(nombre_cookie): pagina_html.set_cookie(key=nombre_cookie, value="visitado", max_age=86400)
    return pagina_html

@app.get("/generar_qr/{identificador}")
def generar_qr_elegante(identificador: str, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return templates.TemplateResponse("imprimir_qr.html", {"request": request, "url_perfil": str(request.base_url) + f"perfil/{identificador}", "nombre": perfil.nombre})

@app.get("/admin/", response_class=HTMLResponse)
def panel_admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/api/admin/estadisticas")
def estadisticas_admin(request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    """Alimenta el panel. Incluye los datos de contacto de la familia, que son
    información personal: este endpoint exige sesión de admin y nada de esto
    viaja a la página pública del memorial."""
    perfiles = db.query(database.PerfilDifunto).all()
    return {
        "total_perfiles": len(perfiles), "total_visitas": sum([p.visitas for p in perfiles]),
        "total_pendientes": sum(1 for p in perfiles if _estado_pago_valido(p.estado_pago) == "pendiente"),
        "perfiles": [{"identificador": p.identificador, "nombre": p.nombre, "visitas": p.visitas, "ultima_visita": fecha_colombia_str(p.ultima_visita, vacio="Nueva"),
                      "fecha_creacion": fecha_colombia_str(p.fecha_creacion),
                      "contacto_nombre": p.contacto_nombre or "", "contacto_telefono": p.contacto_telefono or "",
                      "contacto_email": p.contacto_email or "", "estado_pago": _estado_pago_valido(p.estado_pago),
                      "notas_internas": p.notas_internas or ""} for p in perfiles]
    }

@app.put("/api/admin/gestion/{identificador}")
def actualizar_gestion(identificador: str, datos: GestionUpdate, request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    """Actualiza el estado de pago y los datos de contacto de la familia.

    Deliberadamente separado de editar_perfil/: ese endpoint lo puede usar la
    familia con su PIN, y esto es información del negocio que solo ve el dueño.
    """
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404, detail="Memorial no encontrado.")

    perfil.contacto_nombre = datos.contacto_nombre.strip()
    perfil.contacto_telefono = datos.contacto_telefono.strip()
    perfil.contacto_email = datos.contacto_email.strip()
    perfil.estado_pago = _estado_pago_valido(datos.estado_pago)
    perfil.notas_internas = datos.notas_internas.strip()
    db.commit()
    return {"mensaje": "Datos de gestión actualizados", "estado_pago": perfil.estado_pago}

@app.get("/api/admin/respaldo")
def descargar_respaldo(request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    """Exporta TODA la plataforma a un archivo JSON descargable.

    Es la red de seguridad: si se pierde la base de datos, este archivo permite
    reconstruir los memoriales. Incluye las URL de Cloudinary, así que también
    sirve para saber a qué perfil pertenece cada foto (sin él, las imágenes
    quedan huérfanas en la nube y no hay forma de reasignarlas).

    OJO: el archivo lleva PINes y los datos de contacto de las familias. Es un
    documento privado, hay que guardarlo como tal.
    """
    def cuando(fecha):
        return fecha.isoformat() if fecha else None

    perfiles = db.query(database.PerfilDifunto).all()
    datos = {
        "generado": datetime.datetime.utcnow().isoformat() + "Z",
        "version": 1,
        "total_perfiles": len(perfiles),
        "perfiles": [],
    }

    for p in perfiles:
        datos["perfiles"].append({
            "identificador": p.identificador,
            "nombre": p.nombre,
            "fechas": p.fechas,
            "biografia": p.biografia,
            "en_memoria_de": p.en_memoria_de,
            "esposa": p.esposa,
            "hijos": p.hijos,
            "cancion_favorita": p.cancion_favorita,
            "juego_favorito": p.juego_favorito,
            "pin_familia": p.pin_familia,
            "foto_perfil": p.foto_perfil,
            "foto_portada": p.foto_portada,
            "audio_voz": getattr(p, "audio_voz", ""),
            "tema_visual": p.tema_visual,
            "visitas": p.visitas,
            "velas": p.velas,
            "ultima_visita": cuando(p.ultima_visita),
            "fecha_creacion": cuando(p.fecha_creacion),
            "gestion": {
                "contacto_nombre": p.contacto_nombre or "",
                "contacto_telefono": p.contacto_telefono or "",
                "contacto_email": p.contacto_email or "",
                "estado_pago": _estado_pago_valido(p.estado_pago),
                "notas_internas": p.notas_internas or "",
            },
            "mapa": {
                "lat": p.mapa_lat, "lng": p.mapa_lng, "direccion": p.mapa_direccion,
                "descripcion": p.mapa_descripcion, "privacidad": p.mapa_privacidad,
            },
            "fotos": [
                {"url": f.url_foto, "likes": f.likes,
                 "comentarios": [{"texto": c.texto, "fecha": cuando(c.fecha_creacion)} for c in f.comentarios]}
                for f in p.fotos_galeria
            ],
            "mensajes": [
                {"autor": m.autor, "texto": m.texto, "likes": m.likes, "fecha": cuando(m.fecha_creacion)}
                for m in p.mensajes
            ],
            "momentos": [
                {"anio": mo.anio, "titulo": mo.titulo, "descripcion": mo.descripcion}
                for mo in p.momentos
            ],
            "familiares": [
                {"nombre": fa.nombre, "relacion": fa.relacion, "foto_url": fa.foto_url, "orden": fa.orden}
                for fa in p.familiares_arbol
            ],
            # Las dedicadas (con nombre y mensaje) van enteras. Las anónimas, que
            # son solo "alguien pasó por aquí", van como lista de fechas: guardan
            # el dato que importa sin sepultar las dedicatorias reales bajo miles
            # de objetos con el mensaje vacío.
            "velas_dedicadas": [
                {"nombre": v.nombre, "mensaje": v.mensaje, "duracion_horas": v.duracion_horas,
                 "fecha": cuando(v.fecha_encendida)}
                for v in p.velas_list if v.duracion_horas > 0
            ],
            "velas_anonimas": [
                cuando(v.fecha_encendida) for v in p.velas_list if not v.duracion_horas
            ],
        })

    # Hora de Colombia: el nombre del archivo lo lee el dueño, y tiene que decir
    # el día en que lo descargó. El "generado" de adentro sí queda en UTC con su Z.
    marca = ahora_colombia().strftime("%Y-%m-%d_%H%M")
    return Response(
        content=json.dumps(datos, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="respaldo-legados-{marca}.json"'},
    )


@app.get("/api/admin/moderacion")
def datos_moderacion(request: Request, db: Session = Depends(get_db), admin: bool = Depends(verificar_admin)):
    fotos = db.query(database.FotoGaleria).all()
    mensajes = db.query(database.MensajeRecuerdo).all()
    return {"fotos": [{"id": f.id, "url": f.url_foto, "perfil": f.perfil.nombre} for f in fotos if f.perfil], "mensajes": [{"id": m.id, "autor": m.autor, "texto": m.texto, "perfil": m.perfil.nombre} for m in mensajes if m.perfil]}

# ==========================================
# 🎨 PREMIUM: TEMA VISUAL
# ==========================================
@app.put("/api/tema/{identificador}")
def actualizar_tema(identificador: str, datos: TemaUpdate, request: Request, db: Session = Depends(get_db)):
    temas_validos = {"noche", "atardecer", "bosque", "marmol", "jardin"}
    if datos.tema not in temas_validos:
        raise HTTPException(status_code=400, detail="Tema no válido")
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    perfil.tema_visual = datos.tema
    db.commit()
    return {"mensaje": "Tema actualizado", "tema": datos.tema}

# ==========================================
# 🕯️ PREMIUM: MURO DE VELAS
# ==========================================
@app.get("/api/velas_muro/{identificador}")
def listar_velas_muro(identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    ahora = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    velas_activas = []

    # Filtramos en SQL y no en Python. Este endpoint se llama en cada visita al
    # memorial, y desde que la vela simple también deja fila, recorrer la relación
    # entera significaba leer todo el historial del memorial para devolver, casi
    # siempre, un puñado de velas vigentes.
    #
    # El corte de 72 horas es seguro porque encender_vela_muro limita la duración
    # a ese máximo: ninguna vela puede seguir encendida más allá. Y duracion_horas
    # > 0 deja fuera las anónimas, que nunca se muestran acá.
    candidatas = (
        db.query(database.VelaEncendida)
          .filter(
              database.VelaEncendida.perfil_id == perfil.id,
              database.VelaEncendida.duracion_horas > 0,
              database.VelaEncendida.fecha_encendida > ahora - datetime.timedelta(hours=72),
          )
          .order_by(database.VelaEncendida.id.desc())
    )

    for v in candidatas:
        horas_transcurridas = (ahora - v.fecha_encendida).total_seconds() / 3600
        if horas_transcurridas < v.duracion_horas:
            horas_restantes = max(0, v.duracion_horas - int(horas_transcurridas))
            velas_activas.append({
                "id": v.id, "nombre": v.nombre, "mensaje": v.mensaje,
                "horas_restantes": horas_restantes,
                "duracion_horas": v.duracion_horas,
                "fecha": fecha_colombia_str(v.fecha_encendida)
            })
        if len(velas_activas) >= 24:
            break
    return {"velas": velas_activas, "total": len(velas_activas)}

@app.post("/api/velas_muro/{identificador}")
def encender_vela_muro(identificador: str, datos: VelaRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(request, "vela_muro", max_calls=3, window=300)
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    duracion = min(72, max(1, datos.duracion_horas))
    nueva_vela = database.VelaEncendida(
        nombre=datos.nombre[:50] if datos.nombre else "Visitante Anónimo",
        mensaje=datos.mensaje[:150] if datos.mensaje else "",
        duracion_horas=duracion,
        perfil_id=perfil.id
    )
    db.add(nueva_vela)
    perfil.velas = (perfil.velas or 0) + 1
    registrar_interaccion(perfil, db)
    return {"mensaje": "Vela encendida", "velas_total": perfil.velas}

# ==========================================
# 🗺️ PREMIUM: MAPA DEL ÚLTIMO DESCANSO
# ==========================================
@app.put("/api/mapa/{identificador}")
def actualizar_mapa(identificador: str, datos: MapaUpdate, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    try:
        float(datos.lat); float(datos.lng)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Coordenadas inválidas")
    perfil.mapa_lat = datos.lat
    perfil.mapa_lng = datos.lng
    perfil.mapa_direccion = datos.direccion[:300] if datos.direccion else ""
    perfil.mapa_descripcion = datos.descripcion[:500] if datos.descripcion else ""
    perfil.mapa_privacidad = datos.privacidad if datos.privacidad in ("publico", "invitados", "privado") else "publico"
    db.commit()
    return {"mensaje": "Mapa actualizado"}

# ==========================================
# 🌳 PREMIUM: ÁRBOL FAMILIAR
# ==========================================
@app.get("/api/familiares/{identificador}")
def listar_familiares(identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    return {"familiares": [
        {"id": f.id, "nombre": f.nombre, "relacion": f.relacion,
         "foto_url": f.foto_url or '', "memorial_id": f.memorial_id or '', "orden": f.orden}
        for f in sorted(perfil.familiares_arbol, key=lambda x: x.orden)
    ]}

@app.post("/api/familiar/{identificador}")
def agregar_familiar(identificador: str, datos: FamiliarRequest, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    nuevo = database.FamiliarArbol(
        nombre=datos.nombre[:80], relacion=datos.relacion,
        foto_url=datos.foto_url[:500] if datos.foto_url else "",
        memorial_id=datos.memorial_id[:100] if datos.memorial_id else "",
        orden=datos.orden, perfil_id=perfil.id
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"id": nuevo.id, "mensaje": "Familiar agregado"}

@app.post("/api/familiar/foto/{identificador}")
async def subir_foto_familiar(identificador: str, request: Request, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    """Sube la foto de un familiar y devuelve su URL. NO la mete a la galería.

    La galería es la vida del difunto, no un directorio de parientes: si la foto
    de una nieta apareciera entre sus recuerdos, el memorial dejaría de ser suyo.
    Por eso va a su propia carpeta y solo se devuelve el enlace, que el árbol
    guarda en foto_url.

    Existe porque el selector solo ofrecía fotos ya subidas, y las caras de los
    familiares no están ahí: quien arma el árbol las tiene en el teléfono."""
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    validar_pin_o_admin(request, perfil)
    try:
        contenido = await archivo.read()
        respuesta = cloudinary.uploader.upload(
            comprimir_imagen(contenido),
            folder=f"memoriales/{identificador}/familiares",
            resource_type="image",
        )
        return {"url": respuesta["secure_url"]}
    except Exception as e:
        print(f"Error subiendo foto de familiar: {e}")
        raise HTTPException(status_code=500, detail="No se pudo subir la foto.")

@app.put("/api/familiar/{familiar_id}")
def editar_familiar(familiar_id: int, datos: FamiliarRequest, request: Request, db: Session = Depends(get_db)):
    """Corregir un familiar ya agregado, en vez de borrarlo y volver a escribirlo.

    Faltaba: solo se podía listar, agregar y eliminar. Arreglar una foto o un
    nombre mal escrito obligaba a borrar a la persona del árbol y volver a
    crearla, lo cual además le cambia el orden."""
    familiar = db.query(database.FamiliarArbol).filter(database.FamiliarArbol.id == familiar_id).first()
    if not familiar: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, familiar.perfil)
    familiar.nombre = datos.nombre[:80]
    familiar.relacion = datos.relacion
    familiar.foto_url = datos.foto_url[:500] if datos.foto_url else ""
    familiar.memorial_id = datos.memorial_id[:100] if datos.memorial_id else ""
    familiar.orden = datos.orden
    db.commit()
    return {"mensaje": "Familiar actualizado"}

@app.delete("/api/familiar/{familiar_id}")
def eliminar_familiar(familiar_id: int, request: Request, db: Session = Depends(get_db)):
    familiar = db.query(database.FamiliarArbol).filter(database.FamiliarArbol.id == familiar_id).first()
    if not familiar: raise HTTPException(status_code=404)
    exigir_pin_o_admin(request, familiar.perfil)
    db.delete(familiar)
    db.commit()
    return {"mensaje": "Familiar eliminado"}
