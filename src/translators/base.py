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


def call_translate(translator: "BaseTranslator", texts: list[str], target_lang: str,
                   source_lang: str | None = None) -> list[str]:
    """Llama a translate() pasando source_lang solo si el proveedor lo acepta.

    Un proveedor externo escrito contra la interfaz original —translate(texts,
    target_lang)— sigue funcionando sin tocarlo.
    """
    if source_lang:
        mode = _source_lang_mode(translator)
        if mode == "keyword":
            return translator.translate(texts, target_lang, source_lang=source_lang)
        if mode == "positional":
            return translator.translate(texts, target_lang, source_lang)
    return translator.translate(texts, target_lang)


class TranslationError(Exception):
    """Raised when a translation provider fails."""
    pass


class BaseTranslator(ABC):
    """Abstract base class for all translation providers."""

    name: str = "unknown"

    @abstractmethod
    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        """Translate a list of strings to target_lang. Returns same-length list.

        source_lang es opcional: cuando se conoce, evita que el proveedor tenga que
        adivinar el idioma linea a linea (una opcion suelta como 'A) Josep Albors'
        se detecta mal). Sin el, el comportamiento es el de siempre.
        """
        pass


class FallbackTranslator(BaseTranslator):
    """Tries multiple providers in order, falling back on failure."""

    def __init__(self, translators: list[BaseTranslator]):
        if not translators:
            raise ValueError("FallbackTranslator requires at least one translator.")
        self.translators = translators

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        errors: list[str] = []
        for t in self.translators:
            try:
                return call_translate(t, texts, target_lang, source_lang)
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
                  source_lang: str | None = None) -> list[str]:
        protected_texts = []
        all_tokens: list[list[str]] = []
        for text in texts:
            protected, tokens = _protect_tokens(text)
            protected_texts.append(protected)
            all_tokens.append(tokens)
        translated = call_translate(self.translator, protected_texts, target_lang, source_lang)
        if len(translated) != len(protected_texts):
            raise TranslationError(
                f"{self.name} returned {len(translated)} translations "
                f"for {len(protected_texts)} inputs"
            )
        return [_restore_tokens(t, tokens) for t, tokens in zip(translated, all_tokens)]
