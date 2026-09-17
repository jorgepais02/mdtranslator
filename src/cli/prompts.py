"""Preguntas de questionary que saben volver atras.

Todas devuelven `BACK` si el usuario pulsa retroceso y `None` si cancela con Ctrl+C,
de modo que quien las llama pueda ser una maquina de pasos y no una lista fija.

API:
    BACK
    ask_select(label, choices, default=None, back=False)    -> valor | BACK | None
    ask_confirm(label, default=True, back=False)            -> bool  | BACK | None
    ask_text(label, default="", validate=None, back=False)  -> str   | BACK | None
    ask_checkbox(label, choices, back=False)                -> list  | BACK | None

El titulo de la pregunta y el filete que lo cierra los pinta rich, y a questionary se
le pasa un mensaje vacio. No es un rodeo: questionary tiene una unica clase
`separator` para todo lo que no es una opcion, y el filete (#33364a) y los subtitulos
(#4b5263, cursiva) son dos roles distintos — compartiendo clase saldrian iguales. De
paso, la linea vacia del mensaje es justo el aire que va entre el filete y la lista.
"""

import questionary
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from rich.text import Text

from .styles import console, MARGEN, META, RULE, TITLE, WIZARD_STYLE

# questionary trae "?" y "»" por defecto. El "?" se quita del todo: en una pantalla
# con lista, el unico glifo debe ser el que se mueve. Y el puntero es "❯", que es el
# que usa todo lo demas del proyecto.
_QMARK   = ""
_POINTER = "❯"

# `if instruction:` — con cadena vacia questionary cae al else y escribe "(Use arrow
# keys)". Un espacio es lo que hay que pasarle para que no escriba nada.
_SIN_PISTA = " "


class _Back:
    def __repr__(self):
        return "BACK"


BACK = _Back()

# Retroceso, no Esc ni flecha izquierda: en un terminal Esc significa cancelar y la
# flecha izquierda mueve el cursor dentro de un campo de texto. ⌫ no significa nada
# mas en una lista, asi que esta libre.
#
# De la linea de pistas queda lo que no se adivina, y donde no estorba: alineada a la
# derecha del titulo, en el gris mas apagado de la paleta. ↑↓ y ⏎ sobre una lista no
# hay que explicarlos —eran dos tercios de aquella linea— pero ⌫ para volver es
# invencion nuestra y "space" para marcar no se adivina.
_HINT_BACK  = "⌫ back"
_HINT_TEXT  = "⏎ confirm · ⌫ back"
_HINT_MULTI = "space · ⌫ back"


def _bind_back(question, cuando=None):
    """Engancha ⌫ a la pregunta para que salga devolviendo BACK.

    En select y confirm el objeto de bindings es un KeyBindings y se le puede anadir
    directamente. En text es un merge inmutable, asi que se envuelve: el ultimo que
    casa gana, y por eso el nuestro va al final.
    """
    def salir(event):
        event.app.exit(result=BACK)

    # `if cuando:` no vale: los filtros de prompt_toolkit prohiben bool() a proposito.
    opciones = {"eager": True}
    if cuando is not None:
        opciones["filter"] = cuando

    app = question.application
    kb = app.key_bindings
    if hasattr(kb, "add"):
        kb.add("backspace", **opciones)(salir)
    else:
        extra = KeyBindings()
        extra.add("backspace", **opciones)(salir)
        app.key_bindings = merge_key_bindings([kb, extra])
    return question


# ── la cabecera de una pregunta ───────────────────────────────────────────────
# El filete va DEBAJO del titulo, no encima: en vez de anunciarlo, lo cierra. Se mide
# sobre el ancho del terminal y no sobre la opcion mas larga, que es de donde venia
# que no llegara ni hasta el final del propio titulo. Con tope, porque una raya de 150
# columnas sobre una lista de cuatro palabras ya no cierra nada: subraya la pantalla.
_REGLA_MAX = 72
_REGLA_MIN = 24


def _regla() -> str:
    return "─" * max(_REGLA_MIN, min(max(32, console.width) - 2, _REGLA_MAX))


def _cabecera(label: str, pista: str = "") -> None:
    """Titulo de la pantalla, su pista y el filete. El aire de debajo lo pone el
    mensaje vacio que se le pasa a questionary.

    El filete va pegado al titulo, sin linea en blanco en medio: con el hueco, la raya
    flotaba a medio camino entre la pregunta y la lista y no se sabia de cual de las dos
    era. Pegada, es el subrayado de la pregunta y lo que abre la lista.

    La pista va en la misma linea que el titulo y acabando donde acaba el filete: ahi
    cae fuera del camino de lectura y no se come la linea en blanco que separa el
    filete de la lista. Si no cabe, se cae — antes que partirse en dos o empujar al
    titulo.
    """
    regla = _regla()
    linea = Text(MARGEN)
    linea.append(label, style=f"bold {TITLE}")
    hueco = len(regla) - len(label) - len(pista)
    if pista and hueco >= 4:
        linea.append(" " * hueco)
        linea.append(pista, style=META)
    console.print(linea)
    console.print(Text(MARGEN + regla, style=RULE))


# ── la lista ──────────────────────────────────────────────────────────────────
# Por encima de este numero de opciones la lista va apretada: con dieciocho idiomas,
# una linea en blanco entre cada uno son treinta y seis renglones y ya no cabe.
_AIRE_MAX = 6


