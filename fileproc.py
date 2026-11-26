"""Converting and spell-checking uploaded .docx / .txt files.

Everything here is synchronous and CPU-bound; the bot runs it in a worker thread.
"""
import copy
import io
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from alphabetCheck import is_cyrillic
from checkWords import is_known, suggest, tokenize
from translitarate import convert, is_new_latin, protected_spans

# Above this many distinct misspelled words we still mark them, but stop looking up
# suggestions (each lookup takes ~20 ms here, ~60 ms on the alwaysdata server).
MAX_SUGGESTION_LOOKUPS = 300
# Words per file; protects the small server from huge uploads.
MAX_WORDS = 100_000
# Total unpacked size of a .docx (a normal 100k-word document is ~20 MB unpacked)
MAX_UNPACKED_DOCX = 60 * 1024 * 1024

W_P, W_T, W_R, W_RPR = qn('w:p'), qn('w:t'), qn('w:r'), qn('w:rPr')
# Elements that sit between words inside a run: they separate words but are never rewritten
SEPARATORS = {qn('w:tab'): '\t', qn('w:br'): '\n', qn('w:cr'): '\n', qn('w:noBreakHyphen'): '-'}
W_TXBX = qn('w:txbxContent')
XML_SPACE = qn('xml:space')


class FileError(Exception):
    """A problem with the user's file that we can explain to them (message in old Latin)."""


# ---------------------------------------------------------------- helpers

