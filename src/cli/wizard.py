"""Configuracion interactiva. Solo recoge datos; el pipeline hace el trabajo.

El wizard es una maquina de pasos, no una lista de preguntas seguidas: cada pregunta
puede devolver BACK y entonces se retrocede uno y se vuelve a desplegar con la
respuesta anterior ya puesta. Por eso repinta la pantalla entera en cada paso —lo ya
contestado se colapsa a una linea de migas— en vez de ir dejando ecos debajo.

API:
    run_wizard(preselected_source=None) -> dict | None
"""

import questionary
from pathlib import Path
from rich.text import Text

from .folder_picker import (configured_folder, create_folder_next_to,
                             next_folder_name, pick_drive_folder)
from .prompts import BACK, ask_checkbox, ask_confirm, ask_select, ask_text
from .styles import (console, clear_screen, elide, marca, aire_superior, LANGUAGES,
                     CONTEXT, MARGEN, META, RED, YELLOW)

from core.sources import (ALL_FILES, VALID_EXTS, collect_sources,
                          list_source_folders, needs_formatting)
from translators.registry import AVAILABLE_TRANSLATORS, supported_by

# El paso no aplica en esta ejecucion (no hay texto crudo, o el fichero venia dado).
SKIP = object()

_AUTO      = "auto"
_AUTO_NAME = "Auto (fallback)"
_OTRO      = "__otro__"

_MISMA  = "__misma__"
_NUEVA  = "__nueva__"
_ELEGIR = "__elegir__"


def _ancho() -> int:
    return max(32, console.width)


def _opciones(nombres: list[str]) -> list:
    """Opciones para questionary con el titulo recortado y el valor intacto.

    questionary envuelve las opciones largas en dos lineas y la seleccion deja de
    leerse. Recortando solo el titulo, collect_sources sigue recibiendo el nombre real.
    """
    cabe = _ancho() - 6
    return [nombre if len(nombre) <= cabe
            else questionary.Choice(title=elide(nombre, cabe), value=nombre)
            for nombre in nombres]


# ── las migas de lo ya contestado ─────────────────────────────────────────────

_ETIQUETAS = ("source", "format", "provider", "output", "drive_folder", "languages")


def _valor(clave: str, estado: dict) -> str:
    """Como se lee una respuesta ya dada, en una sola pieza de texto."""
    v = estado[clave]
    if clave == "languages":
        return " ".join(v)
    if clave == "format":
        return "format with Gemini" if v else "leave as is"
    if clave == "source":
        n = len(estado.get("files") or [])
        if v == ALL_FILES:
            return f"all {n} files"
        # Un lote: el nombre solo no dice cuantos documentos arrastra, y ese numero es
        # justo lo que decide si la ejecucion dura un minuto o veinte.
        if n > 1:
            return f"{v}/ · {n} files"
    return str(v)


def _migas(estado: dict) -> Text | None:
    """Lo contestado, en una linea: "> apuntes.md · Auto (fallback) · EN FR".

    Antes esto era una rejilla de etiqueta y dato, una fila por pregunta: cinco lineas
    encima de la pregunta viva, y la etiqueta a ancho fijo dejaba "File" y "apuntes.md"
    a seis espacios, tan lejos que ya no se leian como una pareja. Las migas dicen lo
    mismo en un renglon y en un solo tono, que es lo que les toca: son el contexto de
    la pregunta, no la pregunta.

    El valor se explica solo —"Auto (fallback)", "Local only", "EN FR"—, asi que la
    etiqueta no hace falta; lo que importa es el orden, y el orden es el de los pasos.
    """
    partes = [_valor(c, estado) for c in _ETIQUETAS if c in estado]
    if not partes:
        return None
    t = Text(MARGEN)
    t.append("> ", style=META)
    for i, parte in enumerate(partes):
        if i:
            t.append(" · ", style=META)
        t.append(parte, style=CONTEXT)
    # Se recorta entero y no parte a parte: partido, el corte cae siempre en el ultimo
    # valor, que es justo el que se acaba de contestar.
    t.truncate(max(16, console.width - 2), overflow="ellipsis")
    return t


