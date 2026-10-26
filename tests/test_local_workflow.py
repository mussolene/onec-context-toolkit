"""Observable regression checks using synthetic sources only."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from scripts import build_local_kb as builder  # noqa: E402
from scripts import install_agent, ensure_workspace  # noqa: E402
from onec_help.runtime_db import ensure_sqlite_db  # noqa: E402
from tools.local_kb_query import query_pack  # noqa: E402


class LocalWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ, {"ONEC_CONTEXT_CACHE_DIR": str(self.root / "cache")}
        )
        self.env.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.env.stop)

    def build(self, rows):
        source = self.root / "jsonl"
        source.mkdir(exist_ok=True)
        (source / "api_members.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        )
        db, archive = self.root / "help.db", self.root / "help.db.zst"
        builder._build_help_jsonl(
            jsonl_dir=source,
            db_path=db,
            out_zst=archive,
            selected_versions=set(),
            max_payload_chars=200,
            keep_db=True,
        )
        return db, archive

    def test_exact_unicode_all_versions_and_lossless_record(self):
        record = {
            "full_name": "Структура.Вставить",
            "topic_path": "api/structure/insert",
            "versions": ["8.3.1", "8.5.1"],
            "summary": "Описание " * 100,
            "params": [{"name": "Ключ", "description": "Важное " * 200}],
            "availability": "Сервер",
            "restrictions": "Не использовать вне контекста",
            "code": "ПерваяСтрока();\nВтораяСтрока();",
        }
        _, archive = self.build([record])
        result = query_pack(archive, "структура.вставить", version="8.5.1", exact=True)
        self.assertTrue(result["found"])
        item = result["results"][0]
        self.assertEqual(item["params"], record["params"])
        self.assertEqual(item["restrictions"], record["restrictions"])
        self.assertTrue(item["summary_truncated"])
        self.assertEqual(
            query_pack(archive, record["full_name"], detail="full")["results"][0][
                "record"
            ],
            record,
        )
        self.assertFalse(
            query_pack(archive, record["full_name"], version="8.2.1")["found"]
        )
        self.assertTrue(query_pack(archive, "Вставить")["found"])

    def test_invalid_fts_operators_are_literal_and_missing_db_not_created(self):
        db, _ = self.build([{"name": "И", "versions": ["v"], "summary": "OR NOT AND"}])
        self.assertTrue(query_pack(db, "OR NOT AND")["found"])
        missing = self.root / "missing.db"
        with self.assertRaises(FileNotFoundError):
            query_pack(missing, "x")
        self.assertFalse(missing.exists())

    def test_cache_reuses_then_replaces_only_own_generation(self):
        db, archive = self.build([{"name": "Первый", "versions": ["v"]}])
        first, _ = ensure_sqlite_db(archive)
        stamp = first.stat().st_mtime_ns
        self.assertEqual(ensure_sqlite_db(archive)[0].stat().st_mtime_ns, stamp)
        unrelated = first.parent / "unrelated.db"
        unrelated.write_text("keep")
        self.build([{"name": "Второй", "versions": ["v"]}])
        second, _ = ensure_sqlite_db(archive)
        self.assertNotEqual(first, second)
        self.assertFalse(first.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(query_pack(archive, "Второй")["found"])
        # A stale uncompressed sibling never overrides the archive.
        db.write_text("not a database")
        self.assertTrue(query_pack(archive, "Второй")["found"])

    def test_two_sources_with_identical_archive_names_have_distinct_caches(self):
        _, archive = self.build([{"name": "Имя", "versions": ["v"]}])
        other = self.root / "other" / archive.name
        other.parent.mkdir()
        other.write_bytes(archive.read_bytes())
        os.utime(other, ns=(archive.stat().st_atime_ns, archive.stat().st_mtime_ns))
        self.assertNotEqual(ensure_sqlite_db(archive)[0], ensure_sqlite_db(other)[0])

    def test_skill_update_preserves_pack_and_environment_and_runs_outside_repo(self):
        _, archive = self.build(
            [{"name": "Структура", "versions": ["v"], "params": ["Ключ"]}]
        )
        target = Path(
            install_agent._install_codex("onec-context", self.root / "skills")[
                "primary"
            ]
        )
        (target / ".venv").mkdir()
        (target / ".venv" / "keep").write_text("runtime")
        (target / "artifacts").mkdir()
        (target / "artifacts" / "platform.kb.db.zst").write_bytes(archive.read_bytes())
        install_agent._install_codex("onec-context", self.root / "skills")
        self.assertTrue((target / ".venv" / "keep").exists())
        result = subprocess.run(
            [
                sys.executable,
                str(target / "tools/local_kb_query.py"),
                "--q",
                "структура",
                "--exact",
                "--json",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(json.loads(result.stdout)["found"])
        self.assertEqual(len(list((self.root / "skills").iterdir())), 1)
        for ref in (target / "references").iterdir():
            self.assertTrue(ref.stat().st_size)

    def test_help_scratch_cleaned_on_failure(self):
        args = argparse.Namespace(
            hbk_base=None, help_jsonl_dir="synthetic", platform=[], languages="ru"
        )
        observed = []

        def fail(a):
            observed.append(Path(a.work_dir))
            (Path(a.work_dir) / "unpacked").mkdir()
            raise ValueError("fixture failure")

        with patch.object(builder, "_resolve_help_jsonl_dir", side_effect=fail):
            with self.assertRaises(ValueError):
                builder._run_help(args)
        self.assertFalse(observed[0].exists())

    def test_explicit_new_version_does_not_take_unchanged_shortcut(self):
        manifest = {
            "profile": "base",
            "requested_platforms": ["old"],
            "packs": {"platform": "exists"},
        }
        commands = []
        argv = [
            "ensure",
            "--workspace-root",
            str(self.root),
            "--need",
            "platform",
            "--platform",
            "new",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(ensure_workspace, "_manifest_exists", return_value=True),
            patch.object(
                ensure_workspace, "load_workspace_manifest", return_value=manifest
            ),
            patch.object(ensure_workspace, "_run_capture_ok", return_value=True),
            patch.object(
                ensure_workspace, "_manifest_satisfies_needs", return_value=True
            ),
            patch.object(ensure_workspace, "_run", side_effect=commands.append),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ensure_workspace.main()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][commands[0].index("--platform") + 1], "new")

    def test_failed_compression_preserves_archive_and_cleans_staging(self):
        archive = self.root / "help.db.zst"
        archive.write_bytes(b"previous complete pack")

        def fail(source, target, level):
            target.write_bytes(b"incomplete")
            raise OSError("fixture compression failure")

        with patch.object(builder, "zstd_compress_path", side_effect=fail):
            with self.assertRaises(OSError):
                builder._pack_zstd(self.root / "input.db", archive)
        self.assertEqual(archive.read_bytes(), b"previous complete pack")
        self.assertFalse(list(self.root.glob(".onec-pack-*")))

    def test_help_build_cleans_database_staging_on_failure(self):
        source = self.root / "source"
        source.mkdir()
        args = argparse.Namespace(
            hbk_base=None,
            help_jsonl_dir=str(source),
            platform=[],
            languages="ru",
            db_path=str(self.root / "output.db"),
            manifest=str(self.root / "manifest.json"),
            keep_db=False,
        )

        def fail(a, jsonl, started):
            Path(a.db_path).write_bytes(b"partial sqlite")
            raise ValueError("fixture indexing failure")

        with (
            patch.object(builder, "_resolve_help_jsonl_dir", return_value=source),
            patch.object(builder, "_finish_help", side_effect=fail),
        ):
            with self.assertRaises(ValueError):
                builder._run_help(args)
        self.assertFalse(list(self.root.glob(".onec-build-*")))
        self.assertFalse((self.root / "output.db").exists())
        self.assertTrue(source.is_dir())

    def test_empty_pack_is_rejected(self):
        con = builder._create_docs_db(self.root / "empty.db")
        try:
            with self.assertRaisesRegex(ValueError, "empty pack"):
                builder._finalize_docs_db(con)
        finally:
            con.close()

    def test_standard_full_text_and_search_beyond_preview(self):
        source = self.root / "standards"
        source.mkdir()
        content = "# Проверка\n" + "Объяснение " * 100 + "\nУникальноеОграничение"
        (source / "rule.md").write_text(content)
        archive = self.root / "standards.db.zst"
        builder._build_standards_markdown(
            source, self.root / "standards.db", archive, "v", 200, False
        )
        result = query_pack(archive, "УникальноеОграничение", detail="full")
        self.assertEqual(result["results"][0]["record"]["text"], content)

    def test_global_function_and_definition_precede_example(self):
        _, archive = self.build(
            [
                {"full_name": "Глобальный контекст.ПрочитатьJSON", "versions": ["v"]},
            ]
        )
        self.assertTrue(query_pack(archive, "прочитатьjson", exact=True)["found"])

    def test_mcp_exposes_structured_facts(self):
        from scripts.mcp_server import _call_tool

        _, archive = self.build(
            [{"name": "Метод", "versions": ["v"], "restrictions": "Ограничение"}]
        )
        result = _call_tool(
            "onec_query_kb",
            {"db": str(archive), "q": "Метод", "exact": True, "detail": "full"},
        )
        text = result["content"][0]["text"]
        self.assertIn("Ограничение", text)
        self.assertTrue(json.loads(text)["found"])

    def test_source_snapshot_detects_same_size_change(self):
        source = self.root / "8.5.1.1343"
        source.mkdir()
        hbk = source / "shcntx_ru.hbk"
        hbk.write_bytes(b"abc")
        first = builder.help_source_snapshot(source, [source.name])
        hbk.write_bytes(b"xyz")
        self.assertNotEqual(first, builder.help_source_snapshot(source, [source.name]))

    def test_question_search_resolves_identifier_and_ignores_question_words(self):
        _, archive = self.build(
            [
                {
                    "full_name": "HTTPСоединение.Получить",
                    "summary": "Получает данные HTTP запроса",
                    "versions": ["8.5"],
                },
                {
                    "full_name": "Глобальный контекст.ПрочитатьJSON",
                    "summary": "Чтение JSON в соответствие",
                    "versions": ["8.5"],
                },
                {
                    "full_name": "ТаблицаЗначений.НайтиСтроки",
                    "summary": "Поиск строк таблицы",
                    "versions": ["8.5"],
                },
            ]
        )
        for question, expected in [
            ("Как прочитать JSON в соответствие?", "Глобальный контекст.ПрочитатьJSON"),
            (
                "Можно ли вызвать HTTPСоединение.Получить на клиенте?",
                "HTTPСоединение.Получить",
            ),
            (
                "Что возвращает ТаблицаЗначений.НайтиСтроки, если совпадений нет?",
                "ТаблицаЗначений.НайтиСтроки",
            ),
            ("Как отправить HTTP запрос на сервер?", "HTTPСоединение.Получить"),
        ]:
            result = query_pack(archive, question, version="8.5")
            self.assertIn(expected, [item["name"] for item in result["results"]])
            self.assertFalse(query_pack(archive, question, version="missing")["found"])
        self.assertFalse(
            query_pack(archive, "Структура.ВымышленныйМетод", exact=True)["found"]
        )
        self.assertFalse(
            query_pack(archive, "Как прочитать JSON?", exact=True)["found"]
        )

    def test_examples_require_explicit_domain(self):
        source = self.root / "jsonl"
        source.mkdir()
        for domain in ("api_members", "api_examples"):
            (source / (domain + ".jsonl")).write_text(json.dumps({
                "full_name": "Структура.Вставить", "summary": "УникальныйПоиск", "versions": ["8.5.1"],
            }, ensure_ascii=False))
        db, archive = self.root / "help.db", self.root / "help.db.zst"
        builder._build_help_jsonl(jsonl_dir=source, db_path=db, out_zst=archive,
                                 selected_versions=set(), max_payload_chars=200, keep_db=True)
        for query, exact in (("Структура.Вставить", True), ("УникальныйПоиск", False)):
            result = query_pack(archive, query, exact=exact)
            self.assertEqual([r["domain"] for r in result["results"]], ["api_members"])
            result = query_pack(archive, query, exact=exact, domain="api_examples")
            self.assertEqual([r["domain"] for r in result["results"]], ["api_examples"])

    def test_restrictions_require_explicit_restriction(self):
        from onec_help.knowledge.help_structured import _extract_restrictions
        self.assertEqual(_extract_restrictions("Тонкий клиент, сервер, внешнее соединение."), "")
        self.assertEqual(_extract_restrictions("Примечание о методе."), "")
        for text in ("Доступен только на сервере.", "Не поддерживается в веб-клиенте.",
                     "Не использовать вне контекста.", "Недоступен на клиенте."):
            self.assertEqual(_extract_restrictions(text), text)

    def test_export_does_not_copy_unreadable_private_manifest(self):
        from scripts.export_skill_bundle import export_bundle
        workspace = self.root / "workspace"
        (workspace / ".onec").mkdir(parents=True)
        packs = self.root / "packs"
        packs.mkdir()
        manifests = self.root / "manifests"
        manifests.mkdir()
        archive = packs / "platform.db.zst"
        archive.write_bytes(b"synthetic")
        (manifests / "platform.manifest.json").write_text("invalid private metadata")
        (workspace / ".onec" / "workspace.manifest.json").write_text(
            json.dumps({"packs": {"platform": str(archive)}}))
        output = self.root / "export"
        with self.assertRaises(json.JSONDecodeError):
            export_bundle(workspace, output, "bundle")
        self.assertFalse((output / "bundle" / "artifacts" / "platform.manifest.json").exists())

    def test_parameter_sections_keep_defaults_and_union_types(self):
        from bs4 import BeautifulSoup
        from onec_help.help_core.html2md import extract_v8sh_sections
        from onec_help.knowledge.help_structured import _parse_param_lines

        soup = BeautifulSoup(
            """<p class="V8SH_chapter">Параметры:</p>
        <div class="V8SH_rubric"><p>&lt;Имена&gt; (необязательный)</p></div>
        Тип: <a>Массив</a>, <a>Строка</a>, <a>ФиксированныйМассив</a>.<br>
        Имена свойств.<br>Значение по умолчанию: <a>Неопределено</a>.
        <div class="V8SH_rubric"><p>&lt;Предел&gt; (необязательный)</p></div>
        Тип: <a>Число</a>.<br>Максимальная глубина.<br>Значение по умолчанию: 500.
        <p class="V8SH_chapter">Описание:</p>Проверка.
        """,
            "html.parser",
        )
        params = _parse_param_lines(extract_v8sh_sections(soup)["params"])
        assert len(params) == 2
        assert params[0]["type"] == "Массив, Строка, ФиксированныйМассив"
        assert "Неопределено" in params[0]["description"]
        assert "500" in params[1]["description"]
        assert all(item["name"].startswith("<") for item in params)

    def test_code_dom_preserves_spacing_comments_and_entity_literals(self):
        from bs4 import BeautifulSoup
        from onec_help.help_core.html2md import extract_v8sh_sections

        for wrapper in ["<table><tr><td>{code}</td></tr></table>", "<pre>{code}</pre>"]:
            code = '<span>// Комментарий</span><br><span>Запрос</span> = <b>Новый</b>&nbsp;<a>Запрос</a>;<br>Сообщить("&amp;lt;");'
            soup = BeautifulSoup(
                '<p class="V8SH_chapter">Пример:</p>' + wrapper.format(code=code),
                "html.parser",
            )
            example = extract_v8sh_sections(soup)["example"]
            assert (
                '// Комментарий\nЗапрос = Новый Запрос;\nСообщить("&lt;");' in example
            )
            assert "НовыйЗапрос" not in example


if __name__ == "__main__":
    unittest.main()
