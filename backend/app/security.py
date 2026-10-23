"""Identidad del usuario que llama a la API.

AUTH_MODE=dev  -> headers X-User-Id y X-User-Role (TUTOR | ESTUDIANTE | DIRECTOR). SOLO para desarrollo.
AUTH_MODE=jwt  -> "Authorization: Bearer <jwt>" firmado con JWT_SECRET. Claims: `sub` = documento
                  del usuario (el mismo `numDocumento` del monolito, texto) y `rol` (o `role`) =
                  TUTOR | ESTUDIANTE | DIRECTOR (también se aceptan los roles del monolito `tutor`, `student`
                  y `director`).

Si tu servicio de usuarios emite tokens con otros nombres de claims, ajusta `_desde_jwt`.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

ROLES = {"TUTOR": "TUTOR", "TUTOR_ACADEMICO": "TUTOR", "ESTUDIANTE": "ESTUDIANTE", "STUDENT": "ESTUDIANTE",
         "DIRECTOR": "DIRECTOR"}


@dataclass(frozen=True)
class Usuario:
    id: str          # numDocumento del monolito
    rol: str


def _no_autorizado(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg)


def _normalizar_rol(rol: str | None) -> str:
    r = ROLES.get((rol or "").strip().upper().replace(" ", "_"))
    if not r:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Rol no autorizado para este servicio.")
    return r


def _desde_jwt(authorization: str | None, s: Settings) -> Usuario:
    import jwt  # PyJWT

    if not s.jwt_secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "AUTH_MODE=jwt pero falta JWT_SECRET.")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _no_autorizado("Falta el token de autenticación.")
    try:
        claims = jwt.decode(authorization.split(" ", 1)[1], s.jwt_secret, algorithms=[s.jwt_algorithm])
        uid = str(claims["sub"]).strip()
        if not uid or len(uid) > 30:
            raise ValueError("sub inválido")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _no_autorizado("Token inválido o vencido.")
    return Usuario(uid, _normalizar_rol(claims.get("rol") or claims.get("role")))


def usuario_actual(
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
    s: Settings = Depends(get_settings),
) -> Usuario:
    if s.auth_mode == "jwt":
        return _desde_jwt(authorization, s)
    if not x_user_id or not x_user_id.strip() or len(x_user_id.strip()) > 30:
        raise _no_autorizado("Falta el header X-User-Id (modo dev).")
    return Usuario(x_user_id.strip(), _normalizar_rol(x_user_role))


def solo_tutor(u: Usuario = Depends(usuario_actual)) -> Usuario:
    if u.rol != "TUTOR":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el tutor puede hacer esto.")
    return u


def solo_estudiante(u: Usuario = Depends(usuario_actual)) -> Usuario:
    if u.rol != "ESTUDIANTE":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el estudiante puede hacer esto.")
    return u


def solo_director(u: Usuario = Depends(usuario_actual)) -> Usuario:
    """El director solo consulta (routers/director.py: únicamente GET)."""
    if u.rol != "DIRECTOR":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el director puede hacer esto.")
    return u