def _pintar(estado: dict) -> None:
    """La cabecera fija: la marca, y debajo pegadas las migas. Luego, aire.

    El "step 3 of 5" que cerraba el filete se ha ido con el: contaba unos pasos que ni
    son siempre los mismos —la fuente no se pregunta si vino por argumento, el
    formateo solo si hay algun .txt— ni llevan a ningun sitio, porque el wizard no se
    puede abandonar a la mitad. Era una cuenta atras de algo que dura cuatro teclas.
    """
    clear_screen()
    for _ in range(aire_superior()):
        console.print()
    console.print(marca())
    migas = _migas(estado)
    if migas is not None:
        # Marca y migas son el mismo grupo, pero pegadas la una debajo de la otra el
        # bloque se lee como un parrafo de dos lineas. El escalon lo dan los tonos.
        console.print()
        console.print(migas)
        # Dos lineas, y una sola entre marca y migas: la cabecera es un grupo y la
        # pregunta es otro, y con la misma distancia en los dos sitios se leia todo
        # como una lista de cuatro renglones.
        console.print()
    # Un aviso de la vuelta anterior: lo pinta quien limpia la pantalla, o se borraria
    # antes de leerse. Se consume al pintarlo, para que no siga ahi dos preguntas mas.
    pendiente = estado.pop("_aviso", None)
    if pendiente:
        _aviso(pendiente)
    console.print()


def _aviso(texto: str) -> None:
    console.print(f"[{YELLOW}]⚠ {texto}[/{YELLOW}]")


# ── los pasos ─────────────────────────────────────────────────────────────────

def _paso_source(estado: dict, volver: bool):
    if estado.get("_preselected"):
        estado["source"] = Path(estado["_preselected"]).name
        estado["files"] = [p.name for p in estado["_selected"]]
        return SKIP

    estado.pop("source", None)
    estado.pop("files", None)
    _pintar(estado)

    # Los lotes delante: una subcarpeta de sources/ es un modulo entero y es lo que se
    # elige el 90 % de las veces, asi que va donde cae el cursor al abrirse la lista.
    # "Process ALL files" no aparece si no hay ningun fichero suelto: seria una opcion
    # que solo lleva al aviso de que no hay nada.
    sueltos = (sorted(f.name for f in estado["_dir"].iterdir()
                      if f.is_file() and f.suffix.lower() in VALID_EXTS)
               if estado["_dir"].exists() else [])

    cabe = _ancho() - 6
    opciones: list = [
        questionary.Choice(title=elide(f"{carpeta.name}/", cabe - 10) + f"   {n} files",
                           value=carpeta.name)
        for carpeta, n in list_source_folders(estado["_dir"])
    ]
    if sueltos:
        opciones.append(ALL_FILES)
        opciones += _opciones(sueltos)

    if not opciones:
        _aviso(f"No sources in {estado['_dir'].name}/")
        return None

    r = ask_select("Select source file", opciones,
                   default=estado.get("_ultimo_source"), back=volver)
    if r is None or r is BACK:
        return r

    seleccion = collect_sources(r, estado["_dir"])
    if not seleccion:
        estado["_aviso"] = f"No source files found for: {r}"
        return BACK if volver else SKIP

    estado["source"] = estado["_ultimo_source"] = r
    estado["_selected"] = seleccion
    estado["files"] = [p.name for p in seleccion]
    return True


def _paso_format(estado: dict, volver: bool):
    crudos = [p for p in estado["_selected"] if needs_formatting(p)]
    if not crudos:
        estado.pop("format", None)
        return SKIP

    estado.pop("format", None)
    _pintar(estado)
    if len(crudos) == 1:
        label = f"Format {elide(crudos[0].name, max(16, _ancho() - 40))} with Gemini AI?"
    else:
        label = f"Format {len(crudos)} raw files with Gemini AI?"

    r = ask_confirm(label, default=True, back=volver)
    if r is None or r is BACK:
        return r
    estado["format"] = r
    return True


def _paso_provider(estado: dict, volver: bool):
    estado.pop("provider", None)
    _pintar(estado)

    # La lista sale del registro, no de una constante paralela: anadir un proveedor
    # era tocar tres sitios y olvidarse de uno (Gemini estaba registrado y no
    # aparecia aqui). Los que no tienen clave se ven, en gris y sin poder elegirse:
    # es mas util saber que existen que fingir que no.
    # El subtitulo va en su renglon, en cursiva y bajo la opcion. Pegado detras a 22
    # columnas era una segunda columna de texto que solo tenia una fila.
    opciones = [questionary.Choice(title=_AUTO_NAME, value=_AUTO,
                                   description="use whichever is configured")]
    for pid, (nombre, cls) in AVAILABLE_TRANSLATORS.items():
        try:
            cls()
            opciones.append(questionary.Choice(title=nombre, value=pid))
        except Exception:
            opciones.append(questionary.Choice(title=nombre, value=pid,
                                               disabled="no API key in .env"))

    r = ask_select("Choose translation provider", opciones,
                   default=estado.get("_ultimo_provider"), back=volver)
    if r is None or r is BACK:
        return r
    estado["_provider_id"] = estado["_ultimo_provider"] = r
    estado["provider"] = _AUTO_NAME if r == _AUTO else AVAILABLE_TRANSLATORS[r][0]
    return True


