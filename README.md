# SPP · Servicio de Evaluación

Evaluaciones con preguntas **manuales** o **generadas con IA** a partir de un tema o de las
evidencias y archivos del estudiante (que viven en otro servicio). Backend en **Python
(FastAPI + SQLAlchemy)**, base de datos **PostgreSQL**, interfaz en el estilo de SPP.

```
servicio-evaluacion/
├── db/schema.sql                Esquema PostgreSQL (fuente de verdad)
├── backend/app/                 FastAPI: routers/, services/ (IA, extracción, calificación), models, schemas
├── backend/tests/               pytest (lógica + flujo completo de la API)
├── docker-compose.yml           PostgreSQL + API
CSS/evaluacion.css               Estilos (usa variables.css y shell.css del proyecto)
HTML/evaluaciones-tutor.html     Pantalla del tutor
HTML/evaluaciones-estudiante.html Pantalla del estudiante
JavaScript/evaluacion-*.js       config, api (backend real), mock (sin backend), ui, tutor, estudiante
```

## Puesta en marcha

**Con Docker (lo más rápido)**
```bash
cd servicio-evaluacion
docker compose up --build        # Postgres + API en http://localhost:8000  (docs: /docs)
```
**Sin Docker**
```bash
createdb spp_evaluacion && psql spp_evaluacion -f db/schema.sql
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env             # ajusta DATABASE_URL y, si quieres IA real, ANTHROPIC_API_KEY
uvicorn app.main:app --reload
pytest                           # pruebas (usan SQLite temporal y la IA simulada)
```
Abre luego `HTML/evaluaciones-tutor.html` con un servidor estático (por ejemplo la extensión
Live Server, o `python -m http.server 5500` en la raíz del repo). `CORS_ORIGINS` debe incluir ese origen.

## Interfaz con o sin backend

Al final de ambos HTML hay un bloque **«MODO SIN BACKEND»**:

```html
<script src="../JavaScript/evaluacion-api.js"></script>               <!-- backend real -->
<!-- <script src="../JavaScript/evaluacion-mock.js"></script> -->     <!-- descomenta para usar SIN backend -->
```
Descomentando la segunda línea, toda la interfaz (tutor **y** estudiante) funciona con datos de
ejemplo guardados en el navegador: generación con IA simulada, aprobación, publicación,
presentar la evaluación, calificar. Tutor y estudiante comparten esos datos. Para volver al
backend, vuelve a comentarla. La URL del backend y los ids de prueba están en
`JavaScript/evaluacion-config.js`.

> Esta carpeta es el prototipo autónomo. Para usarlo **dentro del monolito** (`software_spp`) sigue la sección
> **«Acoplar al monolito»** más abajo: ahí las pantallas, la sesión y los permisos son los del monolito.

## Cómo funciona la generación con IA

1. El tutor elige **tema libre** y/o **evidencias** del estudiante, cantidad, tipos y dificultad.
2. El servicio pide las evidencias/archivos al **servicio de evidencias por HTTP** (nunca a su BD).
3. Extrae el texto (PDF, Word, PowerPoint, texto/HTML; imágenes y PDF escaneados se envían al modelo).
4. Arma el prompt (contenido marcado como *datos*, no instrucciones) y llama a Claude con **salida
   estructurada** (tool use). Sin `ANTHROPIC_API_KEY` usa un generador **simulado** (la UI lo avisa).
5. Valida cada pregunta (una sola correcta, 4 opciones, sin repetidas…), descarta las malas y guarda
   el resto como **BORRADOR** con su trazabilidad: `generacion_ia` (parámetros, modelo, tokens, errores)
   y `contexto_pregunta` (qué evidencia/archivo y qué texto se usó).
6. El tutor **aprueba/rechaza/edita**; solo las aprobadas ven los estudiantes.

Cambiar de proveedor de IA = una clase más en `services/llm.py`.

## IA real y gratis

Sin configurar nada, el servicio usa un generador **simulado** (preguntas sencillas de completar / verdadero-falso).
Para IA real hay dos caminos; el servicio elige solo según las variables:

