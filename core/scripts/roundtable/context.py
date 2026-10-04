#!/usr/bin/env python3
"""Б2 — the package: manifest, registries, canonical bytes, one hash.

Guarantee 1 of the whole design is that both critics got **the same verifiable
package, byte for byte**, proven by a hash rather than asserted.

What is guaranteed, and by what:

* **Determinism.** Two builds of the same input give the same bytes: no
  timestamp or host path enters, mappings are serialised with sorted keys, and
  the manifest, file texts, registries and evidence journal are sorted by
  content, so neither declaration order nor the interpreter's hash seed moves
  the hash.
* **Read once, from a descriptor.** A declared file is opened exactly once by
  walking the path component by component with `O_NOFOLLOW` relative to a
  directory descriptor. Each component is spelled exactly as the disk spells
  it and lives on the root's device; after the read the name must still lead
  to the same single-link inode. The same bytes give the hash and the text that
  travels in the package. Hard links, FIFOs, devices, directories, oversize and
  non-UTF-8 files are refused by name.
* **A snapshot.** `Package` keeps only the canonical bytes and their hash
  (verified at construction); every view is a fresh copy parsed from them.
* **Rules are data.** Schemas of registry records, field formats, forbidden
  paths, allowed extensions, secret signatures, section names and every limit
  come from `vocabulary.yaml: пакет`; this module only reads them.
* **A blind package carries no trace of what is hidden.** `withheld` is
  mandatory and exactly the hidden names. Texts are compared as *skeletons*
  (NFKC, casefold, Latin look-alikes folded to Cyrillic, ё to е, only letters
  and digits kept) over every leaf value and key of the shown sections, the
  registries and the manifest paths -- never over serialised JSON. A long hidden
  text is found by any slice of `мин_длина_следа`; a short one (an author's
  name) by its stem, which survives declension, prefixes and look-alikes.

Deliberately NOT guaranteed (accepted, not overlooked): a reordering of words,
base64/hex or any other re-encoding, a translation and a paraphrase are not
caught; an honest solution that quotes the task verbatim for longer than the
threshold is refused (safely, and the refusal names the channel and the hidden
section, never the hidden text). Secret detection is by file name, extension
and a short list of signatures, not a scanner.

Path rules are refusals, not warnings (§6.9). `existing_evidence` must exist;
`planned_output` is created later, so its absence is normal (§7.3).
"""

from __future__ import annotations

import bisect
import errno
import fnmatch
import functools
import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import state as state_module
from . import tables as tables_module


