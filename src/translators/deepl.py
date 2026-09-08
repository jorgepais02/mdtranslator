import os
import time
import requests
from .base import BaseTranslator, TranslationError, chunk_texts
from .langs import PROVIDER_CODES, SUPPORTED

_MAX_RETRIES = 3
_BASE_DELAY  = 1.0


class DeepLTranslator(BaseTranslator):
    """Translator strategy using DeepL API."""

    name = "deepl"
    lang_codes = PROVIDER_CODES["deepl"]
    supported  = SUPPORTED["deepl"]

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("DEEPL_API_KEY", "")
        if not self.api_key:
            raise TranslationError("DEEPL_API_KEY not found in .env")

        # Keys ending in ":fx" belong to the free plan → api-free.deepl.com
        if self.api_key.endswith(":fx"):
            self.base_url = "https://api-free.deepl.com"
        else:
            self.base_url = "https://api.deepl.com"

        self.translate_url = f"{self.base_url}/v2/translate"
        self.max_batch_size = 50
        # El limite real del endpoint es 128 KiB por peticion; 100.000 deja margen
        # para la cabecera JSON y el escapado.
        self.max_batch_chars = 100_000

    def _post_with_retry(self, payload: dict, headers: dict) -> list[str]:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(self.translate_url, json=payload, headers=headers, timeout=60)
                if resp.status_code == 456:
                    raise TranslationError("DeepL quota exceeded.")
                if resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < _MAX_RETRIES - 1:
                        delay = int(resp.headers.get("Retry-After", _BASE_DELAY * (2 ** attempt)))
                        time.sleep(delay)
                        continue
                resp.raise_for_status()
                return [item["text"] for item in resp.json()["translations"]]
            except TranslationError:
                raise
            except requests.exceptions.RequestException as e:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BASE_DELAY * (2 ** attempt))
                    continue
                raise TranslationError(f"DeepL API request failed: {e}") from e
        raise TranslationError("DeepL API: max retries exceeded")

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        if not texts:
            return []

        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        results: list[str] = []

        for chunk in chunk_texts(texts, self.max_batch_size, self.max_batch_chars):
            # api_lang, no target_lang a pelo: DeepL ya no admite EN ni PT como
            # destino salvo por compatibilidad. Ver translators/langs.py.
            payload = {"text": chunk, "target_lang": self.api_lang(target_lang)}
            if source_lang:
                payload["source_lang"] = source_lang.split("-")[0].upper()
            results.extend(self._post_with_retry(payload, headers))

        return results
