"""Список поломок из инструкции «ломать таблицу», сделанный исполнимым.

Ручная инструкция сама по себе — обещание: она говорит, что такая-то поломка
ловится таким-то сторожем, и проверить это можно только руками. Ревью #21
показало, чем это кончается: три подмены в реестре находок прошли все тесты,
а одна находка была объявлена устранённой при живом дефекте.

Поэтому каждая строка инструкции живёт здесь и проверяется двумя условиями:

1. **положительный контроль** — до мутации названный сторож ПРОХОДИТ;
2. **отрицательный** — после мутации падает ИМЕННО он и ИМЕННО с той причиной,
   которая записана. Падение чего-то другого — не «поймано», а совпадение.

Второе условие поставлено ревью #21 после разбора П18: там проверялось
отсутствие причины переоткрытия, а падало из-за отсутствующего разрешения —
нужное правило могло не выполниться вовсе.
"""

import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "core" / "scripts" / "roundtable" / "tables"
SCRIPTS = ROOT / "core" / "scripts"
SUITE = Path(__file__).with_name("test_roundtable_tables.py")


def _module():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import roundtable.tables
    return roundtable.tables


def _blocks(raw):
    return raw["blocks"]


def _grant(raw):
    return raw["blocks"]["разрешения_исполнения"][0]


def _absorb(raw, keep_text: bool):
    b = _blocks(raw)["блоки"]
    b["БТ2"].update({"состояние": "объединён_с", "объединён_с": "БИ"})
    b["БИ"]["поглощает"] = ["БТ2"]
    b["БИ"]["зависит"] = ["Б2", "БТ"]
    b["БИ"]["пишет"] = sorted(set(b["БИ"]["пишет"]) | set(b["БТ2"]["пишет"]))
    b["БИ"]["читает"] = sorted(set(b["БИ"]["читает"]) | set(b["БТ2"]["читает"]))
    b["БИ"]["приёмка"] = b["БИ"]["приёмка"] + [
        {"id": i["id"], "условие": i["условие"] if keep_text else "ПОДМЕНЕНО"}
        for i in b["БТ2"]["приёмка"]]


def _cycle(raw):
    b = _blocks(raw)["блоки"]
    b["БТ2"].update({"состояние": "объединён_с", "объединён_с": "БИ",
                     "поглощает": ["БИ"]})
    b["БИ"].update({"состояние": "объединён_с", "объединён_с": "БТ2",
                    "поглощает": ["БТ2"]})


def _reopen_without_reason(raw):
    """Переоткрыть Б9 и ВЫДАТЬ ему честное разрешение на текущий объём.

    Иначе первым сработает замок полномочий, и мы засчитаем поимку не той
    мутации — ровно тот дефект, который ревью #21 нашло в ручной инструкции.
    """
    module = _module()
    _blocks(raw)["блоки"]["Б9"]["состояние"] = "переоткрыт"
    grant = _grant(raw)
    grant["блоки"].append("Б9")
    block = module.Block.parse("Б9", _blocks(raw)["блоки"]["Б9"], raw["vocabulary"])
    grant["scope_sha256"]["Б9"] = block.scope_sha256(_blocks(raw))


def _drop_env_from_the_fingerprint(root):
    spec = _blocks(root)["отпечаток_изоляции"]
    spec["входит_в_отпечаток"].remove("хеш_нормализованного_env")
    del spec["пока_не_вычисляется"]["хеш_нормализованного_env"]


def _swap_a_finding_to_a_foreign_break(raw):
    """Оставить статус «устранена», подменив поломку на чужую существующую.

    Программа не выведет смысловую связь «эта поломка проверяет ИМЕННО этот
    дефект» — её проверяют один раз при ревью и дальше защищают от подмены.
    """
    for finding in raw["findings"]["находки"]:
        if finding["статус"] != "устранена":
            continue
        if finding.get("поломка", "вне_таблиц") == "вне_таблиц":
            continue
        # Меняем ТОЛЬКО привязку. Раньше опыт заодно переписывал имя теста на
        # литерал "загрузчик", теста с таким именем нет — и подмену ловила
        # старая проверка существования, а не новый замок. Опыт доказывал не
        # то, что должен: ревью #23 поймало это на разборе.
        finding["поломка"] = "П10"          # опечатка в состоянии блока
        return
    raise AssertionError("нет находки с исполнимой поломкой")


