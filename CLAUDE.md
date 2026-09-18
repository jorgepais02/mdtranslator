# CLAUDE.md — mdtranslator

## 1. Descripción
Pipeline CLI para convertir apuntes académicos en Markdown a múltiples idiomas, generando DOCX y PDF con formato académico real (RTL, CJK, cabeceras, paginación). Sube automáticamente a Google Drive. Pensado para uso personal por un estudiante.

---

## 2. Stack Técnico
- **Python 3.11+**, sin framework web
- **Pandoc** (binario externo, requerido) → DOCX desde Markdown
- **LibreOffice headless** (opcional) → PDF desde DOCX
- **Modelos de IA** (`src/ai/`) → formateado de txt, refinamiento post-traducción y un
  proveedor de traducción. Gemini con su SDK (`google-genai`); Groq y Cerebras con la API
  compatible con OpenAI (`requests`), y con ella cualquier otro endpoint. Fallback por
  **modelo**, no solo por proveedor
- **DeepL API + Azure AI Translator** → traducción, con fallback automático
- **rich + questionary** → UI CLI interactiva
- **lxml** → manipulación directa del XML del DOCX (postproceso)
- **python-docx** → generación DOCX
- **Google Drive API + Docs API** → subida OAuth2 desde `secrets/credentials.json`
- **SQLite (WAL)** → caché de traducciones en `cache/translations.db`

---

## 3. Estructura de Directorios
```
src/
  ai/                     # Modelos de IA: quién hay, en qué orden y qué hacer con un 429
    base.py               # AIModel ABC, AIError/AIQuotaError, FallbackModel, espera_pedida
    gemini.py             # GeminiModel (SDK google-genai)
    openai_compat.py      # OpenAICompatModel: /v1/chat/completions (Groq, Cerebras, …)
    registry.py           # AVAILABLE_MODELS + get_model(orden) + modelo_de(proveedor)
  cli/                    # Presentación: wizard, vistas Live, entry point
    main.py               # Entry point (python -m src.cli.main). Flags, --json, --set-folder
    wizard.py             # Config interactiva: máquina de pasos con retroceso (solo recoge datos)
    prompts.py            # questionary + ⌫ para volver atrás (BACK / None)
    confirmation.py       # Pantalla de confirmación previa (yes / no / back)
    pipeline.py           # Orquestación real: ThreadPoolExecutor, vistas Live, cancelación
    folder_picker.py      # Carpetas de Drive: navegar, crear, recordar (wizard y --set-folder)
    key_setup.py          # Alta de una clave: elegir proveedor, abrir su página, escribir .env
    results.py            # Tabla final de resultados
    styles.py             # console, paleta y su significado, summary_grid, LANGUAGES
    errors.py             # CLIError y subclases
  core/
    config.py             # PROJECT_ROOT, SOURCES_DIR, TRANSLATED_DIR, CONFIG, DRIVE_FOLDER_ID
    sources.py            # collect_sources / needs_formatting / load_markdown
    parser.py             # parse_markdown_lines / rebuild + contexto_del_documento
    docgen.py             # generate_docx_document + convert_docx_to_pdf (LibreOffice)
  translators/
    base.py               # BaseTranslator ABC, Fallback, Protected, chunk_texts, call_translate
    registry.py           # AVAILABLE_TRANSLATORS + get_translator() + supported_by()
    langs.py              # Código de la UI → código de cada API, y qué cubre cada una
    deepl.py azure.py gemini.py   # Proveedores
    wrappers.py           # CachingTranslator
    cache.py              # TranslationCache (SQLite WAL, conexión por hilo)
  document/
    converter.py          # convert(md, docx, lang, header) via Pandoc
    postprocess.py        # Manipula el XML del DOCX post-Pandoc (RTL, CJK, header, footer)
    refiner.py            # Refinamiento nodo a nodo con src/ai (solo AR/ZH/JA/KO/FA/HE/UR)
  integrations/
    drive.py              # GoogleDocsManager: auth, carpetas, naming, upload/replace
    generate_md.py        # .txt crudo → .md académico con src/ai
tests/                    # pytest, sin red ni credenciales (ver §9)
sources/                  # Archivos .md/.txt de entrada
templates/                # template_ltr.docx + template_rtl.docx (referencia Pandoc)
translated/               # Salida: translated/{lang}/{stem}.{lang}.{md,docx,pdf} (gitignored)
cache/                    # translations.db (gitignored)
secrets/                  # credentials.json + token.json (gitignored)
public/header.png         # Imagen de cabecera opcional para DOCX
config.json               # Config del usuario (gitignored); config.example.json es la plantilla
.env                      # API keys (gitignored)
```

---

## 4. Comandos Esenciales
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Ejecutar (modo recomendado)
./run_pipeline.sh                          # CLI interactivo
./run_pipeline.sh sources/apuntes.md       # con archivo pre-seleccionado
./run_pipeline.sh --set-folder             # elegir carpeta de Drive (se guarda en config.json)
./run_pipeline.sh --add-key                # dar de alta una clave de API (se guarda en .env)
./run_pipeline.sh --add-key groq           # …esa, sin preguntar de quién

# Directo (sin bash wrapper)
source .venv/bin/activate
python -m src.cli.main
python -m src.cli.main --all --lang EN FR --output both --source-lang ES -y
python -m src.cli.main --all --lang EN --json     # JSON limpio en stdout, UI a stderr

# Módulos como scripts
python -m src.ai.registry --check           # qué modelos hay y qué ids acepta cada API
python -m src.integrations.generate_md sources/apuntes.txt
python -m src.document.converter translated/es/apuntes.es.md --lang es
python -m src.document.postprocess output.docx --lang ar --header public/header.png

