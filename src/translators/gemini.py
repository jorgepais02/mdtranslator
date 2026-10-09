import os
import re
from .langs import PROVIDER_CODES, SUPPORTED
from .base import (BaseTranslator, TranslationError, TranslationQuotaError, SIN_FECHA,
                   en_pausa, pausar)

_NUM_PREFIX_RE = re.compile(r"^\d+\.\s*")


class GeminiTranslator(BaseTranslator):
    """Translator using Gemini with a technical translation prompt.

    Los modelos los dice el registro de src/ai/. Cuando uno se queda sin cuota pasa al
    siguiente de la misma cuenta —el cupo gratuito se cuenta por modelo, 20 peticiones
    al dia—, y solo por cuota: un fallo de otra clase no cambia de modelo. Sigue siendo
    Gemini; lo que no hace es caer en Groq o Cerebras, que no traducen.
    """

    name = "gemini"
    lang_codes = PROVIDER_CODES["gemini"]
    supported  = SUPPORTED["gemini"]
    key_env    = "GEMINI_API_KEY"
    signup     = "https://aistudio.google.com/apikey"
    free       = "20 requests/day per model (measured)"
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

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from google import genai
        from google.genai import types as _types
        # Perezoso como el del SDK: saber quien tiene clave no deberia arrastrar el
        # registro de modelos ni google.genai.
        try:
            from ..ai.registry import modelos_de
        except ImportError:
            from ai.registry import modelos_de
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not self._api_key:
            raise TranslationError("GEMINI_API_KEY not found in .env")
        self._client = genai.Client(api_key=self._api_key)
        self._types = _types
        self._models = [model] if model else modelos_de("gemini")

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None,
                  context: str | None = None) -> list[str]:
        if not texts:
            return []
        lang_name = self._LANG_NAMES.get(target_lang.upper().split("-")[0], target_lang)
        src_name  = (self._LANG_NAMES.get(source_lang.upper().split("-")[0], source_lang)
                     if source_lang else None)
        results: list[str] = []

        for i in range(0, len(texts), self.max_batch_size):
            chunk = texts[i: i + self.max_batch_size]
            numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(chunk))
            prompt = self._PROMPT_TMPL.format(lang_name=lang_name, numbered=numbered)
            # Aqui el contexto es una linea del prompt, no un parametro de la API: es
            # lo mismo que hace DeepL con su `context`, y sirve para lo mismo —elegir
            # la acepcion del modulo y no la del español general—.
            if context:
                prompt = (f"These lines come from academic notes about: {context}\n"
                          f"Use that to disambiguate terms. Do not translate this line.\n"
                          + prompt)
            if src_name:
                prompt = f"The source text is written in {src_name}.\n" + prompt
            try:
                response = self._generar(prompt)
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

    def _generar(self, prompt: str):
        """La respuesta del primer modelo con cuota. Si no queda ninguno, TranslationQuotaError."""
        try:
            from ..ai.base import es_cuota, segundos_pedidos
        except ImportError:
            from ai.base import es_cuota, segundos_pedidos
        ultimo: Exception | None = None
        for modelo in self._models:
            clave = f"gemini:{modelo}"
            if en_pausa(clave) > 0:
                continue
            try:
                return self._client.models.generate_content(
                    model=modelo, contents=prompt,
                    # Ver ai/gemini.py: sin esto el SDK avisa por stderr en cada
                    # ejecucion y el aviso cae encima de la vista Live.
                    config=self._types.GenerateContentConfig(
                        automatic_function_calling=(
                            self._types.AutomaticFunctionCallingConfig(disable=True))))
            except Exception as e:
                if not es_cuota(e):
                    raise
                # Un 429 diario trae retryDelay de ~25 min: ese modelo no vuelve en esta
                # ejecucion y no merece otra peticion. Sin numero, un minuto.
                pausar(clave, segundos_pedidos(e) or 60)
                ultimo = e
        restan = [r for m in self._models if (r := en_pausa(f"gemini:{m}")) > 0]
        raise TranslationQuotaError(
            f"Gemini API request failed: 429 no quota left on {len(self._models)} "
            f"model(s)" + (f" — {ultimo}" if ultimo else ""),
            retry_after=min(restan) if restan else SIN_FECHA)
