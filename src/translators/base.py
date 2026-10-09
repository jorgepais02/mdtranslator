import inspect as _inspect
import random as _random
import re as _re
import threading as _threading
import time as _time
from abc import ABC, abstractmethod

try:
    from ..core.parser import espaciado_cjk, sin_envoltorio
except ImportError:
    from core.parser import espaciado_cjk, sin_envoltorio


_INLINE_CODE_RE    = _re.compile(r'`[^`\n]+`')
_FORMULA_BLOCK_RE  = _re.compile(r'\$\$[\s\S]+?\$\$')
_FORMULA_INLINE_RE = _re.compile(r'\$[^$\n]+\$')
_URL_RE            = _re.compile(r'https?://\S+')
# Lo que quien escribe marca para que no se traduzca: "[C]{.notranslate}", como el
# translate="no" de HTML. Desde fuera no hay forma de saber qué palabra de una línea no
# debe traducirse: la letra de "Respuesta: C" la cambiaba el árabe por "ج", y entonces
# no apuntaba a ninguna opción. Pandoc pinta el span como texto normal.
_NO_TRADUCIR_RE    = _re.compile(r'\[[^\]\n]*\]\{[^}\n]*\.notranslate\b[^}\n]*\}')

# Las siglas que el texto explica entre paréntesis: "Agencia Española de Protección de Datos
# (AEPD)". Con la sigla suelta el traductor la lee como palabra y la cambia —el árabe
# tradujo AEPD por «la Policía»— y quien lee ya tiene el nombre largo al lado. Solo las
# de dos o más mayúsculas: "(Plan)" o "(Madrid)" son palabras que sí hay que traducir.
# Quedan fuera los numerales romanos —"(II)" es la parte de una serie— y las españolas
# que en inglés son otras: RGPD→GDPR, IA→AI, UE→EU, ONU→UN, IVA→VAT. La lista es corta
# a propósito: se amplía cuando aparezca otra, no se adivina.
_SIGLA_ENTRE_PARENTESIS_RE = _re.compile(
    r'\((?!(?:RGPD|IA|UE|ONU|IVA|PYME|LOPD|EEUU|OTAN|[IVXLC]+)\))'
    r'[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*\)')


