-- Datos de ejemplo SOLO para desarrollo (tutor 'T-1001', estudiante 'E-2002', práctica 'PRA-DEV-10').
-- Se cargan automáticamente con docker compose; no los uses en producción.

INSERT INTO evaluacion (id_practica, id_actividad, id_tutor, id_estudiante, titulo, descripcion, estado, intentos_permitidos)
VALUES ('PRA-DEV-10', 'PRA-DEV-10-A5', 'T-1001', 'E-2002', 'Evaluación de planeación de clase',
        'Preguntas sobre la planeación y ejecución de la clase de matemáticas.', 'PUBLICADA', 2);

INSERT INTO pregunta (id_evaluacion, tipo_pregunta, enunciado, valor_pregunta, orden, origen, estado_revision, explicacion)
VALUES (1, 'OPCION_MULTIPLE', '¿Cuál es el primer elemento que debe definirse al planear una clase?', 1, 1, 'MANUAL', 'APROBADA',
        'Los objetivos de aprendizaje orientan el resto de decisiones de la planeación.'),
       (1, 'VERDADERO_FALSO', 'La evaluación formativa solo se realiza al final de la unidad.', 1, 2, 'MANUAL', 'APROBADA',
        'La evaluación formativa es continua: ocurre durante el proceso.');

INSERT INTO pregunta (id_evaluacion, tipo_pregunta, enunciado, valor_pregunta, orden, origen, estado_revision, respuesta_esperada)
VALUES (1, 'ABIERTA', 'Describe cómo adaptaste una actividad al ritmo de tus estudiantes.', 2, 3, 'MANUAL', 'APROBADA',
        'Debe mencionar al menos una estrategia de diferenciación y su efecto observado.');

INSERT INTO opcion_pregunta (id_pregunta, texto, es_correcta, orden) VALUES
  (1, 'Los objetivos de aprendizaje', TRUE, 1),
  (1, 'La lista de asistencia', FALSE, 2),
  (1, 'El color del tablero', FALSE, 3),
  (1, 'La hora del recreo', FALSE, 4),
  (2, 'Verdadero', FALSE, 1),
  (2, 'Falso', TRUE, 2);
