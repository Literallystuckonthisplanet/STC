#!/usr/bin/env python3
"""Б2 — the package: manifest, registries, canonical bytes, one hash.

Guarantee 1 of the whole design is that both critics got **the same verifiable
package, byte for byte**, proven by a hash rather than asserted. What this
module guarantees, and by what:

**Determinism.** Two builds of the same input give the same bytes. Nothing that
varies between builds enters the package (no timestamp, no host path); every
mapping is serialised with sorted keys; the manifest, the file texts, the
registries and the evidence journal are sorted by content, so neither the
declaration order nor the interpreter's hash seed can move the hash.

**Read once, from a descriptor.** A declared file is opened exactly once, by
walking the path component by component with `O_NOFOLLOW` relative to a
directory descriptor, so a symlink swapped in at any level after the early
`_check_path` is still refused. The same bytes give the hash and the text that
travels in the package. Hard links, FIFOs, devices, directories, oversize and
non-UTF-8 files are refused by name.

**A snapshot.** The canonical bytes are computed once at the end of the build
and stored; `hash` and `material()` return the stored value, and the data
fields are deep copies, so mutating the caller's objects (or deleting the file)
afterwards changes nothing.

**Not guaranteed here** (needs table changes, decided elsewhere): closed schemas
of registry records, filtering registries in the blind mode, allowed/forbidden
path lists, a closed list of section names outside the blind mode.

Path rules are refusals, not warnings (§6.9). `existing_evidence` must exist;
`planned_output` is created later, so its absence is normal (§7.3).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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


def _check_path(root: Path, relative: str) -> Path:
    """Early, readable refusals of §6.9. The real defence is the descriptor walk."""
    if not isinstance(relative, str):
        raise PackageRefused("некорректный_вход", f"путь не строка: {relative!r}")
    if "\x00" in relative:
        raise PackageRefused("файл_нечитаем", "NUL в пути")
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise PackageRefused("путь_с_родительским_переходом", relative)
    if not relative or relative != "/".join(PurePosixPath(relative).parts):
        raise PackageRefused("путь_не_канонический", relative)
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


def _read_by_descriptors(root: Path, relative: str, cap: int):
    """Open `relative` below `root` without ever following a link; read once.

    Returns `(data, (st_dev, st_ino))`, or None if some component is absent.
    """
    parts = PurePosixPath(relative).parts
    opened = []
    try:
        try:
            current = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        except (OSError, ValueError) as error:
            raise PackageRefused("файл_нечитаем", f"корень: {error}")
        opened.append(current)
        for part in parts[:-1]:
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
        try:
            leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                           dir_fd=current)
        except FileNotFoundError:
            return None
        except ValueError as error:
            raise PackageRefused("файл_нечитаем", f"{relative}: {error}")
        except OSError as error:
            raise _classify_open_error(error, parts[-1], current, relative)
        opened.append(leaf)

        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode):
            raise PackageRefused("файл_не_обычный", relative)
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
        return b"".join(chunks), (info.st_dev, info.st_ino)
    finally:
        for descriptor in opened:
            os.close(descriptor)


def read_file(root: Path, relative: str, file_class: str, tables):
    """Read one declared file once; return `(entry, text, identity)` or refuse.

    The one read yields the bytes for the hash *and* the text that goes into the
    package. `text` and `identity` are None only for an absent `planned_output`.
    """
    classes = set(tables.precheck["классы_файлов"])
    if not isinstance(file_class, str) or file_class not in classes:
        raise PackageRefused("неизвестный_класс_файла", f"{relative}: {file_class}")
    cap = tables.vocabulary["пакет"]["предел_файла_байт"]
    root = Path(root)
    _check_path(root, relative)

    found = _read_by_descriptors(root, relative, cap)
    if found is None:
        if file_class == "planned_output":
            # Declared, created later: absence is the normal case (§7.3).
            return ManifestEntry(relative, file_class, None, None), None, None
        raise PackageRefused("отсутствие_обязательного_файла", relative)
    data, identity = found
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageRefused("файл_не_текст", relative)
    return ManifestEntry(relative, file_class, digest(data), len(data)), text, identity


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
    """A snapshot: canonical bytes fixed at build time, and the hash of them."""

    stage: str
    manifest: list
    manifest_hash: str
    registries: dict
    sections: dict
    files: dict
    _bytes: bytes
    _hash: str

    def as_dict(self) -> dict:
        """A fresh deep copy of the packaged data on every call."""
        return json.loads(self._bytes.decode("utf-8"))

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


def _validate_input(declared_files, sections, registries, stage):
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
    if not isinstance(registries, dict):
        raise _bad("реестры не словарь")


def _registry_list(registries, name, key=None):
    items = registries[name]
    if not isinstance(items, (list, tuple)):
        raise _bad(f"реестр {name} не список")
    for item in items:
        if not isinstance(item, dict):
            raise _bad(f"запись реестра {name} не словарь")
        if key is not None and not isinstance(item.get(key), str):
            raise _bad(f"запись реестра {name} без строкового {key}")
    if key is not None:
        ids = [item[key] for item in items]
        if len(set(ids)) != len(ids):
            raise PackageRefused("дубль_в_реестре", f"{name}: {key}")
    return list(items)


def build_package(root, declared_files, sections, registries, stage,
                  blind: bool = False, tables=None) -> Package:
    """Assemble one verifiable package.

    `declared_files` is an explicit list of `(path, class)` pairs — the manifest
    is never discovered by walking the disk, because a glob makes the package
    depend on what happens to be lying around.
    """
    tables = tables or tables_module.load()
    limits = tables.vocabulary["пакет"]
    root = Path(root)

    _validate_input(declared_files, sections, registries, stage)
    if stage not in tables.stages["стадии"]:
        raise PackageRefused("неизвестная_стадия", stage)

    forbidden = set(limits["не_попадает"]) & set(sections)
    if forbidden:
        raise PackageRefused("раздел_вне_пакета", ", ".join(sorted(forbidden)))

    allowed = visible_sections(tables, stage, blind)
    if allowed is not None:
        # Exact equality: a blind package that lacks a shown section is as wrong
        # as one that carries a hidden one. A blank value counts as missing.
        if declared_files:
            raise PackageRefused("слепой_пакет_с_файлами",
                                 ", ".join(sorted(str(pair[0]) for pair in declared_files)))
        hidden = set(sections) - allowed
        if hidden:
            raise PackageRefused("слепой_вопрос_показывает_лишнее",
                                 ", ".join(sorted(hidden)))
        present = {name for name, value in sections.items() if value.strip()}
        missing = allowed - present
        if missing:
            raise PackageRefused("слепой_пакет_неполон", ", ".join(sorted(missing)))

    seen_names, seen_files, entries, files = set(), set(), [], {}
    for path, file_class in declared_files:
        name = unicodedata.normalize("NFC", path).casefold()
        if name in seen_names:
            raise PackageRefused("файл_объявлен_дважды", path)
        seen_names.add(name)
        entry, text, identity = read_file(root, path, file_class, tables)
        if identity is not None:
            if identity in seen_files:
                raise PackageRefused("файл_объявлен_дважды", path)
            seen_files.add(identity)
        entries.append(entry)
        if text is not None:
            files[path] = text
    entries.sort(key=lambda entry: entry.path)

    expected = set(limits["реестры"])
    if set(registries) != expected:
        raise PackageRefused("реестры_не_полны",
                             f"{sorted(registries)} против {sorted(expected)}")

    decisions = _registry_list(registries, "решения", "decision_id")
    areas = _registry_list(registries, "области", "area_id")
    records = _registry_list(registries, "журнал_доказательств")

    kinds = set(limits["виды_решений_в_реестре"])
    for decision in decisions:
        kind = decision.get("kind")
        if not isinstance(kind, str) or kind not in kinds:
            raise PackageRefused("неизвестный_вид_решения", str(kind))

    journal = []
    for record in records:
        if not isinstance(record.get("тип"), str):
            raise _bad("запись журнала без строкового типа")
        check_creator(record, tables)
        journal.append({**record, "отпечаток": fingerprint(record, tables)})

    normalised = {
        "решения": sorted(decisions, key=lambda d: d["decision_id"]),
        "области": sorted(areas, key=lambda a: a["area_id"]),
        "журнал_доказательств": sorted(
            journal, key=lambda r: (r["отпечаток"], canonical_json(r))),
    }

    manifest_dicts = [entry.as_dict() for entry in entries]
    manifest_hash = digest(canonical_json(manifest_dicts))
    payload = {
        "стадия": stage,
        "манифест": manifest_dicts,
        "хеш_манифеста": manifest_hash,
        "реестры": normalised,
        "разделы": dict(sections),
        "файлы": files,
    }
    packed = canonical_json(payload)
    if len(packed) > limits["предел_пакета_байт"]:
        raise PackageRefused(
            "превышение_размера",
            f"пакет {len(packed)} > {limits['предел_пакета_байт']}")

    # Deep copies, made from the very bytes that were hashed.
    frozen = json.loads(packed.decode("utf-8"))
    return Package(stage=stage, manifest=list(entries), manifest_hash=manifest_hash,
                   registries=frozen["реестры"], sections=frozen["разделы"],
                   files=frozen["файлы"], _bytes=packed, _hash=digest(packed))


def same_package(first: Package, second: Package) -> bool:
    """Equality of packages is a hash comparison and goes into the protocol."""
    return first.hash == second.hash
