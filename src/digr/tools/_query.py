"""Plain-English query engine for sample search.

Pure stdlib, no new dependencies -- this module is imported by the FREE
``search_samples`` path, so it must never reach for numpy/scipy/soundfile.

The old engine lowercased the query, split it on spaces, and asked whether
every keyword appeared as a SUBSTRING anywhere in the full path. That has
three failure classes producers hit constantly:

  (a) plural/variant misses -- ``breaks`` never finds ``..._break.wav``;
  (b) no synonym normalisation -- ``hi-hat`` / ``hihat`` / ``hat`` are three
      different searches, as are ``perc`` / ``percussion``;
  (c) unintended substring hits -- ``loop`` matches the pack folder
      ``Loopmasters``, and ``.mid`` matches a folder called
      ``...WAV.MiDi.SERUM.PRESETS``.

The pipeline that replaces it::

    raw query  -> parse_query() -> QuerySpec { terms[], bpm_targets[] }
    file path  -> file_tokens() -> TokenBag { name{}, folder{}, bpm_hint }
                  match_query(QuerySpec, TokenBag) -> (matched, score, terms)

Both tiers benefit: ``search_samples_by_bpm`` goes through the same
``search_all_libraries``, and so do ``collect_samples`` and ``sort_samples``.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Stage 1 -- normalisation & tokenisation
# ---------------------------------------------------------------------------

# Anything that is not a letter or a digit separates tokens. One rule subsumes
# the whole zoo of pack-naming punctuation (space - _ . / \ ( ) [ ] ' &),
# including Windows path separators.
_SEPARATORS = re.compile(r"[^0-9A-Za-z]+")

# Within a chunk, split camelCase and letter<->digit boundaries:
#   DarkReese -> Dark, Reese      MIDIFile -> MIDI, File
#   174dnb    -> 174, dnb         kick808  -> kick, 808
#
# This split is also what stops the query ".mid" from matching a FOLDER called
# "...2019.WAV.MiDi.SERUM.PRESETS": "MiDi" becomes "mi" + "di", so the token
# "mid" is simply not there. The extension therefore does NOT need dropping --
# and keeping it is what preserves searching by file type ("wav", "mid").
_SUBTOKENS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens. Used on BOTH queries and paths."""
    tokens: list[str] = []
    for chunk in _SEPARATORS.split(text):
        if chunk:
            tokens.extend(piece.lower() for piece in _SUBTOKENS.findall(chunk))
    return tokens


def compound_join(tokens: list[str]) -> list[str]:
    """Join each adjacent pair, so ``hi`` + ``hat`` also yields ``hihat``."""
    return [a + b for a, b in zip(tokens, tokens[1:])]


# ---------------------------------------------------------------------------
# Stage 3 -- stemming: plurals ONLY
# ---------------------------------------------------------------------------


def stem(token: str) -> str:
    """Strip plural endings. Deliberately NOT a Porter stemmer.

    Porter would turn ``string`` into ``str``; here we only want
    ``break``<->``breaks`` and ``pad``<->``pads``. Applied to both sides, so
    any over-stemming is at least symmetric. Tokens of 3 characters or fewer
    are untouched (``fx``, ``sub``), as are non-alphabetic ones (``808``), and
    ``...ss`` is protected so ``bass`` survives. Tense (``-ing``/``-ed``) is
    explicitly not handled.
    """
    if len(token) <= 3 or not token.isalpha():
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith(("sses", "shes", "ches")):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


# ---------------------------------------------------------------------------
# Stage 2 -- alias/synonym expansion (OVERLAPPING sets, not disjoint groups)
# ---------------------------------------------------------------------------
#
# A token may belong to several groups, because real vocabulary collides:
# "cb" is cowbell (TR-808) AND contrabass (orchestral); "cl" is claves AND
# clarinet. So the API is expansions(token) -> set, and two tokens match when
# their groups overlap -- a structure equivalence classes cannot express.