def decode_txt(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise FileError("Faylni oʻqib boʻlmadi: matn kodirovkasi notanish. UTF-8 da saqlab qayta yuboring.")


def open_docx(data):
    # A .docx is a zip: refuse "zip bombs" (tiny upload, gigabytes once unpacked) before parsing
    try:
        unpacked = sum(i.file_size for i in zipfile.ZipFile(io.BytesIO(data)).infolist())
    except (zipfile.BadZipFile, ValueError):
        unpacked = 0  # not a zip at all: Document() below reports it properly
    if unpacked > MAX_UNPACKED_DOCX:
        raise FileError("Fayl juda katta. Kichikroq fayl yuboring.")
    try:
        return Document(io.BytesIO(data))
    except Exception:
        raise FileError("Faylni ochib boʻlmadi. U haqiqiy .docx (Word) fayl ekanini tekshiring. "
                        "Eski .doc formatini Wordda .docx qilib saqlab yuboring.")


def save_docx(doc):
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _xml_parts(doc):
    """Main document plus headers, footers, footnotes and endnotes."""
    seen = set()
    for part in doc.part.package.iter_parts():
        element = getattr(part, 'element', None)
        if element is None or id(part) in seen:
            continue
        name = str(part.partname)
        if name == '/word/document.xml' or any(k in name for k in ('header', 'footer', 'footnotes', 'endnotes')):
            seen.add(id(part))
            yield element


def _paragraphs(root):
    for p in root.iter(W_P):
        nodes = _paragraph_nodes(p)
        if any(n.tag == W_T for n in nodes):
            yield p, nodes


def _paragraph_nodes(p):
    """Text nodes and separators (tabs, breaks) of this paragraph, in order, excluding those
    of text boxes nested inside it."""
    return [n for n in p.iter(W_T, *SEPARATORS) if _owner_paragraph(n) is p]


def node_text(n):
    return SEPARATORS[n.tag] if n.tag in SEPARATORS else (n.text or '')


def _paragraph_text(nodes):
    return ''.join(node_text(n) for n in nodes)


def _owner_paragraph(el):
    el = el.getparent()
    while el is not None and el.tag != W_P:
        el = el.getparent()
    return el


def _inside_textbox(el):
    el = el.getparent()
    while el is not None:
        if el.tag == W_TXBX:
            return True
        el = el.getparent()
    return False


def words_outside_links(text):
    """tokenize(text) minus the words that are part of a link, email or @mention."""
    spans = protected_spans(text)
    for start, end, word in tokenize(text):
        if not any(s <= start < e for s, e in spans):
            yield start, end, word


def _count_words(texts):
    n = sum(1 for t in texts for _ in tokenize(t))
    if n > MAX_WORDS:
        raise FileError(f"Fayl juda katta: {n} ta soʻz. Hozircha {MAX_WORDS} tagacha soʻzli fayllar qabul qilinadi.")
    return n


# ---------------------------------------------------------------- conversion

def _word_converter(target, new_alphabet):
    @lru_cache(maxsize=None)
    def conv(word):
        return convert(word, target, new_alphabet)
    return conv


def _rewrite_paragraph(nodes, fn):
    """Apply fn to every word of a paragraph whose text is spread over several w:t nodes.
    A converted word is written into the node where it starts, so it keeps that run's formatting."""
    texts = [node_text(n) for n in nodes]
    full = ''.join(texts)
    owner = [i for i, t in enumerate(texts) for _ in t]
    out = [[] for _ in nodes]
    pos = 0
    for start, end, word in words_outside_links(full):
        for k in range(pos, start):
            out[owner[k]].append(full[k])
        new = fn(word)
        if new == word:
            for k in range(start, end):
                out[owner[k]].append(full[k])
        else:
            out[owner[start]].append(new)
        pos = end
    for k in range(pos, len(full)):
        out[owner[k]].append(full[k])
    for node, parts in zip(nodes, out):
        if node.tag != W_T:
            continue  # separators never change (words never include tabs/breaks)
        text = ''.join(parts)
        if text != (node.text or ''):
            node.text = text
            node.set(XML_SPACE, 'preserve')


def convert_docx(data, target):
    """Return the .docx converted to target ('cyrillic', 'latin_new', 'latin_old')."""
    doc = open_docx(data)
    paragraphs = [(p, nodes) for root in _xml_parts(doc) for p, nodes in _paragraphs(root)]
    all_text = [_paragraph_text(nodes) for _, nodes in paragraphs]
    _count_words(all_text)
    # decide once for the whole document whether its Latin is the new alphabet
    conv = _word_converter(target, is_new_latin(''.join(all_text)))
    for _, nodes in paragraphs:
        _rewrite_paragraph(nodes, conv)
    return save_docx(doc)


def convert_txt(data, target):
    text = decode_txt(data)
    if not text.strip():
        raise FileError("Faylda matn topilmadi.")
    _count_words([text])
    return convert(text, target).encode('utf-8')


# ---------------------------------------------------------------- spell check

@dataclass
class SpellReport:
    total_words: int = 0
    errors: int = 0                                      # misspelled occurrences
    unique: dict = field(default_factory=dict)           # word (lower, as written) -> suggestions
    lines: dict = field(default_factory=dict)            # word -> list of line numbers (txt only)
    truncated: bool = False                              # suggestions skipped for some words


class _Checker:
    """Checks words written in any alphabet; remembers results per distinct word."""

    def __init__(self, new_alphabet, latin_variant):
        self.new_alphabet = new_alphabet
        self.latin_target = 'latin_new' if latin_variant == 'new' else 'latin_old'
        self.cache = {}
        self.lookups = 0
        self.truncated = False

    def check(self, word):
        """None if the word is fine, otherwise a tuple of suggestions (may be empty)."""
        key = word.lower()
        if key in self.cache:
            return self.cache[key]
        cyrillic = is_cyrillic(word)
        cyr = key if cyrillic else convert(key, 'cyrillic', self.new_alphabet)
        if is_known(cyr):
            result = None
        elif self.lookups >= MAX_SUGGESTION_LOOKUPS:
            self.truncated = True
            result = ()
        else:
            self.lookups += 1
            result = suggest(cyr)
            if not cyrillic:  # answer in the alphabet the user writes in
                result = tuple(convert(s, self.latin_target) for s in result)
        self.cache[key] = result
        return result


def spellcheck_docx(data, latin_variant, ui=lambda s: s):
    """Highlight misspelled words in yellow; the first occurrence of each gets a Word
    comment with suggestions. Returns (docx bytes, SpellReport)."""
    doc = open_docx(data)
    body = doc.element.body
    paragraphs = list(_paragraphs(body))
    all_text = [_paragraph_text(nodes) for _, nodes in paragraphs]
    report = SpellReport(total_words=_count_words(all_text))
    checker = _Checker(is_new_latin(''.join(all_text)), latin_variant)
    commented = set()

    for (p, nodes), full in zip(paragraphs, all_text):
        bad = []  # (start, end, word, suggestions)
        for start, end, word in words_outside_links(full):
            report_word = word.lower()
            suggestions = checker.check(word)
            if suggestions is None:
                continue
            report.errors += 1
            report.unique.setdefault(report_word, suggestions)
            bad.append((start, end, report_word, suggestions))
        if not bad:
            continue

        paragraph = Paragraph(p, None)
        # one text item per run, so a highlight covers just the word (text is unchanged)
        if _split_multi_runs(p):
            nodes = _paragraph_nodes(p)
        word_runs = _highlight(paragraph, nodes, [(s, e) for s, e, _, _ in bad])
        if _inside_textbox(p):
            continue  # comments inside text boxes upset Word; the highlight is enough
        for (_, _, word, suggestions), runs in zip(bad, word_runs):
            if word in commented or not runs:
                continue
            commented.add(word)
            text = (ui("Taklif: ") + ", ".join(suggestions)) if suggestions else ui("Lugʻatda topilmadi")
            doc.add_comment([runs[0], runs[-1]], text=text, author="Imlo bot", initials="IB")

    report.truncated = checker.truncated
    return save_docx(doc), report


def _split_multi_runs(p):
    """Split runs of this paragraph that hold several items (text + tab + break...) into one
    run per item, each keeping the run's formatting. Returns True if anything changed."""
    changed = False
    for r in [r for r in p.iter(W_R) if _owner_paragraph(r) is p]:
        items = [c for c in r if c.tag != W_RPR]
        if len(items) < 2 or not any(c.tag == W_T for c in items):
            continue
        for item in items:
            new_r = copy.deepcopy(r)
            for c in [c for c in new_r if c.tag != W_RPR]:
                new_r.remove(c)
            new_r.append(item)  # moves the original item into the new run
            r.addprevious(new_r)
        r.getparent().remove(r)
        changed = True
    return changed


def _highlight(paragraph, nodes, ranges):
    """Split runs so each range (offsets in the paragraph text) gets its own highlighted run(s).
    Returns, for each range, the list of Run objects that make it up."""
    # offsets of every node inside the paragraph text
    spans, pos = [], 0
    for n in nodes:
        length = len(node_text(n))
        spans.append((pos, pos + length))
        pos += length

    # per node: local [a, b) pieces to highlight, tagged with the range index
    per_node = {i: [] for i in range(len(nodes))}
    for ri, (s, e) in enumerate(ranges):
        for i, (ns, ne) in enumerate(spans):
            if s < ne and e > ns:
                per_node[i].append((max(s, ns) - ns, min(e, ne) - ns, ri))

    result = [[] for _ in ranges]
    for i, pieces in per_node.items():
        if not pieces:
            continue
        t = nodes[i]
        r = t.getparent()
        if t.tag != W_T or r.tag != W_R:
            continue
        simple = [c for c in r if c.tag != W_RPR] == [t]
        if not simple:
            # run also holds tabs/breaks/other text: highlight the whole run
            run = Run(r, paragraph)
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            for _, _, ri in pieces:
                result[ri].append(run)
            continue

        text = t.text or ''
        segments, cursor = [], 0  # (text, range index or None)
        for a, b, ri in sorted(pieces):
            if a > cursor:
                segments.append((text[cursor:a], None))
            segments.append((text[a:b], ri))
            cursor = b
        if cursor < len(text):
            segments.append((text[cursor:], None))

        for seg_text, ri in segments:
            new_r = copy.deepcopy(r)
            new_t = new_r.find(W_T)
            new_t.text = seg_text
            new_t.set(XML_SPACE, 'preserve')
            r.addprevious(new_r)
            if ri is not None:
                run = Run(new_r, paragraph)
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                result[ri].append(run)
        r.getparent().remove(r)
    return result


def spellcheck_txt(data, latin_variant, ui=lambda s: s):
    """Returns (report .txt bytes, SpellReport). The report lists every misspelled word,
    the lines it appears on and suggestions. ui() renders our own (old-Latin) labels."""
    text = decode_txt(data)
    report = SpellReport(total_words=_count_words([text]))
    checker = _Checker(is_new_latin(text), latin_variant)
    for line_no, line in enumerate(text.splitlines(), 1):
        for _, _, word in words_outside_links(line):
            suggestions = checker.check(word)
            if suggestions is None:
                continue
            key = word.lower()
            report.errors += 1
            report.unique.setdefault(key, suggestions)
            report.lines.setdefault(key, [])
            if line_no not in report.lines[key]:
                report.lines[key].append(line_no)
    report.truncated = checker.truncated

    out = [ui(f"Jami soʻzlar: {report.total_words}"),
           ui(f"Xatolar: {report.errors} (turli soʻzlar: {len(report.unique)})"), ""]
    for word, suggestions in report.unique.items():
        lines = report.lines[word]
        where = ", ".join(map(str, lines[:20])) + (" ..." if len(lines) > 20 else "")
        out.append(f"❌ {word}  " + ui(f"(qator: {where})"))
        out.extend(f"   ✅ {s}" for s in suggestions)
        if not suggestions:
            out.append("   — " + ui("lugʻatda topilmadi"))
        out.append("")
    return "\n".join(out).encode('utf-8'), report