# Lo que questionary pone delante de cada opcion antes del texto: " ❯ " son tres.
_SANGRIA = "   "


def _desplegar(choices: list) -> tuple[list, dict[int, str], bool]:
    """Intercala los huecos entre opciones. API: (lista, {indice: subtitulo}, aireada).

    El subtitulo se saca del Choice y se devuelve aparte: lo pinta `_subtitulo_vivo`,
    que si sabe donde esta el cursor. Al Choice se le quita la `description` para que
    questionary no la ensene ademas al pie de la lista con un "Description:" delante.
    """
    aire = len(choices) <= _AIRE_MAX
    fuera: list = []
    subtitulos: dict[int, str] = {}
    for i, c in enumerate(choices):
        subtitulo = getattr(c, "description", None)
        if subtitulo:
            c.description = None
            subtitulos[len(fuera)] = subtitulo
        fuera.append(c)
        if aire and i < len(choices) - 1:
            # Separator("") no vale: `line or default` devolveria "---------------".
            fuera.append(questionary.Separator(" "))
    return fuera, subtitulos, aire


def _subtitulo_vivo(question, subtitulos: dict[int, str], aire: bool) -> None:
    """Hace que un subtitulo solo se vea mientras el cursor esta en su opcion.

    questionary pinta los separadores siempre igual: no sabe donde esta el cursor, asi
    que un subtitulo puesto como separator se queda encendido toda la pantalla y acaba
    leyendose como una linea mas de la lista. Aqui se envuelve el armador de tokens del
    control y se **inserta** el subtitulo debajo de la opcion senalada.

    Insertar, no rellenar el hueco: el subtitulo lleva su propia linea en blanco
    respecto a la opcion siguiente, asi que las de abajo bajan un renglon mientras
    esta encendido y vuelven a subir al salir. En estado normal la separacion entre
    opciones es siempre la misma; solo se abre para ensenar algo, y se cierra.
    """
    if not subtitulos:
        return
    from questionary.prompts.common import InquirerControl
    control = next((c for c in question.application.layout.find_all_controls()
                    if isinstance(c, InquirerControl)), None)
    if control is None:      # si questionary cambia de tripas, mejor sin subtitulo que roto
        return
    armar = control.text

    def con_subtitulo():
        tokens = list(armar())
        texto = subtitulos.get(control.pointed_at)
        if not texto:
            return tokens

        filas, actual = [], []
        for t in tokens:
            actual.append(t)
            if t[1].endswith("\n"):
                filas.append(actual)
                actual = []
        if actual:
            filas.append(actual)

        extra = [[("class:text", _SANGRIA), ("class:separator", texto), ("", "\n")]]
        # En una lista apretada no hay hueco detras: el salto lo pone el subtitulo.
        if not aire:
            extra.append([("", "\n")])
        sitio = control.pointed_at + 1
        # questionary se come el salto de la ultima fila. Si la opcion senalada es la
        # ultima, el subtitulo pasa a ser el final: hereda el corte y se lo devuelve.
        if sitio == len(filas):
            filas[-1].append(("", "\n"))
            extra[-1].pop()
        filas[sitio:sitio] = extra
        return [t for fila in filas for t in fila]

    control.text = con_subtitulo


def _ask(question, back: bool, cuando=None):
    if back:
        _bind_back(question, cuando)
    try:
        return question.unsafe_ask()
    except KeyboardInterrupt:
        return None


def ask_select(label: str, choices: list, default=None, back: bool = False):
    _cabecera(label, _HINT_BACK if back else "")
    opciones, subtitulos, aire = _desplegar(choices)
    q = questionary.select(
        "", qmark=_QMARK, pointer=_POINTER, choices=opciones,
        default=default, style=WIZARD_STYLE, instruction=_SIN_PISTA,
        show_description=False, erase_when_done=True,
    )
    _subtitulo_vivo(q, subtitulos, aire)
    return _ask(q, back)


def ask_confirm(label: str, default: bool = True, back: bool = False):
    # Sin filete: no hay lista debajo que separar, y una raya con nada detras se lee
    # como que falta algo.
    q = questionary.confirm(
        label, qmark=_QMARK, default=default, style=WIZARD_STYLE,
        instruction=("(Y/n) · ⌫ back" if back else None),
        erase_when_done=True,
    )
    return _ask(q, back)


def ask_text(label: str, default: str = "", validate=None, back: bool = False):
    q = questionary.text(
        label, qmark=_QMARK, default=default, style=WIZARD_STYLE, validate=validate,
        instruction=_HINT_TEXT if back else "",
        erase_when_done=True,
    )
    # En un campo de texto ⌫ borra: solo vuelve atras cuando ya no queda nada que
    # borrar, que es como se comporta cualquier formulario de terminal.
    vacio = Condition(lambda: not q.application.current_buffer.text)
    return _ask(q, back, cuando=vacio)


def ask_checkbox(label: str, choices: list, back: bool = False):
    _cabecera(label, _HINT_MULTI if back else "space")
    opciones, subtitulos, aire = _desplegar(choices)
    q = questionary.checkbox(
        "", qmark=_QMARK, pointer=_POINTER, choices=opciones,
        style=WIZARD_STYLE, instruction=_SIN_PISTA, erase_when_done=True,
    )
    _subtitulo_vivo(q, subtitulos, aire)
    return _ask(q, back)