# Tests (no tocan red, APIs ni Drive)
pip install -r requirements-dev.txt
pytest -q
```

Flags de `main.py`: `file`, `--lang`, `--provider {azure,deepl,auto}`, `--output {local,drive,both}`,
`--all`, `--no-format`, `--source-lang`, `--set-folder`, `--add-key [PROVIDER]`, `--yes/-y`, `--json`,
`--version`.

---

## 5. Convenciones de Código
- Funciones públicas tienen docstrings cortos con API/CLI describiendo argumentos
- Los módulos con API pública abren con un docstring `API:` / `CLI:` listando sus entradas
- `Path` de `pathlib` siempre sobre strings para rutas; siempre `.resolve()` antes de pasar a subprocess
- Módulos con doble modo: importable como librería + ejecutable con `if __name__ == "__main__"`
- Idiomas: códigos ISO lowercase (`es`, `ar`, `zh`) internamente; uppercase (`EN`, `ZH`) en la UI
- `console = Console()` de rich para todo output; nunca `print()` salvo warnings a stderr o `--json`
- Variables de entorno cargadas con `load_dotenv()` solo en el entry point o `__main__`
- Los comentarios explican **por qué**, no qué: casi todos documentan un fallo real ya observado

---

## 6. Arquitectura y Decisiones Clave

### Flujo de datos principal
```
sources/*.md
  → wizard.py (config) | main.py (flags)
  → pipeline.py: _prepare_docs → parser.parse_markdown_lines → detect_source_language
  → ThreadPoolExecutor sobre tareas (fichero × idioma)
      → translators (Protected → Fallback → Caching → proveedor)
      → parser.rebuild_markdown_from_translations
      → refiner.refine_markdown (solo idiomas que lo piden)
      → docgen.generate_docx_document → document/converter.py → document/postprocess.py
  → docgen.convert_many_to_pdf: los PDFs de toda la ejecución, en una invocación de
    LibreOffice por carpeta y las carpetas en paralelo
      → drive.resolve_target + upload_docx
  → results.py
```

El wizard y la confirmación forman un bucle: "Change something…" vuelve al wizard con
`previo=config`, y ⌫ retrocede una pregunta dentro del wizard.

### Por qué LibreOffice y no LaTeX
El formato del documento vive en `templates/*.docx` y en las ~440 líneas de
`document/postprocess.py`. LibreOffice renderiza **ese mismo fichero**, así que el PDF y el
DOCX son el mismo documento. Una ruta `pandoc --pdf-engine=xelatex` sería un segundo motor
de estilos en paralelo, y sin configurar fuentes pierde 99 glifos árabes y 35 chinos —
con código de salida 0, sin avisar.

Medido: arrancar LibreOffice cuesta ~1,4s y convertir un documento ~0,2s. Por eso los PDFs
se hacen todos al final (`convert_many_to_pdf`), una invocación por carpeta de destino y
las carpetas en paralelo, en vez de un proceso por documento.

### Un color, un significado
`styles.py` documenta el reparto y es el único sitio donde se decide. Hay **dos**
repartos, porque hay dos clases de pantalla:

- **Las de pregunta** (wizard, confirmación, selector de carpetas) no tienen estados,
  tienen niveles, y cada color ocupa un único nivel: `BRAND` #7dcfff solo para
  `mdtranslator`, `TITLE` #e6e6e6 solo para el título de la pregunta viva, `SELECT`
  #7aa2f7 solo para lo elegido y el ❯ que lo señala, `CONTEXT` #565f89 para las migas
  y los datos ya contestados, `OPTION` #6b7280 para todo lo no elegido, `META` #4b5263
  para versión, subtítulos, pistas de teclado y "back", y `RULE` #33364a para el
  filete. La rampa de grises va META < CONTEXT < OPTION < TITLE: antes eran tres tonos
  entre #d4d7dc y #e8e9ec, tan parecidos que la pantalla se veía plana por mucho que la
  estructura estuviera bien.
- **Las de ejecución** (pipeline y resultados) sí tienen estados: gris nombra, blanco
  es contenido, cian es identidad de idioma, azul es dónde está el cursor, amarillo es
  "en marcha o avisa", verde es **solo** éxito y rojo solo fallo. El verde significaba
  dos cosas —la opción elegida en el wizard y el éxito de una tarea— y con cuatro
  preguntas contestadas la pantalla llegaba verde al pipeline: el primer ✓ de verdad
  ya no destacaba. `status_style()` decide el color de un estado; ninguna vista lo
  elige por su cuenta.

El cian no cruza de un reparto al otro: en el picker `BRAND` ya ocupa esa zona del
espectro y dos cianes en la misma pantalla dejan de significar cosas distintas, así que
allí la identidad de idioma es un dato más y va en `CONTEXT`.

`styles.py` pone `PROMPT_TOOLKIT_COLOR_DEPTH=DEPTH_24_BIT` antes de importar
questionary. Sin eso prompt_toolkit cuantiza a 256 colores mientras rich pinta 24 bits y
la misma constante sale con dos valores en la misma pantalla (#5f6673 → #6c6c6c,
#b3bac4 → #bcbcbc, #56a8ee → #5fafff). Medido capturando la terminal en un pty.

### El wizard es una máquina de pasos
`run_wizard` recorre `_PASOS` con un índice y una dirección, no una lista de preguntas
seguidas. Cada paso devuelve `SKIP` (no aplica en esta ejecución), `BACK`, `None`
(Ctrl+C) o `True`. Por eso repinta la pantalla entera en cada paso: lo ya contestado se
colapsa a **una línea** de migas (`_migas`) y la pregunta viva se despliega debajo.
Antes cada pregunta dejaba su lista entera de opciones en pantalla; luego fue una
rejilla de etiqueta y dato, una fila por respuesta, y cinco filas encima de la pregunta
pesaban tanto como ella. Las migas no llevan etiqueta porque el valor se explica solo
—"Auto (fallback)", "Local only", "EN FR"— y lo que importa es el orden, que es el de
los pasos.

El "step 3 of 5" que cerraba el filete se quitó: contaba unos pasos que ni son siempre
los mismos —la fuente no se pregunta si vino por argumento, el formateo solo si hay
algún `.txt`— ni llevan a ningún sitio, porque el wizard no se puede abandonar a la
mitad.

`prompts.py` engancha ⌫ a los prompts de questionary. En `select` y `confirm` el objeto
de bindings admite `.add`; en `text` es un merge inmutable y hay que envolverlo, y ahí
el binding lleva un filtro: solo vuelve atrás con el campo **vacío**, o no se podría
corregir una letra. `Esc` no se usa —en terminal significa cancelar— ni `←`, que dentro
de un campo mueve el cursor. La confirmación tiene "Change something…", que reabre el
wizard con `previo=config` y todo preseleccionado.

Las cuatro preguntas empiezan por `_exige_terminal()`: prompt_toolkit necesita un tty
para leer las teclas y sin él suelta un `EOFError` con veinte líneas de traza —lo dio el
`!` de un cliente que no abre pty—, y una traza no es una pantalla. Se mira en las cuatro
funciones y no dentro de `_ask`, que en las listas ya tiene el título pintado encima. El
`CLIError` que lanza lo pinta `main` con `styles.bloque(destacar=True)`: antes `main` solo
atrapaba `KeyboardInterrupt`, así que un mensaje ya redactado salía también como traza.

El título de la pregunta y el filete los pinta **rich**, y a questionary se le pasa un
mensaje vacío. questionary tiene una única clase `separator` para todo lo que no es una
opción, y el filete (`RULE`) y los subtítulos (`META`, cursiva) son dos roles: con la
misma clase saldrían iguales. De paso, la línea vacía del mensaje es el aire que va
entre el filete y la lista. `instruction=" "` —un espacio, no cadena vacía— es lo que
hay que pasarle para que no escriba "(Use arrow keys)" por su cuenta.

De la línea de pistas (`↑↓ move · ⏎ select · ⌫ back`) queda solo lo que no se adivina,
y alineado a la derecha del título: ↑↓ y ⏎ sobre una lista no hay que explicarlos y eran
dos tercios de aquella línea, pero ⌫ para volver es invención nuestra y "space" para
marcar no se adivina. Si no cabe, se cae antes que empujar al título.

`_desplegar()` intercala los huecos: una línea en blanco entre opciones cuando la lista
tiene seis o menos —con dieciocho idiomas serían treinta y seis renglones y no cabe en
ninguna ventana—. Ojo con `Separator("")`: `line or default` devuelve
`"---------------"`, así que el hueco se hace con `Separator(" ")`.

El subtítulo de una opción («use whichever is configured») solo se ve mientras el
cursor está en ella. questionary pinta los separadores siempre igual —no sabe dónde
está el cursor—, así que puesto como separator se quedaba encendido toda la pantalla y
acababa leyéndose como una línea más de la lista. `_subtitulo_vivo()` envuelve el
armador de tokens del `InquirerControl` y **inserta** el subtítulo debajo de la opción
señalada, con su línea en blanco respecto a la siguiente: las de abajo bajan un renglón
mientras está encendido y vuelven a subir al salir. Es a propósito —se probó rellenar el
hueco que ya había para que la lista no cambiara de alto, y el bloque quedaba pegado a
la opción siguiente—: en estado normal la separación entre opciones es siempre la
misma, y solo se abre para enseñar algo. En una lista apretada el salto lo pone el
propio subtítulo; si la opción señalada es la última, hereda el corte final.

El filete va pegado al título, sin línea en blanco en medio: con el hueco, la raya
flotaba a medio camino entre la pregunta y la lista y no se sabía de cuál de las dos era.

La cabecera es un grupo (marca, una línea, migas) y la pregunta es otro: entre los dos
van dos líneas. Con la misma distancia en los dos sitios se leía todo como una lista de
cuatro renglones.

`styles.aire_superior()` da las líneas en blanco que van sobre la marca, entre 1 y 4
según el alto de la ventana. Con una fija la cabecera quedaba clavada al borde de arriba,
y a pantalla completa se nota el doble porque debajo queda media ventana vacía. Depende
solo del alto y no del contenido: si dependiera del contenido, el bloque saltaría de
sitio entre una pregunta y la siguiente.

### Códigos de idioma por proveedor
`translators/langs.py` es la única traducción entre el código que se ve (`EN`, `PT`,
`ZH`) y el que espera cada API. DeepL **sí** traduce al inglés y al portugués, pero como
destino ya no acepta el idioma a secas: su lista oficial tiene `EN-GB`/`EN-US` y
`PT-BR`/`PT-PT`. Hoy `target_lang=EN` devuelve 200 porque lo mantienen como alias
obsoleto; el día que lo retiren, los dos idiomas más usados dejan de traducirse sin que
nadie haya tocado nada. `BaseTranslator.api_lang()` aplica la tabla y `supported`
declara qué cubre cada proveedor (`None` = no publica lista, se intenta igual).
Comprobado contra las APIs: Azure declara 138 idiomas y DeepL 110 destinos, y los 18 de
la interfaz están en las dos.

### El contexto del documento viaja con la traducción
Cada línea se traduce **sola**, y eso elige mal la acepción cuando la palabra tiene dos.
Medido en el chino del módulo 19: `Selección del Origen` salió `产地选择` —la procedencia
de un producto— y `Análisis Forense` salió `法医分析`, el forense de las autopsias. Lo
mismo en árabe (`الطب الشرعي`, medicina legal) y en francés (`légiste`). No es un fallo del
traductor: en español «forense» es las dos cosas y en la línea no hay nada que lo aclare.

Un glosario prefijado no vale — cada módulo habla de otra cosa y las palabras que se
vuelven ambiguas no se saben de antemano —, así que el contexto **sale del propio
documento**: `contexto_del_documento()` junta el `#` y la prosa de debajo hasta 600
caracteres. No para en el primer `##`: hay apuntes que van del título a la primera sección
sin entradilla, y ahí «Técnicas de Extracción Invasivas» era todo el contexto — el chino
tradujo la extracción como la **dental** (`侵入性拔牙技术`). Sigue las vallas de código en
vez de reconocerlas a secas, o el `dd if=/dev/sda` de dentro se cuela como si fuera prosa.

Cada proveedor lo usa como puede, y el que no puede no se entera:

- **DeepL** tiene `context` nativo, que no se traduce y **no se cobra**: medido contra la
  API, el mismo texto de 32 caracteres factura 32 con y sin 423 de contexto. Comprobado
  con el código real: `产地选择` → `选择数据源` y `法医分析` → `取证分析`
- **Gemini** lo mete en su prompt, que es lo mismo por otra vía
- **Azure no tiene nada equivalente**. Su `category` es un modelo entrenado aparte (de
  pago) y de su diccionario dinámico dice Microsoft que «solo es seguro para nombres
  propios». Como es el fallback, esa pasada va sin contexto
- **El refiner** es la red de seguridad, y no depende de quién tradujo: ya corre para
  `{ar, zh, ja, ko, fa, he, ur}` —los idiomas donde el defecto es grave— y el contexto es
  una coletilla de su `SYSTEM`, sin una petición de más

`call_translate` lo pasa **solo por nombre** y solo a quien lo declare, igual que
`source_lang`. Por posición no: es el cuarto argumento y su sitio depende de que
`source_lang` venga puesto, así que un proveedor con `*args` lo recibiría descolocado.

**No entra en la clave de la caché**, por lo mismo que `source_lang` y por algo más:
meterlo invalidaría las ~16.000 traducciones que ya hay —una pasada entera son 204.628
caracteres, el 41 % del cupo mensual gratuito— para reescribirlas con lo que ya dicen. Lo
que viaja con contexto es el texto **nuevo**, que de todas formas iba a la API, así que
esto mejora los módulos que vengan y no cuesta nada por los de antes. La consecuencia —dos
documentos que compartan una línea exacta comparten su traducción— es aceptable: en líneas
largas no pasa, y en las cortas el contexto del módulo es el mismo.

### Vistas y ancho del terminal
`styles.elide()` es el único recorte y `styles.bloque()` es su contrario: lo que se dice
en varias líneas suele acabar en un comando, y un comando a medias no sirve de nada
(`elide()` dejaba `python -m src.ai.registr…` a 50 columnas), así que ahí el texto
**dobla** con sangría colgante — una columna de tres para el glifo y el texto plegando
debajo de sí mismo. Lo usan el aviso del modelo al dar de alta una clave, el bloque
*Unfinished* y los `CLIError` que pinta `main`. `destacar=True` pinta la primera línea en
el color del glifo: un error tiene titular y detalle, un aviso es todo detalle.

Recortar, en cambio, lo usan el pipeline, el wizard y el selector de carpetas. questionary/prompt_toolkit envuelven las etiquetas largas en dos líneas y la
selección deja de leerse, así que lo que se les pasa va recortado — en un `Choice` el
título se recorta y el **valor se deja intacto**, o `collect_sources` no encontraría el
fichero.
Las barras y separadores se calculan sobre `console.width`, no con constantes: estaban
fijos a 40 y 44 y se partían en dos líneas en cualquier terminal estrecho.

`ProgressView` es **una sola vista** para los dos modos: con un fichero las filas son
sus idiomas, con `--all` son los ficheros. Había una segunda vista, una rejilla
fichero × idioma con su modo compacto y su propio vocabulario de glifos; se quitó porque
no contestaba a nada accionable —ver que `tema03` en árabe va por la mitad no permite
reordenar, ni cancelar esa celda, ni saltarse el fichero— y lo único que sí contestaba,
"¿se ha atascado algo?", lo dicen la línea de resumen y una barra que deja de moverse.

`_medidas()` reparte el ancho: la barra tiene un tope (`_MAX_BAR`) porque estirada a 100
columnas deja de leerse como barra, y un suelo (`_MIN_BAR`); antes de estrecharla se
sacrifica el texto del estado, y por debajo de seis columnas el estado desaparece entero
en vez de quedarse en `ge…`. El total de abajo se alinea con la columna de tiempos, no
con el borde de la pantalla.

La barra de cada fila avanza con hechos, no con un reloj: `_FASES` da el tramo de la
tarea en curso (traducir 0,30 · refinar 0,60 · subir 0,85) y el resto son tareas
terminadas. Nunca se pinta llena por debajo del 100 %, porque una barra llena en una
fila que sigue en marcha se lee como terminada. El Live recibe `_Vivo`, un renderable
que vuelve a preguntarle a la vista en cada refresco: pasándole un `Group` ya construido
los cronómetros solo avanzaban cuando algo cambiaba de estado.

### Orden de las tareas
La lista se ordena poniendo delante las que pasan por Gemini (`needs_refine`). El
refinamiento está serializado por cuota: si AR y ZH salen las últimas, los demás hilos
acaban parados esperándolas; lanzándolas antes, EN y FR se solapan con su cola.

### Modelo de paralelismo
Una **tarea = (documento, idioma)**, y todas viven en un único `ThreadPoolExecutor` plano
(`pipeline.max_workers`, por defecto 4). No hay un pool por fichero ni por idioma: con
`--all` y varios idiomas eso dejaba hilos ociosos esperando al fichero más lento.
El documento en su idioma origen también es una tarea (se salta la traducción pero
comparte el camino de escritura/conversión/subida).

Puntos de sincronización, y por qué existen:
- `view_lock` — la vista Live de rich no es thread-safe
- `gemini_sem` — presupuesto **único** de Gemini para toda la ejecución: el formateo de
  las fuentes (fase 0) y el refinamiento van contra la misma cuota. `pipeline.gemini_workers`,
  por defecto 1; subirlo arriesga un 429 en el free tier
- `folders_lock` — protege `used_folders` y `scratch`
- `GoogleDocsManager._lock_for(carpeta)` — un lock **por carpeta**, más las cachés de
  carpetas y listados, todo **de clase, no de instancia**: el pipeline crea un manager por
  hilo (httplib2 no es thread-safe) y el estado único de la ejecución vive en la clase.
  `reset_run_state()` lo limpia al arrancar
- `cancelled: threading.Event` — Ctrl+C; ver abajo

### Cancelación (Ctrl+C)
`executor.shutdown(wait=True, cancel_futures=True)` descarta lo encolado y el `Event`
hace que las tareas ya en marcha aborten antes de traducir, escribir o subir. Las
llamadas HTTP en vuelo terminan (no se puede matar un hilo bloqueado en socket), así que
la salida tarda lo que tarde la petición más lenta de las que ya salieron.

### Translator pattern
`registry.py` usa Strategy + Registry: `AVAILABLE_TRANSLATORS = {"deepl":…, "azure":…, "gemini":…}`.
`get_translator()` devuelve `ProtectedTranslator(FallbackTranslator([CachingTranslator(p), …]))`.
Añadir proveedor = crear clase que extiende `BaseTranslator`, añadirla al dict y poner su
fila en `langs.py`. El wizard **saca la lista de ahí**, no de una constante paralela: era
tocar tres sitios y olvidarse de uno (Gemini estaba registrado y no aparecía en el menú).
Los proveedores sin clave se ven en gris y no se pueden elegir.
`ProtectedTranslator` sustituye código inline, fórmulas `$…$` y URLs por placeholders `⟦n⟧`.

### Compatibilidad de la interfaz `translate()`
`BaseTranslator.translate` acepta un tercer argumento **opcional** `source_lang`. Nada lo
llama directamente: todo pasa por `call_translate(translator, texts, target, source)`, que
inspecciona la firma (`inspect.signature`, cacheado por clase) y solo pasa el tercer
argumento si el proveedor lo acepta. Un traductor externo escrito contra la firma original
sigue funcionando sin tocarlo. **Si tocas esto, mantén esa garantía.**

### Detección del idioma origen
`detect_source_language()` analiza solo el texto traducible (sin almohadillas, tuberías de
tabla ni URLs) y exige `MIN_LANG_CONFIDENCE = 0.90`. Si no llega, devuelve `(None, aviso)`
y el pipeline **no** genera la copia en el idioma original: es preferible no generar a
crear `translated/pt/` con contenido español. `--source-lang` o `document.source_language`
saltan la detección.

### Troceado de peticiones
`chunk_texts(texts, max_items, max_chars)` respeta a la vez el nº de elementos y el tamaño
del request: contar solo elementos generaba peticiones de 60.000 caracteres que Azure
rechaza con 400. Límites: DeepL 50 items / 100.000 chars (tope real 128 KiB), Azure
100 items / 45.000 chars (tope real 50.000). Un texto que por sí solo excede el máximo
viaja en su propio request, nunca partido: rompería la correspondencia 1:1.

### Caché de traducciones
SQLite en modo WAL con **una conexión por hilo** (`threading.local`) y `busy_timeout=30s`.
Clave: `sha256(text ∥ target_lang ∥ provider)`. **No incluye `source_lang` a propósito** —
el mismo texto al mismo destino da la misma traducción, e incluirlo invalidaría todo lo
cacheado. Escritura por lote (`set_many`), un commit por llamada al proveedor.

### Retomar un lote que murió a la mitad
Cuarenta documentos contra tres APIs, una de ellas con cuota gratuita: que el lote se
muera a la mitad no es el caso raro. La forma de retomarlo es **relanzar el mismo
comando**, no un `--resume` con un puntero de progreso. Lo que lo permite:

- cada unidad de trabajo se identifica por su **contenido**, no por su posición: la clave
  de la caché es `sha256(texto ∥ idioma ∥ proveedor)`, así que lo ya hecho sale de SQLite
  y no de la API. Un puntero "iba por el documento 27" se queda mentiroso en cuanto
  cambia la lista de ficheros o el orden de las tareas
- el destino es idempotente: `replace_existing` reutiliza el id del documento en Drive, y
  `_reserved`/`_claimed` evitan que dos tareas peleen por el mismo nombre. Relanzar no
  duplica
- lo que quedó a medias se marca: `incomplete` en el resultado de la tarea

El refinamiento entra en **esa misma caché** con `provider="gemini-refine"`: `provider` es
el namespace de la tabla, así que no hubo migración ni tabla nueva. Medido: el mismo
documento+idioma pasó de 23,0s a 0,0s en la segunda pasada, sin una sola llamada a Gemini.
La clave **no lleva el id del modelo**, y el namespace sigue llamándose `gemini-refine`
aunque hoy refine cualquier modelo: meterlo invalidaría todo lo ya refinado y volvería a
costar ~23s por documento, igual que la clave de traducción no lleva `source_lang`. La
consecuencia —un texto refinado por Cerebras se reutiliza aunque mañana el preferido sea
Gemini— es aceptable: lo cacheado es texto ya editado, no una traducción cruda.

Antes de rendirse, `refiner._llamar_modelo` reintenta: `ai.base.espera_pedida()` saca los
segundos que pide el 429 —el `retryDelay` del JSON de Gemini, la cabecera `Retry-After` o
la frase del cuerpo, según la API— y duerme eso **+1s** (`MAX_ESPERA` 60s), en pasos de un
segundo para que Ctrl+C siga cortando. El +1 es porque esperar exactamente lo que pide la
API vuelve a chocar con la ventana; `retry_after` guarda siempre lo crudo para que sumarlo
dos veces sea imposible. Lo que no es cuota (400, 503) no gasta intentos.

`_MAX_INTENTOS = 2`, y no más, porque el `retryDelay` **no es una promesa**. Medido el
mismo día contra la misma clave: a las 13:35 dos peticiones OK y luego 429 con esperas que
suben y bajan (59 → 34 → 9 → 43 → 17 s), o sea una ventana reponiéndose; a las 14:25, 429
seguidos durante casi cuatro minutos con la espera siempre al tope. No se sabe en cuál de
los dos casos estás, así que el reintento cubre el primero y el aviso cubre el segundo.
Con tres intentos de 75s eran 225s por tarea para acabar sin refinar nada.

Cuando de verdad no queda cuota, un contador (`_UMBRAL_CUOTA = 2`) enciende `sin_cuota` y
las demás tareas se saltan el refinamiento: es la diferencia entre acabar sin refinar y no
acabar. El `sin_cuota` se mira **dentro** de `gemini_sem`, no antes: el semáforo serializa
el refinamiento, así que con muchas tareas casi todas están en la cola y ya han pasado el
primer control cuando llega el aviso. Medido con 16 tareas: mirándolo solo antes, cinco
pagaban sus reintentos (33s); mirándolo con el semáforo en la mano, dos (12s). La pantalla final abre entonces un bloque
**Unfinished** con cuántos documentos van a medias y el comando entero para relanzar
(`main._retry_command`), porque "relánzalo y solo se repetirá lo que falta" no se adivina;
en `--json` viajan `incomplete` y `retry_command`. Un documento a medias **no** es un
fallo: está traducido, generado y subido, y se usa — el pie sigue diciendo que la
ejecución fue bien.

Y una regla que el resto da por hecha: **relanzar no puede dejarte con menos de lo que
tenías**. `_conserva_lo_refinado()` deja quieto el fichero de salida cuando esta pasada no
ha podido refinar y la fuente no ha cambiado desde que se escribió — lo que hay en disco es
igual o mejor que lo que traemos. Sin eso, una segunda pasada sin cuota sobrescribía el
documento ya refinado con la traducción cruda: pasó de verdad, nueve documentos AR/ZH del
módulo 19 perdieron el refinado así. Si la fuente **sí** es más nueva, se reescribe aunque
venga sin refinar: ahí lo de disco está caducado. Ojo: lo que salvó a los otros documentos
fue la comparación de contenido que ya había (`out_file.read_text() != new_content`), que
no es una garantía — solo no reescribe cuando el texto coincide byte a byte.

Lo mismo por el lado de la traducción: elegir proveedor a mano **desactiva el fallback a
propósito** —quien pide DeepL lo pide por algo, y cambiárselo a mitad de ejecución sería
traducir con otro motor sin decirlo—, pero entonces su 429 dejaba el lote sin traducir y
sin mencionar que hay otras claves cargadas. `_retry_provider()` mira los fallos: si el
proveedor elegido cayó por cuota y hay otros con clave, el comando de reintento lleva
`--provider auto` —escrito aunque sea el valor por defecto, porque ahí está el cambio— y
una línea que dice a cuáles va a preguntar. En modo auto no se propone nada: la cadena ya
los probó todos.

### Proveedores de modelos de IA: el fallback es por modelo
`src/ai/` es el hermano de `src/translators/` para lo que no es traducir: formatear un
`.txt` y refinar una traducción. El reparto es el mismo —el ABC y el fallback en `base.py`,
la composición en `registry.py`— pero **la unidad de la lista es `proveedor:modelo`**, no el
proveedor. Esa es la decisión que importa, y la pagó un lote: el módulo 19 se quedó 16 de
24 tareas sin refinar con un 429 de `gemini-2.5-flash` mientras cinco modelos de la misma
cuenta contestaban. El id del error dice
`GenerateRequestsPerDayPerProjectPer**Model**-FreeTier`: cada modelo es un cubo de cuota
distinto, así que el fallback más útil de todos es entre dos modelos del mismo proveedor, y
por eso el orden de fábrica empieza por **tres** Gemini. Se desatasca sin pedir ninguna clave
nueva.

Tres y no dos porque el cubo es pequeño: medido en el 429, `limit: 20` peticiones al día por
modelo. Con dos modelos, esas mismas 16 tareas AR/ZH gastaron los dos cubos y la última se
quedó sin refinar; el tercero es lo que cierra el lote el mismo día.

```json
"ai": { "fallback_order": ["gemini:gemini-2.5-flash", "gemini:gemini-3.5-flash",
                           "gemini:gemini-3.5-flash-lite", "groq", "cerebras"] }
```

Una entrada sin `:` usa el modelo por defecto del proveedor. Groq y Cerebras hablan el
dialecto de OpenAI (`/v1/chat/completions`), así que los cubre **una** clase con otra
`base_url` y sin dependencias nuevas; por eso "que el usuario meta el modelo que quiera" es
una fila más en `AVAILABLE_MODELS`. Solo Gemini tiene clase propia, porque tiene SDK propio.
Los proveedores sin clave se caen de la cadena en silencio: la lista es un orden de
preferencia, no una elección para esta ejecución.

Dos cosas que no se adivinan:
- **La pasada por la lista no duerme.** `FallbackModel` prueba todos los modelos sin
  esperar, y solo cuando ninguno tiene cuota lanza `AIQuotaError` y decide el refiner si
  espera. Al revés —dormir los 60s del primero antes de probar el segundo— eran hasta 120s
  por lote para acabar usando uno que estaba libre.
- **El tipo del error decide, no el texto.** `es_cuota()` mira si es `AIQuotaError` cuando
  el error ya viene de un adaptador, porque el corte por cuota del pipeline
  (`refiner.es_aviso_de_cuota`, `_UMBRAL_CUOTA`) busca `429` en el aviso: un
  "503 unavailable, retry after 429 ms" apagaba el refinamiento de toda la ejecución. Por
  lo mismo, el `AIError` que agrega varios fallos mixtos pasa por `sin_pistas_de_cuota()`,
  y el que agrega solo fallos de cuota **conserva** el `429` a propósito.

`python -m src.ai.registry --check` pregunta a cada API qué ids acepta hoy, porque el
listado y lo que de verdad responde no son lo mismo: `gemini-2.5-flash-lite` sale en la
lista de Google y devuelve 404 («no longer available to new users»). Los ids por defecto de
Groq y Cerebras no están comprobados contra sus APIs (hacen falta claves): si uno caduca, la
respuesta es 404, el fallback pasa al siguiente y ese comando dice con qué sustituirlo. Y no
todo fallo es cuota: `gemini-3.1-flash-lite` contestó 503 («overloaded») el mismo día en que
los otros tres lite respondían, que es justo el caso que no debe apagar el refinamiento de
toda la ejecución.

`refine_markdown()` devuelve `(líneas, aviso, cambio_de_modelo)`, y el tercer valor solo
trae algo cuando **no** contestó el preferido: si el resultado sale del primero de la lista
no hay nada que contar. El pipeline lo guarda en `refine_model` y `results.py` lo pinta como
una fila más de **Warnings** en `DIM` (`AR · refined with gemini-3.5-flash — gemini-2.5-flash
had no quota`); en `--json` viaja el dict `{used, instead_of, reason}`. Sin color nuevo:
amarillo ya significa "avisa".

El traductor Gemini (`translators/gemini.py`) toma el id del modelo del registro
(`modelo_de("gemini")`, que respeta el orden configurado) pero **no** hereda el fallback: en
el menú es el proveedor "Gemini (Google AI)", la traducción ya tiene su propio fallback por
proveedor, y cambiarle el motor por dentro sería traducir con otra cosa sin decirlo.

### La carpeta de Drive se elige en la ejecución, no en el config
Un módulo nuevo es una carpeta nueva, y antes eso significaba salir del programa: ir a
Drive, crearla, copiar el trozo final de la URL y pegarlo en `config.json`. Ahora el
wizard pregunta (`_paso_drive`, solo si el destino incluye Drive) y ofrece tres cosas:
seguir en la de siempre —que va preseleccionada—, **crear una al lado de ella**, o
navegar el Drive entero (`pick_drive_folder`). Crear es elegir: la carpeta creada es la
respuesta, no hay que volver a buscarla.

`next_folder_name()` propone el nombre: `M18` → `M19`, y conserva el relleno (`M08` →
`M09`, o la carpeta dejaría de ordenarse por nombre). Se propone, no se impone: es el
`default` de un campo de texto.

Por eso `config.json` guarda también `drive.folder_name` — el nombre se ve en la
confirmación y es de donde sale la propuesta; con solo el id, la pantalla enseñaba
`1lWVaE…` y no había nada que incrementar. `configured_folder()` **relee el fichero**
en vez de mirar el `CONFIG` ya cargado: el config cambia durante la propia ejecución.

Quién escribe qué, que es lo que mantiene al wizard sin lógica de negocio:
- `wizard.py` solo devuelve `drive_folder_id` / `drive_folder_name` en la config; todo
  el trabajo con Drive lo hace `folder_picker`
- `pipeline.py` prefiere `config["drive_folder_id"]` sobre `DRIVE_FOLDER_ID`: la carpeta
  de esta ejecución puede haberse creado un segundo antes
- `main._remember_drive_folder` guarda la elección en `config.json` **al arrancar la
  fase 3**, no al elegirla: cancelar en la confirmación no tiene que dejar cambiada la
  carpeta de la próxima vez

### Las claves se dan de alta desde la terminal
Lo único que decía la interfaz de un proveedor sin clave era el `disabled="no API key"`
del menú: a qué página ir, cómo se llama la variable y dónde se escribe había que
saberlo de memoria o buscarlo en el README. `--add-key` lo pregunta: elegir proveedor,
abrir su página en el navegador, pegar el token, **comprobarlo contra la API** y
escribirlo en `.env`.

La lista de proveedores sale de los dos registros —`AVAILABLE_TRANSLATORS` y
`AVAILABLE_MODELS`— y no de una constante nueva, que es la misma lección del menú del
wizard, donde Gemini estaba registrado y no aparecía. Por eso `BaseTranslator` gana
`key_env`, `extra_env`, `signup` y `free`: un proveedor tiene que ser **una fila**.
`extra_env` existe porque Azure no funciona solo con la clave —sin `AZURE_TRANSLATOR_REGION`
contesta 401 aunque la clave sea buena— y es el único que pide algo más.

La deduplicación es **por variable de entorno, no por id**: `GEMINI_API_KEY` sirve a la
vez para traducir y para refinar, así que Gemini es una sola ficha (`translate + refine`)
y no dos preguntas por lo mismo. Cuando una clave la comparten las dos familias, la
comprobación que gana es la del modelo: `modelos_disponibles()` es un **GET** al listado
y no gasta ninguna de las peticiones de generación, que es justo lo que escasea (20 al
día por modelo). La del traductor manda una traducción de verdad —dos caracteres del cupo
del mes— porque es la única forma de saber que la clave traduce y no solo que la API la
reconoce.

Tres cosas que no se adivinan:
- **`.env` se edita línea a línea, no se vuelca.** Lo escribe el usuario a mano y tiene
  sus comentarios y su orden; reescribirlo entero le borraría lo que no entendemos. Una
  variable que ya está se sustituye **en su sitio** (también si viene con `export`), o
  quedarían dos asignaciones de la misma y el valor dependería de cuál gane. El fichero
  que creamos nosotros nace con permisos `600`.
- **Guardar una clave sin comprobar es una salida de verdad**, no una cortesía: la API
  puede estar caída y la de Azure necesita acertar además con la región. La pantalla lo
  dice (`(not checked)`) y no obliga a editar `.env` a mano.
- **Una clave de IA que no está en `ai.fallback_order` no se usa nunca**, y eso no se ve
  en ninguna parte: la lista es un orden de preferencia y el que no aparece no se
  intenta. Así que al guardarla se ofrece meterla, al final —lo de arriba es lo que el
  usuario ya eligió— y sin `:`, o sea con el modelo por defecto. Si el config no tenía
  sección `ai`, se parte del orden de fábrica y no de una lista vacía: escribir la
  sección no puede dejar el fallback en un solo modelo.

El aviso del modelo por defecto (`llama-3.3-70b is not among the 21 models this key can
use · pick another with: python -m src.ai.registry --check`) se **dobla** con sangría
colgante en vez de recortarse, igual que el comando del bloque *Unfinished*: a 50
columnas `elide()` cortaba el comando por la mitad y un comando a medias no sirve de
nada. Y es el momento de decirlo, porque dar de alta una clave es la primera vez que se
puede preguntar: el id que estaba puesto de memoria para Groq, `llama-3.3-70b-versatile`,
**no existe** en su free tier. Comprobado con una clave de verdad (18-09-2026): de los 13
modelos que devuelve, los que refinan son `openai/gpt-oss-120b`, `openai/gpt-oss-20b` y
`qwen/qwen3.8-27b` —el resto son Whisper, clasificadores de prompts y TTS—, así que el
`default_model` de Groq es hoy `openai/gpt-oss-120b`. El de Cerebras sigue sin comprobar.
El aviso funcionó exactamente como tenía que funcionar: la clave quedó guardada y lo único
roto era el id.

El ✓ de "ya tiene clave" va dentro de la etiqueta de la opción y **sin color**:
questionary pinta el título de una opción con un solo estilo, y verde significa "salió
bien" — tener clave es un dato, no un éxito. Delante y no detrás, para que las etiquetas
queden alineadas.

### Nombres y consistencia local ↔ Drive
- Local: `local.naming_pattern`, por defecto `{title}.{lang}` → `translated/en/apuntes.en.docx`.
  La identidad de salida es el código **completo** (`en-gb`, no `en`): colapsar la variante
  regional hacía que dos tareas escribieran el mismo fichero a la vez. El formato del
  documento (RTL, CJK, plantilla) sí usa el código corto.
- Drive: `drive.sequential_naming_pattern`, por defecto `{n}. {title}`; `{n}` es el primer
  hueco libre en la carpeta, y lo asigna el hilo que llega antes: con varios documentos en
  paralelo el orden es el de subida, no el del curso. Si el número ya viene en el nombre
  del fichero (`3. Jaulas de Faraday.txt`), `sequential_naming: false` — o el título sale
  numerado dos veces. `_find_next_number` cuenta tanto los nombres que casan con el
  patrón actual **como cualquier nombre que empiece por número**: al cambiar de patrón la
  numeración no se reinicia.
- `drive.replace_existing` → `files().update()` en vez de `create()`: mismo id, mismo enlace,
  y Drive guarda la versión anterior en el historial. Sin él, cada pasada duplica.
- `resolve_target()` reserva el nombre bajo el lock de esa carpeta en `_reserved`, porque
  Drive todavía no conoce los nombres que otros hilos están subiendo en ese mismo instante.
  Y anota el id en `_claimed`: dos tareas de la misma ejecución no pueden reemplazar el
  mismo documento — la segunda crea uno nuevo en vez de pisar a la primera.
- Cada carpeta se lista **una sola vez por ejecución** (`_cached_files`). Eran dos llamadas
  por documento y con un lock global: 40 subidas eran 80 peticiones en fila.
- Con `organize_by_language: false` todos los idiomas comparten carpeta, así que
  `_effective_pattern` añade `{lang}` al patrón si no lo lleva → `12. apuntes (FR)`. Sin eso,
  los cuatro idiomas resolvían al mismo documento y se sobrescribían entre ellos.
- El `(I)`/`(II)`/`(III)` que separa las partes de un mismo tema vive **solo en el nombre
  del fichero**. El `.txt` es la transcripción hablada y no lo menciona, así que el modelo
  que escribe el `#` del documento no tiene de dónde sacarlo: `SYSTEM` lo pedía desde el
  primer commit y no podía cumplirse, porque `generate_markdown` recibía el texto y nunca
  el nombre. Se vio en el módulo 19, con las tres partes de "Técnica de extracciones"
  tituladas como tres temas sin relación **en los cinco idiomas** —el título se traduce, y
  lo que no está en el origen no aparece en ninguna traducción—. El nombre en Drive nunca
  lo perdió, porque sale del `stem` del fichero: el síntoma era un documento que por fuera
  decía `(I)` y por dentro otra cosa.
- El indicador **no es contenido, es la posición del documento en una serie**, y por eso
  `core/parser.py` lo saca al leer (`quita_la_parte`, en `_prepare_one`) y lo vuelve a
  poner al escribir (`conserva_la_parte`, con `doc.stem`). Al traductor no le incumbe:
  mandándoselo, el árabe lo devolvía como `(الجزء الأول)` y el chino como `（一）` mientras
  su hermano decía `（II）` —tres convenciones en la misma carpeta—, y además cambiaba la
  traducción del título entero por haberle pegado un paréntesis: `Técnicas de Extracción
  Invasivas` pasó de `侵入性提取技术` a `侵入性拔牙技术`, extracción **dental**. Sacándolo,
  el texto que viaja es el de siempre, la caché sigue acertando y la serie se lee igual en
  los cinco idiomas. `generate_markdown` lo recibe también —tercer argumento opcional,
  como el `source_lang` de `translate()`— para que el `.md` de `sources/` lo lleve escrito.
  Se impone en vez de pedirse: un modelo obedece casi siempre, y "casi siempre" aquí se ve
  en la pantalla del usuario. Solo romanos hasta XX y arábigos de dos cifras, y anclado al
  final: un título que acaba en `(DFIR)` o `(ECU)` no es la parte de nada.

### DOCX postprocess
El DOCX lo genera Pandoc usando una template `.docx`. Luego `document/postprocess.py` lo
reempaqueta manipulando el XML directamente (zipfile + lxml). RTL inyecta `<w:bidi>` en cada
párrafo. CJK fuerza Noto Sans CJK SC. Headers/footers se inyectan en los XML de relaciones.

### AI Refiner (document/refiner.py)
Solo actúa en `{ar, zh, ja, ko, fa, he, ur}` (`styles.needs_refine`). Parsea MD en nodos
tipados, extrae inline spans como placeholders `⟦0⟧`, manda texto plano al modelo en batches,
restaura placeholders. No toca headings, code_blocks ni tables. El modelo lo elige
`ai.registry.get_model()`, no una constante.

Lo que vuelve del modelo se `rstrip()`ea línea a línea, y no es cosmética: **dos espacios
al final de una línea son un salto forzado en Markdown** y Pandoc los mete como un `<br>`
en medio del párrafo. Gemini no los ponía; `openai/gpt-oss-120b` cierra con ellos casi
cada línea, así que el defecto apareció el día que hubo clave de Groq. Mismo arreglo en
`generate_md._strip_fences`, que formatea los `.txt` con el mismo modelo.

Las llaves de los placeholders son **por línea** (`imaps[pos]`), pero el modelo edita un
lote de 25: puede llevarse un `⟦0⟧` a la línea de al lado, o partirlo por dentro
(`⟦0 lock⟧`). Entonces la vecina no tiene nada que restaurar y el símbolo llega al
documento, mientras la línea de origen pierde su cursiva y, con ella, la palabra. Pasó en
el módulo 19, en dos apuntes chinos que se subieron con `⟦0 lock⟧系统集…` a la vista. Por
eso, al restaurar, una línea cuyas marcas no han vuelto **enteras** se queda con la
traducción cruda: se lee, y `⟦0⟧` no. Refinar nunca puede dejar el documento peor de lo
que estaba, que es la misma regla de `_conserva_lo_refinado()`.

### Limpieza en modo solo-Drive
Cuando la salida es solo Drive, los ficheros locales son scratch. Se borran **solo los que
esta ejecución ha creado** (`scratch`), y las carpetas con `rmdir()`, que falla si no están
vacías. Borrar la carpeta entera se llevaba por delante traducciones anteriores.

### Path resolution
`collect_sources()` acepta `ALL_FILES`, un nombre suelto, una **subcarpeta** de `sources/`,
una ruta `sources/…` o una ruta absoluta. En modo ALL los stems duplicados colapsan:
`apuntes.md` gana sobre `apuntes.txt`, que es su materia prima, para que no compitan por el
mismo fichero de salida.

Una subcarpeta de `sources/` es un **lote** —un módulo, un curso— y el wizard la ofrece
como una opción más (`list_source_folders`, que dice también cuántas fuentes trae; las
vacías no salen). `ALL_FILES` son los ficheros **sueltos** de `sources/`, no todo el árbol,
y `_en_carpeta` no baja a las subcarpetas: bajando, "todos los de este módulo" arrastraría
los del anterior en cuanto se anidaran dos.

---

## 7. Reglas de Comportamiento

**SIEMPRE:**
- Usar rutas absolutas (`.resolve()`) antes de pasarlas a `subprocess.run()`
- Activar `.venv` antes de ejecutar cualquier script
- Probar que `pandoc` existe antes de asumir que funciona (ya lo hace `run_pipeline.sh`)
- Un perfil de usuario privado por llamada a LibreOffice (`-env:UserInstallation`): con el
  perfil compartido, dos conversiones a la vez devuelven 0 sin escribir ningún PDF
- Verificar los cambios ejecutándolos, no leyéndolos

**NUNCA:**
- Modificar archivos en `translated/` manualmente; los regenera el pipeline
- Poner lógica de negocio en `wizard.py` (solo recoger datos del usuario)
- Usar verde para algo que no sea "salió bien", ni añadir un color sin decir en
  `styles.py` qué significa
- Traducir code_blocks — `parser.py` los marca como `code_block` y el rebuild los copia tal cual
- Romper la interfaz `translate(texts: list[str], target_lang: str) → list[str]`: el tercer
  argumento es opcional y se pasa solo vía `call_translate` (ver §6)
- Asumir que `source_cfg` del wizard es solo el nombre del archivo (puede tener prefijo `sources/`)
- Reformatear `config.example.json` con `json.dumps` — usa 2 espacios y hay que respetarlo
- Compartir un `GoogleDocsManager` entre hilos: httplib2 no es thread-safe (da `TimeoutError`).
  Un manager por hilo, credenciales compartidas

---

## 8. Contexto Adicional

**Deuda técnica conocida:**
- Las llamadas a Gemini (formateo y refinamiento) están serializadas por cuota, no por
  diseño: con AR/ZH sobre muchos ficheros manda `gemini_workers` sobre `max_workers`.
  Mitigado ordenando esas tareas primero, pero el techo sigue ahí
- El formateo de `.txt` y el refinamiento comparten `gemini_sem`, así que comparten
  presupuesto de peticiones aunque ya no compartan cubo de cuota: la cuota es por modelo y
  el fallback los reparte, pero el semáforo sigue serializándolos. Poner el formateo en
  otro modelo **a propósito** (una entrada distinta del orden) está sin hacer
- Ctrl+C no puede abortar una petición HTTP ya lanzada; la salida tarda lo que tarde la
  más lenta de las que ya salieron. La UI dice cuántas quedan
- Manipulación XML directa del DOCX en vez de Lua filters de Pandoc (frágil)

**Áreas a tener en cuenta:**
- `document/postprocess.py` es el módulo más frágil — cambios en la estructura XML de Pandoc lo rompen
- Google Auth requiere `secrets/credentials.json` y genera `secrets/token.json` en el primer run.
  Con la app en modo *Testing* en Google Cloud, el refresh token caduca **cada 7 días**
- `lxml` no está en `requirements.txt` — es una dependencia implícita de otro paquete
- `azure.py` reintenta **cualquier** fallo de red, incluido un 401: `raise_for_status()`
  cae dentro del `try`, así que una clave mal puesta tarda ~7s (1+2+4) en decirlo. Se ve
  al darla de alta con `--add-key`; en el pipeline solo se nota al fallar
- Los templates `template_ltr.docx` y `template_rtl.docx` definen los estilos Word
- La paginación localizada (números árabes/chinos) está desactivada para AR/ZH/JA porque
  Google Docs y LibreOffice la ignoran

---

## 9. Tests
`tests/` cubre la lógica pura: sin red, sin credenciales, sin Pandoc ni LibreOffice. Cada
test corresponde a un fallo real observado en producción, no a cobertura por cobertura.
Ejecutar con `pytest -q`. Si añades lógica de troceado, numeración, detección de idioma,
resolución de rutas, reanudación (cuota, reintentos, caché), fallback de modelos
(`tests/test_ai_models.py`) o alta de claves (`tests/test_key_setup.py`), el test va
con ella.
