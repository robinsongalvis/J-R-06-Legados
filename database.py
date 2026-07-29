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

    # Relaciones con otras tablas
    fotos_galeria = relationship("FotoGaleria", back_populates="perfil")
    mensajes = relationship("MensajeRecuerdo", back_populates="perfil")
    momentos = relationship("MomentoInolvidable", back_populates="perfil")
    velas_list = relationship("VelaEncendida", back_populates="perfil", cascade="all, delete-orphan")
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
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="velas_list")

class FamiliarArbol(Base):
    __tablename__ = "familiares_arbol"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String)
    relacion = Column(String)
    foto_url = Column(String, default="")
    memorial_id = Column(String, default="")
    orden = Column(Integer, default=0)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="familiares_arbol")

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