def _reclose_with_a_foreign_break(raw):
    """Снова объявить R15-8 устранённой, прикрывшись чужой поломкой.

    Настоящий дефект при этом жив: полный проверяльщик по-прежнему запускает
    один файл тестов.
    """
    guards = {case[0]: case[3] for case in CASES}
    for finding in raw["findings"]["находки"]:
        if finding["id"] != "R15-8":
            continue
        finding.pop("критерий", None)
        finding["статус"] = "устранена"
        finding["поломка"] = "П29"
        finding["тест"] = guards["П29"]     # настоящее имя теста, не литерал
        return
    raise AssertionError("R15-8 в реестре нет")


def _point_a_finding_at_a_stranger(raw):
    """Подменить сторожа у находки, чью поломку стережёт ИМЕННО тест.

    ⚠️ Бить надо по такой: у находок, помеченных `вне_таблиц`, и у тех, чья
    поломка ловится загрузчиком или контрактом, имя теста сверять не с чем —
    это остаточная слабость реестра, и она посчитана в рендере.
    """
    guards = {case[0]: case[3] for case in CASES}
    for finding in raw["findings"]["находки"]:
        if finding["статус"] != "устранена":
            continue
        guard = guards.get(finding.get("поломка", ""))
        if guard and guard not in ("контракт", "загрузчик"):
            finding["тест"] = "test_precheck_states_what_it_cannot_do"
            return
    raise AssertionError("нет находки, чью поломку стережёт именованный тест")


def _first(findings, status):
    return next(f for f in findings if f["статус"] == status)


