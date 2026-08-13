import os
import datetime
import ssl
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

# 1. Abrimos la caja fuerte
load_dotenv()

# 2. Leemos la URL de Neon.tech
#
# SIN valor por defecto a propósito. Antes caía a un SQLite local, y en Render ese
# archivo vive en un disco que se borra en cada despliegue: la app arrancaba
# "bien" y los memoriales desaparecían en silencio. Es preferible que no arranque
# a que pierda los recuerdos de una familia.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
_PERMITIR_SQLITE_LOCAL = os.getenv("ALLOW_INSECURE_DEV_AUTH", "false").lower() == "true"

if not SQLALCHEMY_DATABASE_URL:
    if _PERMITIR_SQLITE_LOCAL:
        SQLALCHEMY_DATABASE_URL = "sqlite:///./memoriales.db"
    else:
        raise ValueError(
            "FATAL: falta la variable de entorno DATABASE_URL. La aplicación no "
            "arranca sin base de datos persistente para no perder los memoriales. "
            "Configúrala en Render (Environment) o, solo para pruebas locales, "
            "define ALLOW_INSECURE_DEV_AUTH=true para usar SQLite."
        )

# 3. EL CORTADOR MÁGICO: Borra cualquier parámetro extra que confunda al sistema
if "?" in SQLALCHEMY_DATABASE_URL and not SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.split("?")[0]

# 4. Corrección para usar el nuevo traductor "pg8000"
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql+pg8000://", 1)
elif SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)

# 5. Conectamos el motor (Con escudo de seguridad SSL nativo para la nube)
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Creamos el túnel seguro SSL
    ctx = ssl.create_default_context()
    # En producción: verificación SSL completa (default)
    # Para desarrollo local: DB_SSL_REQUIRED=false deshabilita verificación
    if os.getenv("DB_SSL_REQUIRED", "true").lower() == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"ssl_context": ctx})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==========================================
# MODELOS DE TABLAS
# ==========================================

class PerfilDifunto(Base):
    __tablename__ = "perfiles"

    id = Column(Integer, primary_key=True, index=True)
    identificador = Column(String, unique=True, index=True)
    nombre = Column(String, index=True)
    fechas = Column(String)
    biografia = Column(Text)
    
    foto_perfil = Column(String)
    foto_portada = Column(String, default="https://images.unsplash.com/photo-1444065707204-12decac917e8?q=80&w=1200&auto=format&fit=crop")
    
    en_memoria_de = Column(String, default="")
    esposa = Column(String, default="")
    hijos = Column(String, default="")
    cancion_favorita = Column(String, default="")
    juego_favorito = Column(String, default="")
    
    pin_familia = Column(String, default="0000")
    
    visitas = Column(Integer, default=0)
    ultima_visita = Column(DateTime, default=datetime.datetime.utcnow)
    
    audio_voz = Column(String, default="")
    
    # 🕯️ CONTADOR DE VELAS VIRTUALES
    velas = Column(Integer, default=0)

    # ❤️ NUEVO: MÉTRICAS DE INTERACCIÓN DIARIA
    interacciones_hoy = Column(Integer, default=0)
    dia_interacciones = Column(String, default="")

    # 🎨 PREMIUM: TEMA VISUAL
    tema_visual = Column(String, default="noche")

    # 🗺️ PREMIUM: MAPA DEL ÚLTIMO DESCANSO
    mapa_lat = Column(String, default="")
    mapa_lng = Column(String, default="")
    mapa_direccion = Column(String, default="")
    mapa_descripcion = Column(String, default="")
    mapa_privacidad = Column(String, default="publico")

    # 📒 GESTIÓN DEL NEGOCIO (solo admin)
    # Datos personales de la familia que compró el memorial. NUNCA se envían a
    # perfil.html: la página pública se arma con un diccionario explícito en
    # main.py, así que estos campos solo salen por los endpoints /api/admin/*.
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)
    contacto_nombre = Column(String, default="")
    contacto_telefono = Column(String, default="")
    contacto_email = Column(String, default="")
    estado_pago = Column(String, default="pendiente")  # pendiente | pagado | cortesia
    notas_internas = Column(Text, default="")

    # Cuándo se le avisó por última vez a la familia de un recuerdo nuevo.
    # Sirve para no mandarles veinte correos la tarde del funeral: ver
    # ESPERA_ENTRE_AVISOS en notificaciones.py.
    ultimo_aviso = Column(DateTime, nullable=True)

    # Relaciones con otras tablas
    #
    # order_by explícito: sin ORDER BY, Postgres puede devolver las filas en el
    # orden que le convenga, y ese orden cambia cuando una fila se actualiza (por
    # ejemplo al dar un corazón a una foto). El código las recorre con reversed()
    # dando por hecho que van de la más vieja a la más nueva, así que el orden
    # tiene que pedirse, no suponerse.
    fotos_galeria = relationship("FotoGaleria", back_populates="perfil", order_by="FotoGaleria.id")
    mensajes = relationship("MensajeRecuerdo", back_populates="perfil", order_by="MensajeRecuerdo.id")
    momentos = relationship("MomentoInolvidable", back_populates="perfil")
    velas_list = relationship("VelaEncendida", back_populates="perfil", cascade="all, delete-orphan", order_by="VelaEncendida.id")
    familiares_arbol = relationship("FamiliarArbol", back_populates="perfil", cascade="all, delete-orphan")

