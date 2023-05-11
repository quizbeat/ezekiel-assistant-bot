
def split_into_chunks(text: str, chunk_size: int):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
