"""Volver atrás con ⌫: el enganche a questionary y la regla del campo de texto.

⌫ y no Esc, que en un terminal significa cancelar, ni ←, que dentro de un campo de
texto mueve el cursor. Estos tests aprietan la tecla de verdad contra un prompt real.
"""

import io

import pytest
import questionary
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.plain_text import PlainTextOutput

from cli.prompts import BACK, _bind_back

RETROCESO = "\x7f"


def _pulsar(construir, teclas, cuando=None):
    buf = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text(teclas)
        q = construir(input=pipe, output=PlainTextOutput(buf))
        _bind_back(q, cuando)
        return q.unsafe_ask()


def _select(**kw):
    return questionary.select("x", choices=["a", "b"], **kw)


def _confirm(**kw):
    return questionary.confirm("x", default=True, **kw)


def test_retroceso_en_una_lista_devuelve_back():
    assert _pulsar(_select, RETROCESO) is BACK


def test_enter_en_una_lista_sigue_eligiendo():
    assert _pulsar(_select, "\r") == "a"


def test_retroceso_en_un_si_o_no_devuelve_back():
    assert _pulsar(_confirm, RETROCESO) is BACK


def test_en_un_campo_de_texto_el_retroceso_borra():
    # Si ⌫ volviera atrás siempre, no se podría corregir una letra mal escrita.
    def construir(**kw):
        q = questionary.text("y", **kw)
        construir.q = q
        return q

    buf = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text("EN FRX" + RETROCESO + "\r")
        q = questionary.text("y", input=pipe, output=PlainTextOutput(buf))
        _bind_back(q, Condition(lambda: not q.application.current_buffer.text))
        assert q.unsafe_ask() == "EN FR"


def test_en_un_campo_vacio_el_retroceso_vuelve_atras():
    buf = io.StringIO()
    with create_pipe_input() as pipe:
        pipe.send_text("AB" + RETROCESO * 3)
        q = questionary.text("y", input=pipe, output=PlainTextOutput(buf))
        _bind_back(q, Condition(lambda: not q.application.current_buffer.text))
        assert q.unsafe_ask() is BACK


def test_el_enganche_no_pisa_el_resto_de_teclas():
    # El binding se anade al final: el ultimo que casa gana, y solo casa con ⌫.
    assert _pulsar(_select, "\x1b[B\r") == "b"        # flecha abajo + enter
