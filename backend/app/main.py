"""SPP · Servicio de Evaluación (FastAPI)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import estudiante, meta, tutor_evaluaciones, tutor_generacion, tutor_preguntas, tutor_resultados

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:   # solo desarrollo; en producción se usa db/schema.sql
        from .database import Base, engine
        from . import models  # noqa: F401  (registra las tablas)
        Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="SPP · Servicio de Evaluación",
    version="1.0.0",
    description="Evaluaciones con preguntas manuales o generadas con IA a partir de evidencias.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
for r in (meta.router, tutor_evaluaciones.router, tutor_preguntas.router, tutor_generacion.router,
          tutor_resultados.router, estudiante.router):
    app.include_router(r, prefix=API)
