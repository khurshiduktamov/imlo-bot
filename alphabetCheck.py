def is_cyrillic(text):
    # Check if any character in the text is in the Cyrillic Unicode range
    return any('А' <= char <= 'я' or 'Ё' <= char <= 'ё' for char in text)

def is_latin(text):
    # Check if any character in the text is in the Latin Unicode range
    return any('A' <= char <= 'Z' or 'a' <= char <= 'z' for char in text)