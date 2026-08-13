#!/usr/bin/env python3
"""Б2 — the package: manifest, registries, canonical bytes, one hash.

Guarantee 1 of the whole design is that both critics got **the same verifiable
package, byte for byte**, proven by a hash rather than asserted. That makes two
things load-bearing:

**Determinism.** Two builds of the same input must produce the same bytes, so
nothing that varies between builds may enter the package — no build timestamp,
no dictionary order, no absolute host paths. The one obvious ingredient that
would quietly break it is a timestamp, which is exactly why there is a test that
builds twice and compares.

**Read once.** Files are read a single time and the *same* bytes are hashed,
canonicalised and handed to both vendors. Reading a second time at send-time
would leave a window in which the file changed between the hash and the wire.

Path rules are refusals, not warnings (§6.9): a symlink, a `..` component, a
path outside the root and an oversize file are all rejected. `existing_evidence`
must exist and its hash is checked; `planned_output` is created later, so its
absence is normal (§7.3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

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
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


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


def _check_path(root: Path, relative: str, limits: dict) -> Path:
    """Every refusal of §6.9, in the order that makes the message useful."""
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise PackageRefused("путь_с_родительским_переходом", relative)
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


def read_file(root: Path, relative: str, file_class: str, tables) -> ManifestEntry:
    """Read one declared file once, or refuse with a named reason."""
    classes = set(tables.precheck["классы_файлов"])
    if file_class not in classes:
        raise PackageRefused("неизвестный_класс_файла", f"{relative}: {file_class}")
    limits = tables.vocabulary["пакет"]
    root = Path(root)
    target = _check_path(root, relative, limits)

    if not target.exists():
        if file_class == "planned_output":
            # Declared, created later: absence is the normal case (§7.3).
            return ManifestEntry(relative, file_class, None, None)
        raise PackageRefused("отсутствие_обязательного_файла", relative)

    data = target.read_bytes()
    if len(data) > limits["предел_файла_байт"]:
        raise PackageRefused(
            "превышение_размера",
            f"{relative}: {len(data)} > {limits['предел_файла_байт']}")
    return ManifestEntry(relative, file_class, digest(data), len(data))


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
    """An assembled package and the hash that proves two of them are equal."""

    stage: str
    manifest: list
    manifest_hash: str
    registries: dict
    sections: dict
    files: dict = field(repr=False, default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "стадия": self.stage,
            "манифест": [entry.as_dict() for entry in self.manifest],
            "хеш_манифеста": self.manifest_hash,
            "реестры": self.registries,
            "разделы": self.sections,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def hash(self) -> str:
        return digest(self.canonical_bytes)

    def material(self) -> str:
        """What actually goes down the critic's stdin — never into argv (§5.2)."""
        return self.canonical_bytes.decode("utf-8")


def visible_sections(tables, stage: str, blind: bool) -> set | None:
    """Which sections a blind first question may carry (stages.yaml).

    Blind means the critic is asked for a solution *before* being shown ours:
    anchoring is the failure mode, and the cure is to hide the answer, not the
    context. So everything except the hidden list stays.
    """
    if not blind:
        return None
    rules = tables.stages["слепой_вопрос"]
    if tables.stages["стадии"][stage]["первый_вопрос"] != "предложи_решение":
        raise PackageRefused("слепой_вопрос_не_на_этой_стадии", stage)
    return set(rules["показываем"])


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

    forbidden = set(limits["не_попадает"]) & set(sections)
    if forbidden:
        raise PackageRefused("раздел_вне_пакета", ", ".join(sorted(forbidden)))

    allowed = visible_sections(tables, stage, blind)
    if allowed is not None:
        hidden = set(sections) - allowed
        if hidden:
            raise PackageRefused("слепой_вопрос_показывает_лишнее",
                                 ", ".join(sorted(hidden)))

    seen, manifest, files = set(), [], {}
    for path, file_class in declared_files:
        if path in seen:
            raise PackageRefused("файл_объявлен_дважды", path)
        seen.add(path)
        entry = read_file(root, path, file_class, tables)
        manifest.append(entry)
        if entry.sha256 is not None:
            files[path] = (root / path).read_bytes()

    expected = set(limits["реестры"])
    if set(registries) != expected:
        raise PackageRefused("реестры_не_полны",
                             f"{sorted(registries)} против {sorted(expected)}")

    kinds = set(limits["виды_решений_в_реестре"])
    for decision in registries["решения"]:
        if decision.get("kind") not in kinds:
            raise PackageRefused("неизвестный_вид_решения", str(decision.get("kind")))

    journal = []
    for record in registries["журнал_доказательств"]:
        check_creator(record, tables)
        journal.append({**record, "отпечаток": fingerprint(record, tables)})

    normalised = {
        "решения": sorted(registries["решения"], key=lambda d: d["decision_id"]),
        "области": sorted(registries["области"], key=lambda a: a["area_id"]),
        "журнал_доказательств": sorted(journal, key=lambda r: r["отпечаток"]),
    }

    manifest_hash = digest(canonical_json([entry.as_dict() for entry in manifest]))
    package = Package(stage=stage, manifest=manifest, manifest_hash=manifest_hash,
                      registries=normalised, sections=dict(sections), files=files)

    if len(package.canonical_bytes) > limits["предел_пакета_байт"]:
        raise PackageRefused(
            "превышение_размера",
            f"пакет {len(package.canonical_bytes)} > {limits['предел_пакета_байт']}")
    return package


def same_package(first: Package, second: Package) -> bool:
    """Equality of packages is a hash comparison and goes into the protocol."""
    return first.hash == second.hash
