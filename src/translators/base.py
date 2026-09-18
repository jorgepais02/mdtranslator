import inspect as _inspect
import re as _re
from abc import ABC, abstractmethod


_INLINE_CODE_RE    = _re.compile(r'`[^`\n]+`')
_FORMULA_BLOCK_RE  = _re.compile(r'\$\$[\s\S]+?\$\$')
_FORMULA_INLINE_RE = _re.compile(r'\$[^$\n]+\$')
_URL_RE            = _re.compile(r'https?://\S+')


def _protect_tokens(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []
    def _replace(m: _re.Match) -> str:
        tokens.append(m.group(0))
        return f"⟦{len(tokens)-1}⟧"
    out = _FORMULA_BLOCK_RE.sub(_replace, text)
    out = _FORMULA_INLINE_RE.sub(_replace, out)
    out = _INLINE_CODE_RE.sub(_replace, out)
    out = _URL_RE.sub(_replace, out)
    return out, tokens


def _restore_tokens(text: str, tokens: list[str]) -> str:
    for i, tok in enumerate(tokens):
        text = text.replace(f"⟦{i}⟧", tok)
    return text


def chunk_texts(texts: list[str], max_items: int, max_chars: int) -> list[list[str]]:
    """Trocea respetando a la vez el nº de elementos y el tamaño total del request.

    Contar solo elementos no basta: los proveedores limitan tambien por caracteres,
    y una transcripcion de parrafos largos supera ese limite mucho antes de llegar
    al tope de elementos. Un texto que por si solo excede el maximo viaja en su
    propio request en vez de partirse, para no romper la correspondencia 1:1.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for text in texts:
        n = len(text)
        if current and (len(current) >= max_items or size + n > max_chars):
            chunks.append(current)
            current, size = [], 0
        current.append(text)
        size += n
    if current:
        chunks.append(current)
    return chunks


# Como acepta source_lang cada proveedor: None | "keyword" | "positional".
_SOURCE_MODE: dict[type, str | None] = {}


def _source_lang_mode(translator: "BaseTranslator") -> str | None:
    """Averigua si translate() admite source_lang y de que forma.

    No basta con saber que lo acepta: un proveedor con **kwargs lo admite solo por
    nombre, y pasarselo por posicion revienta con TypeError.
    """
    cls = type(translator)
    if cls in _SOURCE_MODE:
        return _SOURCE_MODE[cls]

    mode: str | None = None
    try:
        params = _inspect.signature(translator.translate).parameters
        param = params.get("source_lang")
        if param is not None:
            mode = "positional" if param.kind is param.POSITIONAL_ONLY else "keyword"
        elif any(p.kind is p.VAR_KEYWORD for p in params.values()):
            mode = "keyword"
        elif any(p.kind is p.VAR_POSITIONAL for p in params.values()):
            mode = "positional"
    except (TypeError, ValueError):
        mode = None

    _SOURCE_MODE[cls] = mode
    return mode


# Quien acepta context. Cacheado por clase, como el de source_lang.
_ACEPTA_CONTEXT: dict[type, bool] = {}


def _acepta_context(translator: "BaseTranslator") -> bool:
    """Si translate() admite context, y **solo por nombre**.

    Por posicion no se pasa nunca: context es el cuarto argumento y su sitio depende
    de que source_lang venga puesto, asi que un proveedor con *args lo recibiria
    descolocado. Azure no lo acepta y no se entera de que existe.
    """
    cls = type(translator)
    if cls in _ACEPTA_CONTEXT:
        return _ACEPTA_CONTEXT[cls]

    acepta = False
    try:
        params = _inspect.signature(translator.translate).parameters
        param = params.get("context")
        acepta = ((param is not None and param.kind is not param.POSITIONAL_ONLY)
                  or any(p.kind is p.VAR_KEYWORD for p in params.values()))
    except (TypeError, ValueError):
        acepta = False

    _ACEPTA_CONTEXT[cls] = acepta
    return acepta


def call_translate(translator: "BaseTranslator", texts: list[str], target_lang: str,
                   source_lang: str | None = None,
                   context: str | None = None) -> list[str]:
    """Llama a translate() pasando source_lang y context solo si el proveedor los acepta.

    Un proveedor externo escrito contra la interfaz original —translate(texts,
    target_lang)— sigue funcionando sin tocarlo.

    context dice de que van los apuntes para que el proveedor elija la acepcion
    correcta. No se traduce, no viaja en la clave de cache y no todos lo tienen:
    DeepL lo lleva nativo, Gemini lo mete en su prompt y Azure no tiene nada
    equivalente (su `category` es un modelo entrenado aparte).
    """
    args: list = [texts, target_lang]
    kwargs: dict = {}

    if source_lang:
        mode = _source_lang_mode(translator)
        if mode == "keyword":
            kwargs["source_lang"] = source_lang
        elif mode == "positional":
            args.append(source_lang)

    if context and _acepta_context(translator):
        kwargs["context"] = context

    return translator.translate(*args, **kwargs)


class TranslationError(Exception):
    """Raised when a translation provider fails."""
    pass


class BaseTranslator(ABC):
    """Abstract base class for all translation providers."""

    name: str = "unknown"

    # Codigos que este proveedor escribe distinto, y los que sabe traducir. Se
    # rellenan desde translators/langs.py; vacios significa "los codigos de la
    # interfaz valen tal cual" y None en supported significa "no publica lista".
    lang_codes: dict[str, str] = {}
    supported:  frozenset[str] | None = None

    # Lo que hace falta para darle de alta una clave, aqui y no en una constante
    # aparte: la leccion del menu del wizard es que un proveedor tiene que ser una
    # fila. `extra_env` son los valores que la API pide **ademas** de la clave —Azure
    # no funciona sin su region— como (variable, etiqueta, valor por defecto).
    key_env:   str = ""
    extra_env: tuple[tuple[str, str, str], ...] = ()
    signup:    str = ""          # la pagina donde se saca la clave
    free:      str = ""          # que da el plan gratuito, en una linea

    def api_lang(self, code: str) -> str:
        """Codigo de la interfaz → codigo de este proveedor. API: str."""
        return self.lang_codes.get(code.upper(), code)

    def supports(self, code: str) -> bool | None:
        """Si traduce a ese idioma. Devuelve None cuando no hay lista que consultar."""
        if self.supported is None:
            return None
        return code.upper() in self.supported

    @abstractmethod
    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None,
                  context: str | None = None) -> list[str]:
        """Translate a list of strings to target_lang. Returns same-length list.

        source_lang es opcional: cuando se conoce, evita que el proveedor tenga que
        adivinar el idioma linea a linea (una opcion suelta como 'A) Josep Albors'
        se detecta mal). Sin el, el comportamiento es el de siempre.

        context tambien: de que van los apuntes, para desambiguar. Un proveedor que no
        lo declare no lo recibe (ver call_translate), asi que anadirlo aqui no obliga a
        nadie a implementarlo.
        """
        pass


class FallbackTranslator(BaseTranslator):
    """Tries multiple providers in order, falling back on failure."""

    def __init__(self, translators: list[BaseTranslator]):
        if not translators:
            raise ValueError("FallbackTranslator requires at least one translator.")
        self.translators = translators

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None,
                  context: str | None = None) -> list[str]:
        errors: list[str] = []
        for t in self.translators:
            try:
                return call_translate(t, texts, target_lang, source_lang, context)
            except TranslationError as e:
                errors.append(f"{type(t).__name__}: {e}")
        raise TranslationError(
            "All translation providers failed:\n  " + "\n  ".join(errors)
        )


class ProtectedTranslator(BaseTranslator):
    """Wraps any translator to protect inline code spans, formulas, and URLs."""

    def __init__(self, translator: BaseTranslator):
        self.translator = translator
        self.name = translator.name

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None,
                  context: str | None = None) -> list[str]:
        protected_texts = []
        all_tokens: list[list[str]] = []
        for text in texts:
            protected, tokens = _protect_tokens(text)
            protected_texts.append(protected)
            all_tokens.append(tokens)
        translated = call_translate(self.translator, protected_texts, target_lang,
                                    source_lang, context)
        if len(translated) != len(protected_texts):
            raise TranslationError(
                f"{self.name} returned {len(translated)} translations "
                f"for {len(protected_texts)} inputs"
            )
        return [_restore_tokens(t, tokens) for t, tokens in zip(translated, all_tokens)]
