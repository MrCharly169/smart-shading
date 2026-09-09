"""Native per-client flow presentation without a server language decision.

Dynamic summaries contain measured values and user names. Supply both reviewed
versions to HA; the native translation for the viewing user selects its copy.
No profile, request, global configuration or shared entity state is modified.
"""
from functools import wraps


def bilingual_placeholders(function):
    """Produce paired placeholders from a pure summary builder, synchronously."""
    @wraps(function)
    def render(self, *args, **kwargs):
        previous = getattr(self, "_copy_language", "en")
        outputs = {}
        try:
            for language in ("en", "de"):
                self._copy_language = language
                outputs[language] = function(self, *args, **kwargs)
        finally:
            self._copy_language = previous
        english = outputs["en"]
        german = outputs["de"]
        is_tuple = isinstance(english, tuple)
        en_values = english[0] if is_tuple else english
        de_values = german[0] if is_tuple else german
        result = dict(en_values)
        for key in en_values:
            # Nested paired summaries already contain both reviewed versions.
            if key.endswith(("__en", "__de")):
                continue
            result[f"{key}__en"] = en_values[key]
            result[f"{key}__de"] = de_values[key]
        return (result, english[1]) if is_tuple else result
    return render
