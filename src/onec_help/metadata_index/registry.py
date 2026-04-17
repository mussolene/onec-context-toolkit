"""Folder/kind mapping for Designer XML config exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class MetadataKindDef:
    folder: str
    kind: str
    collection_ru: str


_KIND_DEFS: tuple[MetadataKindDef, ...] = (
    MetadataKindDef("Catalogs", "Catalog", "Справочники"),
    MetadataKindDef("Documents", "Document", "Документы"),
    MetadataKindDef("DocumentJournals", "DocumentJournal", "ЖурналыДокументов"),
    MetadataKindDef("Enums", "Enum", "Перечисления"),
    MetadataKindDef("Reports", "Report", "Отчеты"),
    MetadataKindDef("DataProcessors", "DataProcessor", "Обработки"),
    MetadataKindDef("ChartsOfCharacteristicTypes", "ChartOfCharacteristicTypes", "ПланыВидовХарактеристик"),
    MetadataKindDef("ChartsOfAccounts", "ChartOfAccounts", "ПланыСчетов"),
    MetadataKindDef("ChartsOfCalculationTypes", "ChartOfCalculationTypes", "ПланыВидовРасчета"),
    MetadataKindDef("InformationRegisters", "InformationRegister", "РегистрыСведений"),
    MetadataKindDef("AccumulationRegisters", "AccumulationRegister", "РегистрыНакопления"),
    MetadataKindDef("AccountingRegisters", "AccountingRegister", "РегистрыБухгалтерии"),
    MetadataKindDef("CalculationRegisters", "CalculationRegister", "РегистрыРасчета"),
    MetadataKindDef("BusinessProcesses", "BusinessProcess", "БизнесПроцессы"),
    MetadataKindDef("Tasks", "Task", "Задачи"),
    MetadataKindDef("ExchangePlans", "ExchangePlan", "ПланыОбмена"),
    MetadataKindDef("ExternalDataSources", "ExternalDataSource", "ВнешниеИсточникиДанных"),
    MetadataKindDef("Constants", "Constant", "Константы"),
    MetadataKindDef("CommonModules", "CommonModule", "ОбщиеМодули"),
    MetadataKindDef("SessionParameters", "SessionParameter", "ПараметрыСеанса"),
    MetadataKindDef("FilterCriteria", "FilterCriterion", "КритерииОтбора"),
    MetadataKindDef("ScheduledJobs", "ScheduledJob", "РегламентныеЗадания"),
    MetadataKindDef("FunctionalOptions", "FunctionalOption", "ФункциональныеОпции"),
    MetadataKindDef("FunctionalOptionsParameters", "FunctionalOptionsParameter", "ПараметрыФункциональныхОпций"),
    MetadataKindDef("SettingsStorages", "SettingsStorage", "ХранилищаНастроек"),
    MetadataKindDef("EventSubscriptions", "EventSubscription", "ПодпискиНаСобытия"),
    MetadataKindDef("CommandGroups", "CommandGroup", "ГруппыКоманд"),
    MetadataKindDef("Roles", "Role", "Роли"),
    MetadataKindDef("Interfaces", "Interface", "Интерфейсы"),
    MetadataKindDef("Styles", "Style", "Стили"),
    MetadataKindDef("WebServices", "WebService", "WebСервисы"),
    MetadataKindDef("HTTPServices", "HTTPService", "HTTPСервисы"),
    MetadataKindDef("WSReferences", "WSReference", "WSСсылки"),
    MetadataKindDef("IntegrationServices", "IntegrationService", "СервисыИнтеграции"),
    MetadataKindDef("Subsystems", "Subsystem", "Подсистемы"),
    MetadataKindDef("Sequences", "Sequence", "Последовательности"),
    MetadataKindDef("DefinedTypes", "DefinedType", "ОпределяемыеТипы"),
    MetadataKindDef("CommonForms", "CommonForm", "ОбщиеФормы"),
    MetadataKindDef("CommonTemplates", "CommonTemplate", "ОбщиеМакеты"),
    MetadataKindDef("CommonPictures", "CommonPicture", "ОбщиеКартинки"),
    MetadataKindDef("CommonCommands", "CommonCommand", "ОбщиеКоманды"),
)

FOLDER_TO_KIND: Final[dict[str, str]] = {item.folder: item.kind for item in _KIND_DEFS}
KIND_TO_COLLECTION: Final[dict[str, str]] = {item.kind: item.collection_ru for item in _KIND_DEFS}