| Opción | Variables | Costo |
|---|---|---|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY` | de pago por uso |
| **API compatible con OpenAI** (Gemini, Groq, OpenRouter, Ollama…) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | los gratuitos tienen límites |

**Gemini (Google AI Studio) — la opción gratuita más simple**
1. Entra a <https://aistudio.google.com/apikey> con una cuenta de Google y crea una API key.
2. En `backend/.env`:
   ```
   LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   LLM_API_KEY=<tu clave>
   LLM_MODEL=gemini-3.8-flash
   ```
   (confirma el nombre del modelo en AI Studio; los modelos «Flash» tienen capa gratuita, los «Pro» no).
3. Reinicia el servicio. La pantalla del tutor deja de mostrar el aviso de «IA simulada».

**Otras gratuitas con el mismo formato:** Groq (`https://api.groq.com/openai/v1`), OpenRouter (`https://openrouter.ai/api/v1`,
modelos con sufijo `:free`) u **Ollama** en tu propio equipo (`http://localhost:11434/v1`, sin clave, gratis y privado,
pero necesita una máquina con memoria suficiente). Cambia solo las tres variables.

**Antes de elegir, ten en cuenta**
- **Privacidad:** en la capa gratuita de Gemini, Google puede usar el contenido enviado para mejorar sus productos
  (lo dice su página de precios). Las evidencias son trabajo de estudiantes: si no quieres que salga de tu control, usa
  Ollama o un plan de pago. Revisa también las condiciones de cada proveedor.
- **Límites:** los planes gratuitos limitan peticiones por minuto y por día; al pasarse, la pantalla muestra
  «Se alcanzó el límite gratuito» y basta reintentar más tarde. Cambian con frecuencia: consúltalos en el proveedor.
- **Archivos:** por este formato se envían las imágenes, pero **no** los PDF escaneados; los PDF con texto, Word y
  PowerPoint funcionan porque el texto se extrae antes.
- La calidad depende del modelo. Las preguntas generadas siempre quedan como «Por revisar» hasta que el tutor las aprueba.
- Probado con un servidor simulado (formato de respuesta, reintentos, errores 401/429/500); **no** contra Gemini real
  (no había salida a Internet).

## Contrato con el servicio de evidencias (`EVIDENCIAS_MODE=http`)

Si tus rutas son distintas, solo adapta `backend/app/services/evidencias_client.py`.
```
GET {URL}/practicas/{id_practica}/evidencias   -> [{id_evidencia, descripcion, horas_realizadas, id_actividad, nombre_actividad, archivos:[{id_archivo, nombre_archivo, tipo_mime}]}]
GET {URL}/evidencias/{id}                      -> uno de los anteriores
GET {URL}/evidencias/archivos/{id_archivo}     -> bytes del archivo
GET {URL}/actividades/{id}                     -> {id_actividad, nombre, descripcion, archivos:[…]}
GET {URL}/actividades/archivos/{id_archivo}    -> bytes del archivo
```
Con `EVIDENCIAS_MODE=stub` (por defecto) usa datos de ejemplo. Con `practice_db` lee directamente la base de prácticas del monolito (solo lectura). En modo `http` incluye `id_practica` en cada evidencia/actividad: sin él, la IA rechaza esa fuente (no puede comprobar que sea de la práctica).

## API (prefijo `/api/v1`)

| Rol | Endpoint |
|---|---|
| Tutor | `GET/POST /tutor/evaluaciones` · `GET/PATCH/DELETE /tutor/evaluaciones/{id}` · `POST …/publicar · despublicar · cerrar` |
| Tutor | `POST /tutor/evaluaciones/{id}/preguntas` (manual) · `PATCH/DELETE /tutor/preguntas/{id}` · `POST …/aprobar · rechazar` · `POST …/preguntas/aprobar-todas` · `PUT …/preguntas/orden` |
| Tutor | `GET /tutor/evidencias?id_practica=` · `POST /tutor/evaluaciones/{id}/generar` |
| Tutor | `GET /tutor/evaluaciones/{id}/intentos` · `GET /tutor/intentos/{id}` · `POST /tutor/respuestas/{id}/calificar · retro` |
| Estudiante | `GET /estudiante/evaluaciones` · `POST …/evaluaciones/{id}/intentos` · `GET …/intentos/{id}` · `PUT …/intentos/{id}/respuestas/{id_pregunta}` (autoguardado) · `POST …/intentos/{id}/enviar` |
| Director | `GET /director/resumen` · `GET /director/evaluaciones` (filtros `estado`, `id_tutor`, `id_practica`, `q`, `solo_alertas`, `limite`, `desplazamiento`) · `GET /director/evaluaciones/{id}` — **solo lectura** |
| — | `GET /health` |