# (id, что ломаем, мутация, сторож, кусок ожидаемого сообщения)
#
# Сторож: "загрузчик" | "контракт" | имя теста из test_roundtable_tables.py.
CASES = [
    ("П1", "убрать карту scope_sha256 из разрешения",
     lambda r: _grant(r).pop("scope_sha256"), "контракт", "без карты scope_sha256"),
    ("П2", "подменить отпечаток объёма Б1",
     lambda r: _grant(r)["scope_sha256"].__setitem__("Б1", "a" * 64),
     "контракт", "Б1: в работе"),
    ("П3", "дописать Б1 файл в пишет после разрешения",
     lambda r: _blocks(r)["блоки"]["Б1"]["пишет"].append("core/scripts/roundtable/cli.py"),
     "контракт", "Б1: в работе"),
    ("П4", "переписать текст критерия под прежним ID",
     lambda r: _blocks(r)["блоки"]["Б1"]["приёмка"][0].__setitem__("условие", "что угодно"),
     "контракт", "Б1: в работе"),
    ("П5", "перенести БТ2 перед Б1 в порядке",
     lambda r: (_blocks(r)["порядок"].remove("БТ2"),
                _blocks(r)["порядок"].insert(_blocks(r)["порядок"].index("Б1"), "БТ2")),
     "контракт", "в работе"),
    ("П6", "убрать Б1 из до_закрытия ремонтного шлюза",
     lambda r: _blocks(r)["шлюзы"]["ремонт_после_ревью_12"]["до_закрытия"].remove("Б1"),
     "контракт", "в работе"),
    ("П7", "пометить Б15 сделанным при незакрытом ремонте",
     lambda r: _blocks(r)["блоки"]["Б15"].__setitem__("состояние", "сделано"),
     "контракт", "шлюз ремонт_после_ревью_12"),
    ("П8", "удалить native_uuid из основания",
     lambda r: _grant(r)["основание"].pop("native_uuid"),
     "контракт", "без ['native_uuid']"),
    ("П9", "фальшивый sha256 у заключения ревью",
     lambda r: _blocks(r)["заключения_ревью"][0]["основание"].__setitem__("sha256", "0" * 64),
     "test_every_real_permission_actually_resolves", "sha256"),
    ("П10", "опечатка в состоянии блока",
     lambda r: _blocks(r)["блоки"]["Б9"].__setitem__("состояние", "сделанно"),
     "загрузчик", "нет в словаре"),
    ("П11", "строка вместо списка в области записи",
     lambda r: _blocks(r)["блоки"]["Б9"].__setitem__("пишет", "core/x.py"),
     "загрузчик", "ожидался список"),
    ("П12", "выдуманное внешнее действие",
     lambda r: _blocks(r)["блоки"]["Б9"].__setitem__("внешние_действия", ["удалить_всё"]),
     "загрузчик", "нет в словаре"),
    ("П13", "нецелое объявленное количество",
     lambda r: _blocks(r)["блоки"]["Б9"].__setitem__("объявленное_количество", {"таблицы": 0}),
     "загрузчик", "положительное целое"),
    ("П14", "цикл поглощения БТ2↔БИ", _cycle, "контракт", "цикл поглощения"),
    ("П15", "поглотить БТ2, сохранив ID приёмки и заменив текст",
     lambda r: _absorb(r, keep_text=False), "контракт", "потеряна или подменена"),
    ("П16", "один ID приёмки у двух блоков",
     lambda r: _blocks(r)["блоки"]["Б9"].__setitem__(
         "приёмка", [{"id": "Б1-1", "условие": "чужой"}]),
     "контракт", "у двух блоков"),
    ("П17", "чужая версия контракта у blocks.yaml",
     lambda r: _blocks(r).__setitem__("версия_контракта", 99),
     "загрузчик", "contract version"),
    ("П18", "переоткрыть блок, не сказав почему",
     _reopen_without_reason, "контракт", "переоткрыт, но не сказано почему"),
    ("П19", "удалить находку из реестра",
     lambda r: r["findings"]["находки"].pop(0),
     "test_no_finding_can_be_quietly_dropped", "находка"),
    ("П20", "устранённая находка ссылается на несуществующий тест",
     lambda r: _first(r["findings"]["находки"], "устранена").__setitem__("тест", "test_нет"),
     "test_a_finding_marked_fixed_names_a_test_that_actually_exists", "в наборе нет"),
    ("П21", "находка назначена несуществующему критерию",
     lambda r: _first(r["findings"]["находки"], "назначена_блоку").__setitem__("критерий", "Б99-1"),
     "test_a_finding_assigned_to_a_block_names_a_criterion_that_exists", "нет"),
    ("П22", "избыточна без обоснования",
     lambda r: (r["findings"]["находки"][0].__setitem__("статус", "избыточна"),
                r["findings"]["находки"][0].pop("почему", None)),
     "test_a_dismissed_or_open_finding_carries_its_reason", "без обоснования"),
    ("П23", "убрать «расхождение закрывает шлюз»",
     lambda r: _blocks(r)["отпечаток_изоляции"].pop("расхождение"),
     "test_a_drifted_fingerprint_closes_the_gate_rather_than_warning", "расхождение"),
    ("П24", "удалить закрытый словарь оценки критерия",
     lambda r: r["vocabulary"].pop("оценка_критерия"),
     "test_the_idea_stage_vocabularies_are_closed_sets", "оценка_критерия"),
    ("П25", "удалить историю разрешения Б2",
     lambda r: _blocks(r)["история_разрешений"].pop(2),
     "test_a_reopened_block_keeps_the_permission_it_was_first_started_under", "126e123a"),
    ("П29", "назначить находку критерию УЖЕ ЗАКРЫТОГО блока",
     lambda r: _first(r["findings"]["находки"], "назначена_блоку").__setitem__("критерий", "Б3а-1"),
     "test_a_finding_may_only_be_assigned_to_a_block_still_open", "закрыт"),
    ("П30", "подменить текст находки, сохранив её ID",
     lambda r: r["findings"]["находки"][0].__setitem__("что", "ПОДМЕНЕНО"),
     "test_the_text_of_every_finding_is_pinned", "подменён"),
    # ⚠️ Мутация бьёт по находке с ИСПОЛНИМОЙ поломкой. У находок, помеченных
    # `вне_таблиц`, сторожем служит только имя теста, и подмену там поймать
    # нечем — это остаточная слабость, и она посчитана в рендере реестра.
    ("П34", "убрать правило «переход к архитектуре только по явному ОК»",
     lambda r: _blocks(r)["блоки"]["БИ"].__setitem__(
         "приёмка", [i for i in _blocks(r)["блоки"]["БИ"]["приёмка"]
                     if i["id"] != "БИ-13"]),
     "test_the_conveyor_rules_survive_as_acceptance_criteria", "пропал"),
    ("П35", "выхолостить критерий конвейера, сохранив его ID",
     lambda r: next(i for i in _blocks(r)["блоки"]["БП"]["приёмка"]
                    if i["id"] == "БП-1").__setitem__("условие", "готовность определяется движком"),
     "test_the_conveyor_rules_survive_as_acceptance_criteria", "выхолощено"),
    # Обе прогнало ревью #25 против прежнего замка — обе прошли.
    ("П36", "удалить критерий «прежняя редакция не переписывается»",
     lambda r: _blocks(r)["блоки"]["БУ"].__setitem__(
         "приёмка", [i for i in _blocks(r)["блоки"]["БУ"]["приёмка"] if i["id"] != "БУ-3"]),
     "test_the_conveyor_rules_survive_as_acceptance_criteria", "выхолощено"),
    ("П37", "вывернуть критерий наизнанку, сохранив опорные слова",
     lambda r: next(i for i in _blocks(r)["блоки"]["БП"]["приёмка"]
                    if i["id"] == "БП-1").__setitem__(
         "условие", "готовность НЕ требует трёх условий: личное принятие Антона не требуется"),
     "test_the_conveyor_rules_survive_as_acceptance_criteria", "выхолощено"),
    ("П38", "снять архитектуру со шлюза изоляции, оставив ей вызов модели",
     lambda r: _blocks(r)["шлюзы"]["изоляция_подтверждена"]["блокирует"].remove("БА"),
     "test_a_block_calling_models_is_held_by_the_isolation_gate", "вызов_модели"),
    ("П39", "снять зависимость выпуска от конвейера",
     lambda r: _blocks(r)["блоки"]["Б13"].__setitem__("зависит", ["Б12"]),
     "test_the_conveyor_is_mandatory_for_release", "не зависит от конвейера"),
    ("П40", "удалить раздел согласий целиком",
     lambda r: _blocks(r).pop("согласия"),
     "test_the_consent_rule_is_mandatory_and_pinned", "пропал"),
    ("П41", "снять зависимость архитектуры от блока запуска вендоров",
     lambda r: _blocks(r)["блоки"]["БА"].__setitem__("зависит", ["БУ"]),
     "test_a_block_calling_models_must_depend_on_the_launcher", "звать нечем"),
    ("П42", "превратить два согласия в три",
     lambda r: _blocks(r)["согласия"].__setitem__("сколько", 3),
     "test_the_consent_rule_is_mandatory_and_pinned", "два ОК"),
    ("П43", "назначить запускателем сборщик команд, который не запускает",
     lambda r: _blocks(r)["отпечаток_изоляции"].__setitem__("блок_запуска", "Б3а"),
     "test_the_launcher_is_a_block_that_can_actually_launch", "процессов не запускает"),
    ("П44", "объявить успешным любой вердикт отчёта изоляции",
     lambda r: _blocks(r)["отпечаток_изоляции"].__setitem__("успешный_вердикт", "INCONCLUSIVE"),
     "test_the_isolation_report_must_be_a_successful_one", "PASS"),
    ("П45", "вернуть находку с положительной приёмки на отрицательный критерий",
     lambda r: next(f for f in r["findings"]["находки"]
                    if f["id"] == "R23-1").__setitem__("критерий", "БИ-13"),
     "test_the_binding_between_a_finding_and_its_break_is_pinned", "привязка"),
    ("П46", "снять зависимость архитектуры от расчёта вердикта",
     lambda r: _blocks(r)["блоки"]["БА"].__setitem__("зависит", ["БУ", "Б3б", "Б5"]),
     "test_the_architecture_stage_waits_for_the_machinery_it_needs", "не ждёт Б6"),
    ("П47", "выбросить обязательный файл из списка артефактов",
     lambda r: _blocks(r)["отпечаток_изоляции"]["артефакты"].pop("хеш_probe"),
     "контракт", "ядро"),
    ("П48", "объявить в отпечатке поле, которое никто не считает",
     lambda r: _blocks(r)["отпечаток_изоляции"]["входит_в_отпечаток"].append("хеш_чего_нибудь"),
     "контракт", "обещано, но не считается"),
    ("П49", "тихо сузить отпечаток: выкинуть окружение из обоих списков разом",
     _drop_env_from_the_fingerprint,
     "test_the_fingerprint_does_not_promise_more_than_it_computes", "сужен"),
    ("П50", "отложить поле отпечатка без владельца",
     lambda r: _blocks(r)["отпечаток_изоляции"]["пока_не_вычисляется"]["хеш_схемы_ответа"].pop("закрывает"),
     "контракт", "без владельца"),
    ("П51", "отдать поле критерию, который о нём не говорит",
     lambda r: _blocks(r)["отпечаток_изоляции"]["пока_не_вычисляется"]["хеш_нормализованного_env"].update(закрывает="Ш2-1"),
     "контракт", "не говорит"),
    ("П52", "вывести владельца полного отпечатка из шлюза изоляции",
     lambda r: _blocks(r)["шлюзы"]["изоляция_подтверждена"]["до_закрытия"].remove("Ш2"),
     "контракт", "не держит шлюз"),
    ("П55", "закрыть блок, не назвав его коммитов",
     lambda r: _blocks(r)["блоки"]["БТ2"].update(состояние="сделано"),
     "контракт", "коммиты не названы"),
    ("П56", "выбросить файл тестов у блока, пишущего код движка",
     lambda r: _blocks(r)["блоки"]["Б5"]["пишет"].remove("deploy/tests/test_roundtable_registry.py"),
     "контракт", "файл тестов не объявлен"),
    ("П57", "увести блок от сверки, дописав его в «до правила»",
     lambda r: _blocks(r)["сверка_записи"]["до_правила"].append("Б1"),
     "test_the_write_scope_rule_is_pinned", "до правила"),
    ("П58", "записать коммиты незакрытому блоку",
     lambda r: _blocks(r)["блоки"]["Б5"].update(коммиты=["a" * 40]),
     "контракт", "не закрыт"),
    ("П59", "поставить в одну волну два блока с общим файлом",
     lambda r: _blocks(r)["исполнение"]["блоки"]["Б10"].update(волна=9),
     "контракт", "пишут общее"),
    ("П60", "поставить блок в одну волну с его зависимостью",
     lambda r: _blocks(r)["исполнение"]["блоки"]["БИ"].update(волна=3),
     "контракт", "не раньше"),
    ("П61", "исполнить блок без внешнего критика",
     lambda r: _blocks(r)["исполнение"]["блоки"]["Б5"]["ревью"].remove("codex"),
     "контракт", "без внешнего критика"),
    ("П62", "оставить незакрытый блок без исполнителя",
     lambda r: _blocks(r)["исполнение"]["блоки"].pop("Б6"),
     "контракт", "без исполнителя"),
    ("П63", "выкинуть сверку подготовленного из шагов исполнения",
     lambda r: _blocks(r)["исполнение"]["шаги"].pop(3),
     "test_the_execution_plan_is_checked_by_the_contract", "сверка подготовленного"),
    ("П54", "выхолостить приёмку: проверять не каждый из семи компонентов",
     lambda r: _blocks(r)["блоки"]["Ш2"]["приёмка"][6].update(условие="полный корректный отпечаток проходит"),
     "test_every_deferred_field_has_an_owner_with_acceptance", "выхолощена"),
    ("П32", "подменить поломку находки на чужую, но существующую",
     _swap_a_finding_to_a_foreign_break,
     "test_the_binding_between_a_finding_and_its_break_is_pinned", "привязка"),
    ("П33", "вернуть ложную «устранена», сославшись на чужую поломку и её тест",
     _reclose_with_a_foreign_break,
     "test_the_binding_between_a_finding_and_its_break_is_pinned", "привязка"),
    ("П31", "сослать находку на существующий, но посторонний тест",
     _point_a_finding_at_a_stranger,
     "test_a_fixed_finding_names_a_guard_that_actually_guards_it", "не стережёт"),
]


