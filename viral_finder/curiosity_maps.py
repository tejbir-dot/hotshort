"""Language-specific curiosity lexicons.
Extend by adding new language keys mapping to lists of phrases.
"""
CURIOSITY_MAPS = {
    "en": ["why", "secret", "mistake", "nobody tells", "truth", "you won't believe", "what if"],
    "hi": ["sach", "raaz", "galti", "koi nahi batata", "aap nahin jaanenge"],
    "es": ["verdad", "secreto", "error", "nadie dice", "no creerás"],
}

def get_map(lang: str):
    return CURIOSITY_MAPS.get(lang, CURIOSITY_MAPS.get("en", []))
