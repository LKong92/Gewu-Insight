from __future__ import annotations

import hashlib
from html import unescape
import re
from typing import Any

from bs4 import BeautifulSoup


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def clean_markup_text(value: Any) -> str:
    text = unescape(clean_text(value))
    if "<" not in text or ">" not in text:
        return text

    soup = BeautifulSoup(text, "html.parser")
    for math in soup.find_all(lambda tag: tag.name and tag.name.lower().endswith("math")):
        math.replace_with(_mathml_text(math))
    for sub in soup.find_all("sub"):
        sub.replace_with(_subscript_text(sub.get_text("", strip=True)))
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"(?<=[A-Za-z)\]])\s+([₀₁₂₃₄₅₆₇₈₉₊₋₍₎ₓᵧ]+)", r"\1", text)
    text = re.sub(r"\s+([,.;:!?%)\]}])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    return clean_text(text)


TITLE_PROPER_WORDS = {
    "abelian": "Abelian",
    "abrikosov": "Abrikosov",
    "aharonov": "Aharonov",
    "alphen": "Alphen",
    "anderson": "Anderson",
    "bardeen": "Bardeen",
    "berry": "Berry",
    "berezinskii": "Berezinskii",
    "bloch": "Bloch",
    "bogoliubov": "Bogoliubov",
    "boltzmann": "Boltzmann",
    "bohm": "Bohm",
    "bose": "Bose",
    "bragg": "Bragg",
    "brillouin": "Brillouin",
    "casimir": "Casimir",
    "chern": "Chern",
    "coulomb": "Coulomb",
    "debye": "Debye",
    "dirac": "Dirac",
    "einstein": "Einstein",
    "fano": "Fano",
    "fermi": "Fermi",
    "ferrell": "Ferrell",
    "feshbach": "Feshbach",
    "floquet": "Floquet",
    "fulde": "Fulde",
    "gennes": "Gennes",
    "ginzburg": "Ginzburg",
    "gibbs": "Gibbs",
    "goldstone": "Goldstone",
    "gorkov": "Gorkov",
    "griffiths": "Griffiths",
    "haas": "Haas",
    "haldane": "Haldane",
    "hall": "Hall",
    "heisenberg": "Heisenberg",
    "hermitian": "Hermitian",
    "higgs": "Higgs",
    "hofstadter": "Hofstadter",
    "hubbard": "Hubbard",
    "hund": "Hund",
    "ising": "Ising",
    "jahn": "Jahn",
    "josephson": "Josephson",
    "kagome": "Kagome",
    "kitaev": "Kitaev",
    "klein": "Klein",
    "kondo": "Kondo",
    "kosterlitz": "Kosterlitz",
    "kramers": "Kramers",
    "landau": "Landau",
    "larkin": "Larkin",
    "lifshitz": "Lifshitz",
    "lorentz": "Lorentz",
    "luttinger": "Luttinger",
    "majorana": "Majorana",
    "maxwell": "Maxwell",
    "meissner": "Meissner",
    "mott": "Mott",
    "nambu": "Nambu",
    "neel": "Neel",
    "newton": "Newton",
    "onsager": "Onsager",
    "ovchinnikov": "Ovchinnikov",
    "pauli": "Pauli",
    "peierls": "Peierls",
    "rabi": "Rabi",
    "raman": "Raman",
    "rashba": "Rashba",
    "rydberg": "Rydberg",
    "schottky": "Schottky",
    "stokes": "Stokes",
    "teller": "Teller",
    "thouless": "Thouless",
    "waals": "Waals",
    "wannier": "Wannier",
    "weyl": "Weyl",
    "wigner": "Wigner",
    "zener": "Zener",
    "zeeman": "Zeeman",
}


TITLE_ACRONYMS = {
    "afm",
    "arpes",
    "bcs",
    "bec",
    "cdw",
    "dft",
    "dmft",
    "dos",
    "edmft",
    "fc",
    "fci",
    "fqhe",
    "hf",
    "ir",
    "mbe",
    "nmr",
    "qah",
    "qhe",
    "qsl",
    "sdw",
    "sem",
    "ssh",
    "spt",
    "stm",
    "sts",
    "tem",
    "tmd",
    "trsb",
    "uv",
    "xrd",
}


TITLE_CHEMICAL_SYMBOLS = {
    "Ac", "Ag", "Al", "Ar", "As", "At", "Au", "B", "Ba", "Be", "Bi", "Br", "C", "Ca", "Cd",
    "Ce", "Cf", "Cl", "Cm", "Cn", "Co", "Cr", "Cs", "Cu", "Db", "Ds", "Dy", "Er", "Es", "Eu",
    "F", "Fe", "Fl", "Fm", "Fr", "Ga", "Gd", "Ge", "H", "He", "Hf", "Hg", "Ho", "Hs", "I",
    "In", "Ir", "K", "Kr", "La", "Li", "Lr", "Lu", "Lv", "Mc", "Md", "Mg", "Mn", "Mo", "Mt",
    "N", "Na", "Nb", "Nd", "Ne", "Nh", "Ni", "No", "Np", "O", "Og", "Os", "P", "Pa", "Pb",
    "Pd", "Pm", "Po", "Pr", "Pt", "Pu", "Ra", "Rb", "Re", "Rf", "Rg", "Rh", "Rn", "Ru", "S",
    "Sb", "Sc", "Se", "Sg", "Si", "Sm", "Sn", "Sr", "Ta", "Tb", "Tc", "Te", "Th", "Ti", "Tl",
    "Tm", "Ts", "U", "V", "W", "Xe", "Y", "Yb", "Zn", "Zr",
}
TITLE_AMBIGUOUS_CHEMICAL_WORDS = {"As", "At", "Be", "He", "In", "No"}
TITLE_SINGLE_LETTER_SYMBOLS = {"K", "T", "X", "Y", "Z"}
TITLE_SUBSCRIPT_CHARS = "₀₁₂₃₄₅₆₇₈₉₊₋₍₎ₓᵧ"
TITLE_WORD_RE = re.compile(rf"[A-Za-z][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}]*")
TITLE_WAVE_SYMMETRY_RE = re.compile(r"\b([spdfgSPDFG]{1,4})\s*[-\u2010\u2011\u2012\u2013\u2014]\s*(waves?)\b")
SUBSCRIPT_TRANS = str.maketrans("0123456789+-()", "₀₁₂₃₄₅₆₇₈₉₊₋₍₎")
TITLE_VARIABLE_FORMULA_RE = re.compile(
    rf"(?<![A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}])"
    rf"([A-Z][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}+\-−–—δΔ]*[+\-−–—xXyYδΔ][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}+\-−–—δΔ]*)"
    rf"(?![A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}])"
)
TITLE_FORMULA_SIGN_SPACE_RE = re.compile(
    rf"(?<=[A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}])\s*([+\-−–—])\s*(?=[xXyYδΔ])"
)
TITLE_FORMULA_COUNT_CHARS = set("0123456789+-−–—()xXyYδΔ" + TITLE_SUBSCRIPT_CHARS)
TITLE_CHEMICAL_SYMBOLS_LOWER = {symbol.lower(): symbol for symbol in TITLE_CHEMICAL_SYMBOLS}
TITLE_COMMON_LOWER_FORMULA_SEGMENTS = {
    "co": "CO",
    "no": "NO",
    "so": "SO",
}


def normalize_publication_title(value: Any) -> str:
    title = clean_markup_text(value)
    if not title:
        return ""
    title = normalize_variable_chemical_formulas(title)
    title = normalize_parenthesized_chemical_formula_counts(title)
    title = join_spaced_chemical_formula_tokens(title)
    letters = re.findall(r"[A-Za-z]", title)
    uppercase = sum(1 for letter in letters if letter.isupper())
    lowercase = sum(1 for letter in letters if letter.islower())
    shouting = bool(letters) and uppercase / max(len(letters), 1) > 0.85 and lowercase <= 2
    first_word = True

    def replace(match: re.Match[str]) -> str:
        nonlocal first_word
        token = match.group(0)
        lower = token.lower()
        is_first = first_word
        first_word = False
        chemical = normalize_chemical_formula_token(token)
        if chemical:
            return chemical
        if lower in TITLE_ACRONYMS:
            return lower.upper()
        if _preserve_title_token(title, token, match.start(), match.end(), shouting=shouting):
            return token
        if lower in TITLE_PROPER_WORDS:
            return TITLE_PROPER_WORDS[lower]
        normalized = lower
        if is_first:
            normalized = normalized[:1].upper() + normalized[1:]
        return normalized

    normalized_title = TITLE_WORD_RE.sub(replace, title)
    normalized_title = normalize_variable_chemical_formulas(normalized_title)
    normalized_title = normalize_parenthesized_chemical_formula_counts(normalized_title)
    normalized_title = normalize_wave_symmetry_terms(normalized_title)
    return clean_text(normalized_title)


def normalize_wave_symmetry_terms(title: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1).lower()}-{match.group(2).lower()}"

    return TITLE_WAVE_SYMMETRY_RE.sub(replace, title)


