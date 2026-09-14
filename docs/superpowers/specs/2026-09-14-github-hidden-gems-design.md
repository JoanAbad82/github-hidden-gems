# GitHub Hidden Gems — Especificación Final V1

**Estado:** FROZEN_DESIGN  
**Fecha:** 2026-09-14  
**Versión:** SPEC_V1  
**Score:** HIDDEN_GEM_SCORE_V1  
**Prompt IA:** DEEP_ANALYZER_PROMPT_V1  
**Formato informe:** REPORT_FORMAT_V1

## 1. Propósito

Sistema automático, ejecutado inicialmente una vez al día en GitHub Actions, para descubrir repositorios públicos poco conocidos pero valiosos en cuatro áreas con el mismo peso: IA/agentes, automatización, extracción/análisis de datos y trading. Bitcoin/crypto no constituye una categoría independiente. La prioridad metodológica es **precision > recall**.

## 2. Arquitectura canónica

GitHub Actions → Discovery Engine → Hard Filter → Light Analyzer → Relationship Explorer (máximo un salto) → Deep Analyzer → Hidden Gem Scorer → SQLite History → Report Builder → GitHub Issue → GitHub Notifications/email.

El núcleo obligatorio es GitHub + Python + SQLite. DeepSeek es una capa opcional de mejora semántica y el sistema debe funcionar con `LLM_ENABLED=false`.

## 3. Discovery Engine

Se combinan cinco vías: repositorios recién creados, recientemente activos, búsquedas temáticas, intersecciones temáticas y exploración relacional limitada. Las búsquedas núcleo son diarias y las secundarias rotativas.

Prioridad de novedad: 0–15 días máxima; 16–30 muy alta; 31–60 alta; 61–90 alta/moderada; >90 sin prioridad especial. Actividad: 0–15 días máxima; 16–30 alta; >30 fuerte penalización salvo excepciones justificadas.

Bandas de estrellas prioritarias: 0–24, 25–99, 100–249, 250–499. Excepción: 500–2.000 estrellas con umbral de notificación 80. Más de 2.000 estrellas no es notificable en V1.

Lenguajes prioritarios: Python, TypeScript/JavaScript, Go y Rust. Otros están permitidos.

Presupuesto máximo inicial por run: ~1.000 repositorios únicos vistos, 200 Light Analyzer, 20 semillas Relationship Explorer y 25 Deep Analyzer.

## 4. Hard Filter

Códigos mínimos de descarte: `REJECT_FORK`, `REJECT_ARCHIVED`, `REJECT_EMPTY`, `REJECT_TUTORIAL`, `REJECT_TEMPLATE`, `REJECT_DEMO`, `REJECT_SPAM`, `REJECT_IRRELEVANT`, `REJECT_LOW_MAX_SCORE`.

Pocas estrellas, autor desconocido, un único contributor, falta de releases, lenguaje no prioritario o extrema juventud no son motivos automáticos de descarte. Principio: agresivo con el ruido, conservador con la innovación.

## 5. Light Analyzer

Inspecciona README, metadatos, árbol de archivos, releases, actividad reciente y manifests/configuración. No descarga ni ejecuta el repositorio. Produce evidencia, hashes y una evaluación preliminar. Antes del análisis caro se calcula `maximum_possible_score`; si es <70 se descarta.

## 6. Hidden Gem Score V1

Escala: 0–69 no notificable; 70–84 INTERESTING; 85–100 EXCEPTIONAL.

| Dimensión | Máximo |
|---|---:|
| Relevancia temática | 20 |
| Calidad técnica/documentación | 20 |
| Actividad reciente | 20 |
| Baja visibilidad | 15 |
| Novedad | 10 |
| Originalidad/utilidad | 10 |
| Intersección temática | 5 |
| **Total** | **100** |

Visibilidad: 0–24 estrellas=15; 25–99=13; 100–249=10; 250–499=7; 500–999=4; 1.000–2.000=1–3; >2.000=0 y no notificable.