Reglas: opción múltiple y verdadero/falso se califican solas; las abiertas quedan «por calificar»
hasta que el tutor ponga la nota (el intento pasa a CALIFICADO). Nota = suma obtenida / suma de valores × nota máxima
(5.0 por defecto); la nota final de la evaluación es la mejor de sus intentos. Con intentos presentados las preguntas ya no se pueden modificar.
Al cerrar o vencer la fecha límite, los intentos en curso se envían con lo guardado.

## Panel del director (solo lectura)

El director solo consulta. `routers/director.py` tiene únicamente `GET` y exige el rol `DIRECTOR`; con cualquier otro rol responde 403.

* `GET /director/resumen`: totales, estado de evaluaciones e intentos, notas finales (mejor intento calificado, en % de la nota máxima),
  aprobación (60 % = 3.0 de 5.0), uso y aceptación de la IA, actividad de los últimos 6 meses, tabla por tutor y alertas.
* `GET /director/evaluaciones`: lista filtrable y paginada. `GET /director/evaluaciones/{id}`: acierto por pregunta, intentos y generaciones de IA.
* **No devuelve** lo que escribieron los estudiantes, los comentarios del tutor ni el prompt enviado a la IA: solo cifras y notas.
* Las cuentas están en `app/services/estadisticas.py` (funciones puras, sin base de datos) con sus pruebas en `tests/test_estadisticas.py`.
  Los umbrales de las alertas (`DIAS_REVISION_ATRASADA`, `DIAS_BORRADOR_ANTIGUO`, `DIAS_SIN_INTENTOS`, `UMBRAL_APROBACION`) están al inicio de ese archivo.
* El servicio solo conoce documentos e ids: los nombres de personas y prácticas los agrega el monolito (`directorio`).
* Carga todas las evaluaciones con sus preguntas e intentos en memoria para calcular; está pensado para cientos de evaluaciones, no para millones.

## Cambios respecto a tu diagrama ER

`evaluacion` + `id_estudiante`, `id_tutor`, `id_actividad`, `titulo`, límites e intentos · `pregunta` + `origen` (MANUAL/IA),
`estado_revision`, `orden`, `dificultad`, `respuesta_esperada`, `explicacion` · **nuevas**: `opcion_pregunta`,
`intento_evaluacion` (la respuesta ahora cuelga de un intento), `contexto_pregunta`, `generacion_ia` · `respuesta` + `id_opcion`, `es_correcta`,
`calificada_por` · `retro_pregunta` igual. Las llaves a otros servicios (práctica, actividad, tutor, estudiante, evidencia) son
referencias lógicas `VARCHAR(30)` sin FK (igual que `idPractica` y `numDocumento` del monolito); si usan otro tipo, cámbialas en `schema.sql` y `models.py`.

## Autenticación

Por defecto `AUTH_MODE=dev`: el backend confía en los headers `X-User-Id` y `X-User-Role` (**solo desarrollo**). En producción usa
`AUTH_MODE=jwt` + `JWT_SECRET`; el token debe traer `sub` (documento del usuario, texto) y `rol` (`TUTOR` | `ESTUDIANTE` | `DIRECTOR`). Ajusta `security.py` si tu
servicio de usuarios emite otros claims. Además, el backend **no verifica con el servicio de prácticas** que el tutor sea el de esa práctica:
solo que sea el creador de la evaluación.

## Privacidad

Las evidencias pueden contener datos personales de estudiantes y se envían al proveedor de IA. Revisa la política de tu institución
antes de usar un proveedor externo. El contenido enviado queda guardado en `contexto_pregunta.texto_extraido` para auditar.

## Estado de verificación

Probado de verdad: `schema.sql` en PostgreSQL 16 (con sus restricciones); la lógica de extracción, generación,
validación y calificación; y la interfaz completa en navegador (tutor + estudiante, modo sin backend, cliente real contra un servidor
simulado, escritorio y celular, tema oscuro). **Sin ejecutar** en el entorno donde se escribió (no había acceso a PyPI): el arranque de
FastAPI/SQLAlchemy y `pytest`. Si algo falla al primer `pytest` o `uvicorn`, es lo primero que hay que mirar.