class PackageRefused(Exception):
    """The package could not be assembled as a verifiable one."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def canonical_json(payload) -> bytes:
    """The one serialisation used for every hash in the package.

    Sorted keys and fixed separators, so that two builds of the same content
    cannot differ by dictionary order; UTF-8 without escaping, so the Russian
    text stays readable in the artefact a human has to audit.
    """
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as error:
        raise PackageRefused("некорректный_вход", f"не сериализуется: {error}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestEntry:
    """One declared input file (§6.9)."""

    path: str
    file_class: str
    sha256: str | None
    bytes_read: int | None

    def as_dict(self) -> dict:
        return {"путь": self.path, "класс": self.file_class,
                "хеш": self.sha256, "байт": self.bytes_read}


def _syntax(relative) -> None:
    """The refusals that need no disk: type, encoding, `..`, canonical form."""
    if not isinstance(relative, str):
        raise PackageRefused("некорректный_вход", f"путь не строка: {relative!r}")
    _encodable(relative, "путь")
    if "\x00" in relative:
        raise PackageRefused("файл_нечитаем", "NUL в пути")
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise PackageRefused("путь_с_родительским_переходом", relative)
    if not relative or relative != "/".join(PurePosixPath(relative).parts):
        raise PackageRefused("путь_не_канонический", relative)


def _encodable(text: str, where: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise PackageRefused("некорректный_вход", f"{where}: суррогаты в строке")


def _policy(relative: str, limits: dict) -> None:
    """What may leave the machine at all: forbidden names, then the extension."""
    banned = _forbidden(relative, limits["запрещённые_пути"])
    if banned is not None:
        raise PackageRefused("путь_запрещён", f"{relative}: {banned}")
    suffix = PurePosixPath(relative).suffix.casefold()
    if suffix not in limits["разрешённые_расширения"]:
        raise PackageRefused("путь_запрещён", f"{relative}: расширение {suffix or '(нет)'}")


def _check_path(root: Path, relative: str) -> Path:
    """Early, readable refusals of §6.9. The real defence is the descriptor walk."""
    _syntax(relative)
    target = root / relative

    # A symlink anywhere along the way is enough: the leaf may be innocent while
    # a parent directory points outside the root.
    probe = root
    for part in Path(relative).parts:
        probe = probe / part
        if probe.is_symlink():
            raise PackageRefused("симлинк", str(probe.relative_to(root)))

    try:
        resolved = target.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        raise PackageRefused("путь_вне_корня", relative)
    return target


_NOCTTY = getattr(os, "O_NOCTTY", 0)


def _classify_open_error(error: OSError, name: str, parent_fd: int, relative: str):
    """Turn a failed component open into a named refusal."""
    if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
        try:
            info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            info = None
        if error.errno in (errno.ELOOP, errno.EMLINK) or (
                info is not None and stat.S_ISLNK(info.st_mode)):
            return PackageRefused("симлинк", relative)
    return PackageRefused("файл_нечитаем", f"{relative}: {error.strerror or error}")


def _folded(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _forbidden(relative: str, patterns) -> str | None:
    """The first path component that never leaves the machine, if any."""
    folded = [_folded(pattern) for pattern in patterns]
    for part in PurePosixPath(relative).parts:
        name = _folded(part)
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in folded):
            return part
    return None


def _read_by_descriptors(root: Path, relative: str, cap: int):
    """Open `relative` below `root` without ever following a link; read once.

    Returns the bytes, or None if some component is absent.
    Every component must be spelled exactly as the disk spells it, live on the
    root's device, and the file must still be the same single-link inode after
    the read.
    """
    parts = PurePosixPath(relative).parts
    opened = []
    try:
        try:
            current = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        except (OSError, ValueError) as error:
            raise PackageRefused("файл_нечитаем", f"корень: {error}")
        opened.append(current)
        root_device = os.fstat(current).st_dev

        def spelled(directory, part):
            if len(part.encode("utf-8", "surrogateescape")) > 255:
                raise PackageRefused("файл_нечитаем", f"{relative}: слишком длинное имя")
            try:
                listing = set(os.listdir(directory))
            except OSError as error:
                raise PackageRefused("файл_нечитаем", f"{relative}: {error.strerror or error}")
            if part in listing:
                return True
            if any(_folded(entry) == _folded(part) for entry in listing):
                raise PackageRefused("путь_не_канонический", relative)
            return False

        for part in parts[:-1]:
            if not spelled(current, part):
                return None
            try:
                current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=current)
            except FileNotFoundError:
                return None
            except ValueError as error:
                raise PackageRefused("файл_нечитаем", f"{relative}: {error}")
            except OSError as error:
                raise _classify_open_error(error, part, opened[-1], relative)
            opened.append(current)
            if os.fstat(current).st_dev != root_device:
                raise PackageRefused("путь_вне_корня", f"{relative}: другая файловая система")
        if not spelled(current, parts[-1]):
            return None
        name = parts[-1]
        try:
            leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _NOCTTY,
                           dir_fd=current)
        except FileNotFoundError:
            return None
        except ValueError as error:
            raise PackageRefused("файл_нечитаем", f"{relative}: {error}")
        except OSError as error:
            raise _classify_open_error(error, name, current, relative)
        opened.append(leaf)

        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode):
            raise PackageRefused("файл_не_обычный", relative)
        if info.st_dev != root_device:
            raise PackageRefused("путь_вне_корня", f"{relative}: другая файловая система")
        if info.st_nlink > 1:
            raise PackageRefused("жёсткая_ссылка", f"{relative}: ссылок {info.st_nlink}")
        if info.st_size > cap:
            raise PackageRefused("превышение_размера", f"{relative}: {info.st_size} > {cap}")
        chunks, total = [], 0
        try:
            while total <= cap:
                chunk = os.read(leaf, min(65536, cap + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        except OSError as error:
            raise PackageRefused("файл_нечитаем", f"{relative}: {error.strerror or error}")
        if total > cap:
            raise PackageRefused("превышение_размера", f"{relative}: >{cap}")

        # After the read: the name must still lead to this very inode, and both
        # measurements must see exactly one link. A secret hard-linked in under
        # the declared name, or a file swapped for another, shows up here.
        after = os.fstat(leaf)
        try:
            named = os.stat(name, dir_fd=current, follow_symlinks=False)
        except OSError:
            raise PackageRefused("файл_изменился", f"{relative}: имя больше не ведёт к файлу")
        if (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino) or \
                (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino):
            raise PackageRefused("файл_изменился", relative)
        if after.st_nlink != 1 or named.st_nlink != 1 or info.st_nlink != 1:
            raise PackageRefused("жёсткая_ссылка", f"{relative}: ссылок {named.st_nlink}")
        return b"".join(chunks)
    finally:
        for descriptor in opened:
            os.close(descriptor)


def _looks_secret(text: str, limits: dict) -> str | None:
    """A secret signature in the raw text or in the text with invisibles removed."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKC", text)
                       if unicodedata.category(ch) != "Cf")
    for pattern in limits["признаки_секрета"]:
        if re.search(pattern, text) or re.search(pattern, stripped):
            return pattern
    return None