class FotoGaleria(Base):
    __tablename__ = "fotos_galeria"
    id = Column(Integer, primary_key=True, index=True)
    url_foto = Column(String)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="fotos_galeria")
    
    # ❤️ NUEVO: CORAZONES Y COMENTARIOS DE LA GALERÍA
    likes = Column(Integer, default=0)
    comentarios = relationship("ComentarioFoto", back_populates="foto", cascade="all, delete-orphan")

# 💬 NUEVA TABLA: COMENTARIOS CORTOS POR FOTO
class ComentarioFoto(Base):
    __tablename__ = "comentarios_foto"
    id = Column(Integer, primary_key=True, index=True)
    texto = Column(String(120))
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)
    foto_id = Column(Integer, ForeignKey("fotos_galeria.id"))
    foto = relationship("FotoGaleria", back_populates="comentarios")

class MensajeRecuerdo(Base):
    __tablename__ = "mensajes_recuerdo"
    id = Column(Integer, primary_key=True, index=True)
    autor = Column(String)
    texto = Column(Text)
    likes = Column(Integer, default=0)
    fecha_creacion = Column(DateTime, default=datetime.datetime.utcnow)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="mensajes")

class MomentoInolvidable(Base):
    __tablename__ = "momentos_inolvidables"
    id = Column(Integer, primary_key=True, index=True)
    anio = Column(String)
    titulo = Column(String)
    descripcion = Column(Text)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="momentos")

class VelaEncendida(Base):
    __tablename__ = "velas_encendidas"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, default="Visitante Anónimo")
    mensaje = Column(String(150), default="")
    duracion_horas = Column(Integer, default=24)
    fecha_encendida = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    # Indexado: esta tabla es la que más crece (una fila por vela encendida) y se
    # consulta por perfil en cada visita al memorial.
    perfil_id = Column(Integer, ForeignKey("perfiles.id"), index=True)
    perfil = relationship("PerfilDifunto", back_populates="velas_list")

class FamiliarArbol(Base):
    """Una persona del árbol. Con jerarquía: puede descender de otra y tener pareja.

    'relacion' es relativa a AQUEL DE QUIEN DESCIENDE, no al difunto. El hijo de
    una hija es "Hijo" —hijo de ella—, y que sea nieto del homenajeado se deduce
    de su posición en el árbol. Decirlo al revés obligaría a cada persona a saber
    a qué distancia está del difunto, y esa distancia cambia cuando el árbol
    crece por arriba.

    padre_id nulo significa "cuelga del homenajeado": es el caso de sus padres,
    sus hermanos y sus hijos, y es lo que tenían todas las filas antes de que
    existiera la jerarquía. Por eso los datos viejos siguen siendo correctos.

    LOS HIJOS CUELGAN DE UNA SOLA PERSONA, no de la pareja. Genealógicamente lo
    correcto sería una entidad "unión", pero eso son dos tablas y tres consultas
    más para agregar a alguien. Acá el vínculo de pareja es aparte (pareja_id) y
    quien dibuja junta a los dos y les pone los hijos debajo es la interfaz: el
    árbol se ve correcto sin que agregar a un nieto cueste tres pasos.
    """
    __tablename__ = "familiares_arbol"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    relacion = Column(String)
    foto_url = Column(String, default="")
    memorial_id = Column(String, default="")
    orden = Column(Integer, default=0)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="familiares_arbol")

    padre_id = Column(Integer, ForeignKey("familiares_arbol.id"), nullable=True, index=True)
    pareja_id = Column(Integer, ForeignKey("familiares_arbol.id"), nullable=True)

# Esto crea las tablas automáticamente en Neon.tech si no existen
Base.metadata.create_all(bind=engine)

# ==========================================
# MAGIA DE ACTUALIZACIÓN SEGURA INDIVIDUAL
# ==========================================
try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN velas INTEGER DEFAULT 0"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fotos_galeria ADD COLUMN likes INTEGER DEFAULT 0"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN interacciones_hoy INTEGER DEFAULT 0"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN dia_interacciones VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN audio_voz VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN tema_visual VARCHAR DEFAULT 'noche'"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN mapa_lat VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN mapa_lng VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN mapa_direccion VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN mapa_descripcion VARCHAR DEFAULT ''"))
except Exception:
    pass

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE perfiles ADD COLUMN mapa_privacidad VARCHAR DEFAULT 'publico'"))
except Exception:
    pass

