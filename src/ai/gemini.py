"""
Gemini como AIModel. Unico proveedor con clase propia: tiene SDK propio.

API:
    GeminiModel(model="gemini-2.5-flash") -> AIModel
"""

import os

from google import genai
from google.genai import types

from .base import AIError, AIModel, AIQuotaError, es_cuota, espera_pedida, sin_pistas_de_cuota

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiModel(AIModel):
    def __init__(self, model: str = DEFAULT_MODEL, name: str = "gemini",
                 label: str = "Gemini (Google AI)", key_env: str = "GEMINI_API_KEY"):
        super().__init__(model=model, name=name, label=label, key_env=key_env)
        clave = os.getenv(key_env, "").strip()
        if not clave:
            raise AIError(f"{key_env} not set")
        try:
            self._client = genai.Client(api_key=clave)
        except Exception as e:
            raise AIError(f"gemini init failed: {e}") from e

    def complete(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system or None,
                    temperature=temperature,
                    # Aqui solo se pide texto. Sin desactivarlo, el SDK entra en la
                    # rama de "automatic function calling" y escribe un warning por
                    # ejecucion que en la vista Live se mete por medio de la tabla.
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True),
                ),
            )
        except Exception as e:
            if es_cuota(e):
                raise AIQuotaError(f"{self.ref}: {e}", espera_pedida(e)) from e
            raise AIError(sin_pistas_de_cuota(f"{self.ref}: {e}")) from e
        return resp.text or ""

    def modelos_disponibles(self) -> list[str]:
        """Los ids que la API acepta hoy. API: lista de ids (puede lanzar AIError).

        Ojo: el listado no es lo que de verdad contesta. gemini-2.5-flash-lite sale
        aqui y devuelve 404 ("no longer available to new users"), asi que esto sirve
        para descubrir nombres, no para dar por bueno un id.
        """
        try:
            return [m.name.removeprefix("models/") for m in self._client.models.list()]
        except Exception as e:
            raise AIError(f"{self.name}: {e}") from e
