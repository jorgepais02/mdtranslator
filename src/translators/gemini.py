import os
import re
from .base import BaseTranslator, TranslationError

_NUM_PREFIX_RE = re.compile(r"^\d+\.\s*")


class GeminiTranslator(BaseTranslator):
    """Translator using Gemini (gemini-2.5-flash) with a technical translation prompt."""

    name = "gemini"
    max_batch_size = 30

    _LANG_NAMES = {
        "EN": "English", "FR": "French", "AR": "Arabic", "ZH": "Chinese (Simplified)",
        "DE": "German", "IT": "Italian", "PT": "Portuguese", "RU": "Russian",
        "JA": "Japanese", "KO": "Korean", "HE": "Hebrew", "FA": "Persian",
        "UR": "Urdu", "ES": "Spanish", "NL": "Dutch", "PL": "Polish",
    }
    _PROMPT_TMPL = (
        "You are a professional technical translator specialized in cybersecurity and computer science.\n"
        "Translate each line of the following numbered list to {lang_name}.\n"
        "Rules:\n"
        "- Return ONLY the translated lines, one per line, same count as input\n"
        "- Preserve Markdown formatting\n"
        "- Do NOT translate inline code spans (text between backticks)\n"
        "- Do NOT translate acronyms like API, RSA, SQL, HTTP, DNS, IP\n"
        "- Use correct cybersecurity terminology natural in {lang_name}\n"
        "- No explanations, no extra text\n\n"
        "Lines to translate:\n{numbered}"
    )

    def __init__(self, api_key: str | None = None):
        from google import genai
        from google.genai import types as _types
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not self._api_key:
            raise TranslationError("GEMINI_API_KEY not found in .env")
        self._client = genai.Client(api_key=self._api_key)
        self._types = _types

    def translate(self, texts: list[str], target_lang: str) -> list[str]:
        if not texts:
            return []
        lang_name = self._LANG_NAMES.get(target_lang.upper().split("-")[0], target_lang)
        results: list[str] = []

        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i: i + self.max_batch_size]
            numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(chunk))
            prompt = self._PROMPT_TMPL.format(lang_name=lang_name, numbered=numbered)
            try:
                response = self._client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                lines = [l.strip() for l in response.text.strip().splitlines() if l.strip()]
                # If Gemini added commentary or blank lines, try keeping only numbered lines
                if len(lines) != len(chunk):
                    numbered = [l for l in lines if _NUM_PREFIX_RE.match(l)]
                    if len(numbered) == len(chunk):
                        lines = numbered
                cleaned = [_NUM_PREFIX_RE.sub("", l) for l in lines]
                if len(cleaned) != len(chunk):
                    raise TranslationError(f"Gemini returned {len(cleaned)} lines for {len(chunk)} inputs")
                results.extend(cleaned)
            except TranslationError:
                raise
            except Exception as e:
                raise TranslationError(f"Gemini API request failed: {e}") from e

        return results