def _paso_output(estado: dict, volver: bool):
    estado.pop("output", None)
    _pintar(estado)
    opciones = ["Google Drive", "Local only", "Local + Google Drive"]
    r = ask_select("Output destination", opciones,
                   default=estado.get("_ultimo_output"), back=volver)
    if r is None or r is BACK:
        return r
    estado["output"] = estado["_ultimo_output"] = r
    return True


def _fijar_drive(estado: dict, carpeta: tuple[str, str]):
    estado["_drive"] = estado["_ultimo_drive"] = carpeta
    estado["drive_folder"] = carpeta[1] or "Drive folder"
    return True


def _paso_drive(estado: dict, volver: bool):
    """En que carpeta de Drive. Solo se pregunta si algo va a subirse.

    Era lo unico de la configuracion que se tocaba a mano y fuera del programa: crear
    la carpeta del modulo nuevo en Drive, copiar el trozo final de la URL y pegarlo en
    config.json. Aqui se elige entre la de siempre, una nueva —que se crea al lado de
    la anterior, que es donde van las de los modulos— y cualquier otra.

    El wizard sigue sin decidir nada: pregunta, y quien habla con Drive es
    folder_picker. Lo que se guarda en config.json se guarda al arrancar, no al
    elegir, para que cancelar en la confirmacion no deje la eleccion puesta.
    """
    if "Google Drive" not in (estado.get("output") or ""):
        estado.pop("drive_folder", None)
        estado.pop("_drive", None)
        return SKIP

    estado.pop("drive_folder", None)
    actual_id, actual_nombre = estado.get("_ultimo_drive") or configured_folder()

    # Sin ninguna carpeta que ofrecer no hay nada que preguntar: se abre el selector,
    # que es lo que haria la unica opcion de esa lista.
    if not actual_id:
        _pintar(estado)
        elegida = pick_drive_folder()
        if elegida is None:
            estado["_aviso"] = "Drive needs a folder to upload to."
            return BACK
        return _fijar_drive(estado, elegida)

    # El nombre esta guardado en el config al lado del id: pintar esta pregunta no
    # habla con Drive ni obliga a autenticarse para leer una etiqueta.
    etiqueta = elide(actual_nombre or "The configured folder", max(12, _ancho() - 20))
    opciones = [
        questionary.Choice(title=f"{etiqueta}   (current)", value=_MISMA),
        questionary.Choice(title="Create a new folder…", value=_NUEVA,
                           description=f"next to {etiqueta}"),
        questionary.Choice(title="Choose another folder…", value=_ELEGIR,
                           description="browse your Drive"),
    ]

    _pintar(estado)
    r = ask_select("Drive folder", opciones, default=_MISMA, back=volver)
    if r is None or r is BACK:
        return r

    if r == _MISMA:
        return _fijar_drive(estado, (actual_id, actual_nombre))

    if r == _NUEVA:
        # El nombre viene ya escrito: si la anterior es M18, la de este modulo es M19.
        # Propuesto, no impuesto —es el contenido del campo, y se borra escribiendo.
        nombre = ask_text("New folder name",
                          default=next_folder_name(actual_nombre) or "", back=True)
        if nombre is None:
            return None
        if nombre is BACK or not nombre.strip():
            return _paso_drive(estado, volver)
        creada = create_folder_next_to(nombre.strip(), actual_id)
        if creada is None:
            estado["_aviso"] = f"Could not create {nombre.strip()} in Drive."
            return _paso_drive(estado, volver)
        return _fijar_drive(estado, creada)

    elegida = pick_drive_folder()
    if elegida is None:
        # Cancelar el selector vuelve a la pregunta, no cancela la ejecucion entera.
        return _paso_drive(estado, volver)
    return _fijar_drive(estado, elegida)


