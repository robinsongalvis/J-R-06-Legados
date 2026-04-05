from fastapi import FastAPI, Request, Depends, HTTPException, File, UploadFile, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import io # <-- LA PIEZA CLAVE PARA QUE CLOUDINARY ACEPTE LOS ARCHIVOS
from sqlalchemy.orm import Session
from pydantic import BaseModel
import datetime
import os
import socket
import random
from typing import List
import requests
import re

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


os.makedirs("static", exist_ok=True) 
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
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
    hoy_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    if perfil.dia_interacciones != hoy_str:
        perfil.interacciones_hoy = 1
        perfil.dia_interacciones = hoy_str
    else:
        perfil.interacciones_hoy += 1
    db.commit()

# --- RUTAS DE IA Y SEGURIDAD ---
@app.post("/api/generar_biografia")
def generar_biografia(datos: DatosIA):
    try:
        url_modelos = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_GEMINI}"
        res_modelos = requests.get(url_modelos)
        if res_modelos.status_code != 200: raise HTTPException(status_code=500, detail="Error API Key")
        lista_modelos = res_modelos.json().get("models", [])
        modelo_elegido = next((m.get("name") for m in lista_modelos if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "").lower()), None)
        if not modelo_elegido: raise HTTPException(status_code=500, detail="Sin modelos")
        instruccion = f"Actúa como un escritor profesional especializado en homenajes y obituarios. Redacta una biografía breve, respetuosa, poética y muy emotiva para un memorial digital basada en estos datos: '{datos.datos_clave}'. No uses lenguaje robótico ni frases cliché. Hazlo sonar humano, reconfortante y divide el texto en 2 o 3 párrafos cortos. No pongas título."
        url_generar = f"https://generativelanguage.googleapis.com/v1beta/{modelo_elegido}:generateContent?key={API_KEY_GEMINI}"
        respuesta = requests.post(url_generar, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": instruccion}]}]})
        if respuesta.status_code != 200: raise HTTPException(status_code=500, detail="Error de Google")
        return {"biografia": respuesta.json()['candidates'][0]['content']['parts'][0]['text']}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error general de la IA")

@app.post("/api/generar_homenaje")
def generar_homenaje(datos: DatosHomenaje):
    try:
        url_modelos = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_GEMINI}"
        res_modelos = requests.get(url_modelos)
        if res_modelos.status_code != 200: raise HTTPException(status_code=500, detail="Error API Key")
        lista_modelos = res_modelos.json().get("models", [])
        modelo_elegido = next((m.get("name") for m in lista_modelos if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", "").lower()), None)
        if not modelo_elegido: raise HTTPException(status_code=500, detail="Sin modelos")
        instruccion = f"Escribe o redacta un hermoso y breve mensaje de condolencia o recuerdo para la persona fallecida '{datos.perfil_nombre}'. Mi relación o anécdota con él/ella es la siguiente: '{datos.parentezco_o_anecdota}'. Quiero publicarlo en su libro de recuerdos (Guestbook). Que el mensaje sea corto (máximo 40 palabras), poético, profundamente empático y cálido, en primera persona hacia él o ella. Omite saludos o despedidas largas. Entrega sólo el texto final sin comillas ni aclaraciones."
        url_generar = f"https://generativelanguage.googleapis.com/v1beta/{modelo_elegido}:generateContent?key={API_KEY_GEMINI}"
        respuesta = requests.post(url_generar, headers={'Content-Type': 'application/json'}, json={"contents": [{"parts": [{"text": instruccion}]}]})
        if respuesta.status_code != 200: raise HTTPException(status_code=500, detail="Error de Google")
        texto_generado = respuesta.json()['candidates'][0]['content']['parts'][0]['text'].strip().replace('"', '')
        return {"homenaje": texto_generado[:150]}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error general de la IA")

@app.post("/api/verificar_pin/{identificador}")
def verificar_pin(identificador: str, req: PinRequest, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    if perfil.pin_familia == req.pin: return {"success": True}
    raise HTTPException(status_code=401, detail="PIN incorrecto")

@app.post("/crear_perfil/")
def crear_perfil(perfil: PerfilDatos, db: Session = Depends(get_db)):
    existente = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == perfil.identificador).first()
    if existente: raise HTTPException(status_code=400, detail="Ese identificador ya existe.")
    nuevo_difunto = database.PerfilDifunto(identificador=perfil.identificador, nombre=perfil.nombre, fechas=perfil.fechas, biografia=perfil.biografia, foto_perfil="https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_1280.png", foto_portada="https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop", en_memoria_de=perfil.en_memoria_de, esposa=perfil.esposa, hijos=perfil.hijos, cancion_favorita=perfil.cancion_favorita, juego_favorito=perfil.juego_favorito, pin_familia=perfil.pin_familia)
    db.add(nuevo_difunto)
    db.commit()
    return {"mensaje": f"Perfil creado."}

@app.put("/editar_perfil/{identificador}")
def editar_perfil(identificador: str, datos_nuevos: PerfilDatos, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    perfil.nombre = datos_nuevos.nombre; perfil.fechas = datos_nuevos.fechas; perfil.biografia = datos_nuevos.biografia; perfil.en_memoria_de = datos_nuevos.en_memoria_de; perfil.esposa = datos_nuevos.esposa; perfil.hijos = datos_nuevos.hijos; perfil.cancion_favorita = datos_nuevos.cancion_favorita; perfil.juego_favorito = datos_nuevos.juego_favorito
    db.commit()
    return {"mensaje": "Perfil actualizado"}

# --- SUBIDAS CLOUDINARY 100% REPARADAS ---
@app.post("/cambiar_foto_perfil/{identificador}")
async def cambiar_foto_perfil(identificador: str, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
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
async def cambiar_foto_portada(identificador: str, archivos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
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
async def subir_fotos(identificador: str, archivos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
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
async def subir_audio_voz(identificador: str, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
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
def eliminar_foto(foto_id: int, db: Session = Depends(get_db)):
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    try:
        url_partes = foto.url_foto.split('/')
        cloudinary.uploader.destroy("/".join(url_partes[url_partes.index("memoriales"):]).split('.')[0], resource_type="image")
    except: pass
    db.delete(foto)
    db.commit()
    return {"mensaje": "Foto eliminada"}

# --- RUTAS DE RECUERDOS Y MOMENTOS ---
@app.post("/dejar_mensaje/{identificador}")
def dejar_mensaje(identificador: str, mensaje: MensajeNuevo, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    nuevo_msj = database.MensajeRecuerdo(autor=mensaje.autor, texto=mensaje.texto[:150], perfil_id=perfil.id)
    db.add(nuevo_msj)
    registrar_interaccion(perfil, db)
    return {"mensaje": "Recuerdo guardado"}

@app.post("/likear_mensaje/{mensaje_id}")
def likear_mensaje(mensaje_id: int, db: Session = Depends(get_db)):
    mensaje = db.query(database.MensajeRecuerdo).filter(database.MensajeRecuerdo.id == mensaje_id).first()
    if not mensaje: raise HTTPException(status_code=404)
    mensaje.likes += 1
    if mensaje.perfil: registrar_interaccion(mensaje.perfil, db)
    return {"likes": mensaje.likes}

@app.delete("/eliminar_mensaje/{mensaje_id}")
def eliminar_mensaje(mensaje_id: int, db: Session = Depends(get_db)):
    mensaje = db.query(database.MensajeRecuerdo).filter(database.MensajeRecuerdo.id == mensaje_id).first()
    if not mensaje: raise HTTPException(status_code=404)
    db.delete(mensaje)
    db.commit()
    return {"mensaje": "Mensaje eliminado"}

@app.post("/agregar_momento/{identificador}")
def agregar_momento(identificador: str, momento: MomentoNuevo, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    nuevo_momento = database.MomentoInolvidable(anio=momento.anio, titulo=momento.titulo, descripcion=momento.descripcion, perfil_id=perfil.id)
    db.add(nuevo_momento)
    db.commit()
    return {"mensaje": "Momento agregado"}

@app.put("/editar_momento/{momento_id}")
def editar_momento(momento_id: int, momento: MomentoNuevo, db: Session = Depends(get_db)):
    momento_db = db.query(database.MomentoInolvidable).filter(database.MomentoInolvidable.id == momento_id).first()
    if not momento_db: raise HTTPException(status_code=404)
    momento_db.anio = momento.anio; momento_db.titulo = momento.titulo; momento_db.descripcion = momento.descripcion
    db.commit()
    return {"mensaje": "Momento actualizado"}

@app.delete("/eliminar_momento/{momento_id}")
def eliminar_momento(momento_id: int, db: Session = Depends(get_db)):
    momento = db.query(database.MomentoInolvidable).filter(database.MomentoInolvidable.id == momento_id).first()
    if not momento: raise HTTPException(status_code=404)
    db.delete(momento)
    db.commit()
    return {"mensaje": "Momento eliminado"}

@app.post("/api/encender_vela/{identificador}")
def encender_vela(identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if perfil.velas is None: perfil.velas = 0
    perfil.velas += 1
    registrar_interaccion(perfil, db)
    return {"velas": perfil.velas}

@app.post("/api/likear_foto/{foto_id}")
def likear_foto(foto_id: int, db: Session = Depends(get_db)):
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    if foto.likes is None: foto.likes = 0
    foto.likes += 1
    db.commit() 
    if foto.perfil: registrar_interaccion(foto.perfil, db)
    return {"likes": foto.likes}

@app.post("/api/comentar_foto/{foto_id}")
def comentar_foto(foto_id: int, comentario: ComentarioNuevo, db: Session = Depends(get_db)):
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    nuevo_comentario = database.ComentarioFoto(texto=comentario.texto[:120], foto_id=foto.id)
    db.add(nuevo_comentario)
    db.commit()
    if foto.perfil: registrar_interaccion(foto.perfil, db)
    return {"mensaje": "Comentario agregado"}

class PinUpdate(BaseModel): nuevo_pin: str
@app.put("/api/admin/reset_pin/{identificador}")
def reset_pin_perfil(identificador: str, datos: PinUpdate, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    perfil.pin_familia = datos.nuevo_pin
    db.commit()
    return {"mensaje": "PIN actualizado correctamente"}

@app.delete("/api/admin/eliminar_perfil/{identificador}")
def eliminar_perfil_completo(identificador: str, db: Session = Depends(get_db)):
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

# 🎬 CONSTRUCCIÓN DE LA VISTA PRINCIPAL 🎬
@app.get("/perfil/{identificador}", response_class=HTMLResponse)
def ver_perfil(request: Request, identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: return HTMLResponse(content="<h1>Error 404: Perfil no encontrado</h1>", status_code=404)

    hoy_str = datetime.datetime.utcnow().strftime("%Y-%m-%d")
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

    foto_aleatoria = random.choice(fotos_feed) if fotos_feed else None
    foto_mas_recordada = max(fotos_feed, key=lambda f: f["likes"]) if fotos_feed and total_corazones_galeria > 0 else None

    mensajes_feed = [{"id": m.id, "autor": m.autor, "texto": m.texto, "fecha": m.fecha_creacion.strftime("%d/%m/%Y"), "likes": m.likes} for m in reversed(perfil.mensajes)]
    momentos_feed = [{"id": m.id, "anio": m.anio, "titulo": m.titulo, "descripcion": m.descripcion, "icono": obtener_icono_momento(m.titulo)} for m in perfil.momentos]
    momentos_feed.sort(key=lambda x: parse_date_for_sorting(x["anio"])) # ✅ CRONOLOGÍA AUTOMÁTICA
    
    es_video_perfil = perfil.foto_perfil.endswith(('.mp4', '.mov', '.webm'))
    
    portadas_raw = perfil.foto_portada.split(',') if perfil.foto_portada else ["https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop"]
    lista_portadas = [{"url": p.strip(), "es_video": p.endswith(('.mp4', '.mov', '.webm'))} for p in portadas_raw if p.strip()]
    
    datos_diccionario = {
        "identificador": perfil.identificador, "nombre": perfil.nombre, "fechas": perfil.fechas,
        "biografia": perfil.biografia, "foto_perfil": perfil.foto_perfil, 
        "portadas": lista_portadas, "foto_portada_og": lista_portadas[0]["url"] if lista_portadas else "",
        "es_video_perfil": es_video_perfil, "visitas": perfil.visitas, "ultima_visita": perfil.ultima_visita.strftime("%d/%m/%Y"), 
        "en_memoria_de": perfil.en_memoria_de, "esposa": perfil.esposa, "hijos": perfil.hijos, 
        "cancion_favorita": perfil.cancion_favorita, "juego_favorito": perfil.juego_favorito, 
        "fotos": fotos_feed, "mensajes": mensajes_feed, "momentos": momentos_feed, "velas": perfil.velas or 0,
        "interacciones_hoy": perfil.interacciones_hoy,
        "total_corazones_galeria": total_corazones_galeria,
        "foto_aleatoria": foto_aleatoria,
        "foto_mas_recordada": foto_mas_recordada,
        "audio_voz": getattr(perfil, 'audio_voz', '') # ✅ AUDIO REAL
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
def estadisticas_admin(db: Session = Depends(get_db)):
    perfiles = db.query(database.PerfilDifunto).all()
    return {
        "total_perfiles": len(perfiles), "total_visitas": sum([p.visitas for p in perfiles]), 
        "perfiles": [{"identificador": p.identificador, "nombre": p.nombre, "visitas": p.visitas, "ultima_visita": p.ultima_visita.strftime("%d/%m/%Y") if p.ultima_visita else "Nueva", "pin": p.pin_familia} for p in perfiles]
    }

@app.get("/api/admin/moderacion")
def datos_moderacion(db: Session = Depends(get_db)):
    fotos = db.query(database.FotoGaleria).all()
    mensajes = db.query(database.MensajeRecuerdo).all()
    return {"fotos": [{"id": f.id, "url": f.url_foto, "perfil": f.perfil.nombre} for f in fotos if f.perfil], "mensajes": [{"id": m.id, "autor": m.autor, "texto": m.texto, "perfil": m.perfil.nombre} for m in mensajes if m.perfil]}