import os
import datetime
import ssl
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

# 1. Abrimos la caja fuerte
load_dotenv()

# 2. Leemos la URL de Neon.tech
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./memoriales.db")

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
    # Creamos el túnel seguro
    ctx = ssl.create_default_context()
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

    # Relaciones con otras tablas
    fotos_galeria = relationship("FotoGaleria", back_populates="perfil")
    mensajes = relationship("MensajeRecuerdo", back_populates="perfil")
    momentos = relationship("MomentoInolvidable", back_populates="perfil")

class FotoGaleria(Base):
    __tablename__ = "fotos_galeria"
    id = Column(Integer, primary_key=True, index=True)
    url_foto = Column(String)
    perfil_id = Column(Integer, ForeignKey("perfiles.id"))
    perfil = relationship("PerfilDifunto", back_populates="fotos_galeria")

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

# Esto crea las tablas automáticamente en Neon.tech si no existen
Base.metadata.create_all(bind=engine)