def read_file(root: Path, relative: str, file_class: str, tables):
    """Read one declared file once; return `(entry, text)` or refuse by name.

    The one read yields the bytes for the hash *and* the text that goes into the
    package. `text` is None only for an absent `planned_output`.
    """
    classes = set(tables.precheck["классы_файлов"])
    if not isinstance(file_class, str) or file_class not in classes:
        raise PackageRefused("неизвестный_класс_файла", f"{relative}: {file_class}")
    limits = tables.vocabulary["пакет"]
    root = Path(root)
    _check_path(root, relative)
    _policy(relative, limits)
    try:
        absolute = (root / relative).resolve()
        inside_runs = absolute.is_relative_to(state_module.RUNS_ROOT.resolve())
    except OSError:
        raise PackageRefused("путь_вне_корня", relative)
    if inside_runs:
        raise PackageRefused("путь_запрещён", f"{relative}: внутри каталога прогонов")
    # The same deny-list over the ABSOLUTE path: a service directory above the
    # root (`~/.stc/...`, `.codex/...`) is as forbidden as one below it.
    ancestors = absolute.parts[1:-len(PurePosixPath(relative).parts)]
    banned = _forbidden("/".join(ancestors), limits["запрещённые_предки"]) if ancestors else None
    if banned is not None:
        raise PackageRefused("путь_запрещён", f"{relative}: служебный каталог выше корня — {banned}")

    data = _read_by_descriptors(root, relative, limits["предел_файла_байт"])
    if data is None:
        if file_class == "planned_output":
            # Declared, created later: absence is the normal case (§7.3).
            return ManifestEntry(relative, file_class, None, None), None
        raise PackageRefused("отсутствие_обязательного_файла", relative)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageRefused("файл_не_текст", relative)
    if _looks_secret(text, limits) is not None:
        raise PackageRefused("похоже_на_секрет", f"файл {relative}")
    return ManifestEntry(relative, file_class, digest(data), len(data)), text


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

def fingerprint(record: dict, tables) -> str:
    """The content fingerprint of one evidence record (§6.1, round 10).

    Computed over exactly the fields the vocabulary names for that type — the
    identifier and the time are deliberately not among them, because re-sending
    the same span would otherwise get a fresh id and look like new evidence.
    """
    kind = record.get("тип")
    shapes = tables.vocabulary["отпечаток"]
    if kind not in shapes:
        raise PackageRefused("неизвестный_тип_доказательства", str(kind))
    missing = [name for name in shapes[kind] if name not in record]
    if missing:
        raise PackageRefused("неполное_доказательство", f"{kind}: нет {missing}")
    return digest(canonical_json([kind] + [record[name] for name in shapes[kind]]))


