-- =============================================================================
--  SPP · Servicio de Evaluación  ·  Esquema PostgreSQL
--
--  Base de datos propia del microservicio (ej. "spp_evaluacion"). Las llaves
--  hacia el monolito (práctica, actividad, tutor, estudiante, evidencia) son
--  REFERENCIAS LÓGICAS (VARCHAR(30) sin FOREIGN KEY): viven en otra base.
--  Usan los mismos tipos del monolito: idPractica / idActividad / numDocumento son varchar(30).
--
--  Mapeo con el diagrama ER:
--    evaluacion      -> evaluacion      (+ id_estudiante, id_tutor, id_actividad)
--    Pregunta        -> pregunta        (+ origen, estado_revision, ...)
--    (nuevo)         -> opcion_pregunta (opciones de selección / verdadero-falso)
--    Respuesta       -> respuesta       (ahora cuelga de un intento)
--    retroPregunta   -> retro_pregunta
--    (nuevo)         -> intento_evaluacion, contexto_pregunta, generacion_ia
-- =============================================================================

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
--  evaluacion
-- -----------------------------------------------------------------------------
CREATE TABLE evaluacion (
    id_evaluacion        BIGSERIAL     PRIMARY KEY,
    id_practica          VARCHAR(30)   NOT NULL,            -- ref. lógica: practica."idPractica" del monolito
    id_actividad         VARCHAR(30),                       -- ref. lógica (opcional): actividad."idActividad"
    id_tutor             VARCHAR(30)   NOT NULL,            -- numDocumento del tutor que la crea y la asigna
    id_estudiante        VARCHAR(30)   NOT NULL,            -- numDocumento del estudiante dueño de la práctica
    titulo               VARCHAR(200)  NOT NULL,
    descripcion          TEXT,
    estado               VARCHAR(10)   NOT NULL DEFAULT 'BORRADOR'
                         CHECK (estado IN ('BORRADOR', 'PUBLICADA', 'CERRADA')),
    fecha_evaluacion     TIMESTAMPTZ   NOT NULL DEFAULT now(),
    fecha_limite         TIMESTAMPTZ,
    intentos_permitidos  SMALLINT      NOT NULL DEFAULT 1 CHECK (intentos_permitidos >= 1),
    nota_maxima          NUMERIC(5,2)  NOT NULL DEFAULT 5.00 CHECK (nota_maxima > 0),
    mostrar_resultados   BOOLEAN       NOT NULL DEFAULT TRUE,
    nota_final           NUMERIC(5,2),                      -- mejor nota calificada de sus intentos
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_evaluacion_practica   ON evaluacion (id_practica);
CREATE INDEX ix_evaluacion_tutor      ON evaluacion (id_tutor);
CREATE INDEX ix_evaluacion_estudiante ON evaluacion (id_estudiante, estado);
CREATE TRIGGER trg_evaluacion_updated BEFORE UPDATE ON evaluacion
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
--  generacion_ia : bitácora de cada petición de "generar preguntas con IA"
-- -----------------------------------------------------------------------------
CREATE TABLE generacion_ia (
    id_generacion        BIGSERIAL     PRIMARY KEY,
    id_evaluacion        BIGINT        NOT NULL REFERENCES evaluacion (id_evaluacion) ON DELETE CASCADE,
    id_tutor             VARCHAR(30)   NOT NULL,
    cantidad_solicitada  SMALLINT      NOT NULL CHECK (cantidad_solicitada BETWEEN 1 AND 50),
    cantidad_generada    SMALLINT      NOT NULL DEFAULT 0,
    parametros           JSONB         NOT NULL DEFAULT '{}'::jsonb,   -- tipos, dificultad, instrucciones, tema
    proveedor            VARCHAR(30),                                   -- anthropic | mock
    modelo               VARCHAR(80),
    prompt_usado         TEXT,
    estado               VARCHAR(10)   NOT NULL DEFAULT 'PENDIENTE'
                         CHECK (estado IN ('PENDIENTE', 'COMPLETADA', 'FALLIDA')),
    error                TEXT,
    tokens_entrada       INTEGER,
    tokens_salida        INTEGER,
    duracion_ms          INTEGER,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_generacion_evaluacion ON generacion_ia (id_evaluacion);

-- -----------------------------------------------------------------------------
--  pregunta
-- -----------------------------------------------------------------------------
CREATE TABLE pregunta (
    id_pregunta          BIGSERIAL     PRIMARY KEY,
    id_evaluacion        BIGINT        NOT NULL REFERENCES evaluacion (id_evaluacion) ON DELETE CASCADE,
    id_generacion        BIGINT        REFERENCES generacion_ia (id_generacion) ON DELETE SET NULL,
    tipo_pregunta        VARCHAR(20)   NOT NULL
                         CHECK (tipo_pregunta IN ('OPCION_MULTIPLE', 'VERDADERO_FALSO', 'ABIERTA')),
    enunciado            TEXT          NOT NULL,
    valor_pregunta       NUMERIC(6,2)  NOT NULL DEFAULT 1 CHECK (valor_pregunta > 0),  -- peso relativo
    orden                INTEGER       NOT NULL DEFAULT 0,
    origen               VARCHAR(6)    NOT NULL DEFAULT 'MANUAL' CHECK (origen IN ('MANUAL', 'IA')),
    estado_revision      VARCHAR(10)   NOT NULL DEFAULT 'APROBADA'
                         CHECK (estado_revision IN ('BORRADOR', 'APROBADA', 'RECHAZADA')),
    dificultad           VARCHAR(10)   CHECK (dificultad IN ('FACIL', 'MEDIA', 'DIFICIL')),
    respuesta_esperada   TEXT,                              -- rúbrica / respuesta modelo (abiertas)
    explicacion          TEXT,                              -- por qué la respuesta correcta lo es
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_pregunta_evaluacion ON pregunta (id_evaluacion, orden);
CREATE INDEX ix_pregunta_generacion ON pregunta (id_generacion);
CREATE TRIGGER trg_pregunta_updated BEFORE UPDATE ON pregunta
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
--  opcion_pregunta
-- -----------------------------------------------------------------------------
CREATE TABLE opcion_pregunta (
    id_opcion            BIGSERIAL     PRIMARY KEY,
    id_pregunta          BIGINT        NOT NULL REFERENCES pregunta (id_pregunta) ON DELETE CASCADE,
    texto                TEXT          NOT NULL,
    es_correcta          BOOLEAN       NOT NULL DEFAULT FALSE,
    orden                SMALLINT      NOT NULL DEFAULT 0
);
CREATE INDEX ix_opcion_pregunta ON opcion_pregunta (id_pregunta, orden);
-- A lo sumo UNA opción correcta por pregunta (garantizado por la BD)
CREATE UNIQUE INDEX ux_opcion_una_correcta ON opcion_pregunta (id_pregunta) WHERE es_correcta;

-- -----------------------------------------------------------------------------
--  contexto_pregunta : de dónde salió el contenido usado para generar preguntas
--  (trazabilidad). id_referencia_externa apunta a la evidencia/archivo/actividad
--  del OTRO servicio; texto_extraido es una copia de lo que realmente se envió.
-- -----------------------------------------------------------------------------
CREATE TABLE contexto_pregunta (
    id_contexto            BIGSERIAL     PRIMARY KEY,
    id_evaluacion          BIGINT        NOT NULL REFERENCES evaluacion (id_evaluacion) ON DELETE CASCADE,
    id_generacion          BIGINT        REFERENCES generacion_ia (id_generacion) ON DELETE CASCADE,
    tipo_fuente            VARCHAR(20)   NOT NULL
                           CHECK (tipo_fuente IN ('TEMA_LIBRE', 'EVIDENCIA', 'ARCHIVO_EVIDENCIA',
                                                  'ACTIVIDAD', 'ARCHIVO_ACTIVIDAD')),
    id_referencia_externa  VARCHAR(100),
    nombre                 VARCHAR(255),
    texto_extraido         TEXT,
    caracteres             INTEGER       NOT NULL DEFAULT 0,
    truncado               BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_contexto_evaluacion ON contexto_pregunta (id_evaluacion);
CREATE INDEX ix_contexto_generacion ON contexto_pregunta (id_generacion);

-- -----------------------------------------------------------------------------
--  intento_evaluacion : una vez que el estudiante presenta la evaluación
-- -----------------------------------------------------------------------------
CREATE TABLE intento_evaluacion (
    id_intento           BIGSERIAL     PRIMARY KEY,
    id_evaluacion        BIGINT        NOT NULL REFERENCES evaluacion (id_evaluacion) ON DELETE CASCADE,
    id_estudiante        VARCHAR(30)   NOT NULL,
    numero_intento       SMALLINT      NOT NULL CHECK (numero_intento >= 1),
    estado               VARCHAR(10)   NOT NULL DEFAULT 'EN_CURSO'
                         CHECK (estado IN ('EN_CURSO', 'ENVIADO', 'CALIFICADO')),
    fecha_inicio         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    fecha_envio          TIMESTAMPTZ,
    nota_obtenida        NUMERIC(5,2),
    UNIQUE (id_evaluacion, id_estudiante, numero_intento)
);
CREATE INDEX ix_intento_evaluacion ON intento_evaluacion (id_evaluacion);
CREATE INDEX ix_intento_estudiante ON intento_evaluacion (id_estudiante);

-- -----------------------------------------------------------------------------
--  respuesta
-- -----------------------------------------------------------------------------
CREATE TABLE respuesta (
    id_respuesta         BIGSERIAL     PRIMARY KEY,
    id_intento           BIGINT        NOT NULL REFERENCES intento_evaluacion (id_intento) ON DELETE CASCADE,
    id_pregunta          BIGINT        NOT NULL REFERENCES pregunta (id_pregunta) ON DELETE CASCADE,
    id_opcion            BIGINT        REFERENCES opcion_pregunta (id_opcion) ON DELETE SET NULL,
    respuesta            TEXT,                              -- texto libre (abiertas) o texto de la opción elegida
    es_correcta          BOOLEAN,                           -- NULL = pendiente de calificar
    nota_obtenida        NUMERIC(6,2),                      -- NULL = pendiente (opcional, como en el ER)
    calificada_por       VARCHAR(5)    CHECK (calificada_por IN ('AUTO', 'TUTOR')),
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (id_intento, id_pregunta)
);
CREATE INDEX ix_respuesta_pregunta ON respuesta (id_pregunta);
CREATE TRIGGER trg_respuesta_updated BEFORE UPDATE ON respuesta
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
--  retro_pregunta : comentario del tutor sobre una respuesta
-- -----------------------------------------------------------------------------
CREATE TABLE retro_pregunta (
    id_retro_pregunta    BIGSERIAL     PRIMARY KEY,
    id_respuesta         BIGINT        NOT NULL REFERENCES respuesta (id_respuesta) ON DELETE CASCADE,
    id_tutor             VARCHAR(30)   NOT NULL,
    comentario           TEXT          NOT NULL,
    fecha                TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX ix_retro_respuesta ON retro_pregunta (id_respuesta);
