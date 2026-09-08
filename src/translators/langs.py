"""Como llama cada proveedor a cada idioma. Un solo sitio, a proposito.

Los codigos que se ven en la interfaz son siempre los mismos —EN, PT, ZH— pase lo
que pase por debajo. Aqui vive la unica traduccion entre esos codigos y los que
espera cada API, y aqui se anade la fila cuando se anade un proveedor.

Por que hace falta: DeepL **si** traduce al ingles y al portugues, pero como destino
ya no acepta el idioma a secas. Su lista oficial de destinos tiene EN-GB, EN-US,
PT-BR y PT-PT, no EN ni PT. Hoy `target_lang=EN` sigue devolviendo 200 porque lo
mantienen como alias obsoleto por compatibilidad; el dia que lo retiren, los dos
idiomas mas usados de este proyecto dejan de traducirse sin que nadie haya tocado
nada. Fijar la variante aqui quita esa dependencia.

Comprobado contra las APIs en vivo (Azure /languages, DeepL /v2/languages):
Azure declara 138 idiomas y DeepL 110 destinos; los 18 de la interfaz estan en los
dos. La cobertura no es el problema; la ortografia del codigo si.

API:
    PROVIDER_CODES: dict[str, dict[str, str]]   codigo de UI → codigo de la API
    SUPPORTED:      dict[str, frozenset | None] codigos de UI que traduce, None si no publica lista
"""

# Variantes europeas por defecto, que es el destino habitual de estos apuntes.
# Cambiar EN-GB por EN-US o PT-PT por PT-BR es cambiar esta linea y nada mas.
PROVIDER_CODES: dict[str, dict[str, str]] = {
    "deepl": {
        "EN": "EN-GB",      # DeepL exige variante: EN a secas es un alias obsoleto
        "PT": "PT-PT",      # idem
    },
    "azure": {
        "ZH":    "zh-Hans",  # Azure separa simplificado y tradicional
        "EN-GB": "en-GB",
    },
    "gemini": {},
}

# Los 18 codigos que ofrece la interfaz, verificados uno a uno contra cada API.
_UI = frozenset({"EN", "ES", "FR", "DE", "IT", "PT", "RU", "JA", "KO", "ZH",
                 "AR", "FA", "HE", "UR", "HI", "TR", "PL", "NL"})

SUPPORTED: dict[str, frozenset[str] | None] = {
    "deepl": _UI,
    "azure": _UI,
    # Gemini es un modelo de lenguaje: no publica lista de destinos y no tiene sentido
    # inventarle una. None significa "no lo se", no "todos".
    "gemini": None,
}
