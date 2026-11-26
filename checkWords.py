import re
from difflib import get_close_matches
from functools import lru_cache

from uzwords import words

# Common words the dictionary is missing: pronouns and place names
EXTRA_WORDS = """
биз улар ўзбекистон тошкент самарқанд бухоро хива андижон наманган фарғона қашқадарё
сурхондарё жиззах сирдарё навоий хоразм қорақалпоғистон нукус термиз қарши гулистон урганч
марғилон қўқон шаҳрисабз россия қозоғистон қирғизистон тожикистон туркманистон
""".split()
WORD_SET = frozenset(words) | frozenset(EXTRA_WORDS)

# A word: letters, optionally joined by apostrophes (oʻ, maʼno) or hyphens (ich-et)
WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼʻ‘`\-][^\W\d_]+)*")


def tokenize(text):
    """Yield (start, end, word) for every word in text, skipping punctuation and numbers."""
    for m in WORD_RE.finditer(text):
        yield m.start(), m.end(), m.group(0)


def checkWord(word, words=words):
    """Check one Cyrillic word. Returns {'available': bool, 'matches': suggestions}."""
    word = word.lower()
    if is_known(word):
        return {'available': True, 'matches': word}
    return {'available': False, 'matches': set(suggest(word))}


VOWELS = set('аеёиоуэюяў')

# Common Uzbek endings. The dictionary only holds base forms (китоб, оширмоқ), so an
# unknown word is accepted if stripping endings leaves a dictionary word.
# Condition: 'V' = only after a vowel, 'C' = only after a consonant, None = anywhere.
NOUN_SUFFIXES = [
    # plural, possessive, case
    ('лар', None), ('нинг', None), ('ни', None), ('га', None), ('ка', None), ('қа', None),
    ('да', None), ('та', None), ('дан', None), ('тан', None), ('гача', None), ('ники', None),
    ('даги', None), ('таги', None), ('ги', None), ('ки', None), ('қи', None),
    ('им', 'C'), ('м', 'V'), ('инг', 'C'), ('нг', 'V'), ('и', 'C'), ('си', 'V'),
    ('имиз', 'C'), ('миз', None), ('ингиз', 'C'), ('нгиз', 'V'),
    # derivation, particles, predicate
    ('лик', None), ('ли', None), ('сиз', None), ('чи', None), ('чилик', None), ('дош', None),
    ('гина', None), ('кина', None), ('қина', None), ('ча', None), ('роқ', None), ('дек', None),
    ('дай', None), ('ми', None), ('дир', None), ('ман', None), ('сан', None), ('мас', None),
    ('ла', None),  # noun -> verb: иш -> ишла(моқ)
]
# These only attach to verb stems: what is left must be a verb (stem + моқ is in the dictionary)
VERB_SUFFIXES = [
    ('моқда', None), ('моқчи', None), ('япти', None), ('яп', None), ('ди', None),
    ('дим', None), ('динг', None), ('дик', None), ('ган', None), ('кан', None), ('қан', None),
    ('ар', 'C'), ('р', 'V'), ('ади', 'C'), ('йди', 'V'), ('аётган', 'C'), ('ётган', 'V'),
    ('иш', 'C'), ('ш', 'V'), ('ил', 'C'), ('л', 'V'), ('ин', 'C'), ('н', 'V'), ('тир', None),
    ('ир', 'C'), ('из', 'C'), ('гиз', None), ('киз', None), ('қиз', None), ('т', 'V'),
    ('иб', 'C'), ('б', 'V'), ('са', None), ('сам', None), ('санг', None),
    ('сак', None), ('гач', None), ('кач', None), ('қач', None), ('ай', 'C'), ('й', 'V'),
    ('син', None), ('ма', None), ('а', 'C'), ('гани', None),
    ('увчи', 'C'), ('вчи', 'V'), ('ув', 'C'),
]
SUFFIXES = sorted([(s, c, False) for s, c in NOUN_SUFFIXES] + [(s, c, True) for s, c in VERB_SUFFIXES],
                  key=lambda x: -len(x[0]))


def is_known(word):
    """Dictionary lookup for a lowercase Cyrillic word, allowing for common endings."""
    if word in WORD_SET:
        return True
    # hyphenated compound: fine if every part is a known word
    if '-' in word:
        return all(is_known(part) for part in word.split('-') if part)
    return _known_stem(word, 4, False)


def _in_dict(stem, verb):
    return stem + 'моқ' in WORD_SET if verb else stem in WORD_SET or stem + 'моқ' in WORD_SET


def _stem_ok(stem, verb):
    if _in_dict(stem, verb):
        return True
    # к/қ soften before a vowel ending: келажак -> келажаги, қишлоқ -> қишлоғи
    if stem[-1] == 'г' and _in_dict(stem[:-1] + 'к', verb):
        return True
    if stem[-1] == 'ғ' and _in_dict(stem[:-1] + 'қ', verb):
        return True
    # dropped vowel: шаҳар -> шаҳри, ўғил -> ўғли
    if not verb and len(stem) >= 3 and stem[-1] not in VOWELS and stem[-2] not in VOWELS:
        return any(stem[:-1] + v + stem[-1] in WORD_SET for v in 'аиу')
    return False


@lru_cache(maxsize=200_000)
def _known_stem(word, depth, verb):
    """verb=True: a verb ending was already stripped, so the stem must be a verb."""
    if depth == 0:
        return False
    for suffix, cond, verb_suffix in SUFFIXES:
        if not word.endswith(suffix) or len(word) - len(suffix) < 2:
            continue
        stem = word[:-len(suffix)]
        if cond == 'V' and stem[-1] not in VOWELS or cond == 'C' and stem[-1] in VOWELS:
            continue
        need_verb = verb or verb_suffix
        if _stem_ok(stem, need_verb) or _known_stem(stem, depth - 1, need_verb):
            return True
    return False


@lru_cache(maxsize=100_000)
def suggest(word):
    """Close dictionary matches for a lowercase Cyrillic word (slow: ~30 ms)."""
    matches = list(get_close_matches(word, words))
    if 'ҳ' in word:
        matches += get_close_matches(word.replace('ҳ', 'х'), words)
    elif 'х' in word:
        matches += get_close_matches(word.replace('х', 'ҳ'), words)
    return tuple(dict.fromkeys(matches))  # dedupe, keep order


if __name__ == '__main__':
    print(checkWord('срорт'))
    print(checkWord('фаросат'))
    print(checkWord('халк'))
    print(checkWord('мошина'))
    print(checkWord('дабдаба'))
    print(checkWord('хаёт'))