def check_creator(record: dict, tables) -> None:
    """Who may create a record of this type (§6.1).

    A critic runs with `--tools ""` and cannot execute anything, so a
    `command_run` from a critic is not a suspicious record — it is an
    impossible one.
    """
    kind, creator = record.get("тип"), record.get("создатель")
    allowed = tables.vocabulary["создатели_доказательства"].get(kind, [])
    if creator not in allowed:
        raise PackageRefused("недопустимый_создатель_доказательства",
                             f"{kind} от {creator!r}, допустимы {allowed}")


# --------------------------------------------------------------------------
# the package
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Package:
    """An immutable snapshot: only the canonical bytes and their hash are kept.

    Every structured view is a fresh copy parsed from those bytes, so editing
    what a caller got back changes neither the next view nor `material()`.
    """

    stage: str
    _bytes: bytes
    _hash: str

    def __post_init__(self):
        if not isinstance(self._bytes, bytes) or digest(self._bytes) != self._hash:
            raise ValueError("пакет: хеш не соответствует байтам")
        try:
            declared = json.loads(self._bytes.decode("utf-8")).get("стадия")
        except (ValueError, AttributeError):
            raise ValueError("пакет: байты не разбираются")
        if declared != self.stage:
            raise ValueError("пакет: стадия не соответствует байтам")

    def as_dict(self) -> dict:
        """A fresh deep copy of the packaged data on every call."""
        return json.loads(self._bytes.decode("utf-8"))

    @property
    def manifest(self) -> list:
        return [ManifestEntry(row["путь"], row["класс"], row["хеш"], row["байт"])
                for row in self.as_dict()["манифест"]]

    @property
    def manifest_hash(self) -> str:
        return self.as_dict()["хеш_манифеста"]

    @property
    def registries(self) -> dict:
        return self.as_dict()["реестры"]

    @property
    def sections(self) -> dict:
        return self.as_dict()["разделы"]

    @property
    def files(self) -> dict:
        return self.as_dict()["файлы"]

    @property
    def canonical_bytes(self) -> bytes:
        return self._bytes

    @property
    def hash(self) -> str:
        return self._hash

    def material(self) -> str:
        """What actually goes down the critic's stdin — never into argv (§5.2)."""
        return self._bytes.decode("utf-8")


def visible_sections(tables, stage: str, blind: bool) -> set | None:
    """Which sections a blind first question carries (stages.yaml).

    Blind means the critic is asked for a solution *before* being shown ours:
    anchoring is the failure mode, and the cure is to hide the answer, not the
    context. So the shown list is exactly what goes in.
    """
    if not blind:
        return None
    rules = tables.stages["слепой_вопрос"]
    if tables.stages["стадии"][stage]["первый_вопрос"] != "предложи_решение":
        raise PackageRefused("слепой_вопрос_не_на_этой_стадии", stage)
    return set(rules["показываем"])


def _bad(detail: str):
    return PackageRefused("некорректный_вход", detail)


def _validate_input(root, declared_files, sections, registries, stage):
    if not isinstance(root, (str, os.PathLike)):
        raise _bad(f"корень не путь: {type(root).__name__}")
    if not isinstance(stage, str):
        raise _bad(f"стадия не строка: {stage!r}")
    if not isinstance(declared_files, (list, tuple)):
        raise _bad("declared_files не список")
    for pair in declared_files:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or not all(isinstance(item, str) for item in pair)):
            raise _bad(f"объявление файла не пара строк: {pair!r}")
    if not isinstance(sections, dict):
        raise _bad("разделы не словарь")
    for name, value in sections.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise _bad(f"раздел {name!r}: имя и значение должны быть строками")
        _encodable(name, "имя раздела")
        _encodable(value, f"раздел {name}")
    if not isinstance(registries, dict):
        raise _bad("реестры не словарь")


# -- registries ----------------------------------------------------------------

