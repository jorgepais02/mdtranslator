from .base import BaseTranslator, TranslationError, call_translate
from .cache import TranslationCache


class CachingTranslator(BaseTranslator):
    """Transparent cache wrapper — checks SQLite before calling the provider."""

    def __init__(self, translator: BaseTranslator, cache: TranslationCache):
        self.translator = translator
        self.cache = cache
        self.name = translator.name

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        # La clave de cache no incluye source_lang a proposito: el mismo texto con el
        # mismo destino da la misma traduccion, y anadirlo invalidaria todo lo cacheado.
        results: list[str | None] = []
        miss_idx: list[int] = []
        miss_texts: list[str] = []

        for i, text in enumerate(texts):
            cached = self.cache.get(text, target_lang, self.name)
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)
                miss_idx.append(i)
                miss_texts.append(text)

        if miss_texts:
            translated = call_translate(self.translator, miss_texts, target_lang, source_lang)
            # A short response would silently leave None holes that reach the DOCX
            # as the literal text "None"; fail instead so the next provider runs.
            if len(translated) != len(miss_texts):
                raise TranslationError(
                    f"{self.name} returned {len(translated)} translations "
                    f"for {len(miss_texts)} inputs"
                )
            fresh = []
            for idx, src, tgt in zip(miss_idx, miss_texts, translated):
                if not isinstance(tgt, str):
                    raise TranslationError(f"{self.name} returned a non-text translation")
                fresh.append((src, tgt))
                results[idx] = tgt
            self.cache.set_many(fresh, target_lang, self.name)

        return results  # type: ignore[return-value]