_ALIAS_GROUPS: list[set[str]] = [
    {"hihat", "hi-hat", "hihats", "hat", "hats"},
    {"percussion", "perc", "percs"},
    {"vocal", "vox", "vocals", "voc"},
    {"snare", "snr"},
    {"reese", "reece"},
    {"fx", "sfx", "effect", "effects"},
    {"oneshot", "one-shot", "hit"},
    # Producers use these interchangeably for the same low-end role.
    {"sub", "808"},
    # --- Stage 2b: drum-machine abbreviations, safe tier ---
    # Free MusicRadar/SampleRadar packs label kicks "E808_Loop_BD_*", so this
    # is a real customer-facing vocabulary gap. Under TOKEN matching the old
    # substring false positives are structurally dead: Abduction_FX.wav
    # tokenises to {abduction, fx} and Seabed_pad.wav to {seabed, pad} --
    # neither contains a token "bd".
    {"bd", "kick"},
    {"sd", "snare"},
    {"cp", "clap"},
    {"rs", "rimshot"},
    {"cy", "cymbal"},
    {"hh", "hihat"},
]

# Allowed but ranked lower: each collides with a real word or with another
# instrument (a vocal "Oh" is a real sample name; "cb" is two instruments).
_WEAK_ALIAS_GROUPS: list[set[str]] = [
    {"oh", "hihat"},
    {"ch", "hihat"},
    {"cb", "cowbell", "contrabass"},
    {"ma", "maraca", "maracas"},
    {"cl", "claves", "clave", "clarinet"},
]


def _normalize_alias(member: str) -> str:
    """Reduce a written alias to the single token matching will actually see."""
    tokens = tokenize(member)
    if not tokens:
        return ""
    return stem("".join(tokens))


def _build_alias_index(groups: list[set[str]]) -> dict[str, frozenset[str]]:
    index: dict[str, set[str]] = {}
    for group in groups:
        members = {_normalize_alias(m) for m in group}
        members.discard("")
        for member in members:
            index.setdefault(member, set()).update(members)
    return {token: frozenset(members) for token, members in index.items()}


_ALIAS_INDEX = _build_alias_index(_ALIAS_GROUPS)
_WEAK_ALIAS_INDEX = _build_alias_index(_WEAK_ALIAS_GROUPS)


def expansions(token: str) -> frozenset[str]:
    """Every stem this token is interchangeable with, itself included."""
    key = stem(token)
    return _ALIAS_INDEX.get(key, frozenset()) | {key}


def weak_expansions(token: str) -> frozenset[str]:
    """Lower-confidence expansions, or empty if the token has none.

    The token itself is NOT included -- the strong tiers already cover
    identity, and this set exists only to be scored lower.
    """
    return _WEAK_ALIAS_INDEX.get(stem(token), frozenset())


# ---------------------------------------------------------------------------
# Stage 4 -- BPM-token tolerance
# ---------------------------------------------------------------------------

BPM_MIN = 40.0
BPM_MAX = 300.0


class BpmTarget(NamedTuple):
    """A tempo the query asked for. ``low == high`` means an exact target.

    Ranges are normalised into the same shape as exact targets so a later
    BPM-range filter can compose with this parse rather than inventing a
    second grammar for tempo.
    """

    low: float
    high: float

    @property
    def is_range(self) -> bool:
        return self.low != self.high

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


# Digit guards rather than \b: "_174_bpm" has no word boundary before the 1,
# because "_" counts as a word character.
_RANGE_RE = re.compile(r"(?<!\d)(\d{2,3})\s*(?:[-–—]|to)\s*(\d{2,3})(?!\d)")
_BPM_AFTER_RE = re.compile(r"(?<!\d)(\d{2,3})\s*[-_]?\s*bpm")
_BPM_BEFORE_RE = re.compile(r"bpm\s*[-_]?\s*(\d{2,3})(?!\d)")