@functools.lru_cache(maxsize=256)
def _format(spec: str):
    return tables_module.parse_field_format(spec, "формат поля")


def _short(names) -> list:
    """Field names for a message: foreign keys are cut, not echoed whole."""
    return sorted((str(name)[:40] + ("…" if len(str(name)) > 40 else "")) for name in names)


def _check_fields(record: dict, where: str, limits: dict) -> None:
    """Every field of a record has a format in the table and fits it."""
    formats = limits["форматы_полей"]
    for field, value in record.items():
        if not isinstance(field, str):
            raise PackageRefused("запись_вне_схемы", f"{where}: имя поля не строка")
        _encodable(field, f"{where}: имя поля")
        if field not in formats:
            raise PackageRefused("запись_вне_схемы", f"{where}: у поля {_short([field])[0]} нет формата")
        kind = _format(formats[field])
        if kind[0] == "int":
            good = (isinstance(value, int) and not isinstance(value, bool)
                    and kind[1] <= value <= kind[2])
        elif kind[0] == "pair":
            good = (isinstance(value, (list, tuple)) and len(value) == 2
                    and all(isinstance(n, int) and not isinstance(n, bool)
                            and kind[1] <= n <= kind[2] for n in value)
                    and value[0] <= value[1])
        else:
            good = isinstance(value, str)
            if good:
                _encodable(value, f"{where}.{field}")
                good = kind[1].fullmatch(value) is not None
        if not good:
            raise PackageRefused("запись_вне_схемы", f"{where}.{field}: недопустимое значение")
        if field == "путь":
            _syntax(value)
            _policy(value, limits)


def _registry_list(registries, name, fields, limits, key=None, optional=()):
    """A registry as a list of records that match the table's closed schema."""
    items = registries[name]
    if not isinstance(items, (list, tuple)):
        raise _bad(f"реестр {name} не список")
    for item in items:
        if not isinstance(item, dict):
            raise _bad(f"запись реестра {name} не словарь")
        if key is not None and not isinstance(item.get(key), str):
            raise _bad(f"запись реестра {name} без строкового {key}")
        if fields is not None:
            missing = set(fields) - set(item)
            extra = set(item) - set(fields) - set(optional)
            if missing or extra:
                raise PackageRefused(
                    "запись_вне_схемы",
                    f"{name}: нет {_short(missing)}, лишние {_short(extra)}")
        _check_fields(item, name, limits)
    if key is not None:
        ids = [item[key] for item in items]
        if len(set(ids)) != len(ids):
            raise PackageRefused("дубль_в_реестре", f"{name}: {key}")
    return list(items)


def _build_registries(registries, tables, blind: bool) -> dict:
    limits = tables.vocabulary["пакет"]
    expected = set(limits["реестры"])
    if set(registries) != expected:
        raise PackageRefused("реестры_не_полны",
                             f"{sorted(registries)} против {sorted(expected)}")
    schemas = limits["схемы_записей"]
    decisions = _registry_list(registries, "решения", schemas["решения"], limits, "decision_id")
    areas = _registry_list(registries, "области", schemas["области"], limits, "area_id")
    records = registries["журнал_доказательств"]
    if not isinstance(records, (list, tuple)) or not all(isinstance(r, dict) for r in records):
        raise _bad("реестр журнал_доказательств: не список записей")

    kinds = set(limits["виды_решений_в_реестре"])
    for decision in decisions:
        if decision["kind"] not in kinds:
            raise PackageRefused("неизвестный_вид_решения", str(decision["kind"]))

    journal = []
    for record in records:
        kind = record.get("тип")
        if not isinstance(kind, str):
            raise _bad("запись журнала без строкового типа")
        if kind not in tables.vocabulary["отпечаток"]:
            raise PackageRefused("неизвестный_тип_доказательства", kind)
        shape = schemas["журнал_общие"] + tables.vocabulary["отпечаток"][kind]
        missing = set(shape) - set(record)
        extra = set(record) - set(shape) - set(schemas["журнал_необязательные"])
        if missing or extra:
            raise PackageRefused(
                "запись_вне_схемы",
                f"журнал_доказательств: нет {_short(missing)}, лишние {_short(extra)}")
        _check_fields(record, "журнал_доказательств", limits)
        check_creator(record, tables)
        journal.append({**record, "отпечаток": fingerprint(record, tables)})

    if blind:
        visible_status = set(limits["видимые_слепому_статусы_решений"])
        for decision in decisions:
            if decision["status"] not in visible_status:
                raise PackageRefused("слепой_пакет_след_скрытого",
                                     f"решение {decision['decision_id']}: статус не из видимых слепому")
        visible_creators = set(limits["видимые_слепому_создатели"])
        for record in journal:
            if record["создатель"] not in visible_creators:
                raise PackageRefused("слепой_пакет_след_скрытого",
                                     "запись журнала от создателя, невидимого слепому")

    return {
        "решения": sorted(decisions, key=lambda d: d["decision_id"]),
        "области": sorted(areas, key=lambda a: a["area_id"]),
        "журнал_доказательств": sorted(
            journal, key=lambda r: (r["отпечаток"], canonical_json(r))),
    }