def _protect_tokens(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []
    def _replace(m: _re.Match) -> str:
        tokens.append(m.group(0))
        return f"⟦{len(tokens)-1}⟧"
    out = _NO_TRADUCIR_RE.sub(_replace, text)
    out = _FORMULA_BLOCK_RE.sub(_replace, out)
    out = _FORMULA_INLINE_RE.sub(_replace, out)
    out = _INLINE_CODE_RE.sub(_replace, out)
    out = _URL_RE.sub(_replace, out)
    # Última, o su marcador quedaría dentro del token de un código, fórmula o URL y la
    # restauración no lo deshace.
    out = _SIGLA_ENTRE_PARENTESIS_RE.sub(_replace, out)
    return out, tokens


def _restore_tokens(text: str, tokens: list[str]) -> str:
    for i, tok in enumerate(tokens):
        text = text.replace(f"⟦{i}⟧", tok)
    return text


# El punto final que el origen no tenía. DeepL se lo pone a lo que le parece una frase y
# no a lo que le parece un rótulo, línea a línea y sin criterio fijo: en el test francés
# del módulo 20 la opción correcta de una pregunta fue la única con punto, y en la
# siguiente fueron dos distractores. Cuatro opciones que en español acaban igual tienen
# que acabar igual traducidas, o la puntuación dice cuál es la buena.
_FIN_DEL_ORIGEN = (".", "。", "!", "?", "…", ":", ";")


def _sin_punto_de_mas(origen: str, traducido: str) -> str:
    fin = traducido.rstrip()
    if origen.rstrip().endswith(_FIN_DEL_ORIGEN) or fin.endswith(("..", "…")):
        return traducido
    return fin[:-1] if fin.endswith((".", "。")) else traducido


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


class TranslationQuotaError(TranslationError):
    """El proveedor no puede traducir *ahora* por cuota o por ritmo.

    `retry_after` son los segundos hasta que tiene sentido volver a intentarlo, y None
    quiere decir que no se sabe (la cuota mensual de DeepL no trae fecha de vuelta).
    Es un TranslationError, asi que quien ya capturaba ese sigue funcionando.
    """

    def __init__(self, mensaje: str, retry_after: float | None = None):
        super().__init__(mensaje)
        self.retry_after = retry_after


# Un proveedor que acaba de decir "no" se deja en pausa para **toda** la ejecucion, no
# para el hilo que lo oyo. Con cuatro hilos y un 429 de Azure, cada uno reintentaba por
# su cuenta con 1+2+4 s de espera —siete segundos, menos de lo que tarda en reponerse—
# y los cuatro volvian a chocar a la vez. Y con la cuota mensual de DeepL agotada, cada
# llamada de cada hilo empezaba pidiendosela otra vez antes de pasar al siguiente.
SIN_FECHA = 24 * 3600     # cuota sin fecha de vuelta: no vuelve en esta ejecucion
MAX_ESPERA = 90           # lo que merece la pena esperar a que vuelva un proveedor

_PAUSAS: dict[str, float] = {}
_PAUSAS_LOCK = _threading.Lock()


def pausar(nombre: str, segundos: float) -> None:
    """Deja `nombre` sin usar durante `segundos`. Nunca acorta una pausa que ya habia."""
    with _PAUSAS_LOCK:
        hasta = _time.monotonic() + segundos
        _PAUSAS[nombre] = max(_PAUSAS.get(nombre, 0.0), hasta)


def en_pausa(nombre: str) -> float:
    """Segundos que le quedan de pausa a `nombre`, o 0. API: float."""
    with _PAUSAS_LOCK:
        return max(0.0, _PAUSAS.get(nombre, 0.0) - _time.monotonic())


def reiniciar_pausas() -> None:
    """Quita todas las pausas. API: nada. Solo para aislar los tests."""
    with _PAUSAS_LOCK:
        _PAUSAS.clear()


# Quien respondio en esta llamada, por hilo: el pipeline pregunta tras traducir un
# documento si alguna parte salio de un proveedor que no recibe el contexto, y asi puede
# avisar de que ese documento merece una lectura. Se anota en CachingTranslator, que esta
# siempre —tambien con un proveedor elegido a mano— y solo cuando el proveedor contesta.
_RESPUESTAS = _threading.local()


def empezar_registro() -> None:
    """Borra lo anotado en este hilo. API: nada."""
    _RESPUESTAS.sin_contexto = []


def anotar_respuesta(traductor: "BaseTranslator") -> None:
    """Anota a `traductor` si no usa contexto. API: nada."""
    if not traductor.usa_contexto:
        lista = getattr(_RESPUESTAS, "sin_contexto", None)
        if lista is not None and traductor.name not in lista:
            lista.append(traductor.name)


def quien_respondio_sin_contexto() -> list[str]:
    """Los proveedores sin contexto que contestaron desde empezar_registro. API: lista."""
    return list(getattr(_RESPUESTAS, "sin_contexto", []))


def dormir(segundos: float) -> None:
    """Duerme en pasos de un segundo, para que Ctrl+C siga cortando."""
    fin = _time.monotonic() + segundos
    while (resto := fin - _time.monotonic()) > 0:
        _time.sleep(min(1.0, resto))


def espera_ante_429(nombre: str, resp, intento: int, base: float = 5.0) -> float:
    """Segundos que dormir tras un 429, dejando al proveedor en pausa para los demas hilos.

    Usa el Retry-After si lo trae (y es un numero: tambien puede ser una fecha) y, si no,
    5, 10, 20 s: menos que eso es menos de lo que tarda la ventana en reponerse.
    """
    try:
        pedida = float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        pedida = None
    espera = min(pedida if pedida is not None else base * 2 ** intento, MAX_ESPERA)
    pausar(nombre, espera)
    return espera


class BaseTranslator(ABC):
    """Abstract base class for all translation providers."""

    name: str = "unknown"
    # Si el proveedor aprovecha `context`. El que no, traduce cada linea a ciegas y su
    # resultado conviene leerlo (ver quien_respondio_sin_contexto).
    usa_contexto: bool = True

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
    """Tries multiple providers in order, falling back on failure.

    Un proveedor sin cuota se salta mientras dure su pausa (ver `pausar`), y si no queda
    ninguno pero alguno vuelve en menos de MAX_ESPERA segundos, espera a que vuelva en
    vez de dar la tarea por fallida: es la diferencia entre un tiron de ritmo y un
    documento sin traducir.
    """

    _RONDAS = 3

    def __init__(self, translators: list[BaseTranslator]):
        if not translators:
            raise ValueError("FallbackTranslator requires at least one translator.")
        self.translators = translators

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None,
                  context: str | None = None) -> list[str]:
        errors: list[str] = []
        for ronda in range(self._RONDAS):
            errors = []
            for t in self.translators:
                resta = en_pausa(t.name)
                if resta > 0:
                    errors.append(f"{type(t).__name__}: no quota right now "
                                  f"(back in {_humano(resta)})")
                    continue
                try:
                    return call_translate(t, texts, target_lang, source_lang, context)
                except TranslationQuotaError as e:
                    pausar(t.name, e.retry_after if e.retry_after is not None else SIN_FECHA)
                    errors.append(f"{type(t).__name__}: {e}")
                except TranslationError as e:
                    errors.append(f"{type(t).__name__}: {e}")
            vuelve = [r for t in self.translators if 0 < (r := en_pausa(t.name)) <= MAX_ESPERA]
            if not vuelve or ronda == self._RONDAS - 1:
                break
            # El azar evita que los hilos que esperaron lo mismo salgan juntos y vuelvan
            # a chocar con la ventana.
            dormir(min(vuelve) + 1 + _random.random() * 3)
        raise TranslationError(
            "All translation providers failed:\n  " + "\n  ".join(errors)
        )


def _humano(segundos: float) -> str:
    return f"{segundos:.0f}s" if segundos < 120 else f"{segundos / 60:.0f} min"


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
        marcas: list[str] = []
        for text in texts:
            interior, marca = sin_envoltorio(text)
            protected, tokens = _protect_tokens(interior)
            protected_texts.append(protected)
            all_tokens.append(tokens)
            marcas.append(marca)
        translated = call_translate(self.translator, protected_texts, target_lang,
                                    source_lang, context)
        if len(translated) != len(protected_texts):
            raise TranslationError(
                f"{self.name} returned {len(translated)} translations "
                f"for {len(protected_texts)} inputs"
            )
        salida = [_sin_punto_de_mas(o, _restore_tokens(espaciado_cjk(t, target_lang), tokens))
                  for o, t, tokens in zip(protected_texts, translated, all_tokens)]
        return [f"{m}{s.strip()}{m}" if m else s for s, m in zip(salida, marcas)]
