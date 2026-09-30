"""El .txt se formatea en su idioma y sin resumirlo.

Las dos cosas pasaron con el módulo 20. Cuatro de seis transcripciones españolas
volvieron formateadas en inglés: con `lang="es"` el prompt no nombraba el idioma y todo
lo demás que veía el modelo estaba en inglés. Y al arreglarlo, tres volvieron resumidas
y sin las herramientas de las que trataban. El .md se guarda junto al .txt y gana sobre
él, así que cualquiera de los dos defectos se habría quedado en las siguientes
ejecuciones también.
"""

import pytest

from ai.base import AIError
from integrations import generate_md

ES = ("Buenas tardes a todos. Hoy vamos a hablar de la respuesta a incidentes de "
      "ransomware, y lo vamos a hacer mirando a la organización como si fuera un "
      "paciente: el ataque entra, evoluciona, da síntomas y se propaga, y si no se "
      "actúa a tiempo puede acabar siendo fatal para el negocio. Lo importante no es "
      "el momento del cifrado, sino entender toda la cadena desde el primer acceso.")

MD_ES = ("# Dr. Ryuk (I)\n\n## La organización como paciente\n\nEl ransomware se "
         "estudia como una enfermedad de la organización: entra, evoluciona, presenta "
         "síntomas y se propaga, y puede ser fatal si no se actúa a tiempo. Lo "
         "importante no es el momento del cifrado, sino la cadena completa de hechos "
         "desde el acceso inicial hasta el impacto en el negocio.")

MD_EN = ("# Dr. Ryuk (I)\n\n## The organization as a patient\n\nRansomware is "
         "studied as an illness of the organization: it enters, evolves, presents "
         "symptoms and spreads, and it can be fatal if nobody acts in time. What "
         "matters is not the moment of encryption, but the whole chain of events "
         "from the initial access to the impact on the business.")


def _modelo(monkeypatch, *respuestas):
    visto = {"prompts": []}
    cola = list(respuestas)

    class Modelo:
        def complete(self, prompt, system="", temperature=0.2):
            visto["prompts"].append(prompt)
            visto["system"] = system
            return cola.pop(0)

    monkeypatch.setattr(generate_md, "get_model", lambda: Modelo())
    return visto


def test_el_prompt_nombra_el_idioma_de_la_transcripcion(monkeypatch):
    visto = _modelo(monkeypatch, MD_ES)
    generate_md.generate_markdown(ES, title="1. Dr. Ryuk (I)")
    assert "Spanish" in visto["prompts"][0]
    assert "Never translate" in visto["system"]


def test_si_vuelve_en_otro_idioma_se_reintenta(monkeypatch):
    visto = _modelo(monkeypatch, MD_EN, MD_ES)
    out = generate_md.generate_markdown(ES, title="1. Dr. Ryuk (I)")
    assert len(visto["prompts"]) == 2
    assert "La organización como paciente" in out


def test_dos_veces_en_otro_idioma_es_un_error(monkeypatch):
    """Un error y no el inglés: load_markdown se queda con el crudo y no guarda el .md."""
    _modelo(monkeypatch, MD_EN, MD_EN)
    with pytest.raises(AIError, match="EN"):
        generate_md.generate_markdown(ES, title="1. Dr. Ryuk (I)")


def test_sin_certeza_no_se_rechaza_nada(monkeypatch):
    """Un texto corto no da para afirmar su idioma: se acepta lo que vuelva."""
    visto = _modelo(monkeypatch, "# Title\n\nShort text.")
    assert generate_md.generate_markdown("habla en crudo").startswith("# Title")
    assert len(visto["prompts"]) == 1


def test_el_md_en_otro_idioma_no_se_guarda(monkeypatch, tmp_path):
    from core.sources import load_markdown
    _modelo(monkeypatch, MD_EN, MD_EN)
    txt = tmp_path / "1. Dr. Ryuk (I).txt"
    txt.write_text(ES, encoding="utf-8")
    contenido, aviso = load_markdown(txt)
    assert contenido == ES
    assert "EN" in aviso
    assert not txt.with_suffix(".md").exists()


# «Dr. Ryuk (II)»: una herramienta por fase del ataque, que es de lo que trata el apunte
HERRAMIENTAS = ("En el reconocimiento se usa AdFind o un escáner de red, y después "
                "Mimikatz para el acceso a credenciales, como hacía LockBit. El acceso "
                "al fichero ntds.dit compromete el dominio entero. Para moverse se usan "
                "PsExec o RDP, para la evasión BYOVD, y para exfiltrar RClone o WinSCP.")

MD_CON = ("# Dr. Ryuk (II)\n\n## Herramientas por fase\n\nEn el reconocimiento se emplea "
          "AdFind; para las credenciales, Mimikatz, como LockBit. El acceso a ntds.dit "
          "compromete el dominio. El movimiento lateral usa PsExec o RDP, la evasión "
          "BYOVD y la exfiltración RClone o WinSCP.")

MD_SIN = ("# Dr. Ryuk (II)\n\n## Herramientas por fase\n\nEl atacante enumera el entorno "
          "con utilidades de consulta y extrae credenciales con software especializado. "
          "El acceso a bases de datos de directorio compromete el dominio, y la "
          "exfiltración usa clientes de transferencia estándar.")


def test_si_vuelve_resumido_se_reintenta(monkeypatch):
    visto = _modelo(monkeypatch, MD_SIN, MD_CON)
    out = generate_md.generate_markdown(HERRAMIENTAS, title="2. Dr. Ryuk (II)")
    assert len(visto["prompts"]) == 2
    assert "Mimikatz" in out


def test_dos_veces_resumido_se_queda_el_que_conserva_mas(monkeypatch, capsys):
    """No es un error: unas notas cortas se leen, el crudo sin encabezados no."""
    casi = MD_SIN + " Se detecta Mimikatz y PsExec."
    _modelo(monkeypatch, MD_SIN, casi)
    out = generate_md.generate_markdown(HERRAMIENTAS, title="2. Dr. Ryuk (II)")
    assert out.endswith("Se detecta Mimikatz y PsExec.")
    assert "Summarized" in capsys.readouterr().err


def test_el_resumido_no_se_prefiere_al_que_vuelve_en_otro_idioma(monkeypatch):
    """El idioma se mira primero: un inglés con todos los nombres sigue sin valer."""
    en = MD_CON.replace("En el reconocimiento se emplea", "Reconnaissance uses")
    en = en.replace("para las credenciales", "for credentials") + (
        " The attacker moves laterally and exfiltrates data with these tools, and the "
        "defender must detect each phase before the encryption starts.")
    _modelo(monkeypatch, en, MD_SIN)
    assert generate_md.generate_markdown(HERRAMIENTAS) == MD_SIN


def test_con_pocos_terminos_no_se_mide_nada():
    """«Mayday, mayday (II)» tiene uno: perderlo sería el 100 % y no diría nada."""
    assert generate_md._perdidos("Hablamos del SOC y de su trabajo diario.", "# Nada") == []


def test_la_medida_separa_los_del_m20_de_los_buenos():
    assert generate_md._perdidos(HERRAMIENTAS, MD_SIN)
    assert generate_md._perdidos(HERRAMIENTAS, MD_CON) == []
