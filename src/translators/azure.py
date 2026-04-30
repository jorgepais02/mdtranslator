import os
import time
import requests
from .base import BaseTranslator, TranslationError

_MAX_RETRIES = 4
_BASE_DELAY  = 1.0


class AzureTranslator(BaseTranslator):
    """Translator strategy using Azure AI Translator API."""

    name = "azure"

    def __init__(self, api_key: str | None = None, region: str | None = None):
        self.api_key = api_key or os.getenv("AZURE_TRANSLATOR_KEY", "")
        self.region = region or os.getenv("AZURE_TRANSLATOR_REGION", "")
        if not self.api_key:
            raise TranslationError("AZURE_TRANSLATOR_KEY not found in .env")

        self.translate_url = "https://api.cognitive.microsofttranslator.com/translate"
        self.max_batch_size = 100

    def _map_lang_code(self, lang: str) -> str:
        if lang.upper() == "EN-GB":
            return "en-GB"
        if lang.upper() == "ZH":
            return "zh-Hans"
        return lang.lower()

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

    def translate(self, texts: list[str], target_lang: str) -> list[str]:
        if not texts:
            return []

        headers = {"Ocp-Apim-Subscription-Key": self.api_key, "Content-type": "application/json"}
        if self.region:
            headers["Ocp-Apim-Subscription-Region"] = self.region

        params  = {"api-version": "3.0", "to": [self._map_lang_code(target_lang)]}
        results = []
        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i: i + self.max_batch_size]
            results.extend(self._post_with_retry(params, [{"text": t} for t in chunk], headers))
        return results
