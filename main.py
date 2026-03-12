from fastapi import FastAPI, Request, Depends, HTTPException, File, UploadFile, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from io import BytesIO
from sqlalchemy.orm import Session
from pydantic import BaseModel
import datetime
import os
import socket
from typing import List
import requests

import cloudinary
import cloudinary.uploader
from PIL import Image, ImageOps

# --- EL LECTOR DE LA CAJA FUERTE ---
from dotenv import load_dotenv
load_dotenv() # Esto abre el archivo .env en secreto

# =========================================================
# 🔑 LECTURA DE LLAVES SEGURAS (Desde el .env)
# =========================================================
API_KEY_GEMINI = os.getenv("GEMINI_API_KEY")

cloudinary.config( 
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"), 
  api_key = os.getenv("CLOUDINARY_API_KEY"), 
  api_secret = os.getenv("CLOUDINARY_API_SECRET"),
  secure = True
)
# =========================================================

import database

app = FastAPI(title="Memorial Digital QR")

os.makedirs("static", exist_ok=True) 
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuración de los templates HTML
templates = Jinja2Templates(directory="templates")

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

def get_db():
    db = database.SessionLocal()
    try: yield db
    finally: db.close()

def obtener_ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# --- COMPRESOR MÁGICO DE IMÁGENES ---
def comprimir_imagen(file_content):
    try:
        img = Image.open(BytesIO(file_content))
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((1600, 1600)) 
        buffer = BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=80)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"Error al comprimir: {e}")
        return BytesIO(file_content) 

# --- RUTA MÁGICA: REDACTOR CON IA ---
@app.post("/api/generar_biografia")
def generar_biografia(datos: DatosIA):
    try:
        url_modelos = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_GEMINI}"
        res_modelos = requests.get(url_modelos)
        
        if res_modelos.status_code != 200:
            raise HTTPException(status_code=500, detail="Error de API Key")
            
        lista_modelos = res_modelos.json().get("models", [])
        
        modelo_elegido = None
        for m in lista_modelos:
            nombre = m.get("name", "")
            metodos = m.get("supportedGenerationMethods", [])
            if "generateContent" in metodos and "gemini" in nombre.lower():
                modelo_elegido = nombre
                break
                
        if not modelo_elegido:
            raise HTTPException(status_code=500, detail="Sin modelos")
            
        instruccion = f"Actúa como un escritor profesional especializado en homenajes y obituarios. Redacta una biografía breve, respetuosa, poética y muy emotiva para un memorial digital basada en estos datos: '{datos.datos_clave}'. No uses lenguaje robótico ni frases cliché. Hazlo sonar humano, reconfortante y divide el texto en 2 o 3 párrafos cortos. No pongas título."
        
        url_generar = f"https://generativelanguage.googleapis.com/v1beta/{modelo_elegido}:generateContent?key={API_KEY_GEMINI}"
        headers = {'Content-Type': 'application/json'}
        payload = {"contents": [{"parts": [{"text": instruccion}]}]}
        
        respuesta = requests.post(url_generar, headers=headers, json=payload)
        
        if respuesta.status_code != 200:
            raise HTTPException(status_code=500, detail="Error de Google")
            
        datos_json = respuesta.json()
        texto_final = datos_json['candidates'][0]['content']['parts'][0]['text']
        
        return {"biografia": texto_final}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error general de la IA")

# --- RUTAS RESTANTES DEL SISTEMA ---
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
    foto_defecto = "https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_1280.png"
    portada_defecto = "https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop"
    nuevo_difunto = database.PerfilDifunto(identificador=perfil.identificador, nombre=perfil.nombre, fechas=perfil.fechas, biografia=perfil.biografia, foto_perfil=foto_defecto, foto_portada=portada_defecto, en_memoria_de=perfil.en_memoria_de, esposa=perfil.esposa, hijos=perfil.hijos, cancion_favorita=perfil.cancion_favorita, juego_favorito=perfil.juego_favorito, pin_familia=perfil.pin_familia)
    db.add(nuevo_difunto)
    db.commit()
    return {"mensaje": f"Perfil creado."}

