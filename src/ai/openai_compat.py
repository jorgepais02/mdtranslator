"""
Un solo adaptador para todo lo que habla el dialecto de OpenAI: /v1/chat/completions.

Groq y Cerebras lo exponen, asi que los dos salen de esta clase con otra base_url, y
por eso "que el usuario meta el modelo que quiera" sale casi gratis: es una fila mas
en el registro. Con requests y sin dependencias nuevas, como ya hace translators/azure.py.

API:
    OpenAICompatModel(base_url, model, name=…, label=…, key_env=…) -> AIModel
"""

import os

import requests

from .base import AIError, AIModel, AIQuotaError, sin_pistas_de_cuota

TIMEOUT = 120          # s: un lote de 25 lineas de refinado tarda ~20s; 120 es el techo


class OpenAICompatModel(AIModel):
    def __init__(self, base_url: str, model: str, name: str = "",
                 label: str = "", key_env: str = ""):
        super().__init__(model=model, name=name, label=label, key_env=key_env)
        self.base_url = base_url.rstrip("/")
        clave = os.getenv(key_env, "").strip() if key_env else ""
        if not clave:
            raise AIError(f"{key_env or 'API key'} not set")
        self._clave = clave

    def complete(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        mensajes = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._clave}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "messages": mensajes,
                      "temperature": temperature},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            raise AIError(sin_pistas_de_cuota(f"{self.ref}: request failed: {e}")) from e

        if r.status_code == 429:
            # La espera viaja en la cabecera; si no la manda, el cuerpo suele traer la
            # frase ("try again in 7.5s") y de eso ya se encarga espera_pedida().
            cabecera = r.headers.get("Retry-After")
            try:
                espera = float(cabecera) if cabecera else None
            except ValueError:
                espera = None
            raise AIQuotaError(f"{self.ref}: 429 {_cuerpo(r)}", espera)
        if r.status_code >= 400:
            raise AIError(sin_pistas_de_cuota(
                f"{self.ref}: HTTP {r.status_code} {_cuerpo(r)}"))

        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise AIError(f"{self.ref}: unexpected response: {_cuerpo(r)}") from e

    def modelos_disponibles(self) -> list[str]:
        """Los ids que la API acepta hoy. API: lista de ids (puede lanzar AIError).

        Existe porque la lista de modelos y lo que de verdad contesta no son lo mismo:
        gemini-2.5-flash-lite sale en el listado de Google y devuelve 404 ("no longer
        available to new users"). Con esto el id por defecto se comprueba en un comando
        en vez de a base de fe.
        """
        try:
            r = requests.get(f"{self.base_url}/models",
                             headers={"Authorization": f"Bearer {self._clave}"},
                             timeout=30)
        except requests.RequestException as e:
            raise AIError(f"{self.name}: request failed: {e}") from e
        if r.status_code >= 400:
            raise AIError(f"{self.name}: HTTP {r.status_code} {_cuerpo(r)}")
        return [m.get("id", "") for m in (r.json().get("data") or [])]


def _cuerpo(r) -> str:
    """El cuerpo del error, recortado: un HTML de 40 KB no cabe en la tabla final."""
    return (r.text or "").strip().replace("\n", " ")[:200]