def _nota_cobertura(code: str, proveedores: list[str]) -> str:
    """Que decir al lado de un idioma que no todos los proveedores traducen.

    Se calla cuando no hay nada que decir, que es el caso normal: los dieciocho
    codigos de la lista estan cubiertos por DeepL y por Azure. Solo habla cuando la
    eleccion de proveedor deja ese idioma cojo, para no ensuciar la lista entera con
    una anotacion que siempre dice lo mismo.
    """
    cubren = supported_by(code, proveedores)
    if len(cubren) == len(proveedores):
        return ""
    if not cubren:
        return "· no configured provider translates this"
    return "· only " + ", ".join(AVAILABLE_TRANSLATORS[p][0].split()[0] for p in cubren)


def _paso_languages(estado: dict, volver: bool):
    estado.pop("languages", None)
    _pintar(estado)

    proveedores = ([p for p in AVAILABLE_TRANSLATORS if _configurado(p)]
                   if estado.get("_provider_id", _AUTO) == _AUTO
                   else [estado["_provider_id"]])
    ya = set(estado.get("_ultimo_langs") or [])

    opciones = []
    for code, info in LANGUAGES.items():
        nota = _nota_cobertura(code, proveedores)
        titulo = f"{code:<4}{info['name']:<12}{nota}".rstrip()
        opciones.append(questionary.Choice(title=titulo, value=code, checked=code in ya))
    opciones.append(questionary.Choice(title="Other code…  (EN-GB, PT-BR, …)",
                                       value=_OTRO, checked=False))

    r = ask_checkbox("Target languages", opciones, back=volver)
    if r is None or r is BACK:
        return r

    langs = [c for c in r if c != _OTRO]
    if _OTRO in r:
        extra = ask_text("Extra codes, space separated", back=True)
        if extra is None:
            return None
        if extra is not BACK:
            langs += [c for c in extra.upper().split() if c not in langs]

    if not langs:
        estado["_aviso"] = "Pick at least one language."
        return _paso_languages(estado, volver)

    estado["languages"] = estado["_ultimo_langs"] = langs
    return True


def _configurado(pid: str) -> bool:
    try:
        AVAILABLE_TRANSLATORS[pid][1]()
        return True
    except Exception:
        return False


_PASOS = (_paso_source, _paso_format, _paso_provider, _paso_output, _paso_drive,
          _paso_languages)


def run_wizard(preselected_source: str = None, previo: dict | None = None) -> dict | None:
    """Recorre los pasos hasta el final. Devuelve la config, o None si se cancela.

    `previo` es la config de una pasada anterior: al volver desde la confirmacion con
    "Change something…" cada pregunta se despliega con lo que ya habias contestado
    puesto, y confirmar es un Enter.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    estado: dict = {"_dir": base_dir / "sources", "_preselected": preselected_source}
    if previo:
        estado["_ultimo_source"]   = previo.get("source")
        estado["_ultimo_provider"] = previo.get("provider")
        estado["_ultimo_output"]   = previo.get("output")
        estado["_ultimo_langs"]    = previo.get("languages")
        if previo.get("drive_folder_id"):
            estado["_ultimo_drive"] = (previo["drive_folder_id"],
                                       previo.get("drive_folder_name") or "")

    if preselected_source:
        seleccion = collect_sources(Path(preselected_source).name, estado["_dir"])
        if not seleccion:
            console.print(f"[{RED}]✗ No source files found for: {preselected_source}[/{RED}]")
            return None
        estado["_selected"] = seleccion

    i, direccion = 0, 1
    while i < len(_PASOS):
        estado["_paso_actual"] = _PASOS[i]
        r = _PASOS[i](estado, volver=i > 0)
        if r is None:
            return None
        if r is SKIP:
            i += direccion
            if i < 0:
                i, direccion = 0, 1
            continue
        if r is BACK:
            direccion = -1
            i -= 1
            if i < 0:
                i, direccion = 0, 1
            continue
        direccion = 1
        i += 1

    _pintar(estado)
    return {
        "source":      estado["source"],
        "provider":       estado["_provider_id"],
        "provider_label": estado["provider"],
        "output":      estado["output"],
        "languages":   estado["languages"],
        "format_raw":  estado.get("format", False),
        "files":       estado["files"],
        "drive_folder_id":   estado.get("_drive", ("", ""))[0],
        "drive_folder_name": estado.get("_drive", ("", ""))[1],
    }
