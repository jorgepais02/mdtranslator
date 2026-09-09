"""Preguntas de questionary que saben volver atras.

Todas devuelven `BACK` si el usuario pulsa retroceso y `None` si cancela con Ctrl+C,
de modo que quien las llama pueda ser una maquina de pasos y no una lista fija.

API:
    BACK
    ask_select(label, choices, default=None, back=False, paso="") -> valor | BACK | None
    ask_confirm(label, default=True, back=False)                  -> bool  | BACK | None
    ask_text(label, default="", validate=None, back=False)        -> str   | BACK | None
    ask_checkbox(label, choices, back=False, paso="")             -> list  | BACK | None

`paso` es la etiqueta del filete que cierra la pregunta ("step 3 of 5"). Solo lo
llevan las preguntas con lista: en un confirm o un campo de texto no hay nada debajo
de lo que separarlas.
"""

import questionary
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

from .styles import console, WIZARD_STYLE

# questionary trae "?" y "»" por defecto. El "?" se quita del todo: en una pantalla
# con lista, el unico glifo debe ser el que se mueve. Y el puntero es "❯", que es el
# que usa todo lo demas del proyecto.
_QMARK   = ""
_POINTER = "❯"


class _Back:
    def __repr__(self):
        return "BACK"


BACK = _Back()

# Retroceso, no Esc ni flecha izquierda: en un terminal Esc significa cancelar y la
# flecha izquierda mueve el cursor dentro de un campo de texto. ⌫ no significa nada
# mas en una lista, asi que esta libre.
_HINT      = "↑↓ move · ⏎ select · ⌫ back"
_HINT_TEXT = "⏎ confirm · ⌫ back"
_HINT_MULTI = "↑↓ move · space toggle · ⏎ confirm · ⌫ back"


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


# El filete va DEBAJO de la pregunta, no encima: en vez de anunciarla, la cierra.
# Antes la pregunta y la primera opcion quedaban pegadas y lo unico que las separaba
# era el ❯, que ya tiene otro trabajo. Se mide sobre la opcion mas larga y no sobre
# el terminal: una raya de 120 columnas encima de una lista de cuatro palabras se lee
# como un separador de seccion, no como el pie de una pregunta.
_FILETE_MIN = 24


def _titulo(choice) -> str:
    texto = getattr(choice, "title", choice)
    if isinstance(texto, list):          # questionary admite titulos por tramos
        texto = "".join(t for _, t in texto)
    return str(texto)


def _filete(choices: list, paso: str) -> questionary.Separator:
    largo = max((len(_titulo(c)) for c in choices), default=0) + 4
    ancho = max(_FILETE_MIN, min(largo, max(32, console.width) - 4))
    if not paso:
        return questionary.Separator("─" * ancho)
    ancho = max(ancho, len(paso) + 8)
    return questionary.Separator("─" * (ancho - 1 - len(paso)) + " " + paso)


def _ask(question, back: bool, cuando=None):
    if back:
        _bind_back(question, cuando)
    try:
        return question.unsafe_ask()
    except KeyboardInterrupt:
        return None


def ask_select(label: str, choices: list, default=None, back: bool = False,
               paso: str = ""):
    choices = [_filete(choices, paso), *choices]
    q = questionary.select(
        label, qmark=_QMARK, pointer=_POINTER, choices=choices, default=default, style=WIZARD_STYLE,
        instruction=_HINT if back else "↑↓ move · ⏎ select",
        erase_when_done=True,
    )
    return _ask(q, back)


def ask_confirm(label: str, default: bool = True, back: bool = False):
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


def ask_checkbox(label: str, choices: list, back: bool = False, paso: str = ""):
    choices = [_filete(choices, paso), *choices]
    q = questionary.checkbox(
        label, qmark=_QMARK, pointer=_POINTER, choices=choices, style=WIZARD_STYLE,
        instruction=_HINT_MULTI if back else "↑↓ move · space toggle · ⏎ confirm",
        erase_when_done=True,
    )
    return _ask(q, back)