# -- the trace of what is hidden -----------------------------------------------

_SCRIPT_TESTS = {
    "кириллица": lambda ch: "а" <= ch <= "я",
    "латиница": lambda ch: "a" <= ch <= "z",
    "цифры": lambda ch: "0" <= ch <= "9",
}


def _skeleton_checked(text: str, scripts=None):
    """`(skeleton, first_foreign_letter)`.

    NFKD, marks off, NFKC, casefold, look-alikes folded (one table with the
    consensus engine), digits of any script to ASCII; only letters and digits
    stay. With `scripts` given, a letter outside those alphabets is reported
    instead of being dropped silently.
    """
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("M"))
    text = unicodedata.normalize("NFKC", text).casefold()
    text = unicodedata.normalize("NFKC", text).translate(tables_module._HOMOGLYPHS)
    kept, foreign = [], None
    for ch in text:
        category = unicodedata.category(ch)
        if category[0] not in "LN":
            continue
        if category[0] == "N":
            digit = unicodedata.digit(ch, None)
            if digit is not None:
                ch = str(digit)
        if scripts is not None and not any(_SCRIPT_TESTS[name](ch) for name in scripts):
            foreign = foreign or ch
            continue
        kept.append(ch)
    return "".join(kept), foreign


def _skeleton(text: str) -> str:
    return _skeleton_checked(text)[0]