def normalize_variable_chemical_formulas(title: str) -> str:
    compact = TITLE_FORMULA_SIGN_SPACE_RE.sub(r"\1", title)

    def replace(match: re.Match[str]) -> str:
        normalized = _normalize_variable_chemical_formula_token(match.group(1), min_elements=2)
        return normalized or match.group(1)

    return TITLE_VARIABLE_FORMULA_RE.sub(replace, compact)


def normalize_parenthesized_chemical_formula_counts(title: str) -> str:
    title = TITLE_FORMULA_SIGN_SPACE_RE.sub(r"\1", title)
    formula_chars = rf"A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}δΔ"
    pattern = re.compile(
        rf"(?<![{formula_chars}])"
        rf"([{formula_chars}]*"
        rf"(?:\([{formula_chars}+\-−–—]+\)"
        rf"[0-9{TITLE_SUBSCRIPT_CHARS}+\-−–—xXyYδΔ]*"
        rf"[{formula_chars}]*)+)"
        rf"(?![{formula_chars}])"
    )

    def replace(match: re.Match[str]) -> str:
        normalized = _normalize_parenthesized_chemical_formula_token(match.group(1))
        return normalized or match.group(1)

    return pattern.sub(replace, title)


def _normalize_parenthesized_chemical_formula_token(token: str) -> str:
    pieces: list[str] = []
    index = 0
    element_count = 0
    counted_group_seen = False

    while index < len(token):
        char = token[index]
        if char == "(":
            close = token.find(")", index + 1)
            if close < 0:
                return ""
            inner = token[index + 1 : close]
            inner_normalized, inner_count = _normalize_parenthesized_formula_inner(inner)
            if not inner_normalized or inner_count < 1:
                return ""
            element_count += inner_count
            pieces.append(f"({inner_normalized})")
            index = close + 1
            count_chars: list[str] = []
            while index < len(token):
                current = token[index]
                if current == "(" or (current.isalpha() and current not in "xXyYδΔ"):
                    break
                if current not in TITLE_FORMULA_COUNT_CHARS:
                    return ""
                count_chars.append(current)
                index += 1
            if count_chars:
                normalized_count = _normalize_formula_count_expression("".join(count_chars))
                if not normalized_count:
                    return ""
                pieces.append(normalized_count)
                counted_group_seen = True
            continue

        if char.isalpha():
            start = index
            while index < len(token) and token[index].isalpha():
                index += 1
            letters = token[start:index]
            parsed, count = _normalize_formula_letters(letters)
            if not parsed:
                return ""
            pieces.append(parsed)
            element_count += count
            count_chars = []
            while index < len(token):
                current = token[index]
                if current == "(" or current.isalpha():
                    break
                if current not in TITLE_FORMULA_COUNT_CHARS:
                    return ""
                count_chars.append(current)
                index += 1
            if count_chars:
                normalized_count = _normalize_formula_count_expression("".join(count_chars))
                if not normalized_count:
                    return ""
                pieces.append(normalized_count)
            continue

        return ""

    if element_count < 1 or not counted_group_seen:
        return ""
    return "".join(pieces)


