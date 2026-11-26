def is_cyrillic(text):
    # Check if any character in the text is Cyrillic (whole Unicode block, incl. ў қ ғ ҳ)
    return any('Ѐ' <= char <= 'ӿ' for char in text)

def is_latin(text):
    # Check if any character in the text is in the Latin Unicode range
    return any('A' <= char <= 'Z' or 'a' <= char <= 'z' for char in text)