Novedad: 0–15 días=10; 16–30=9; 31–60=7; 61–90=5; 91–180=2; >180=0.

Intersección: 1 área=0; 2=2; 3=4; 4=5. La relación debe ser funcional.

Repositorios con 500–2.000 estrellas requieren score >=80. Renotificación por score requiere `current_score - last_notified_score >= 10`.

## 7. Confidence

Estados: HIGH, MEDIUM, LOW. No suma puntos. Un score alto con LOW confidence no se notifica directamente; se intenta ampliar evidencia y, si sigue LOW, se almacena para reconsideración.

## 8. Deep Analyzer e IA

Máximo 25 candidatos/run. Selecciona estáticamente archivos concretos (documentación, manifests, tests, ejemplos, módulos centrales). Nunca ejecuta código externo, instala dependencias, lanza notebooks/tests ni usa Docker del candidato.

DeepSeek es el proveedor inicial detrás de una interfaz genérica. Evalúa relevancia profunda, originalidad, utilidad, coherencia, riesgos, evidencia y confianza. No decide estrellas, antigüedad, actividad objetiva, score total ni notificación. La salida es estructurada y validada. Todo contenido externo es `UNTRUSTED INPUT` y nunca se obedece como instrucción.

Límites obligatorios: `MAX_LLM_CANDIDATES_PER_RUN`, `MAX_LLM_CALLS_PER_RUN`, `MAX_INPUT_TOKENS_PER_REPO`, `MAX_OUTPUT_TOKENS_PER_REPO`, `MAX_LLM_BUDGET_PER_RUN`. Una segunda llamada solo se permite por salida inválida, contradicción relevante, candidato cercano a excepcional o confianza resoluble con nueva evidencia.

## 9. SQLite y memoria

SQLite es la fuente canónica del histórico técnico. Identidad primaria: GitHub repository ID. Tablas principales: `repositories`, `observations`, `discovery_hits`, `filter_decisions`, `scores`, `llm_analyses`, `releases`, `relationships`, `notifications`, `runs`, `schema_migrations`.

Se guardan hashes de README, árbol, dependencias y contenido relevante. El `relevant_content_hash` permite reutilizar análisis IA cuando contenido, prompt y schema siguen compatibles.

Ramas: `main` para código/configuración/tests/workflows/prompts/schemas/docs; `state` para `history.sqlite3`, `state_manifest.json` y backups rotativos. Antes de persistir: transacciones completas, conexiones cerradas, foreign keys activadas, `PRAGMA integrity_check`, schema válido y backup.

## 10. Report Builder y notificaciones

Solo se crea Issue si existe al menos un candidato notificable. 1–5 candidatos: mostrar hasta 5. Si hay más, los puestos 6–10 solo pueden añadirse si su score es >=85. Máximo absoluto 10. No hay relleno.

Cada ficha incluye: qué hace, por qué puede interesarte, estrellas, fecha de creación, última actividad relevante, lenguaje principal, áreas relacionadas, Hidden Gem Score y enlace. También muestra confidence y NEW DISCOVERY/UPDATE.

Un run crea como máximo un Issue. Labels mínimos: `discovery-report`, `exceptional-findings`, `has-updates`. GitHub Issues es el archivo de usuario; SQLite es la memoria canónica.

Email: GitHub Notifications. Configuración prevista `Watch → Custom → Issues` y `NOTIFICATION_GITHUB_LOGIN` para asignar el Issue a la cuenta objetivo cuando sea posible. La entrega real por email se valida en el Controlled Live Test.

Protocolo idempotente canónico: generar `REPORT_FINGERPRINT` → guardar `PENDING_REPORT` y persistir checkpoint → buscar/adoptar Issue existente por fingerprint o crear uno → registrar issue/notifications como `REPORT_PUBLISHED` → integrity check → persistir estado definitivo.

## 11. GitHub Actions, seguridad y coste