def _leaves(node, channel: str):
    """Every string/number leaf and every key below `node`, with its channel."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{channel}.{key}", str(key), True
            yield from _leaves(value, f"{channel}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _leaves(value, f"{channel}[{index}]")
    elif node is not None:
        yield channel, str(node), False


def _shown_leaves(sections: dict, normalised: dict, paths) -> list:
    leaves = []
    for name, value in sections.items():
        leaves.append((f"раздел.{name}", value, False))
    leaves.extend(_leaves(normalised, "реестр"))
    leaves.extend((f"путь[{index}]", path, False) for index, path in enumerate(paths))
    return leaves


def _stems(text: str, minimum: int) -> set:
    """Stems of a hidden NAME: every word, cut before its ending, never below `minimum`."""
    stems = set()
    for token in re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text)):
        word = _skeleton(token)
        if len(word) >= minimum:
            stems.add(word[:max(minimum, len(word) - 2)])
    if not stems:
        whole = _skeleton(text)
        stems.add(whole[:max(minimum, len(whole) - 2)])
    return stems


def _check_secrets(leaves: list, limits: dict) -> None:
    for channel, text, _ in leaves:
        if _looks_secret(text, limits) is not None:
            raise PackageRefused("похоже_на_секрет", channel)


def _check_traces(hidden: dict, leaves: list, limits: dict) -> None:
    """Refuse a blind package in which anything hidden shows up.

    The refusal names the channel and the hidden section, never the text. A
    letter outside the alphabets of the table is refused too, not skipped: a
    silent drop is exactly what a look-alike letter would hide behind.
    """
    window, minimum = limits["мин_длина_следа"], limits["мин_длина_основы"]
    scripts, names = limits["письменности_скелета"], set(limits["скрытые_имена"])
    skeletons = []
    for channel, text, is_key in leaves:
        skeleton, foreign = _skeleton_checked(text, scripts)
        if foreign is not None:
            raise PackageRefused("посторонняя_письменность", f"{channel}: U+{ord(foreign):04X}")
        skeletons.append((channel, skeleton, is_key))

    # A hash of a hidden text -- of the raw text or of its skeleton -- is a trace.
    digests = {}
    for name, text in hidden.items():
        digests[digest(text.encode("utf-8"))] = name
        digests[digest(_skeleton(text).encode("utf-8"))] = name
    for channel, text, _ in leaves:
        name = digests.get(text.strip().lower())
        if name is not None:
            raise PackageRefused("слепой_пакет_след_скрытого",
                                 f"{channel}: хеш скрытого раздела {name}")

    # Two streams: everything (keys too), and values only -- so that keys of a
    # record standing between two glued pieces cannot break the join.
    for stream in (skeletons, [piece for piece in skeletons if not piece[2]]):
        joined = "".join(skeleton for _, skeleton, _ in stream)
        starts, position = [], 0
        for _, skeleton, _ in stream:
            starts.append(position)
            position += len(skeleton)

        def channel_at(index: int, stream=stream, starts=starts) -> str:
            return stream[max(bisect.bisect_right(starts, index) - 1, 0)][0]

        for name, text in hidden.items():
            skeleton = _skeleton(text)
            if name in names:
                needles = _stems(text, minimum)
            elif len(skeleton) >= window:
                grams = {skeleton[i:i + window] for i in range(len(skeleton) - window + 1)}
                for index in range(len(joined) - window + 1):
                    if joined[index:index + window] in grams:
                        raise PackageRefused("слепой_пакет_след_скрытого",
                                             f"{channel_at(index)}: след скрытого раздела {name}")
                continue
            else:
                needles = {skeleton}
            for needle in needles:
                index = joined.find(needle)
                if index >= 0:
                    raise PackageRefused("слепой_пакет_след_скрытого",
                                         f"{channel_at(index)}: след скрытого раздела {name}")


# -- the build, in stages --------------------------------------------------------

def _check_blind(tables, stage, blind, declared_files, sections, withheld):
    """Exact equality with the shown list; returns the hidden texts, or None."""
    allowed = visible_sections(tables, stage, blind)
    if allowed is None:
        return None
    if declared_files:
        raise PackageRefused("слепой_пакет_с_файлами",
                             ", ".join(sorted(pair[0] for pair in declared_files)))
    extra = set(sections) - allowed
    if extra:
        raise PackageRefused("слепой_вопрос_показывает_лишнее", ", ".join(sorted(extra)))
    present = {name for name, value in sections.items() if value.strip()}
    missing = allowed - present
    if missing:
        raise PackageRefused("слепой_пакет_неполон", ", ".join(sorted(missing)))
    wanted = set(tables.stages["слепой_вопрос"]["прячем"])
    if (not isinstance(withheld, dict) or set(withheld) != wanted
            or not all(isinstance(text, str) for text in withheld.values())):
        raise _bad(f"для слепого пакета нужен withheld ровно с {sorted(wanted)}")
    cap = tables.vocabulary["пакет"]["предел_раздела_байт"]
    for name, text in withheld.items():
        _encodable(text, f"скрытый {name}")
        if len(_skeleton(text)) < tables.vocabulary["пакет"]["мин_длина_основы"]:
            raise _bad(f"скрытый {name} короче основы: сравнивать нечего")
        if len(text.encode("utf-8")) > cap:
            raise PackageRefused("превышение_размера", f"скрытый {name}")
    return dict(withheld)


def _check_sections(sections: dict, limits: dict) -> None:
    unknown = set(sections) - set(limits["разделы"])
    if unknown:
        raise PackageRefused("раздел_неизвестен", ", ".join(sorted(unknown)))
    for name, value in sections.items():
        if not value.strip():
            raise _bad(f"раздел {name} пуст")
        if len(value.encode("utf-8")) > limits["предел_раздела_байт"]:
            raise PackageRefused("превышение_размера", f"раздел {name}")


def _read_declared_files(root: Path, declared_files, tables):
    limits = tables.vocabulary["пакет"]
    if len(declared_files) > limits["предел_числа_файлов"]:
        raise PackageRefused("слишком_много_файлов",
                             f"{len(declared_files)} > {limits['предел_числа_файлов']}")
    seen, entries, files, spent = set(), [], {}, 0
    for path, file_class in declared_files:
        name = _folded(path)
        if name in seen:
            raise PackageRefused("файл_объявлен_дважды", path)
        seen.add(name)
        entry, text = read_file(root, path, file_class, tables)
        entries.append(entry)
        if text is not None:
            files[path] = text
            spent += entry.bytes_read
            if spent > limits["предел_пакета_байт"]:
                raise PackageRefused(
                    "превышение_размера",
                    f"пакет: файлы {spent} > {limits['предел_пакета_байт']}")
    entries.sort(key=lambda entry: entry.path)
    return entries, files


def build_package(root, declared_files, sections, registries, stage,
                  blind: bool = False, tables=None, withheld=None) -> Package:
    """Assemble one verifiable package.

    `declared_files` is an explicit list of `(path, class)` pairs -- the manifest
    is never discovered by walking the disk, because a glob makes the package
    depend on what happens to be lying around. In the blind mode `withheld` must
    carry the hidden texts (exactly the names of `слепой_вопрос.прячем`): the
    package is refused if anything of them shows up in what the critic would see.
    """
    tables = tables or tables_module.load()
    limits = tables.vocabulary["пакет"]

    _validate_input(root, declared_files, sections, registries, stage)
    root = Path(root)
    if stage not in tables.stages["стадии"]:
        raise PackageRefused("неизвестная_стадия", stage)
    try:
        inside_runs = root.resolve().is_relative_to(state_module.RUNS_ROOT.resolve())
    except OSError:
        inside_runs = False
    if inside_runs:
        raise PackageRefused("путь_запрещён", "корень сборки внутри каталога прогонов")

    try:
        home = Path.home().resolve()
        resolved_root = root.resolve()
    except (OSError, RuntimeError):
        raise PackageRefused("файл_нечитаем", "корень не разрешается")
    if resolved_root == home or (resolved_root.is_relative_to(home)
                                 and resolved_root.relative_to(home).parts[0].startswith(".")):
        raise PackageRefused("путь_запрещён", "корень сборки — домашний каталог или скрытый каталог в нём")

    forbidden = set(limits["не_попадает"]) & set(sections)
    if forbidden:
        raise PackageRefused("раздел_вне_пакета", ", ".join(sorted(forbidden)))

    hidden_texts = _check_blind(tables, stage, blind, declared_files, sections, withheld)
    _check_sections(sections, limits)
    entries, files = _read_declared_files(root, declared_files, tables)
    normalised = _build_registries(registries, tables, blind)

    leaves = _shown_leaves(sections, normalised, [entry.path for entry in entries])
    _check_secrets(leaves, limits)

    manifest_dicts = [entry.as_dict() for entry in entries]
    manifest_hash = digest(canonical_json(manifest_dicts))
    packed = canonical_json({
        "стадия": stage,
        "манифест": manifest_dicts,
        "хеш_манифеста": manifest_hash,
        "реестры": normalised,
        "разделы": dict(sections),
        "файлы": files,
    })
    # The size is settled before any search: a refusal for size must not wait for
    # an expensive comparison.
    if len(packed) > limits["предел_пакета_байт"]:
        raise PackageRefused(
            "превышение_размера",
            f"пакет {len(packed)} > {limits['предел_пакета_байт']}")
    if hidden_texts is not None:
        _check_traces(hidden_texts, leaves, limits)
    return Package(stage=stage, _bytes=packed, _hash=digest(packed))


def same_package(first: Package, second: Package) -> bool:
    """Equality of packages is a hash comparison and goes into the protocol."""
    return first.hash == second.hash and first.canonical_bytes == second.canonical_bytes
