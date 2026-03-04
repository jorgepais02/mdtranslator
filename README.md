# .MD Translation Tool

Pipeline automático para **traducir apuntes en Markdown** a múltiples idiomas y generar documentos **Word (.docx)** y **PDF** con formato académico.

## Características

- **Traducción automática** multi-idioma con **Fallbacks Dinámicos**: Si una API falla (ej. Cuota de DeepL), salta automáticamente a la siguiente (Azure AI Translator) sin interrumpir el proceso.
- **Generación en Google Docs** directamente a tu Google Drive, con formato nativo, listas reales, y RTL/BiDi perfecto (Alineación a la derecha real).
- **Generación de DOCX local** con formato académico (Times New Roman, márgenes, numeración, RTL nativo).
- **Generación de PDF local** vía LibreOffice (sin APIs externas).
- **CLI Interactivo** súper fácil de usar para seleccionar origen, proveedor, formato de salida e idiomas.
- **Configuración Abstraída**: Comportamiento personalizable (organización en carpetas, nombres secuenciales, idiomas por defecto) mediante `config.json`.

## Estructura

```
├── src/
│   ├── translation_pipeline.py   # Orquestador: traduce y envía a generadores
│   ├── translators.py            # Interfaces de DeepL y Azure Translator
│   ├── document_generator.py     # Generador de DOCX local
│   ├── google_docs_manager.py    # Integración con Google Drive/Docs API
│   └── pdf_converter.py          # Script de LibreOffice
├── sources/                      # Archivos .md de entrada
├── public/
│   └── header.png                # Imagen opcional de cabecera
├── secrets/                      # Credenciales de Google Auth y Tokens (gitignored)
├── translated/                   # Salida generada (gitignored)
│   ├── es/es.md + es.docx + es.pdf
│   ├── en/en.md + en.docx + en.pdf
│   ├── fr/fr.md + fr.docx + fr.pdf
│   ├── ar/ar.md + ar.docx + ar.pdf
│   └── zh/zh.md + zh.docx + zh.pdf
├── run_pipeline.sh               # Script de ejecución interactivo
├── config.example.json           # Plantilla de configuración de usuario
├── requirements.txt
└── .env                          # API keys (no versionado)
```

## Instalación

```bash
# Clonar el repo
git clone <url-del-repo>
cd .md-translation-tool

# Crear entorno virtual e instalar dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configurar API keys copiando el archivo de ejemplo
cp .env.example .env
# Edita el .env con tu clave de DeepL o Azure
nano .env
```

## Configuración de Google Docs (Opcional)

Si quieres que el sistema genere documentos con formato perfecto (especialmente útil para la alineación RTL del Árabe) directamente en tu Google Drive:

1. Ve a [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita "Google Docs API" y "Google Drive API".
3. Crea credenciales de tipo "OAuth client ID" para aplicación de escritorio.
4. Descarga el JSON y guárdalo como `secrets/credentials.json`.
5. La primera vez que lo ejecutes con Google Docs activado se abrirá tu navegador para pedirte permiso y se generará el `token.json` automático.

## Configuración de Usuario (`config.json`)

Para personalizar cómo se comportan los archivos (especialmente en Drive), copia `config.example.json` a `config.json` (ignorado por git). 

**Características principales:**
- `organize_by_language`: Si es `true`, creará subcarpetas en Drive usando los nombres definidos en `language_folder_names`.
- `sequential_naming`: Si es `true`, leerá la carpeta y nombrará el siguiente archivo secuencialmente en base al patrón establecido en `sequential_naming_pattern`.
- `sequential_naming_pattern`: Permite establecer el patrón de nombres automáticos en Drive. Puedes usar cualquier string y las etiquetas mágicas:
  - `{n}`: Número secuencial autocalculado (1, 2, 3...)
  - `{title}`: Nombre original del archivo `.md` (sin extensión)
  - `{lang}`: Código del idioma en mayúsculas (EN, AR, ES...)
  - Ejemplo: `"{n} - {title} ({lang})"` -> `1 - apuntes (EN)`
- `header_image`: Ruta relativa a la imagen de cabecera (opcional).

## Uso

La forma más sencilla y recomendada de lanzar el sistema es usando la interfaz interactiva `run_pipeline.sh`. Te hará unas preguntas rápidas antes de empezar:

```bash
# Iniciar la interfaz interactiva
./run_pipeline.sh

# O pasarle directamente el archivo y que te pregunte lo demás:
./run_pipeline.sh sources/apuntes.md
```

También puedes saltarte la interfaz interactiva y llamar al pipeline de Python directamente si quieres integrarlo en otros scripts:

```bash
source .venv/bin/activate

# Modo local + DeepL (por defecto)
python src/translation_pipeline.py sources/apuntes.md

# Generar solo en Google Drive usando Azure
python src/translation_pipeline.py sources/apuntes.md --provider azure --google --no-local

# Traducir solo a ciertos idiomas
python src/translation_pipeline.py sources/apuntes.md --langs EN-GB FR AR
```

## API Keys y Proveedores (Escalabilidad)

Consulta el archivo `.env.example` para la lista completa de variables. 
1. **DeepL API** (Requiere `DEEPL_API_KEY`)
2. **Azure AI Translator** (Requiere `AZURE_TRANSLATOR_KEY` y `AZURE_TRANSLATOR_REGION`)

El sistema implementa un **Registro Dinámico**: Si en el futuro quieres añadir otra API (ej. OpenAI), solo tienes que crear su clase en `translators.py` y añadirla a `AVAILABLE_TRANSLATORS`. El menú CLI (`run_pipeline.sh`) detectará automáticamente qué APIs tienen configurada su clave en el `.env` y te las ofrecerá, ordenando los fallbacks inteligentemente según tu selección.

## Generación de PDF

Los PDF se generan localmente con LibreOffice en modo headless. Si LibreOffice no está instalado, el pipeline continúa sin interrumpirse (solo se genera `.md` y `.docx`).

```bash
# Instalar LibreOffice en macOS
brew install --cask libreoffice
```