def extract_bpm_from_filename(filename: str) -> float | None:
    """Extract BPM value from a filename if present.

    Matches patterns like "170 bpm", "117BPM", "170_bpm", "bpm_170",
    "BPM 117", and leading-number formats like "120-BreakName".
    Returns None if no BPM pattern is found.

    Lives here rather than in ``_audio_analysis`` (which imports it back for
    its own caller) because it is pure stdlib and the FREE search path needs
    it: importing ``_audio_analysis`` would drag in numpy/scipy/soundfile and
    break every install without the ``[audio]`` extras.
    """
    if not filename:
        return None

    # Strip extension for cleaner matching
    name = re.sub(r'\.[^.]+$', '', filename)

    # Pattern 1: number followed by "bpm" (with optional separator)
    match = re.search(r'(\d{2,3})\s*[-_]?\s*bpm', name, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Pattern 2: "bpm" followed by number
    match = re.search(r'bpm\s*[-_]?\s*(\d{2,3})', name, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Pattern 3: leading number followed by separator then text
    # e.g. "120-GitterBreak", "140_HouseLoop", "170 DnB Roller"
    # Only match if the number is in plausible BPM range (60-300)
    match = re.match(r'^(\d{2,3})[-_\s]', name)
    if match:
        bpm = float(match.group(1))
        if 60 <= bpm <= 300:
            return bpm

    return None


# ---------------------------------------------------------------------------
# Stage 7 -- stopwords: QUERY ONLY, never applied to file tokens
# ---------------------------------------------------------------------------
#
# File tokens are opportunities, never requirements, so keeping everything on
# that side can only improve recall.
#
# "a" is EXCLUDED -- it is a musical key ("Bass_A_minor.wav") -- and for the
# same reason there is no length-based rule. Vendor prefixes ("tsp") are not
# stopwords either: somebody searching TSP should find TSP files.
#
# "bpm" and "tempo" are CONSUMED AS GRAMMAR rather than discarded: they tell
# the parser the adjacent number is a tempo, not a catalogue index. As a
# required AND-term "bpm" would eliminate the majority of correctly labelled
# files, because most packs write "_174_", not "174bpm".
_STOPWORDS = frozenset(
    {"the", "an", "of", "and", "me", "my", "find", "get", "some", "any", "bpm", "tempo"}
)


@dataclass(frozen=True)
class QueryTerm:
    """One thing the user asked for. All terms must match (AND), unchanged."""

    text: str  # the literal typed token -- the ONLY thing substring may use
    stem: str
    aliases: frozenset[str]
    weak_aliases: frozenset[str]
    bpm: "BpmTarget | None" = None


@dataclass(frozen=True)
class QuerySpec:
    raw: str
    terms: tuple[QueryTerm, ...]
    bpm_targets: tuple[BpmTarget, ...]


def _make_term(text: str, bpm: BpmTarget | None = None) -> QueryTerm:
    return QueryTerm(
        text=text,
        stem=stem(text),
        aliases=expansions(text),
        weak_aliases=weak_expansions(text),
        bpm=bpm,
    )


def _collapse_compounds(tokens: list[str]) -> list[str]:
    """Fuse an adjacent pair ONLY when the fusion is known vocabulary.

    Asymmetric with the file side on purpose. File tokens can afford every
    join, but query tokens are AND-requirements: emitting "hi", "hat" AND
    "hihat" for "hi-hat" would demand all three and match nothing. Fusing only
    known aliases collapses "hi hat" into one term while leaving "dark reese"
    as two.
    """
    collapsed: list[str] = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens):
            joined = tokens[i] + tokens[i + 1]
            key = stem(joined)
            if key in _ALIAS_INDEX or key in _WEAK_ALIAS_INDEX:
                collapsed.append(joined)
                i += 2
                continue
        collapsed.append(tokens[i])
        i += 1
    return collapsed


def parse_query(raw: str) -> QuerySpec:
    """Turn a plain-English query into terms plus any tempo targets."""
    text = raw.lower()
    targets: list[BpmTarget] = []
    range_terms: list[QueryTerm] = []

    def _take_range(match: "re.Match[str]") -> str:
        low, high = float(match.group(1)), float(match.group(2))
        if low > high:
            low, high = high, low
        if low < BPM_MIN or high > BPM_MAX:
            return match.group(0)  # not a tempo range -- leave it as tokens
        target = BpmTarget(low, high)
        targets.append(target)
        # A range is consumed whole: leaving "170" and "178" behind would AND
        # them together and match nothing.
        range_terms.append(
            QueryTerm(
                text=f"{int(low)}-{int(high)}",
                stem="",
                aliases=frozenset(),
                weak_aliases=frozenset(),
                bpm=target,
            )
        )
        return " "

    text = _RANGE_RE.sub(_take_range, text)

    for pattern in (_BPM_AFTER_RE, _BPM_BEFORE_RE):
        for match in pattern.finditer(text):
            value = float(match.group(1))
            if BPM_MIN <= value <= BPM_MAX:
                targets.append(BpmTarget(value, value))

    tokens = [t for t in tokenize(text) if t not in _STOPWORDS]

    terms: list[QueryTerm] = []
    seen: set[str] = set()
    for token in _collapse_compounds(tokens):
        if token in seen:
            continue
        seen.add(token)
        bpm: BpmTarget | None = None
        if token.isdigit() and BPM_MIN <= float(token) <= BPM_MAX:
            # A bare in-band integer becomes a tempo target AND stays a
            # literal token, so "_174_" matches either way. 808 sits above the
            # band and stays an ordinary token.
            bpm = BpmTarget(float(token), float(token))
            targets.append(bpm)
        terms.append(_make_term(token, bpm))

    terms.extend(range_terms)

    unique_targets: list[BpmTarget] = []
    for target in targets:
        if target not in unique_targets:
            unique_targets.append(target)

    return QuerySpec(raw=raw, terms=tuple(terms), bpm_targets=tuple(unique_targets))


# ---------------------------------------------------------------------------
# File side -- tokenising a path
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenBag:
    """Tokens of one file, split into filename and folder buckets for ranking.

    The stem sets and ``numbers`` are precomputed rather than derived per
    query term: search walks every file in every library, so the per-file work
    has to stay flat.
    """

    name: frozenset[str]
    folder: frozenset[str]
    name_stems: frozenset[str]
    folder_stems: frozenset[str]
    numbers: frozenset[int]
    bpm_hint: float | None


def _numbers_in(tokens: frozenset[str]) -> frozenset[int]:
    return frozenset(int(t) for t in tokens if t.isdigit() and len(t) <= 4)


def file_tokens(
    path,
    root: Path | None = None,
    folder_cache: dict | None = None,
    want_bpm_hint: bool = True,
) -> TokenBag:
    """Tokenise one file into filename and folder buckets.

    ``root`` should be the library root: folders are taken RELATIVE to it, so
    the machine's own path ("/Users/<name>/...", "/private/var/folders/...")
    never contributes tokens a query could hit by accident.

    ``folder_cache`` is keyed by the folder parts and shared across a whole
    library walk, so a pack folder is tokenised once rather than once per
    sample inside it.
    """
    file_path = Path(path)
    relative = file_path
    if root is not None:
        try:
            relative = file_path.relative_to(root)
        except ValueError:
            relative = file_path

    folder_parts = relative.parts[:-1]
    cached = folder_cache.get(folder_parts) if folder_cache is not None else None
    if cached is None:
        folder_tokens: list[str] = []
        for part in folder_parts:
            part_tokens = tokenize(part)
            folder_tokens.extend(part_tokens)
            folder_tokens.extend(compound_join(part_tokens))
        folder = frozenset(folder_tokens)
        cached = (
            folder,
            frozenset(stem(t) for t in folder),
            _numbers_in(folder),
        )
        if folder_cache is not None:
            folder_cache[folder_parts] = cached
    folder, folder_stems, folder_numbers = cached

    name_tokens = tokenize(file_path.name)
    name = frozenset(name_tokens + compound_join(name_tokens))

    return TokenBag(
        name=name,
        folder=folder,
        name_stems=frozenset(stem(t) for t in name),
        folder_stems=folder_stems,
        numbers=folder_numbers | _numbers_in(name),
        bpm_hint=extract_bpm_from_filename(file_path.name) if want_bpm_hint else None,
    )


# ---------------------------------------------------------------------------
# Stages 5 & 6 -- matching and ranking
# ---------------------------------------------------------------------------

SCORE_FILENAME_EXACT = 3.0
SCORE_FOLDER_EXACT = 2.0
SCORE_ALIAS = 1.5
SCORE_BPM = 1.5
SCORE_WEAK_ALIAS = 0.75
SCORE_SUBSTRING = 0.5
BONUS_ALL_IN_FILENAME = 2.0
BONUS_BPM_HINT = 3.0

# How long a typed term must be before the substring fallback will fire.
SUBSTRING_MIN_LEN = 4


class MatchResult(NamedTuple):
    """``matched`` is the AND verdict; ``matched_terms`` drives Stage 8."""

    matched: bool
    score: float
    matched_terms: frozenset[int]


def _score_term(term: QueryTerm, bag: TokenBag) -> tuple[float | None, bool]:
    """Best-first satisfaction of one term -> (score, matched_in_filename).

    ``None`` means the term is unsatisfied. Tiers are tried in descending
    score order, so the first hit is the best available one.
    """
    if term.text in bag.name:
        return SCORE_FILENAME_EXACT, True
    if term.text in bag.folder:
        return SCORE_FOLDER_EXACT, False
    if term.aliases:
        if term.aliases & bag.name_stems:
            return SCORE_ALIAS, True
        if term.aliases & bag.folder_stems:
            return SCORE_ALIAS, False
    if term.bpm is not None:
        if bag.bpm_hint is not None and term.bpm.contains(bag.bpm_hint):
            return SCORE_BPM, True
        if any(term.bpm.contains(n) for n in bag.numbers):
            return SCORE_BPM, False
    if term.weak_aliases:
        if term.weak_aliases & bag.name_stems:
            return SCORE_WEAK_ALIAS, True
        if term.weak_aliases & bag.folder_stems:
            return SCORE_WEAK_ALIAS, False
    # CRITICAL: the substring fallback uses term.text -- the LITERAL typed
    # term -- and NEVER an alias expansion. Stacking the two guesses would let
    # kick -> bd -> substring resurrect Abduction_FX and Seabed_pad, silently
    # reintroducing the exact bug this module exists to fix.
    #
    # It is also filename-only. Folder names are vendor and pack branding
    # (Loopmasters, Ghosthack) where long accidental substrings live;
    # filenames are where the user's own vocabulary lives. That is what keeps
    # "loop" off the Loopmasters folder while still finding "verb" in
    # "reverb". A folder genuinely called "Loops" still matches, one tier up,
    # via the stemmer.
    if len(term.text) >= SUBSTRING_MIN_LEN:
        for token in bag.name:
            if term.text in token:
                return SCORE_SUBSTRING, True
    return None, False


def match_query(spec: QuerySpec, bag: TokenBag) -> MatchResult:
    """Score one file against one query. A file matches when EVERY term does."""
    if not spec.terms:
        return MatchResult(False, 0.0, frozenset())

    score = 0.0
    matched_terms: set[int] = set()
    all_in_filename = True

    for index, term in enumerate(spec.terms):
        term_score, in_filename = _score_term(term, bag)
        if term_score is None:
            all_in_filename = False
            continue
        matched_terms.add(index)
        score += term_score
        if not in_filename:
            all_in_filename = False

    if matched_terms and all_in_filename:
        score += BONUS_ALL_IN_FILENAME
    if bag.bpm_hint is not None and any(
        target.contains(bag.bpm_hint) for target in spec.bpm_targets
    ):
        score += BONUS_BPM_HINT

    return MatchResult(
        matched=len(matched_terms) == len(spec.terms),
        score=score,
        matched_terms=frozenset(matched_terms),
    )


def rank_key(score: float, path: str) -> tuple[float, int, str]:
    """Deterministic ordering: best score first, then shorter path, then A-Z."""
    return (-score, len(path), path)