def _normalize_parenthesized_formula_inner(inner: str) -> tuple[str, int]:
    normalized, counted = _normalize_formula_fragment(inner)
    if normalized:
        return normalized, 1
    if re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)+", inner):
        return inner, 1
    return "", 0


def _normalize_variable_chemical_formula_token(token: str, *, min_elements: int) -> str:
    pieces: list[str] = []
    index = 0
    element_count = 0
    variable_count_seen = False
    counted_element_seen = False

    while index < len(token):
        char = token[index]
        if not char.isupper():
            return ""
        symbol = ""
        if index + 1 < len(token) and token[index + 1].islower():
            candidate = char + token[index + 1]
            if candidate in TITLE_CHEMICAL_SYMBOLS:
                symbol = candidate
                index += 2
        if not symbol and char in TITLE_CHEMICAL_SYMBOLS:
            symbol = char
            index += 1
        if not symbol:
            return ""

        pieces.append(symbol)
        element_count += 1

        count_chars: list[str] = []
        while index < len(token):
            current = token[index]
            if current.isupper() and current not in "XYΔ":
                break
            if current not in TITLE_FORMULA_COUNT_CHARS:
                return ""
            count_chars.append(current)
            index += 1

        if count_chars:
            count_text = "".join(count_chars)
            normalized_count = _normalize_formula_count_expression(count_text)
            if not normalized_count:
                return ""
            pieces.append(normalized_count)
            counted_element_seen = True
            if re.search(r"[+\-−–—xXyYδΔ₊₋ₓᵧ]", count_text):
                variable_count_seen = True

    if element_count < min_elements or not counted_element_seen or not variable_count_seen:
        return ""
    return "".join(pieces)