@pytest.fixture
def scratch():
    """Свежая копия таблиц на КАЖДЫЙ опыт.

    Общий каталог позволял следующему опыту унаследовать поломку предыдущего,
    и тогда «поймана» относилось бы не к той мутации.
    """
    directory = Path(tempfile.mkdtemp(prefix="rt-mutation-"))
    try:
        for path in CANON.glob("*.yaml"):
            shutil.copy(path, directory / path.name)
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _write(raw, directory):
    for name, table in raw.items():
        (directory / f"{name}.yaml").write_text(
            yaml.dump(table, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _pytest_one(name, directory):
    """Прогнать один тест против мутированных таблиц. True если ПРОШЁЛ."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", f"{SUITE}::{name}", "-q", "--tb=line",
         "-p", "no:cacheprovider"],
        cwd=ROOT, env=dict(os.environ, ROUNDTABLE_TABLES_DIR=str(directory)),
        capture_output=True, text=True)
    assert done.returncode in (0, 1), (
        f"{name}: pytest вернул {done.returncode} — тест не выполнялся\n{done.stdout[-400:]}")
    return done.returncode == 0, done.stdout


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_the_break_list_is_measured_and_not_promised(case, scratch):
    identifier, what, mutate, guard, fragment = case
    assert fragment, (
        f"{identifier}: у опыта нет ожидаемой причины. Без неё «упал нужный тест» "
        f"не отличается от «упал по случайности» — ровно тот разрыв, который "
        f"ревью #22 нашло у П23, П24 и П25")
    module = _module()

    # 1. положительный контроль: на чистой копии сторож молчит
    if guard == "загрузчик" or guard == "контракт":
        module.load(scratch).check()
    else:
        passed, output = _pytest_one(guard, scratch)
        assert passed, f"{identifier}: сторож {guard} падает ДО мутации\n{output[-500:]}"

    # 2. мутация
    raw = {name: module.load_table(name, scratch) for name in module.TABLE_NAMES}
    mutate(raw)
    _write(raw, scratch)

    # 3. отрицательный: падает именно назначенный сторож и по своей причине
    if guard == "загрузчик":
        with pytest.raises(module.ContractError) as error:
            module.load(scratch)
        assert fragment in str(error.value), f"{identifier}: {what} — чужая причина: {error.value}"
    elif guard == "контракт":
        module.load(scratch)          # форма обязана остаться валидной
        with pytest.raises(module.ContractError) as error:
            module.load(scratch).check()
        assert fragment in str(error.value), f"{identifier}: {what} — чужая причина: {error.value}"
    else:
        passed, output = _pytest_one(guard, scratch)
        assert not passed, f"{identifier}: {what} — сторож {guard} не заметил"
        assert fragment, f"{identifier}: ожидаемая причина не задана — опыт ничего не различает"
        assert fragment in output, f"{identifier}: упал по чужой причине\n{output[-500:]}"
