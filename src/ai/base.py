"""
La interfaz de un modelo de IA, el fallback entre varios y la lectura del 429.

Mismo reparto que en src/translators/: aqui viven el ABC y el fallback, y registry.py
compone la cadena. Lo que cambia es la unidad de la lista: alli es el proveedor, aqui
es proveedor:modelo, porque la cuota gratuita de Google se cuenta **por modelo** — el
id del 429 dice GenerateRequestsPerDayPerProjectPer**Model** — y el fallback mas util
de todos resulta ser entre dos modelos del mismo proveedor.

API:
    AIModel                  — ABC: complete(prompt, system="", temperature=0.2) -> str
    AIError / AIQuotaError   — fallo del modelo / fallo por cuota
    FallbackModel(modelos)   — recorre la lista; contesta el primero que puede
    es_cuota(error)          — True si el error es de cuota
    espera_pedida(error)     — segundos que pide un 429, o None si no es cuota
    PISTAS_CUOTA             — lo que se lee como "no queda cuota", aqui y en el aviso
    cambio_de_modelo(modelo) — quien contesto, si no fue el preferido
"""

from abc import ABC, abstractmethod
import math
import re


class AIError(Exception):
    """Un modelo no ha podido contestar."""


class AIQuotaError(AIError):
    """No queda cuota. Su mensaje conserva el 429: el pipeline lo lee para cortar."""

    def __init__(self, mensaje: str, retry_after: float | None = None):
        super().__init__(mensaje)
        self.retry_after = retry_after


# Cuando salta el 429, el propio error dice cuanto falta para que se libere hueco, y
# ese numero baja en cada intento: medido, 59s -> 34s -> 9s. Cada API lo cuenta a su
# manera: Gemini en el JSON del error, los compatibles con OpenAI en la cabecera
# Retry-After y, algunos, solo en la frase del cuerpo.
_RETRY_DELAY_RE = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")
_TRY_AGAIN_RE   = re.compile(r"try again in ([\d.]+)\s*s", re.I)
PISTAS_CUOTA    = ("429", "resource_exhausted", "rate limit", "too many requests")

MAX_ESPERA  = 60          # s: por encima de esto, mejor avisar que colgar el lote
MAX_INTENTOS = 2          # el retryDelay no es una promesa; ver CLAUDE.md §6


def es_cuota(error: Exception) -> bool:
    """True si el error es de cuota y no de otra cosa. API: bool.

    Con un AIError la respuesta la da el tipo, no el texto: el adaptador ya ha mirado
    el codigo HTTP y lo ha clasificado. Adivinarlo del mensaje encima de eso hacia que
    un "503 unavailable, retry after 429 ms" contara como cuota y apagara el
    refinamiento del resto de la ejecucion. La heuristica queda para los errores que
    vienen de fuera (el SDK de Gemini lanza los suyos).
    """
    if isinstance(error, AIError):
        return isinstance(error, AIQuotaError)
    texto = str(error).lower()
    return any(p in texto for p in PISTAS_CUOTA)


def _pedidos_crudos(error: Exception) -> float | None:
    """Los segundos que pide la API, tal cual: sin el +1 ni el tope."""
    pedidos = getattr(error, "retry_after", None)
    if pedidos is not None:
        return float(pedidos)
    m = _RETRY_DELAY_RE.search(str(error)) or _TRY_AGAIN_RE.search(str(error))
    return float(m.group(1)) if m else None


def espera_pedida(error: Exception) -> int | None:
    """Los segundos que hay que dormir ante un 429, o None si no es cuota. API: int|None.

    Un segundo de mas: esperar justo lo que dice la API vuelve a chocar con la ventana.
    `retry_after` guarda siempre lo crudo, para que sumar el +1 dos veces sea imposible.
    """
    if not es_cuota(error):
        return None
    pedidos = _pedidos_crudos(error)
    if pedidos is None:
        return MAX_ESPERA
    return min(math.ceil(pedidos) + 1, MAX_ESPERA)


def sin_pistas_de_cuota(texto: str) -> str:
    """El mismo texto sin las marcas que el pipeline lee como "no queda cuota".

    El corte por cuota del pipeline se decide buscando 429/RESOURCE_EXHAUSTED en el
    aviso, asi que un 503 que mencione un 429 por dentro apagaria el refinamiento de
    toda la ejecucion por un fallo de un solo documento. Solo se aplica a los errores
    que **no** son de cuota: los que si lo son tienen que conservar la marca.
    """
    for pista in PISTAS_CUOTA:
        texto = re.sub(re.escape(pista), "[quota]", texto, flags=re.I)
    return texto


