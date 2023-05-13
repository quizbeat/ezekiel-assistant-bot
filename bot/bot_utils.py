
def split_into_chunks(text: str, chunk_size: int):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def detect_language(text: str) -> str:
    russian_chars = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    english_chars = set("abcdefghijklmnopqrstuvwxyz")

    text_chars = set(text.lower())

    n_russian_chars_in_text = len(text_chars.intersection(russian_chars))
    n_english_chars_in_text = len(text_chars.intersection(english_chars))

    if n_russian_chars_in_text > n_english_chars_in_text:
        return "ru"
    else:
        return "en"