@app.put("/editar_perfil/{identificador}")
def editar_perfil(identificador: str, datos_nuevos: PerfilDatos, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    perfil.nombre = datos_nuevos.nombre
    perfil.fechas = datos_nuevos.fechas
    perfil.biografia = datos_nuevos.biografia
    perfil.en_memoria_de = datos_nuevos.en_memoria_de
    perfil.esposa = datos_nuevos.esposa
    perfil.hijos = datos_nuevos.hijos
    perfil.cancion_favorita = datos_nuevos.cancion_favorita
    perfil.juego_favorito = datos_nuevos.juego_favorito
    db.commit()
    return {"mensaje": "Perfil actualizado"}

# --- SUBIDAS A CLOUDINARY (SOPORTE PARA FOTOS Y VIDEOS) ---
@app.post("/cambiar_foto_perfil/{identificador}")
async def cambiar_foto_perfil(identificador: str, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    
    contenido = await archivo.read()
    es_video = archivo.content_type.startswith('video/')
    
    if es_video:
        # Si es un video, Cloudinary lo recibe directo y lo optimiza
        respuesta_cloud = cloudinary.uploader.upload(
            contenido, 
            folder=f"memoriales/{identificador}/perfiles",
            resource_type="video"
        )
    else:
        # Si es imagen, usamos el compresor de siempre
        imagen_optimizada = comprimir_imagen(contenido)
        respuesta_cloud = cloudinary.uploader.upload(
            imagen_optimizada, 
            folder=f"memoriales/{identificador}/perfiles",
            resource_type="image"
        )
        
    perfil.foto_perfil = respuesta_cloud['secure_url']
    db.commit()
    return {"mensaje": "Medio de perfil actualizado", "url": respuesta_cloud['secure_url']}

@app.post("/cambiar_foto_portada/{identificador}")
async def cambiar_foto_portada(identificador: str, archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    
    contenido = await archivo.read()
    es_video = archivo.content_type.startswith('video/')
    
    if es_video:
        respuesta_cloud = cloudinary.uploader.upload(
            contenido, 
            folder=f"memoriales/{identificador}/portadas",
            resource_type="video"
        )
    else:
        imagen_optimizada = comprimir_imagen(contenido)
        respuesta_cloud = cloudinary.uploader.upload(
            imagen_optimizada, 
            folder=f"memoriales/{identificador}/portadas",
            resource_type="image"
        )
        
    perfil.foto_portada = respuesta_cloud['secure_url']
    db.commit()
    return {"mensaje": "Portada actualizada", "url": respuesta_cloud['secure_url']}

@app.post("/subir_fotos/{identificador}")
async def subir_fotos(identificador: str, archivos: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    
    fotos_guardadas = []
    for archivo in archivos:
        contenido = await archivo.read()
        imagen_optimizada = comprimir_imagen(contenido)
        
        respuesta_cloud = cloudinary.uploader.upload(imagen_optimizada, folder=f"memoriales/{identificador}/galeria")
        
        nueva_foto = database.FotoGaleria(url_foto=respuesta_cloud['secure_url'], perfil_id=perfil.id)
        db.add(nueva_foto)
        db.commit()
        db.refresh(nueva_foto)
        fotos_guardadas.append({"id": nueva_foto.id, "url": respuesta_cloud['secure_url']})
        
    return {"fotos": fotos_guardadas}

@app.delete("/eliminar_foto/{foto_id}")
def eliminar_foto(foto_id: int, db: Session = Depends(get_db)):
    foto = db.query(database.FotoGaleria).filter(database.FotoGaleria.id == foto_id).first()
    if not foto: raise HTTPException(status_code=404)
    
    try:
        url_partes = foto.url_foto.split('/')
        public_id_con_ext = "/".join(url_partes[url_partes.index("memoriales"):])
        public_id = public_id_con_ext.split('.')[0]
        # Eliminamos asumiendo que es imagen, aunque para galería mantuvimos solo imágenes por ahora
        cloudinary.uploader.destroy(public_id, resource_type="image")
    except:
        pass
        
    db.delete(foto)
    db.commit()
    return {"mensaje": "Foto eliminada"}

@app.post("/dejar_mensaje/{identificador}")
def dejar_mensaje(identificador: str, mensaje: MensajeNuevo, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: raise HTTPException(status_code=404)
    nuevo_msj = database.MensajeRecuerdo(autor=mensaje.autor, texto=mensaje.texto[:150], perfil_id=perfil.id)
    db.add(nuevo_msj)
    db.commit()
    return {"mensaje": "Recuerdo guardado"}

@app.post("/likear_mensaje/{mensaje_id}")
def likear_mensaje(mensaje_id: int, db: Session = Depends(get_db)):
    mensaje = db.query(database.MensajeRecuerdo).filter(database.MensajeRecuerdo.id == mensaje_id).first()
    if not mensaje: raise HTTPException(status_code=404)
    mensaje.likes += 1
    db.commit()
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
    momento_db.anio = momento.anio
    momento_db.titulo = momento.titulo
    momento_db.descripcion = momento.descripcion
    db.commit()
    return {"mensaje": "Momento actualizado"}

@app.delete("/eliminar_momento/{momento_id}")
def eliminar_momento(momento_id: int, db: Session = Depends(get_db)):
    momento = db.query(database.MomentoInolvidable).filter(database.MomentoInolvidable.id == momento_id).first()
    if not momento: raise HTTPException(status_code=404)
    db.delete(momento)
    db.commit()
    return {"mensaje": "Momento eliminado"}

# --- NUEVA FUNCIÓN: RECUPERACIÓN DE CONTRASEÑA (PIN) ---
class PinUpdate(BaseModel):
    nuevo_pin: str

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
    
    try:
        cloudinary.api.delete_resources_by_prefix(f"memoriales/{identificador}/")
        cloudinary.api.delete_folder(f"memoriales/{identificador}")
    except:
        pass
        
    for foto in perfil.fotos_galeria: db.delete(foto)
    for msj in perfil.mensajes: db.delete(msj)
    for mom in perfil.momentos: db.delete(mom)
    db.delete(perfil)
    db.commit()
    return {"mensaje": "Perfil y archivos eliminados correctamente."}

@app.get("/perfil/{identificador}", response_class=HTMLResponse)
def ver_perfil(request: Request, identificador: str, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil: return HTMLResponse(content="<h1>Error 404: Perfil no encontrado</h1>", status_code=404)

    nombre_cookie = f"visita_{identificador}"
    if not request.cookies.get(nombre_cookie):
        perfil.visitas += 1
        perfil.ultima_visita = datetime.datetime.utcnow()
        db.commit()

    fotos_feed = [{"id": foto.id, "url": foto.url_foto} for foto in reversed(perfil.fotos_galeria)]
    mensajes_feed = [{"id": m.id, "autor": m.autor, "texto": m.texto, "fecha": m.fecha_creacion.strftime("%d/%m/%Y"), "likes": m.likes} for m in reversed(perfil.mensajes)]
    momentos_feed = [{"id": m.id, "anio": m.anio, "titulo": m.titulo, "descripcion": m.descripcion} for m in perfil.momentos]
    
    # AGREGAMOS LAS VARIABLES QUE LE DICEN A HTML SI ES VIDEO O IMAGEN
    es_video_perfil = perfil.foto_perfil.endswith('.mp4') or perfil.foto_perfil.endswith('.mov') or perfil.foto_perfil.endswith('.webm')
    es_video_portada = perfil.foto_portada.endswith('.mp4') or perfil.foto_portada.endswith('.mov') or perfil.foto_portada.endswith('.webm')
    
    datos_diccionario = {
        "identificador": perfil.identificador, "nombre": perfil.nombre, "fechas": perfil.fechas,
        "biografia": perfil.biografia, "foto_perfil": perfil.foto_perfil, "foto_portada": perfil.foto_portada,
        "es_video_perfil": es_video_perfil, "es_video_portada": es_video_portada, # Nuevas banderas
        "visitas": perfil.visitas, "ultima_visita": perfil.ultima_visita.strftime("%d/%m/%Y"), 
        "en_memoria_de": perfil.en_memoria_de, "esposa": perfil.esposa, "hijos": perfil.hijos, 
        "cancion_favorita": perfil.cancion_favorita, "juego_favorito": perfil.juego_favorito, 
        "fotos": fotos_feed, "mensajes": mensajes_feed, "momentos": momentos_feed
    }

    pagina_html = templates.TemplateResponse("perfil.html", {"request": request, **datos_diccionario})
    if not request.cookies.get(nombre_cookie):
        pagina_html.set_cookie(key=nombre_cookie, value="visitado", max_age=86400)
    return pagina_html


# ----------------------------------------------------
# GENERADOR DE PÁGINA DE IMPRESIÓN QR (HTML/VECTORES)
# ----------------------------------------------------
@app.get("/generar_qr/{identificador}")
def generar_qr_elegante(identificador: str, request: Request, db: Session = Depends(get_db)):
    perfil = db.query(database.PerfilDifunto).filter(database.PerfilDifunto.identificador == identificador).first()
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    # Obtenemos la URL exacta a la que llevará el QR
    url_perfil = str(request.base_url) + f"perfil/{identificador}"

    # Renderizamos la nueva plantilla HTML pasándole la URL para que arme el código
    return templates.TemplateResponse("imprimir_qr.html", {
        "request": request,
        "url_perfil": url_perfil,
        "nombre": perfil.nombre
    })


@app.get("/admin/", response_class=HTMLResponse)
def panel_admin(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.get("/api/admin/estadisticas")
def estadisticas_admin(db: Session = Depends(get_db)):
    perfiles = db.query(database.PerfilDifunto).all()
    total_visitas = sum([p.visitas for p in perfiles])
    lista_perfiles = []
    for p in perfiles:
        lista_perfiles.append({
            "identificador": p.identificador, 
            "nombre": p.nombre, 
            "visitas": p.visitas,
            "ultima_visita": p.ultima_visita.strftime("%d/%m/%Y") if p.ultima_visita else "Nueva",
            "pin": p.pin_familia
        })
    return {"total_perfiles": len(perfiles), "total_visitas": total_visitas, "perfiles": lista_perfiles}

@app.get("/api/admin/moderacion")
def datos_moderacion(db: Session = Depends(get_db)):
    fotos = db.query(database.FotoGaleria).all()
    lista_fotos = [{"id": f.id, "url": f.url_foto, "perfil": f.perfil.nombre} for f in fotos if f.perfil]
    
    mensajes = db.query(database.MensajeRecuerdo).all()
    lista_mensajes = [{"id": m.id, "autor": m.autor, "texto": m.texto, "perfil": m.perfil.nombre} for m in mensajes if m.perfil]
    
    return {"fotos": lista_fotos, "mensajes": lista_mensajes}