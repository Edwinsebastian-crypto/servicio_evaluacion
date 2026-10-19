"""Salud y configuración pública (sin secretos)."""
from fastapi import APIRouter, Depends

from ..config import Settings, get_settings

router = APIRouter(tags=["Meta"])


@router.get("/health")
def health(s: Settings = Depends(get_settings)):
    proveedor = s.llm_effective
    return {
        "status": "ok",
        "ia": {"proveedor": proveedor, "modelo": s.llm_model_name},
        "evidencias": s.evidencias_mode,
        "auth": s.auth_mode,
    }