class AIModel(ABC):
    """Un modelo que devuelve texto a partir de un prompt.

    Los tres consumidores (refinado, formateo de .txt y el traductor Gemini) piden lo
    mismo, asi que la interfaz es un solo metodo. Es la firma estable de este paquete,
    igual que translate(texts, target_lang) lo es del otro: un argumento nuevo iria
    opcional y detras.
    """

    def __init__(self, model: str, name: str = "", label: str = "", key_env: str = ""):
        self.model   = model
        self.name    = name or type(self).__name__.lower()
        self.label   = label or self.name          # etiqueta de UI: "Gemini (Google AI)"
        self.key_env = key_env

    @property
    def ref(self) -> str:
        """El identificador que se escribe en la config: proveedor:modelo."""
        return f"{self.name}:{self.model}"

    @property
    def usado(self) -> "AIModel":
        """Quien contesto de verdad. En un modelo suelto, el mismo."""
        return self

    @abstractmethod
    def complete(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        """El texto que devuelve el modelo. Lanza AIError o AIQuotaError."""


class FallbackModel(AIModel):
    """Recorre una lista de modelos: contesta el primero que puede.

    La pasada por la lista **no duerme**: un 429 de Gemini cuesta 0s si el siguiente
    modelo contesta al instante. Solo cuando todos se han quedado sin cuota se lanza
    AIQuotaError, y ahi es el llamador (refiner) quien decide esperar y reintentar la
    lista entera. Al reves —dormir 60s con el primero antes de probar el segundo—
    eran hasta 120s por lote para acabar usando un modelo que estaba libre.

    Una instancia por tarea, como hasta ahora el cliente de Gemini: `usado` guarda
    quien contesto y dos hilos compartiendola se pisarian el dato.
    """

    def __init__(self, modelos: list[AIModel]):
        if not modelos:
            raise AIError("FallbackModel needs at least one model")
        super().__init__(model=modelos[0].model, name="fallback", label="fallback")
        self.modelos    = modelos
        self.preferido  = modelos[0]
        self._usado     = modelos[0]
        self._descartes: list[tuple[AIModel, Exception]] = []

    @property
    def usado(self) -> AIModel:
        return self._usado

    @property
    def ref(self) -> str:
        return self._usado.ref

    @staticmethod
    def _con_ref(m: AIModel, e: Exception) -> str:
        """El fallo con el modelo delante, pero solo si no lo trae ya.

        Los adaptadores escriben su ref en el mensaje, asi que anadirla aqui salia
        doble: "gemini:no-existe: gemini:no-existe: 404 NOT_FOUND". Se sigue anadiendo
        cuando falta, porque aqui tambien cae el error pelado de un adaptador roto.
        """
        texto = str(e)
        return texto if texto.startswith(f"{m.ref}:") else f"{m.ref}: {texto}"

    def complete(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        fallos: list[tuple[AIModel, Exception]] = []
        for m in self.modelos:
            try:
                salida = m.complete(prompt, system=system, temperature=temperature)
            except Exception as e:          # un adaptador roto no debe saltarse la lista
                fallos.append((m, e))
                continue
            self._usado    = m
            self.model     = m.model
            self._descartes = fallos
            return salida

        de_cuota = [(m, e) for m, e in fallos if es_cuota(e)]
        detalle  = "\n  ".join(self._con_ref(m, e) for m, e in fallos)
        if len(de_cuota) == len(fallos):
            # La espera es la mas corta de las que piden: es cuando la lista entera
            # vuelve a tener sentido, no cuando la tiene el ultimo.
            pedidas = [s for s in (_pedidos_crudos(e) for _, e in fallos) if s is not None]
            raise AIQuotaError(
                "429 RESOURCE_EXHAUSTED — no quota left on any model:\n  " + detalle,
                retry_after=min(pedidas) if pedidas else None,
            )
        # Mixto: el aviso no puede llevar la marca de cuota, o un 503 cortaria el
        # refinamiento del resto de la ejecucion. Los de cuota se cuentan, no se citan.
        sueltos = [self._con_ref(m, e) for m, e in fallos if not es_cuota(e)]
        if de_cuota:
            sueltos.append(f"and {len(de_cuota)} more with no quota left")
        raise AIError(sin_pistas_de_cuota("no AI model answered:\n  " + "\n  ".join(sueltos)))


def cambio_de_modelo(modelo: AIModel | None) -> dict | None:
    """Quien contesto, si no fue el preferido. API: dict con used/instead_of/reason.

    Devuelve None cuando contesto el preferido: entonces no hay nada que contar, y la
    pantalla final solo debe hablar del modelo cuando el resultado no sale del que el
    usuario puso primero.
    """
    if not isinstance(modelo, FallbackModel):
        return None
    if modelo.usado is modelo.preferido:
        return None
    caidos = [(m, e) for m, e in modelo._descartes]
    motivo = "no quota"
    for m, e in caidos:
        if m is modelo.preferido:
            motivo = "no quota" if es_cuota(e) else "failed"
            break
    mismo_proveedor = modelo.usado.name == modelo.preferido.name
    corto = (lambda x: x.model) if mismo_proveedor else (lambda x: x.ref)
    return {
        "used":       corto(modelo.usado),
        "instead_of": corto(modelo.preferido),
        "reason":     motivo,
    }
