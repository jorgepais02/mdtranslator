# mdtranslator

Pipeline automático para **traducir apuntes en Markdown** a múltiples idiomas y generar documentos **Word (.docx)** y **PDF** con formato académico.

## Características

- **Traducción paralela** multi-idioma (hasta 4 idiomas simultáneos via `ThreadPoolExecutor`).
- **Fallback dinámico**: si una API falla o supera cuota, salta automáticamente a la siguiente sin interrumpir el proceso.
- **Tres proveedores de traducción**: DeepL, Azure AI Translator y Gemini (`gemini-2.5-flash`).
- **Caché SQLite** con WAL mode: evita re-traducir textos ya procesados. Auto-vacuum cuando supera 50 MB.
- **Protección de contenido**: los inline code spans, URLs y fórmulas LaTeX (`$...$`, `$$...$$`) no se traducen.
- **Refinamiento post-traducción** con Gemini para idiomas complejos (árabe, chino, japonés, coreano, hebreo, persa, urdu).
- **Generación DOCX** con formato académico real via Pandoc: alineación RTL (Bidi), fuentes CJK, cabecera personalizada, footer con paginación.
- **Generación PDF local** via LibreOffice headless (opcional, no bloquea si no está instalado).
- **Subida directa a Google Drive**: convierte el DOCX a Google Doc nativo. Soporta organización por carpetas de idioma y nombres secuenciales configurables.
- **CLI interactivo** con Rich: wizard de configuración, vista de progreso en tiempo real, tabla de resultados y sección de warnings.

## Estructura

```
├── src/
│   ├── cli/
│   │   ├── main.py               # Entry point (python -m src.cli.main)
│   │   ├── wizard.py             # Wizard interactivo con questionary
│   │   ├── pipeline.py           # Orquestador con Live view y ThreadPoolExecutor
│   │   ├── results.py            # Tabla de resultados y warnings
│   │   ├── styles.py             # Constantes de color y console compartido
│   │   ├── confirmation.py       # Pantalla de confirmación previa al pipeline
│   │   └── errors.py             # Manejo de errores CLI
│   ├── core/
│   │   ├── config.py             # Carga y validación de config.json + .env
│   │   ├── parser.py             # Parser MD en nodos tipados
│   │   └── docgen.py             # Rebuild de MD traducido
│   ├── document/
│   │   ├── converter.py          # Generador DOCX via Pandoc
│   │   ├── postprocess.py        # Postproceso XML del DOCX (RTL, CJK, header/footer)
│   │   └── refiner.py            # Refinamiento Gemini nodo a nodo (AR/ZH/JA/KO/FA/HE/UR)
│   ├── integrations/
│   │   ├── drive.py              # Subida a Drive, resolución de carpetas, naming secuencial
│   │   └── generate_md.py        # Convierte .txt raw → .md académico con Gemini
│   └── translators/
│       ├── base.py               # BaseTranslator ABC
│       ├── deepl.py              # Proveedor DeepL
│       ├── azure.py              # Proveedor Azure AI Translator
│       ├── gemini.py             # Proveedor Gemini
│       ├── cache.py              # Caché SQLite con WAL mode y auto-vacuum
│       ├── registry.py           # Registro de proveedores disponibles
│       └── wrappers.py           # FallbackTranslator + CachedTranslator
├── sources/                      # Archivos .md/.txt de entrada
├── templates/                    # template_ltr.docx + template_rtl.docx (referencia Pandoc)
├── public/
│   └── header.png                # Imagen opcional de cabecera para DOCX
├── secrets/                      # credentials.json + token.json de Google Auth (gitignored)
├── translated/                   # Salida generada (gitignored)
├── run_pipeline.sh               # Script de ejecución recomendado
├── config.example.json           # Plantilla de configuración
├── requirements.txt
└── .env                          # API keys (no versionado)
```

## Instalación

```bash
git clone <url-del-repo>
cd mdtranslator

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

## Uso

```bash
# Interfaz interactiva (recomendado)
./run_pipeline.sh

# Con archivo pre-seleccionado
./run_pipeline.sh sources/apuntes.md

# Directo con flags
source .venv/bin/activate
python -m src.cli.main
python -m src.cli.main --lang EN FR AR ZH --provider deepl
```

## API Keys

Configura en `.env` las claves de los proveedores que quieras usar. El sistema detecta automáticamente cuáles están disponibles y construye el fallback en orden.

La forma corta es dejar que lo pregunte: abre la página del proveedor, comprueba la clave contra su API y la escribe en `.env`.

```bash
./run_pipeline.sh --add-key            # pregunta de quién
./run_pipeline.sh --add-key groq       # esa, sin preguntar
```

| Variable                  | Proveedor               | Para                     |
|---------------------------|-------------------------|--------------------------|
| `DEEPL_API_KEY`           | DeepL API               | traducir                 |
| `AZURE_TRANSLATOR_KEY`    | Azure AI Translator     | traducir                 |
| `AZURE_TRANSLATOR_REGION` | Azure AI Translator     | traducir (va con la clave) |
| `GEMINI_API_KEY`          | Gemini (Google AI)      | traducir y refinar       |
| `GROQ_API_KEY`            | Groq                    | refinar y formatear      |
| `CEREBRAS_API_KEY`        | Cerebras                | refinar y formatear      |
| `GOOGLE_DRIVE_FOLDER_ID`  | Google Drive (opcional) | subir                    |

Con un solo proveedor el sistema funciona. Con varios, activa el fallback automático si uno falla.

El refinado y el formateo tienen su propia cadena, y su unidad es `proveedor:modelo` —
la cuota gratuita de Gemini se cuenta por modelo, no por cuenta. Se escribe en
`config.json` → `ai.fallback_order`, y `python -m src.ai.registry --check` dice qué ids
acepta hoy cada API.

## Configuración de Google Drive (Opcional)

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita **Google Docs API** y **Google Drive API**.
3. Crea credenciales OAuth client ID para aplicación de escritorio.
4. Descarga el JSON y guárdalo como `secrets/credentials.json`.
5. El primer run abrirá el navegador para autorización y generará `secrets/token.json` automáticamente.

## Configuración (`config.json`)

Copia `config.example.json` a `config.json` (ignorado por git) para personalizar el comportamiento:

- `organize_by_language`: crea subcarpetas en Drive por idioma.
- `sequential_naming`: nombra los archivos secuencialmente en base a un patrón.
- `sequential_naming_pattern`: patrón con etiquetas `{n}`, `{title}`, `{lang}`.  
  Ejemplo: `"{n} - {title} ({lang})"` → `1 - apuntes (EN)`.
- `default_languages`: idiomas por defecto en el wizard.
- `header_image`: ruta relativa a la imagen de cabecera del DOCX.

## Generación de PDF

Se genera localmente con LibreOffice headless. Si no está instalado, el pipeline continúa sin interrumpirse (solo genera `.md` y `.docx`).

```bash
brew install --cask libreoffice
```

## Añadir un proveedor de traducción

1. Crear clase que extienda `BaseTranslator` en `src/translators/base.py`.
2. Implementar `translate(texts: list[str], target_lang: str) -> list[str]`.
3. Registrarla en `src/translators/registry.py`.

El wizard la detectará automáticamente si su API key está en `.env`.