# Campos de gestión del negocio. Misma idea que los de arriba (si la columna ya
# existe, el ALTER falla y se ignora), pero en lote porque entraron todos juntos.
#
# fecha_creacion va SIN DEFAULT a propósito: SQLite no acepta CURRENT_TIMESTAMP
# como default en un ALTER TABLE. Los perfiles que ya existían quedan en NULL,
# que es lo honesto: de esos no sabemos cuándo se vendieron.
_COLUMNAS_GESTION = [
    "fecha_creacion TIMESTAMP",
    "contacto_nombre VARCHAR DEFAULT ''",
    "contacto_telefono VARCHAR DEFAULT ''",
    "contacto_email VARCHAR DEFAULT ''",
    "estado_pago VARCHAR DEFAULT 'pendiente'",
    "notas_internas TEXT DEFAULT ''",
    "ultimo_aviso TIMESTAMP",
]

for _columna in _COLUMNAS_GESTION:
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE perfiles ADD COLUMN {_columna}"))
    except Exception:
        pass

# El árbol pasa de lista a jerarquía. Las columnas se agregan con el patrón
# tolerante de siempre: si ya existen, la excepción se traga y sigue.
_COLUMNAS_ARBOL = [
    "padre_id INTEGER",    # de quién desciende. NULL = cuelga del homenajeado
    "pareja_id INTEGER",   # con quién forma pareja, para dibujarlos juntos
]
for _columna in _COLUMNAS_ARBOL:
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE familiares_arbol ADD COLUMN {_columna}"))
    except Exception:
        pass

try:
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_familiares_arbol_padre_id ON familiares_arbol (padre_id)"))
except Exception:
    pass

# create_all no añade índices a tablas que ya existen, así que el de velas hay
# que crearlo aparte para las bases que ya estaban en producción.
try:
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_velas_encendidas_perfil_id ON velas_encendidas (perfil_id)"))
except Exception:
    pass

# ==========================================
# 🌳 FASE 2 · La familia deja de vivir en dos lugares
# ==========================================
# El memorial guardaba la familia dos veces: 'esposa' e 'hijos' como texto suelto
# en tarjetas, y el Árbol Familiar como tabla con nombre, parentesco y foto. El
# Árbol lo hace mejor, así que las tarjetas se van — pero lo que las familias ya
# escribieron NO se pierde: se muda al Árbol.
#
# Las columnas viejas NO se borran. Quedan como respaldo hasta que la migración
# esté verificada en producción; borrarlas es un paso aparte y deliberado.

def _partes_de_hijos(texto: str) -> list:
    """Separa 'Ana, Luis y Pedro' en tres, pero solo cuando es claramente una lista.

    Si el campo trae una frase —'Sus tres hijos, que lo adoraban'— partirla la
    destroza. Ante la duda se deja entera: una fila con el texto exacto es fea
    pero recuperable; tres filas mal cortadas no.

    La prueba es si CADA pieza parece un nombre: empieza en mayúscula, tiene tres
    palabras o menos y no arrastra puntuación interna. 'que lo adoraban siempre'
    falla la primera condición, y con eso la frase entera se salva de la tijera.
    """
    import re as _re
    limpio = texto.strip()
    if not limpio:
        return []
    if "." in limpio.rstrip("."):          # un punto interior delata una frase
        return [limpio]
    piezas = [p.strip() for p in _re.split(r",| y ", limpio.rstrip(".")) if p.strip()]

    def parece_nombre(p):
        return p[:1].isupper() and len(p.split()) <= 3 and len(p) <= 40

    if len(piezas) > 1 and all(parece_nombre(p) for p in piezas):
        return piezas
    return [limpio]


def _migrar_familia_al_arbol():
    """Muda 'esposa' e 'hijos' al Árbol Familiar. Idempotente y sin pérdida.

    La idempotencia no usa una bandera: comprueba si ya existe un familiar con
    ese mismo nombre y parentesco. Así, correrla mil veces no duplica a nadie, y
    si la familia borró a mano el registro migrado, no vuelve a aparecer.
    """
    sesion = SessionLocal()
    try:
        movidos = 0
        for perfil in sesion.query(PerfilDifunto).all():
            existentes = {(f.nombre or "").strip().lower()
                          for f in sesion.query(FamiliarArbol).filter_by(perfil_id=perfil.id)}
            siguiente = max([f.orden or 0 for f in
                             sesion.query(FamiliarArbol).filter_by(perfil_id=perfil.id)] or [0])

            candidatos = []
            if (perfil.esposa or "").strip():
                candidatos.append((perfil.esposa.strip(), "Compañera de vida"))
            for hijo in _partes_de_hijos(perfil.hijos or ""):
                if hijo:
                    candidatos.append((hijo, "Su legado"))

            for nombre, relacion in candidatos:
                if nombre.lower() in existentes:
                    continue
                siguiente += 1
                sesion.add(FamiliarArbol(nombre=nombre, relacion=relacion, foto_url="",
                                         perfil_id=perfil.id, orden=siguiente))
                existentes.add(nombre.lower())
                movidos += 1
        if movidos:
            sesion.commit()
            print(f"  Fase 2: {movidos} familiares mudados al Árbol Familiar.")
    except Exception as e:
        sesion.rollback()
        print(f"  Fase 2: la migración de familia no corrió ({e}). Las tarjetas viejas siguen intactas.")
    finally:
        sesion.close()


_migrar_familia_al_arbol()