Panel del director: las cuentas (`estadisticas.py`) pasan sus 12 pruebas y sus respuestas encajan en los esquemas pydantic; la pantalla se probó en navegador (claro, oscuro, celular, modo sin backend) contra un servidor que usa ese código real detrás del gateway real. **Sin ejecutar**: las consultas SQLAlchemy de `routers/director.py` y `tests/test_director_api.py` (necesitan FastAPI/SQLAlchemy).

Para el acople con el monolito sí se probó: el lector de evidencias (`practice_db`) contra PostgreSQL con el esquema real de prácticas (20 comprobaciones: aislamiento entre prácticas, dominios de descarga, tamaño máximo), el token firmado por Node contra una verificación HS256 independiente, y la puerta de enlace + pantallas en navegador con la misma política CSP del monolito. **Sin ejecutar**: el monolito completo (`npm install` no funcionó en el entorno) y el servicio Python real conectado a él.


## Acoplar al monolito (software_spp)

El monolito es Node/Express; este servicio es Python. Se ejecutan como **dos procesos** y el monolito hace de puerta
de enlace:

```
Navegador ──cookie──▶ Monolito (Node) ──token firmado 2 min──▶ Servicio de evaluación (FastAPI) ──▶ BD spp_evaluacion
 /pages/*-evaluations.html   /api/evaluations/*                         │
                             valida sesión, rol y que la práctica       └─(solo lectura)─▶ BD de PRÁCTICAS del monolito
                             sea del tutor                                                  (evidencias y archivos → IA)
```
El navegador nunca habla con el servicio: no hace falta CORS ni exponerlo a Internet.

### Qué instalar

| Pieza | Para qué | Versión |
|---|---|---|
| Node.js + `npm install` en el monolito | ya lo tienes; **no se agrega ninguna dependencia nueva** | 18+ |
| Python | servicio de evaluación | 3.12 |
| `pip install -r backend/requirements.txt` | FastAPI, SQLAlchemy, psycopg, PyJWT, anthropic, httpx, pypdf, python-docx | — |
| PostgreSQL: base de datos del servicio (p. ej. `spp_evaluacion`) | el servicio tiene su propio esquema de tablas (`evaluacion`, `pregunta`, `intento`, `respuesta_intento`…) | 14+ |
| Clave de Anthropic (`ANTHROPIC_API_KEY`) | solo si quieres IA real; sin ella usa el generador simulado | — |

### Pasos

1. **Base nueva:** crea `spp_evaluacion` (en Neon: *New database*) y aplica el esquema: `psql "$URL" -f db/schema.sql`.
2. **Secreto compartido:** `node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"`.
3. **Servicio** (`backend/.env`):
   ```
   DATABASE_URL=postgresql+psycopg://usuario:clave@host/spp_evaluacion
   AUTH_MODE=jwt
   JWT_SECRET=<el secreto del paso 2>
   EVIDENCIAS_MODE=practice_db
   PRACTICE_DATABASE_URL=postgresql://usuario_lectura:clave@host/postgres_1      # la base de prácticas
   ANTHROPIC_API_KEY=...                                                          # opcional
   CORS_ORIGINS=
   ```
   Arranque: `cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000` (o `docker compose up --build`).
4. **Monolito** (`.env`):
   ```
   EVALUATION_SERVICE_URL=http://localhost:8000
   EVALUATION_SERVICE_SECRET=<el mismo secreto>
   ```
   Reinicia el monolito. Verás **Evaluations** en el menú del tutor y del estudiante.
5. **Despliegue (Render, Railway…):** dos servicios. El de Python debe ser **privado** (solo alcanzable por el monolito);
   pon su URL interna en `EVALUATION_SERVICE_URL`. Si Python quedara público, cualquiera con el secreto podría suplantar usuarios.

### Qué cambia respecto al prototipo
- Los ids son **texto** como en el monolito (`idPractica`, `numDocumento`: `VARCHAR(30)`), no números.
- El **estudiante** de una evaluación siempre es el de la práctica (lo fija el monolito, no el navegador) y un tutor solo
  opera sobre **sus** prácticas.
- La IA solo puede leer evidencias **de la práctica de esa evaluación**; los archivos se descargan solo de `ALLOWED_FILE_HOSTS`.
- Las evaluaciones nuevas **no reemplazan** el banco de preguntas antiguo (`/api/questions`); conviven.