Triggers: `schedule` y `workflow_dispatch`. Runner Linux estándar de GitHub. Una única ejecución escritora mediante `concurrency`. Se usa `GITHUB_TOKEN` con permisos mínimos; no PAT salvo necesidad demostrada. DeepSeek API key se guarda solo como GitHub Actions Secret.

El cliente GitHub centraliza autenticación, timeouts, retries, backoff, rate-limit monitoring y errores. Zonas de presupuesto: GREEN, YELLOW, RED. En YELLOW se detiene trabajo no esencial; en RED se persiste estado válido y termina como `PARTIAL_SUCCESS_RATE_LIMIT`.

El bot nunca clona ni ejecuta repositorios candidatos. No imprime secretos, headers de autorización ni el entorno completo. Fallos individuales son fail-soft; corrupción SQLite, configuración inválida o violaciones de integridad/seguridad son fallos críticos.

Objetivo económico: GitHub 0 € adicionales, infraestructura externa 0 €, DeepSeek mínimo, limitado y medido.

## 12. Estructura de componentes

Estructura base: `.github/workflows/`, `config/`, `prompts/`, `schemas/`, `migrations/sqlite/`, `src/hidden_gems/` con `discovery`, `filtering`, `light_analysis`, `relationships`, `deep_analysis`, `scoring`, `history`, `reporting`, `github`, `llm`, `security`, `common`; y `tests/unit`, `tests/integration`, `tests/fixtures`, `tests/live`.

Fronteras: `github` es el único acceso programático a GitHub; `llm` es el único acceso a DeepSeek; `history` es el único escritor SQLite; `GitHubIssuePublisher` es el único publicador de Issues; `scoring` no tiene red.

Configuración principal: `config/discovery.yml`, `config/topics.yml`, `config/scoring.yml`, `config/limits.yml`, `prompts/deep_analyzer_v1.txt`, `schemas/llm_analysis_v1.json`. La configuración se valida antes de cualquier llamada externa y claves desconocidas fallan con `FAILED_CONFIGURATION`.

## 13. Testing y aceptación

Niveles: UNIT → INTEGRATION → CONTROLLED LIVE → MULTI-DAY VALIDATION. Modo obligatorio `DRY_RUN=true` sin Issue real. Dataset humano de referencia de 20–40 repositorios con etiquetas GOOD/MAYBE/BAD. KPI principal: Useful Discovery Rate. Criterio mínimo inicial: >=70% GOOD+MAYBE entre notificados.

Antes de V1_ACCEPTED: 7 ejecuciones diarias consecutivas con 0 corrupción SQLite, 0 secretos expuestos, 0 Issues duplicados, 0 conflictos concurrentes y 0 superaciones de presupuesto. Estados de proyecto: IMPLEMENTED → TESTED → LIVE_VALIDATED → V1_ACCEPTED.

## 14. Invariantes congeladas V1

- 4 áreas con el mismo peso.
- `PRIMARY_STAR_LIMIT = 499`.
- `EXCEPTION_STAR_RANGE = 500–2000`.
- `EXCEPTION_THRESHOLD = 80`.
- `NOTIFICATION_THRESHOLD = 70`.
- `EXCEPTIONAL_THRESHOLD = 85`.
- `REN_NOTIFICATION_SCORE_DELTA = +10`.
- `NORMAL_REPORT_MAX = 5`.
- `ABSOLUTE_REPORT_MAX = 10`.
- Puestos 6–10 requieren score >=85.
- `RELATIONSHIP_DEPTH = 1`.
- `EXTERNAL_CODE_EXECUTION = FORBIDDEN`.
- SQLite = histórico canónico.
- GitHub Issue = archivo visible para el usuario.
- Email = GitHub Notifications.
- Proveedor IA inicial = DeepSeek.
- IA no obligatoria.
- Schedule inicial = diario.

Cualquier cambio posterior de estas invariantes requiere una modificación explícita de la especificación.
