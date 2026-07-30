"""Siembra el memorial `demo` completo para probar en local.

    ALLOW_INSECURE_DEV_AUTH=true .venv/bin/python scratch_seed.py

Crea a Roberto Galvis con galería, momentos, recuerdos, árbol familiar y mapa.
PIN familiar: 1234. Borra y rehace el perfil en cada corrida, así que sirve para
volver a un estado conocido después de romper algo probando.

NO siembra `esposa`, `hijos` ni `juego_favorito`. Esas columnas siguen en la base
como respaldo de la migración de la Fase 2, pero ya no se muestran — y llenarlas
rompía la demo: la migración las convertía en familiares nuevos y, como "David"
no coincide con "David Galvis", el árbol terminaba con siete personas en vez de
cuatro.
"""
import datetime
import database as db

s = db.SessionLocal()

ident = "demo"
existente = s.query(db.PerfilDifunto).filter(db.PerfilDifunto.identificador == ident).first()
if existente:
    s.delete(existente)
    s.commit()

p = db.PerfilDifunto(
    identificador=ident,
    nombre="Roberto Galvis Mendoza",
    fechas="1948 — 2023",
    biografia=("Padre, abuelo y maestro de vida. Roberto dedicó su vida a la enseñanza y a su familia. "
               "Amaba la música, los domingos de fútbol y las tardes de café con sus nietos. "
               "Su risa llenaba cualquier habitación y su sabiduría dejó huella en todos los que lo conocieron."),
    foto_perfil="https://images.unsplash.com/photo-1552058544-f2b08422138a?q=80&w=800&auto=format&fit=crop",
    foto_portada="https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop,https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?q=80&w=1200&auto=format&fit=crop",
    en_memoria_de="Su esposa Carmen y sus tres hijos",
    cancion_favorita="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    pin_familia="1234",
    visitas=1287,
    ultima_visita=datetime.datetime.utcnow(),
    velas=342,
    tema_visual="noche",
    mapa_lat="4.6097",
    mapa_lng="-74.0817",
    mapa_direccion="Cementerio Jardines de Paz, Bogotá",
    mapa_descripcion="Un lugar tranquilo rodeado de árboles.",
    mapa_privacidad="publico",
)
s.add(p)
s.commit()
s.refresh(p)

fotos_urls = [
    "https://images.unsplash.com/photo-1511895426328-dc8714191300?q=80&w=800&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1529156069898-49953e39b3ac?q=80&w=800&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1490578474895-699cd4e2cf59?q=80&w=800&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1542037104857-ffbb0b9155fb?q=80&w=800&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1516627145497-ae6968895b74?q=80&w=800&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1471897488648-5eae4ac6686b?q=80&w=800&auto=format&fit=crop",
]
for i, u in enumerate(fotos_urls):
    f = db.FotoGaleria(url_foto=u, perfil_id=p.id, likes=(i * 7 + 3))
    s.add(f)
    s.flush()
    s.add(db.ComentarioFoto(texto="Qué hermoso recuerdo 🤍", foto_id=f.id))
    s.add(db.ComentarioFoto(texto="Lo extrañamos mucho", foto_id=f.id))
s.commit()

mensajes = [
    ("Ana", "Papá, cada día pienso en ti. Gracias por todo lo que nos enseñaste."),
    ("Miguel", "Tu recuerdo vive en cada partida de ajedrez que juego."),
    ("Carmen", "Mi amor eterno, hasta que nos volvamos a encontrar."),
    ("Luis (vecino)", "Un gran hombre, siempre con una sonrisa y una mano amiga."),
]
for autor, texto in mensajes:
    s.add(db.MensajeRecuerdo(autor=autor, texto=texto, perfil_id=p.id, likes=12))
s.commit()

momentos = [
    ("1948", "Nacimiento", "Nació en un pequeño pueblo lleno de amor."),
    ("1972", "Boda con Carmen", "El día más feliz, el inicio de una gran familia."),
    ("1980", "Nace su primer hijo", "David llegó para llenar de alegría el hogar."),
    ("1995", "Maestro del año", "Reconocido por décadas de dedicación a la enseñanza."),
    ("2010", "Primer nieto", "Se convirtió en el abuelo más orgulloso."),
]
for anio, titulo, desc in momentos:
    s.add(db.MomentoInolvidable(anio=anio, titulo=titulo, descripcion=desc, perfil_id=p.id))
s.commit()

familiares = [
    ("Carmen Rodríguez", "Esposa", 0),
    ("David Galvis", "Hijo", 1),
    ("Ana Galvis", "Hija", 2),
    ("Miguel Galvis", "Hijo", 3),
]
for nombre, rel, orden in familiares:
    s.add(db.FamiliarArbol(nombre=nombre, relacion=rel, perfil_id=p.id, orden=orden,
                           foto_url="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?q=80&w=400&auto=format&fit=crop"))
s.commit()

print("SEED OK ->", ident)
s.close()