def _normalize_formula_count_expression(value: str) -> str:
    if not any(char.isdigit() or char in "xXyYδΔₓᵧ₀₁₂₃₄₅₆₇₈₉" for char in value):
        return ""
    pieces: list[str] = []
    for char in value:
        if char in "-−–—":
            pieces.append("₋")
        elif char == "+":
            pieces.append("₊")
        elif char in "xX":
            pieces.append("ₓ")
        elif char in "yY":
            pieces.append("ᵧ")
        elif char == "δ":
            pieces.append("δ")
        elif char == "Δ":
            pieces.append("Δ")
        elif char.isdigit() or char in "()":
            pieces.append(_subscript_text(char))
        elif char in TITLE_SUBSCRIPT_CHARS:
            pieces.append(char)
        else:
            return ""
    return "".join(pieces)


def join_spaced_chemical_formula_tokens(title: str) -> str:
    title = TITLE_FORMULA_SIGN_SPACE_RE.sub(r"\1", title)
    formula_token = rf"(?:[A-Za-z][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}+\-−–—δΔ]*|[0-9{TITLE_SUBSCRIPT_CHARS}]+)"
    pattern = re.compile(rf"(?<![A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}])({formula_token})\s+({formula_token})(?![A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}])")
    current = title
    while True:
        changed = False
        search_start = 0
        while True:
            match = pattern.search(current, search_start)
            if not match:
                break
            joined = _joined_chemical_formula_pair(match.group(1), match.group(2))
            if joined:
                current = current[: match.start(1)] + joined + current[match.end(2) :]
                changed = True
                break
            search_start = max(match.start(2), match.start(1) + 1)
        if not changed:
            break
    return current


def _joined_chemical_formula_pair(left: str, right: str) -> str:
    left_normalized, left_counted = _normalize_formula_fragment(left)
    right_normalized, right_counted = _normalize_formula_fragment(right)
    if not left_normalized or not right_normalized:
        return ""
    if not (left_counted or right_counted):
        return ""
    return left_normalized + right_normalized


def _normalize_formula_fragment(token: str) -> tuple[str, bool]:
    if re.fullmatch(rf"[0-9{TITLE_SUBSCRIPT_CHARS}]+", token):
        return _subscript_text(token), True
    if re.search(r"[+\-−–—xXyYδΔ₊₋ₓᵧ]", token):
        normalized = _normalize_variable_chemical_formula_token(token, min_elements=1)
        if normalized:
            return normalized, True
    if not re.fullmatch(rf"[A-Za-z][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}]*", token):
        return "", False
    counted = any(char.isdigit() or char in TITLE_SUBSCRIPT_CHARS for char in token)
    if counted:
        return normalize_chemical_formula_token(token), True
    if token.islower():
        return "", False
    parsed, count = _normalize_formula_letters(token)
    if not parsed or count < 1:
        return "", False
    return parsed, False


