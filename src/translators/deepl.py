import os
import time
import requests
from .base import BaseTranslator, TranslationError

_MAX_RETRIES = 3
_BASE_DELAY  = 1.0


class DeepLTranslator(BaseTranslator):
    """Translator strategy using DeepL API."""

    name = "deepl"

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

    def translate(self, texts: list[str], target_lang: str) -> list[str]:
        if not texts:
            return []

        headers = {
            "Authorization": f"DeepL-Auth-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        results: list[str] = []

        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i: i + self.max_batch_size]
            results.extend(self._post_with_retry({"text": chunk, "target_lang": target_lang}, headers))

        return results
