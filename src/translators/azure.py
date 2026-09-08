import os
import time
import requests
from .base import BaseTranslator, TranslationError, chunk_texts
from .langs import PROVIDER_CODES, SUPPORTED

_MAX_RETRIES = 4
_BASE_DELAY  = 1.0


class AzureTranslator(BaseTranslator):
    """Translator strategy using Azure AI Translator API."""

    name = "azure"
    lang_codes = PROVIDER_CODES["azure"]
    supported  = SUPPORTED["azure"]

    def __init__(self, api_key: str | None = None, region: str | None = None):
        self.api_key = api_key or os.getenv("AZURE_TRANSLATOR_KEY", "")
        self.region = region or os.getenv("AZURE_TRANSLATOR_REGION", "")
        if not self.api_key:
            raise TranslationError("AZURE_TRANSLATOR_KEY not found in .env")

        self.translate_url = "https://api.cognitive.microsofttranslator.com/translate"
        self.max_batch_size = 100
        # Azure rechaza con 400 cualquier peticion de mas de 50.000 caracteres; 45.000
        # deja margen. Contar solo elementos dejaba pasar peticiones de 60.000.
        self.max_batch_chars = 45_000

    def api_lang(self, code: str) -> str:
        """Como base, pero en minusculas: Azure espera los codigos en minuscula."""
        return self.lang_codes.get(code.upper(), code.lower())

    def _post_with_retry(self, params: dict, payload: list, headers: dict) -> list:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    self.translate_url, params=params, json=payload,
                    headers=headers, timeout=60,
                )
                if resp.status_code == 403:
                    msg = "Azure API Error (403). Check your tier quota or valid region."
                    if "out of call volume quota" in resp.text.lower():
                        msg += " Quota exceeded."
                    raise TranslationError(msg)
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < _MAX_RETRIES - 1:
                        retry_after = int(resp.headers.get("Retry-After", _BASE_DELAY * (2 ** attempt)))
                        time.sleep(retry_after)
                        continue
                resp.raise_for_status()
                return [item["translations"][0]["text"] for item in resp.json()]
            except requests.exceptions.RequestException as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BASE_DELAY * (2 ** attempt))
                    continue
                detail = ""
                if hasattr(e, "response") and e.response is not None:
                    detail = f" — {e.response.text}"
                raise TranslationError(f"Azure API request failed: {e}{detail}") from e
        raise TranslationError("Azure API: max retries exceeded")

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        if not texts:
            return []

        headers = {"Ocp-Apim-Subscription-Key": self.api_key, "Content-type": "application/json"}
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        params = {"api-version": "3.0", "to": [self.api_lang(target_lang)]}
        if source_lang:
            params["from"] = self.api_lang(source_lang)

        results = []
        for chunk in chunk_texts(texts, self.max_batch_size, self.max_batch_chars):
            results.extend(self._post_with_retry(params, [{"text": t} for t in chunk], headers))
        return results