def normalize_chemical_formula_token(token: str) -> str:
    if not re.fullmatch(rf"[A-Za-z][A-Za-z0-9{TITLE_SUBSCRIPT_CHARS}]*", token):
        return ""
    if not any(char.isdigit() or char in TITLE_SUBSCRIPT_CHARS for char in token):
        return ""
    if token.lower() in TITLE_ACRONYMS:
        return ""
    parts = re.findall(rf"[A-Za-z]+|[0-9{TITLE_SUBSCRIPT_CHARS}]+", token)
    if not parts:
        return ""
    normalized_parts: list[str] = []
    element_count = 0
    for part in parts:
        if all(char.isdigit() or char in TITLE_SUBSCRIPT_CHARS for char in part):
            normalized_parts.append(_subscript_text(part))
            continue
        parsed, count = _normalize_formula_letters(part)
        if not parsed:
            return ""
        normalized_parts.append(parsed)
        element_count += count
    if element_count < 1:
        return ""
    return "".join(normalized_parts)


def _normalize_formula_letters(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    if value.islower():
        return _normalize_lower_formula_letters(value)
    pieces: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if not char.isalpha():
            return "", 0
        symbol = ""
        if char.isupper() and index + 1 < len(value) and value[index + 1].islower():
            candidate = char + value[index + 1]
            if candidate in TITLE_CHEMICAL_SYMBOLS:
                symbol = candidate
                index += 2
        if not symbol and char.upper() in TITLE_CHEMICAL_SYMBOLS:
            symbol = char.upper()
            index += 1
        if not symbol:
            return "", 0
        pieces.append(symbol)
    return "".join(pieces), len(pieces)


def _normalize_lower_formula_letters(value: str) -> tuple[str, int]:
    if value in TITLE_COMMON_LOWER_FORMULA_SEGMENTS:
        normalized = TITLE_COMMON_LOWER_FORMULA_SEGMENTS[value]
        return normalized, len(normalized)
    pieces: list[str] = []
    index = 0
    while index < len(value):
        symbol = ""
        if index + 1 < len(value):
            candidate = value[index : index + 2]
            if candidate in TITLE_CHEMICAL_SYMBOLS_LOWER:
                symbol = TITLE_CHEMICAL_SYMBOLS_LOWER[candidate]
                index += 2
        if not symbol and value[index] in TITLE_CHEMICAL_SYMBOLS_LOWER:
            symbol = TITLE_CHEMICAL_SYMBOLS_LOWER[value[index]]
            index += 1
        if not symbol:
            return "", 0
        pieces.append(symbol)
    return "".join(pieces), len(pieces)


def _subscript_text(value: str) -> str:
    return str(value).translate(SUBSCRIPT_TRANS)


def _preserve_title_token(title: str, token: str, start: int, end: int, *, shouting: bool) -> bool:
    if any(char.isdigit() for char in token):
        return True
    if start > 0 and title[start - 1].isdigit():
        return True
    if token in TITLE_SINGLE_LETTER_SYMBOLS:
        return True
    if any(char.isupper() for char in token[1:]) and not token.isupper():
        return True
    if token.isupper() and len(token) >= 2 and not shouting:
        return True
    if token in TITLE_CHEMICAL_SYMBOLS:
        if token not in TITLE_AMBIGUOUS_CHEMICAL_WORDS:
            return True
        before = title[start - 1] if start > 0 else ""
        after = title[end] if end < len(title) else ""
        return before in "-/(" or after in "-/)"
    return False


def _mathml_text(math: Any) -> str:
    text = "".join(math.stripped_strings)
    return clean_text(unescape(text))


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return clean_text(value[0])
    return clean_text(value)


def safe_slug(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", clean_text(value).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "untitled")[:max_len].strip("-")


def sha1_short(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def make_paper_id(doi: str | None, title: str | None, journal: str | None, publication_date: str | None) -> str:
    if doi:
        normalized = doi.lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        return "doi_" + sha1_short(normalized, 16)
    key = "|".join([clean_text(title).lower(), clean_text(journal).lower(), clean_text(publication_date)])
    return "p_" + sha1_short(key, 16)


def normalize_doi(value: str | None) -> str:
    doi = clean_text(value)
    if not doi:
        return ""
    doi = doi.removeprefix("https://doi.org/")
    doi = doi.removeprefix("http://doi.org/")
    return doi.lower()


def journal_name_for_doi(journal_name: Any, doi: str | None) -> str:
    normalized_doi = normalize_doi(doi)
    journal = clean_text(journal_name)
    if normalized_doi.startswith("10.5281/") or "zenodo" in journal.lower():
        return "Zenodo"
    if normalized_doi.startswith("10.32388/"):
        return "Qeios"
    if journal.lower() in {"[]", "{}", "none", "null"}:
        return ""
    return journal
