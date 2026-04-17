"""Resolve common 1C BSL surface-syntax chains to canonical platform-help API names.

This module centralizes language-level normalization for queries that developers write
in code (for example ``Документы.РеализацияТоваровУслуг.СоздатьДокумент``), while
platform help stores placeholder-based canonical names
(``ДокументМенеджер.<Имя документа>.СоздатьДокумент``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SurfaceFamilySpec:
    family: str
    collection_manager: str
    collection_item_placeholder: str
    item_manager_template: str


_SURFACE_FAMILY_SPECS: dict[str, SurfaceFamilySpec] = {
    "Документы": SurfaceFamilySpec(
        family="Документы",
        collection_manager="ДокументыМенеджер",
        collection_item_placeholder="<Имя документа>",
        item_manager_template="ДокументМенеджер.<Имя документа>",
    ),
    "Справочники": SurfaceFamilySpec(
        family="Справочники",
        collection_manager="СправочникиМенеджер",
        collection_item_placeholder="<Имя справочника>",
        item_manager_template="СправочникМенеджер.<Имя справочника>",
    ),
    "Перечисления": SurfaceFamilySpec(
        family="Перечисления",
        collection_manager="ПеречисленияМенеджер",
        collection_item_placeholder="<Имя перечисления>",
        item_manager_template="ПеречислениеМенеджер.<Имя перечисления>",
    ),
    "Константы": SurfaceFamilySpec(
        family="Константы",
        collection_manager="КонстантыМенеджер",
        collection_item_placeholder="<Имя константы>",
        item_manager_template="КонстантаМенеджер.<Имя константы>",
    ),
    "РегистрыНакопления": SurfaceFamilySpec(
        family="РегистрыНакопления",
        collection_manager="РегистрыНакопленияМенеджер",
        collection_item_placeholder="<Имя регистра накопления>",
        item_manager_template="РегистрНакопленияМенеджер.<Имя регистра накопления>",
    ),
    "РегистрыСведений": SurfaceFamilySpec(
        family="РегистрыСведений",
        collection_manager="РегистрыСведенийМенеджер",
        collection_item_placeholder="<Имя регистра сведений>",
        item_manager_template="РегистрСведенийМенеджер.<Имя регистра сведений>",
    ),
    "РегистрыБухгалтерии": SurfaceFamilySpec(
        family="РегистрыБухгалтерии",
        collection_manager="РегистрыБухгалтерииМенеджер",
        collection_item_placeholder="<Имя регистра бухгалтерии>",
        item_manager_template="РегистрБухгалтерииМенеджер.<Имя регистра бухгалтерии>",
    ),
    "РегистрыРасчета": SurfaceFamilySpec(
        family="РегистрыРасчета",
        collection_manager="РегистрыРасчетаМенеджер",
        collection_item_placeholder="<Имя регистра расчета>",
        item_manager_template="РегистрРасчетаМенеджер.<Имя регистра расчета>",
    ),
    "ПланыСчетов": SurfaceFamilySpec(
        family="ПланыСчетов",
        collection_manager="ПланыСчетовМенеджер",
        collection_item_placeholder="<Имя плана счетов>",
        item_manager_template="ПланСчетовМенеджер.<Имя плана счетов>",
    ),
    "ПланыВидовХарактеристик": SurfaceFamilySpec(
        family="ПланыВидовХарактеристик",
        collection_manager="ПланыВидовХарактеристикМенеджер",
        collection_item_placeholder="<Имя плана видов характеристик>",
        item_manager_template="ПланВидовХарактеристикМенеджер.<Имя плана видов характеристик>",
    ),
    "ПланыВидовРасчета": SurfaceFamilySpec(
        family="ПланыВидовРасчета",
        collection_manager="ПланыВидовРасчетаМенеджер",
        collection_item_placeholder="<Имя плана видов расчета>",
        item_manager_template="ПланВидовРасчетаМенеджер.<Имя плана видов расчета>",
    ),
    "ПланыОбмена": SurfaceFamilySpec(
        family="ПланыОбмена",
        collection_manager="ПланыОбменаМенеджер",
        collection_item_placeholder="<Имя плана обмена>",
        item_manager_template="ПланОбменаМенеджер.<Имя плана обмена>",
    ),
    "БизнесПроцессы": SurfaceFamilySpec(
        family="БизнесПроцессы",
        collection_manager="БизнесПроцессыМенеджер",
        collection_item_placeholder="<Имя бизнес-процесса>",
        item_manager_template="БизнесПроцессМенеджер.<Имя бизнес-процесса>",
    ),
    "Задачи": SurfaceFamilySpec(
        family="Задачи",
        collection_manager="ЗадачиМенеджер",
        collection_item_placeholder="<Имя задачи>",
        item_manager_template="ЗадачаМенеджер.<Имя задачи>",
    ),
    "Отчеты": SurfaceFamilySpec(
        family="Отчеты",
        collection_manager="ОтчетыМенеджер",
        collection_item_placeholder="<Имя отчета>",
        item_manager_template="ОтчетМенеджер.<Имя отчета>",
    ),
    "Отчёты": SurfaceFamilySpec(
        family="Отчёты",
        collection_manager="ОтчетыМенеджер",
        collection_item_placeholder="<Имя отчета>",
        item_manager_template="ОтчетМенеджер.<Имя отчета>",
    ),
    "Обработки": SurfaceFamilySpec(
        family="Обработки",
        collection_manager="ОбработкиМенеджер",
        collection_item_placeholder="<Имя обработки>",
        item_manager_template="ОбработкаМенеджер.<Имя обработки>",
    ),
    "ХранилищаНастроек": SurfaceFamilySpec(
        family="ХранилищаНастроек",
        collection_manager="ХранилищаНастроекМенеджер",
        collection_item_placeholder="<Имя хранилища>",
        item_manager_template="ХранилищеНастроекМенеджер.<Имя хранилища>",
    ),
    "ЖурналыДокументов": SurfaceFamilySpec(
        family="ЖурналыДокументов",
        collection_manager="ЖурналыДокументовМенеджер",
        collection_item_placeholder="<Имя журнала документов>",
        item_manager_template="ЖурналДокументовМенеджер.<Имя журнала документов>",
    ),
    "КритерииОтбора": SurfaceFamilySpec(
        family="КритерииОтбора",
        collection_manager="КритерииОтбораМенеджер",
        collection_item_placeholder="<Имя критерия>",
        item_manager_template="КритерийОтбораМенеджер.<Имя критерия>",
    ),
    "Последовательности": SurfaceFamilySpec(
        family="Последовательности",
        collection_manager="ПоследовательностиМенеджер",
        collection_item_placeholder="<Имя последовательности>",
        item_manager_template="ПоследовательностьМенеджер.<Имя последовательности>",
    ),
    "WSСсылки": SurfaceFamilySpec(
        family="WSСсылки",
        collection_manager="WSСсылкиМенеджер",
        collection_item_placeholder="<Имя WS-Ссылки>",
        item_manager_template="WSСсылкаМенеджер.<Имя WS-Ссылки>",
    ),
    "ВнешниеИсточникиДанных": SurfaceFamilySpec(
        family="ВнешниеИсточникиДанных",
        collection_manager="ВнешниеИсточникиДанныхМенеджер",
        collection_item_placeholder="<Имя внешнего источника>",
        item_manager_template="ВнешнийИсточникДанныхМенеджер.<Имя внешнего источника>",
    ),
    "СервисыИнтеграции": SurfaceFamilySpec(
        family="СервисыИнтеграции",
        collection_manager="СервисыИнтеграцииМенеджер",
        collection_item_placeholder="<Имя сервиса интеграции>",
        item_manager_template="СервисИнтеграцииМенеджер.<Имя сервиса интеграции>",
    ),
}

_GLOBAL_CONTEXT_PREFIXES = (
    "Глобальный контекст.",
    "ГлобальныйКонтекст.",
    "Global context.",
)

_METADATA_ROOT_PREFIXES = (
    "Метаданные.",
    "Metadata.",
    "Глобальный контекст.Метаданные.",
    "ГлобальныйКонтекст.Метаданные.",
    "Global context.Metadata.",
)

_METADATA_COLLECTION_TO_HELP_OBJECT: dict[str, str] = {
    "Документы": "ОбъектМетаданных: Документ",
    "Справочники": "ОбъектМетаданных: Справочник",
    "Перечисления": "ОбъектМетаданных: Перечисление",
    "Константы": "ОбъектМетаданных: Константа",
    "РегистрыСведений": "ОбъектМетаданных: РегистрСведений",
    "РегистрыНакопления": "ОбъектМетаданных: РегистрНакопления",
    "РегистрыБухгалтерии": "ОбъектМетаданных: РегистрБухгалтерии",
    "РегистрыРасчета": "ОбъектМетаданных: РегистрРасчета",
    "ПланыСчетов": "ОбъектМетаданных: ПланСчетов",
    "ПланыВидовХарактеристик": "ОбъектМетаданных: ПланВидовХарактеристик",
    "ПланыВидовРасчета": "ОбъектМетаданных: ПланВидовРасчета",
    "ПланыОбмена": "ОбъектМетаданных: ПланОбмена",
    "БизнесПроцессы": "ОбъектМетаданных: БизнесПроцесс",
    "Задачи": "ОбъектМетаданных: Задача",
    "Отчеты": "ОбъектМетаданных: Отчет",
    "Отчёты": "ОбъектМетаданных: Отчет",
    "Обработки": "ОбъектМетаданных: Обработка",
    "ХранилищаНастроек": "ОбъектМетаданных: ХранилищеНастроек",
    "КритерииОтбора": "ОбъектМетаданных: КритерийОтбора",
    "ЖурналыДокументов": "ОбъектМетаданных: ЖурналДокументов",
    "Последовательности": "ОбъектМетаданных: Последовательность",
}


def _collapse_dotted_segments(value: str) -> str:
    parts = [part.strip() for part in (value or "").split(".") if part.strip()]
    return ".".join(parts)


def _strip_global_context_prefix(value: str) -> str:
    current = (value or "").strip()
    for prefix in _GLOBAL_CONTEXT_PREFIXES:
        if current.startswith(prefix):
            return current[len(prefix) :].strip()
    return current


def _strip_metadata_root_prefix(value: str) -> str:
    current = (value or "").strip()
    for prefix in _METADATA_ROOT_PREFIXES:
        if current.startswith(prefix):
            return current[len(prefix) :].strip()
    return current


def _dedup_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item.get("name", ""), item.get("lookup", ""))
        if key in seen or not key[0]:
            continue
        seen.add(key)
        out.append(item)
    return out


def resolve_platform_surface_api_query(query: str) -> dict[str, Any]:
    """Resolve common BSL surface chains to canonical platform-help names."""
    original = (query or "").strip()
    normalized = _collapse_dotted_segments(_strip_global_context_prefix(original))
    if not normalized:
        return {
            "query": original,
            "normalized_query": normalized,
            "resolver_kind": "empty",
            "family": "",
            "segments": [],
            "candidates": [],
        }
    segments = normalized.split(".")
    root = segments[0]
    spec = _SURFACE_FAMILY_SPECS.get(root)
    if spec is None:
        return {
            "query": original,
            "normalized_query": normalized,
            "resolver_kind": "unresolved",
            "family": root,
            "segments": segments,
            "candidates": [],
        }

    placeholder_member = f"{spec.collection_manager}.{spec.collection_item_placeholder}"
    candidates: list[dict[str, str]] = [
        {
            "name": f"Глобальный контекст.{spec.family}",
            "lookup": "member",
            "reason": "global context property for collection family",
        },
        {
            "name": spec.collection_manager,
            "lookup": "object",
            "reason": "collection manager object",
        },
    ]

    if len(segments) == 1:
        return {
            "query": original,
            "normalized_query": normalized,
            "resolver_kind": "platform_surface_chain",
            "family": spec.family,
            "segments": segments,
            "candidates": _dedup_candidates(candidates),
        }

    member_or_name = segments[1]
    candidates.extend(
        [
            {
                "name": f"{spec.collection_manager}.{member_or_name}",
                "lookup": "member",
                "reason": "possible collection-manager member on family root",
            },
            {
                "name": placeholder_member,
                "lookup": "member",
                "reason": "collection item placeholder property",
            },
            {
                "name": spec.item_manager_template,
                "lookup": "object",
                "reason": "item manager placeholder object",
            },
        ]
    )

    if len(segments) >= 3:
        tail = ".".join(segments[2:])
        candidates.insert(
            0,
            {
                "name": f"{spec.item_manager_template}.{tail}",
                "lookup": "member",
                "reason": "member on item manager placeholder object",
            },
        )

    return {
        "query": original,
        "normalized_query": normalized,
        "resolver_kind": "platform_surface_chain",
        "family": spec.family,
        "segments": segments,
        "candidates": _dedup_candidates(candidates),
    }


def resolve_platform_surface_candidate_names(query: str) -> list[str]:
    resolved = resolve_platform_surface_api_query(query)
    return [str(item.get("name") or "") for item in resolved.get("candidates") or [] if item.get("name")]


def resolve_metadata_surface_query(query: str) -> dict[str, Any]:
    original = (query or "").strip()
    stripped = _strip_metadata_root_prefix(original)
    if stripped == original and original not in {"Метаданные", "Metadata", "Глобальный контекст.Метаданные"}:
        return {
            "query": original,
            "normalized_query": _collapse_dotted_segments(original),
            "resolver_kind": "unresolved",
            "family": "",
            "segments": [],
            "candidates": [],
        }
    normalized = "Метаданные" if original.strip() in {"Метаданные", "Metadata"} else _collapse_dotted_segments(stripped)
    root_candidates: list[dict[str, str]] = [
        {
            "name": "Глобальный контекст.Метаданные",
            "lookup": "member",
            "reason": "global context property for metadata root",
        },
        {
            "name": "ОбъектМетаданныхКонфигурация",
            "lookup": "object",
            "reason": "configuration metadata root object",
        },
    ]
    if normalized == "Метаданные" or not normalized:
        return {
            "query": original,
            "normalized_query": "Метаданные",
            "resolver_kind": "metadata_surface_chain",
            "family": "Метаданные",
            "segments": ["Метаданные"],
            "candidates": _dedup_candidates(root_candidates),
        }

    segments = normalized.split(".")
    family = segments[0]
    if family == "СвойстваОбъектов":
        candidates: list[dict[str, str]] = []
        if len(segments) >= 2:
            prop_name = segments[1]
            candidates.extend(
                [
                    {
                        "name": f"ПеречислимыеСвойстваОбъектовМетаданных.{prop_name}",
                        "lookup": "member",
                        "reason": "system enum property on metadata property catalog",
                    },
                    {
                        "name": prop_name,
                        "lookup": "object",
                        "reason": "system enum type returned by metadata property catalog",
                    },
                ]
            )
        candidates.extend(
            [
                {
                    "name": "ОбъектМетаданныхКонфигурация.СвойстваОбъектов",
                    "lookup": "member",
                    "reason": "metadata property catalog on configuration metadata object",
                },
                {
                    "name": "ПеречислимыеСвойстваОбъектовМетаданных",
                    "lookup": "object",
                    "reason": "catalog of system enums for metadata properties",
                },
            ]
        )
        candidates.extend(root_candidates)
        return {
            "query": original,
            "normalized_query": f"Метаданные.{normalized}",
            "resolver_kind": "metadata_surface_chain",
            "family": "СвойстваОбъектов",
            "segments": ["Метаданные", *segments],
            "candidates": _dedup_candidates(candidates),
        }

    help_object = _METADATA_COLLECTION_TO_HELP_OBJECT.get(family)
    if help_object:
        candidates: list[dict[str, str]] = []
        candidates.append(
            {
                "name": f"ОбъектМетаданныхКонфигурация.{family}",
                "lookup": "member",
                "reason": "metadata collection property on configuration metadata object",
            }
        )
        candidates.append(
            {
                "name": help_object,
                "lookup": "object",
                "reason": "help object type for collection element",
            }
        )
        if len(segments) >= 2:
            object_name = segments[1]
            candidates.append(
                {
                    "name": f"{family}.{object_name}",
                    "lookup": "metadata_graph",
                    "reason": "configuration object lookup in KD2 metadata graph",
                }
            )
        candidates.extend(root_candidates)
        return {
            "query": original,
            "normalized_query": f"Метаданные.{normalized}",
            "resolver_kind": "metadata_surface_chain",
            "family": family,
            "segments": ["Метаданные", *segments],
            "candidates": _dedup_candidates(candidates),
        }

    candidates = list(root_candidates)
    return {
        "query": original,
        "normalized_query": f"Метаданные.{normalized}",
        "resolver_kind": "metadata_surface_chain",
        "family": family,
        "segments": ["Метаданные", *segments],
        "candidates": _dedup_candidates(candidates),
    }


def resolve_1c_language_query(query: str) -> dict[str, Any]:
    metadata = resolve_metadata_surface_query(query)
    if metadata.get("candidates"):
        return metadata
    return resolve_platform_surface_api_query(query)
