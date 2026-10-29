"""Proveedores de IA para generar preguntas.

- AnthropicProvider: llama a la API de Claude y fuerza una salida estructurada (tool use).
- OpenAICompatProvider: cualquier API con el formato de OpenAI (Gemini, Groq, OpenRouter, Ollama...),
  útil para modelos gratuitos. También fuerza una salida estructurada (function calling).
- MockProvider: generador SIMULADO y determinista, sin red ni costo. Sirve para desarrollar y
  probar el flujo completo; sus preguntas son sencillas (completar, verdadero/falso, abiertas).

Agregar otro proveedor (OpenAI, Ollama...) = una clase más con el método `generar`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from typing import Protocol

from ..config import Settings
from .extraccion import Adjunto

MAX_ADJUNTOS = 5


class LLMError(Exception):
    """Falla al generar (red, cuota, respuesta inválida...). El mensaje es apto para mostrar."""


@dataclass
class PeticionLLM:
    system: str
    prompt: str
    cantidad: int
    tipos: list[str]
    dificultad: str                      # FACIL | MEDIA | DIFICIL | MIXTA
    texto_contexto: str = ""             # el mock trabaja sobre este texto
    adjuntos: list[Adjunto] = field(default_factory=list)


@dataclass
class ResultadoLLM:
    preguntas: list[dict]
    proveedor: str
    modelo: str
    tokens_entrada: int | None = None
    tokens_salida: int | None = None


class LLMProvider(Protocol):
    nombre: str

    def generar(self, p: PeticionLLM) -> ResultadoLLM: ...


# ----------------------------------------------------------------------------
#  Anthropic
# ----------------------------------------------------------------------------
TOOL_PREGUNTAS = {
    "name": "registrar_preguntas",
    "description": "Registra las preguntas de evaluación generadas a partir del contenido entregado.",
    "input_schema": {
        "type": "object",
        "properties": {
            "preguntas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {"type": "string", "enum": ["OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA"]},
                        "enunciado": {"type": "string", "description": "Texto de la pregunta, claro y autocontenido."},
                        "dificultad": {"type": "string", "enum": ["FACIL", "MEDIA", "DIFICIL"]},
                        "opciones": {
                            "type": "array",
                            "description": "Vacío en ABIERTA. 4 opciones en OPCION_MULTIPLE. 'Verdadero' y 'Falso' en VERDADERO_FALSO.",
                            "items": {
                                "type": "object",
                                "properties": {"texto": {"type": "string"}, "es_correcta": {"type": "boolean"}},
                                "required": ["texto", "es_correcta"],
                            },
                        },
                        "respuesta_esperada": {
                            "type": "string",
                            "description": "Solo ABIERTA: criterios o respuesta modelo para calificar.",
                        },
                        "explicacion": {"type": "string", "description": "1-2 frases que justifican la respuesta correcta."},
                    },
                    "required": ["tipo", "enunciado", "dificultad", "opciones", "explicacion"],
                },
            }
        },
        "required": ["preguntas"],
    },
}


class AnthropicProvider:
    nombre = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int):
        self.api_key, self.model, self.max_tokens = api_key, model, max_tokens

    def generar(self, p: PeticionLLM) -> ResultadoLLM:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("Falta instalar el paquete 'anthropic' (pip install anthropic).") from e

        client = anthropic.Anthropic(api_key=self.api_key, timeout=180.0, max_retries=2)

        content: list[dict] = []
        for a in p.adjuntos[:MAX_ADJUNTOS]:
            content.append({
                "type": a.kind,   # "image" | "document"
                "source": {"type": "base64", "media_type": a.mime,
                           "data": base64.standard_b64encode(a.data).decode("ascii")},
            })
        content.append({"type": "text", "text": p.prompt})

        max_tokens = min(16000, max(self.max_tokens, 500 * p.cantidad + 1500))
        try:
            msg = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=p.system,
                tools=[TOOL_PREGUNTAS],
                tool_choice={"type": "tool", "name": TOOL_PREGUNTAS["name"]},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as e:
            raise LLMError("La API key de Anthropic no es válida.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Se alcanzó el límite de uso de la API de IA. Intenta de nuevo en un momento.") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("No se pudo conectar con la API de IA.") from e
        except anthropic.APIError as e:
            raise LLMError(f"La API de IA devolvió un error: {getattr(e, 'message', e.__class__.__name__)}") from e

        bloque = next((b for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
        if bloque is None or not isinstance(bloque.input, dict):
            raise LLMError("El modelo no devolvió preguntas en el formato esperado.")
        preguntas = bloque.input.get("preguntas")
        if not isinstance(preguntas, list):
            raise LLMError("El modelo devolvió un formato inesperado.")

        usage = getattr(msg, "usage", None)
        return ResultadoLLM(
            preguntas=preguntas, proveedor=self.nombre, modelo=self.model,
            tokens_entrada=getattr(usage, "input_tokens", None),
            tokens_salida=getattr(usage, "output_tokens", None),
        )


# ----------------------------------------------------------------------------
#  API compatible con OpenAI (Gemini, Groq, OpenRouter, Ollama...)
# ----------------------------------------------------------------------------
def _json_de_texto(texto: str):
    """Extrae un JSON de la respuesta cuando el modelo no usó function calling (quita ``` y texto alrededor)."""
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip(), flags=re.IGNORECASE)
    # el JSON "más externo" es el que empieza antes: si hay [ ... { ... } ... ] gana la lista
    candidatos = sorted((s.find(i), i, f) for i, f in (("{", "}"), ("[", "]")) if s.find(i) != -1)
    for a, _ini, fin in candidatos:
        b = s.rfind(fin)
        if b > a:
            try:
                return json.loads(s[a:b + 1])
            except ValueError:
                continue
    return None


class OpenAICompatProvider:
    nombre = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int, http=None):
        self.base_url, self.api_key, self.model, self.max_tokens = base_url.rstrip("/"), api_key, model, max_tokens
        self._http = http

    def _post(self, body: dict):
        import httpx

        http = self._http or httpx.Client(timeout=180.0)
        headers = {"Content-Type": "application/json"}
        if self.api_key:   # Ollama local no la necesita
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            return http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as e:
            raise LLMError("No se pudo conectar con la API de IA.") from e

    def generar(self, p: PeticionLLM) -> ResultadoLLM:
        partes: list[dict] = []
        for a in p.adjuntos[:MAX_ADJUNTOS]:
            if a.kind == "image":   # los PDF escaneados no se pueden enviar por este formato: se omiten
                partes.append({"type": "image_url", "image_url": {
                    "url": f"data:{a.mime};base64,{base64.standard_b64encode(a.data).decode('ascii')}"}})
        partes.append({"type": "text", "text": p.prompt})
        funcion = {"name": TOOL_PREGUNTAS["name"], "description": TOOL_PREGUNTAS["description"],
                   "parameters": TOOL_PREGUNTAS["input_schema"]}
        body = {
            "model": self.model,
            "max_tokens": min(16000, max(self.max_tokens, 500 * p.cantidad + 1500)),
            "temperature": 0.4,
            "messages": [{"role": "system", "content": p.system},
                         {"role": "user", "content": partes if len(partes) > 1 else p.prompt}],
            "tools": [{"type": "function", "function": funcion}],
            "tool_choice": {"type": "function", "function": {"name": funcion["name"]}},
        }

        # Modelos a intentar (permite fallback transparente si el modelo principal está sobrecargado con 503)
        modelos_a_probar = [self.model]
        if "gemini" in self.model.lower():
            for alt in ("gemini-3.5-flash", "gemini-3.5-flash-lite"):
                if alt not in modelos_a_probar:
                    modelos_a_probar.append(alt)

        r = None
        for i, mod in enumerate(modelos_a_probar):
            body["model"] = mod
            r = self._post(body)
            if r.status_code == 400 and "tool_choice" in r.text.lower():   # algunos proveedores no aceptan forzar la función
                body_sin_tool_choice = dict(body)
                body_sin_tool_choice.pop("tool_choice", None)
                r = self._post(body_sin_tool_choice)
            if r.status_code in (401, 403):
                raise LLMError("La API key del proveedor de IA no es válida o no tiene permiso.")
            # Si hay error 503 (alta demanda) o 429 y aún hay modelos de respaldo, intentar con el siguiente
            if r.status_code in (429, 503) and i < len(modelos_a_probar) - 1:
                continue
            if r.status_code == 429:
                raise LLMError("Se alcanzó el límite de uso del proveedor de IA. Intenta de nuevo en un momento.")
            if r.status_code >= 400:
                raise LLMError(f"El proveedor de IA devolvió un error ({r.status_code}).")
            break

        try:
            data = r.json()
            msg = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError("El proveedor de IA devolvió una respuesta inesperada.") from e

        crudo = None
        for call in msg.get("tool_calls") or []:
            args = (call.get("function") or {}).get("arguments")
            crudo = json.loads(args) if isinstance(args, str) and args.strip().startswith(("{", "[")) else args
            break
        if crudo is None:
            crudo = _json_de_texto(msg.get("content") or "")
        preguntas = crudo.get("preguntas") if isinstance(crudo, dict) else crudo
        if not isinstance(preguntas, list):
            raise LLMError("El modelo no devolvió preguntas en el formato esperado.")

        uso = data.get("usage") or {}
        return ResultadoLLM(
            preguntas=preguntas, proveedor=self.nombre, modelo=data.get("model") or self.model,
            tokens_entrada=uso.get("prompt_tokens"), tokens_salida=uso.get("completion_tokens"),
        )


# ----------------------------------------------------------------------------
#  Simulado
# ----------------------------------------------------------------------------
_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{7,}")
_RELLENO = ["planificación", "evaluación", "metodología", "retroalimentación", "didáctica", "competencia"]


def _frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.!?])\s+|\n+", texto)
    frases = [p.strip(" -•\t|") for p in partes]
    buenas = [f for f in frases if 35 <= len(f) <= 280]
    if not buenas and len(texto.strip()) >= 10:
        buenas = [texto.strip()[:280]]
    return buenas


def _clave(frase: str) -> str | None:
    palabras = _PALABRA.findall(frase)
    return max(palabras, key=len) if palabras else None


class MockProvider:
    nombre = "mock"

    def generar(self, p: PeticionLLM) -> ResultadoLLM:
        semilla = int(hashlib.sha256(p.texto_contexto.encode("utf-8")).hexdigest()[:8], 16)
        rnd = random.Random(semilla)
        frases = _frases(p.texto_contexto)
        if not frases:
            raise LLMError("No hay texto suficiente en las fuentes para generar preguntas.")

        pool = list({k.casefold(): k for f in frases if (k := _clave(f))}.values())
        tipos = p.tipos or ["OPCION_MULTIPLE"]
        dificultades = ["FACIL", "MEDIA", "DIFICIL"]
        salida: list[dict] = []

        for i in range(p.cantidad):
            frase = frases[i % len(frases)]
            tipo = tipos[i % len(tipos)]
            dif = p.dificultad if p.dificultad in dificultades else dificultades[i % 3]
            kw = _clave(frase)
            distractores = [w for w in pool if kw and w.casefold() != kw.casefold()]
            rnd.shuffle(distractores)

            vuelta = i // len(frases)

            if tipo == "OPCION_MULTIPLE" and kw:
                falsos = (distractores + [w for w in _RELLENO if w.casefold() != kw.casefold()])[:3]
                ops = [{"texto": kw, "es_correcta": True}] + [{"texto": w, "es_correcta": False} for w in falsos]
                rnd.shuffle(ops)
                prefijo = "Completa la idea del material" if vuelta == 0 else f"Identifica el término adecuado según el material (aspecto {vuelta + 1})"
                salida.append({
                    "tipo": tipo, "dificultad": dif,
                    "enunciado": f"{prefijo}: «" + frase.replace(kw, "_____", 1) + "»",
                    "opciones": ops, "explicacion": f"El material dice: «{frase}»",
                })
            elif tipo == "VERDADERO_FALSO" and kw:
                es_verdadera = (i // len(tipos)) % 2 == 0
                if es_verdadera or not distractores:
                    enun, ok = frase, True
                else:
                    enun, ok = frase.replace(kw, distractores[0], 1), False
                salida.append({
                    "tipo": tipo, "dificultad": dif, "enunciado": enun,
                    "opciones": [{"texto": "Verdadero", "es_correcta": ok}, {"texto": "Falso", "es_correcta": not ok}],
                    "explicacion": f"El material dice: «{frase}»",
                })
            else:  # ABIERTA (o sin palabra clave aprovechable)
                prefijo = "Explica con tus palabras y da un ejemplo de tu práctica sobre esta idea" if vuelta == 0 else f"Analiza y describe la aplicación en tu práctica docente de esta idea (enfoque {vuelta + 1})"
                salida.append({
                    "tipo": "ABIERTA", "dificultad": dif, "opciones": [],
                    "enunciado": f"{prefijo}: «" + frase + "»",
                    "respuesta_esperada": "Debe reflejar la idea central: " + frase,
                    "explicacion": "Se espera que relacione la idea con una experiencia concreta de la práctica.",
                })
        return ResultadoLLM(preguntas=salida, proveedor=self.nombre, modelo="simulado", tokens_entrada=0, tokens_salida=0)


def get_provider(s: Settings) -> LLMProvider:
    if s.llm_effective == "anthropic":
        if not s.anthropic_api_key:
            raise LLMError("LLM_PROVIDER=anthropic pero falta ANTHROPIC_API_KEY.")
        return AnthropicProvider(s.anthropic_api_key, s.anthropic_model, s.llm_max_tokens)
    if s.llm_effective == "openai_compat":
        if not (s.llm_base_url and s.llm_model):
            raise LLMError("LLM_PROVIDER=openai_compat pero faltan LLM_BASE_URL y LLM_MODEL.")
        return OpenAICompatProvider(s.llm_base_url, s.llm_api_key, s.llm_model, s.llm_max_tokens)
    return MockProvider()
