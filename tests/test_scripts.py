#!/usr/bin/env python3
"""tests/test_scripts.py — module-skill-forge 三个确定性脚本的回归测试。

覆盖 docs/design.md 第 8 节的验收点：
  * validate_skills.py：合法技能通过；缺 description、非 kebab-case、
    description>500、相对链接缺失、嵌套 SKILL.md、绝对宿主路径各自报错；
    --json 可解析；--strict 把 warning 当 error；--facts 命令检查；--skill 单技能。
  * scan_module.py：无 git 的小项目也能产出 facts.json（schema_version=1），
    entry_points / commands / tests / signals 等关键字段存在；--module 限定
    范围；--max-files 截断；输出确定（除 generated_at）；不改被扫描项目。
  * refresh.py：index→check ok；改文件/新 commit 后 stale；marker 缺失 untracked
    且 --strict 失败；无 git 且无 index 时 exit 3；scan 刷新 facts 且不改 SKILL.md；
    --json 可解析。

运行：
    cd <repo>
    python3 -m unittest discover -s tests -v
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".dsh" / "skills" / "module-skill-forge" / "scripts"
SCAN = SCRIPTS / "scan_module.py"
VALIDATE = SCRIPTS / "validate_skills.py"
REFRESH = SCRIPTS / "refresh.py"

VALID_DESC = (
    "Use when you need to change the catalog module, debug product listing "
    "failures, or answer questions about catalog data flow in the sample shop."
)
REQUIRED_FACTS_KEYS = [
    "schema_version", "generated_at", "project", "module", "entry_points",
    "public_api", "commands", "tests", "configs", "docs", "dependencies",
    "signals", "file_tree", "hotspots", "warnings",
]


def run(args, cwd=None, timeout=180):
    """用当前解释器跑脚本，返回 CompletedProcess（text 模式）。"""
    return subprocess.run(
        [sys.executable] + [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


class TempWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory(prefix="forge-test-")
        self.tmp = Path(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    # -- 技能夹具 ---------------------------------------------------------

    def write_bundle(
        self,
        root,
        dir_name,
        *,
        name=None,
        description=VALID_DESC,
        body=None,
        references=None,
    ):
        skill_dir = Path(root) / dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = ["---"]
        frontmatter.append("name: %s" % (name if name is not None else dir_name))
        if description is not None:
            frontmatter.append("description: %s" % description)
        frontmatter.append("---")
        if body is None:
            body = (
                "# %s\n\n"
                "Use this skill when working inside the catalog module.\n\n"
                "- Read [architecture](references/architecture.md) when changing data flow.\n"
                "- Run the repository test command before claiming done.\n"
                % dir_name
            )
        (skill_dir / "SKILL.md").write_text(
            "\n".join(frontmatter) + "\n" + body, encoding="utf-8"
        )
        ref_dir = skill_dir / "references"
        ref_dir.mkdir(exist_ok=True)
        if references is None:
            references = {"architecture.md": "# Architecture\n\nDetails.\n"}
        for ref_name, content in references.items():
            target = ref_dir / ref_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return skill_dir

    def write_flat(self, root, stem, *, name=None, description=VALID_DESC, body=None):
        path = Path(root) / ("%s.md" % stem)
        body = body if body is not None else "# Flat skill\n\nUse this skill for flat routing checks.\n"
        text = (
            "---\nname: %s\ndescription: %s\n---\n%s"
            % (name if name is not None else stem, description, body)
        )
        path.write_text(text, encoding="utf-8")
        return path

    # -- 校验器调用 -------------------------------------------------------

    def validate_json(self, root, extra=()):
        proc = run([VALIDATE, "--root", root, "--json"] + list(extra), cwd=REPO_ROOT)
        payload = json.loads(proc.stdout)
        return proc, payload

    def assert_error_code(self, payload, code):
        codes = [item["code"] for item in payload["errors"]]
        self.assertIn(
            code,
            codes,
            "期望 error 代码 %r，实际 %r；errors=%r"
            % (code, codes, payload["errors"]),
        )

    def assert_warning_code(self, payload, code):
        for item in payload["warnings"]:
            self.assertEqual(item["severity"], "warning", item)
        codes = [item["code"] for item in payload["warnings"]]
        self.assertIn(
            code,
            codes,
            "期望 warning 代码 %r，实际 %r；warnings=%r"
            % (code, codes, payload["warnings"]),
        )


class ValidateSkillsTest(TempWorkspaceTest):
    def test_valid_bundle_passes(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "sample-shop-catalog-dev")
        proc = run([VALIDATE, "--root", root], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("结果：通过", proc.stdout)
        self.assertIn("✓", proc.stdout)

    def test_valid_flat_skill_passes(self):
        root = self.tmp / "skills"
        root.mkdir()
        self.write_flat(root, "flat-skill")
        proc = run([VALIDATE, "--root", root], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("flat", proc.stdout)

    def test_valid_skill_json_is_parseable(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "valid-skill")
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["warnings"], [])
        self.assertIn("skills", payload)
        self.assertEqual(len(payload["skills"]), 1)
        self.assertEqual(payload["summary"]["skills"], 1)

    def test_missing_description_reports_error(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "no-description", description=None)
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assert_error_code(payload, "missing_description")

    def test_non_kebab_name_reports_error(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "Bad_Name", name="Bad_Name")
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "invalid_name")

    def test_description_over_500_reports_error(self):
        root = self.tmp / "skills"
        long_desc = "Use when " + ("x" * 520)
        self.write_bundle(root, "long-description", description=long_desc)
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "description_too_long")

    def test_missing_relative_link_reports_error(self):
        root = self.tmp / "skills"
        body = (
            "# Broken links\n\n"
            "Read [missing](references/does-not-exist.md) before changing code.\n"
        )
        self.write_bundle(root, "broken-link", body=body)
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "missing_link_target")

    def test_nested_skill_md_reports_error(self):
        root = self.tmp / "skills"
        skill_dir = self.write_bundle(root, "alpha")
        nested_dir = skill_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "SKILL.md").write_text(
            "---\nname: nested\ndescription: %s\n---\nbody\n" % VALID_DESC,
            encoding="utf-8",
        )
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "nested_skill_md")

    def test_absolute_host_path_reports_error(self):
        root = self.tmp / "skills"
        body = "# Portability\n\nSee /Users/someone/project/notes.md for details.\n"
        self.write_bundle(root, "abs-path", body=body)
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "absolute_host_path")

    def test_duplicate_name_reports_error(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "alpha")
        self.write_flat(root, "alpha")
        proc, payload = self.validate_json(root)
        self.assertEqual(proc.returncode, 1)
        self.assert_error_code(payload, "duplicate_name")

    def test_strict_promotes_warnings(self):
        root = self.tmp / "skills"
        self.write_bundle(root, "warn-skill", description="Use when testing.")
        lenient = run([VALIDATE, "--root", root], cwd=REPO_ROOT)
        self.assertEqual(lenient.returncode, 0, lenient.stderr + lenient.stdout)
        self.assertIn("warning", lenient.stdout)
        strict_proc, strict_payload = self.validate_json(root, extra=("--strict",))
        self.assertEqual(strict_proc.returncode, 1)
        self.assertFalse(strict_payload["ok"])
        self.assertTrue(strict_payload["strict"])
        self.assert_warning_code(strict_payload, "description_short")

    def test_facts_command_warning(self):
        root = self.tmp / "skills"
        body = (
            "# Commands\n\n"
            "Run `pnpm lint` before committing.\n"
        )
        self.write_bundle(root, "command-skill", body=body)
        facts_path = self.tmp / "facts.json"
        facts_path.write_text(
            json.dumps({
                "schema_version": 1,
                "commands": [{"name": "test", "command": "vitest run"}],
            }),
            encoding="utf-8",
        )
        proc, payload = self.validate_json(root, extra=("--facts", facts_path))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assert_warning_code(payload, "command_not_in_facts")

    def _facts_with_scripts(self):
        facts_path = self.tmp / "facts-scripts.json"
        facts_path.write_text(json.dumps({
            "schema_version": 1,
            "commands": [
                {"name": "test", "command": "vitest run", "cwd": "."},
                {"name": "dev", "command": "pnpm -r --parallel dev", "cwd": "."},
            ],
        }), encoding="utf-8")
        return facts_path

    def test_script_name_command_passes(self):
        """`pnpm test` 里的 script 名命中 facts.commands[].name 即视为真实。"""
        root = self.tmp / "skills"
        self.write_bundle(
            root, "script-skill",
            body="# Commands\n\nRun `pnpm test` before committing.\n",
            references={},
        )
        proc, payload = self.validate_json(root, extra=("--facts", self._facts_with_scripts()))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["warnings"], [])

    def test_install_command_passes(self):
        """安装类命令不是 package.json script，白名单直接放行。"""
        root = self.tmp / "skills"
        self.write_bundle(
            root, "install-skill",
            body="# Setup\n\nRun `pnpm install` once.\n",
            references={},
        )
        proc, payload = self.validate_json(root, extra=("--facts", self._facts_with_scripts()))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["warnings"], [])

    def test_skill_flag_validates_single_bundle(self):
        root = self.tmp / "skills"
        bundle = self.write_bundle(root, "solo-skill")
        proc = run([VALIDATE, "--skill", bundle], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("solo-skill", proc.stdout)
        self.assertNotIn("其他问题", proc.stdout)

        empty_bundle = self.tmp / "empty-bundle"
        empty_bundle.mkdir()
        proc = run([VALIDATE, "--skill", empty_bundle], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("SKILL.md", proc.stderr)

        proc = run([VALIDATE, "--root", root, "--skill", bundle], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("二选一", proc.stderr)

    def test_missing_root_exits_2(self):
        proc = run([VALIDATE, "--root", self.tmp / "does-not-exist"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不存在", proc.stderr)


class ScanModuleTest(TempWorkspaceTest):
    def make_js_project(self):
        project = self.tmp / "tiny-shop"
        (project / "src").mkdir(parents=True)
        (project / "tests").mkdir()
        (project / "package.json").write_text(json.dumps({
            "name": "tiny-shop",
            "private": True,
            "scripts": {"test": "vitest run", "build": "tsc -p ."},
            "devDependencies": {"vitest": "^2.0.0", "typescript": "^5.0.0"},
        }, indent=2), encoding="utf-8")
        (project / "src" / "index.ts").write_text(
            "export const loadCatalog = () => [];\n"
            "export class CatalogStore {}\n"
            "// TODO: add pagination before the catalog grows\n"
            "const apiBase = process.env.SHOP_API_URL;\n"
            "export default function main() { return apiBase; }\n",
            encoding="utf-8",
        )
        (project / "tests" / "catalog.test.ts").write_text(
            "import { loadCatalog } from '../src/index';\n"
            "it('loads', () => { expect(loadCatalog()).toEqual([]); });\n",
            encoding="utf-8",
        )
        (project / "README.md").write_text("# tiny-shop\n", encoding="utf-8")
        (project / "tsconfig.json").write_text("{}\n", encoding="utf-8")
        return project

    def scan_project_json(self, project, out_dir, extra=()):
        proc = run(
            [SCAN, "--project", project, "--out", out_dir, "--json"] + list(extra),
            cwd=REPO_ROOT,
        )
        payload = json.loads(proc.stdout)
        return proc, payload

    def resolve_payload_path(self, payload, key):
        """--json 路径：项目内是项目相对路径，项目外是绝对路径，两种都还原成 Path。"""
        path = Path(payload[key])
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
        return path

    def test_scan_without_git_produces_facts(self):
        project = self.make_js_project()
        out_dir = self.tmp / "out"
        proc, payload = self.scan_project_json(project, out_dir)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(payload["ok"])
        facts_path = self.resolve_payload_path(payload, "facts_path")
        pack_path = self.resolve_payload_path(payload, "fact_pack_path")
        self.assertTrue(facts_path.is_file())
        self.assertTrue(pack_path.is_file())

        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        for key in REQUIRED_FACTS_KEYS:
            self.assertIn(key, facts, "facts.json 缺少字段 %r" % key)
        self.assertEqual(facts["schema_version"], 1)
        self.assertEqual(facts["project"]["name"], "tiny-shop")
        self.assertTrue(facts["project"]["languages"])
        self.assertTrue(any(item["path"] == "src/index.ts" for item in facts["entry_points"]),
                        facts["entry_points"])
        command_names = [item["name"] for item in facts["commands"]]
        self.assertIn("test", command_names)
        self.assertIn("build", command_names)
        # 摘要里的命令名必须去重（facts.commands 按 cwd 展开时会有重名）
        summary_names = payload["summary"]["command_names"]
        self.assertEqual(len(summary_names), len(set(summary_names)))
        self.assertTrue(facts["tests"])
        self.assertTrue(facts["signals"]["todos"])
        self.assertTrue(any("SHOP_API_URL" == item["name"] for item in facts["signals"]["env_vars"]))
        # 无 git 时必须降级并写 warning
        self.assertTrue(any("git" in warning for warning in facts["warnings"]),
                        facts["warnings"])
        # 只读扫描：不污染被扫描项目
        self.assertEqual(sorted(path.name for path in project.iterdir()),
                         sorted(["package.json", "src", "README.md", "tests", "tsconfig.json"]))
        self.assertFalse((project / "out").exists())

        # evidence / file_tree 全部相对路径，且 facts.json 里不出现宿主绝对路径
        facts_text = facts_path.read_text(encoding="utf-8")
        self.assertNotIn(str(project), facts_text)
        self.assertNotIn("/Users/", facts_text)
        for key in ("entry_points", "public_api", "commands", "tests", "configs",
                    "docs", "hotspots"):
            for item in facts[key]:
                evidence = item.get("evidence")
                self.assertIsInstance(evidence, str, "%s 缺少 evidence: %r" % (key, item))
                self.assertFalse(evidence.startswith("/"), "%s evidence 不是相对路径: %r" % (key, evidence))
        for rel in facts["file_tree"]:
            self.assertFalse(rel.startswith("/"), "file_tree 不是相对路径: %r" % rel)

        pack_text = pack_path.read_text(encoding="utf-8")
        for heading in ("项目画像", "模块候选", "入口", "公开 API", "命令", "测试",
                        "依赖", "TODO / FIXME", "热点", "警告", "建议下一步"):
            self.assertIn(heading, pack_text)

    def test_scan_module_scope(self):
        project = self.tmp / "mono-shop"
        (project / "packages" / "catalog" / "src").mkdir(parents=True)
        (project / "packages" / "catalog" / "tests").mkdir()
        (project / "packages" / "other").mkdir(parents=True)
        (project / "package.json").write_text(json.dumps({
            "name": "mono-shop",
            "private": True,
            "workspaces": ["packages/*"],
            "scripts": {"test": "vitest run"},
        }), encoding="utf-8")
        (project / "pnpm-workspace.yaml").write_text(
            "packages:\n  - 'packages/*'\n", encoding="utf-8")
        (project / "packages" / "catalog" / "package.json").write_text(json.dumps({
            "name": "@mono/catalog",
            "main": "./src/index.ts",
            "scripts": {"test": "vitest run"},
            "dependencies": {"@mono/other": "workspace:*"},
        }), encoding="utf-8")
        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const catalog = [];\n", encoding="utf-8")
        (project / "packages" / "catalog" / "tests" / "catalog.test.ts").write_text(
            "it('ok', () => {});\n", encoding="utf-8")
        (project / "packages" / "other" / "package.json").write_text(json.dumps({
            "name": "@mono/other",
            "scripts": {"build": "tsc"},
        }), encoding="utf-8")
        out_dir = self.tmp / "out-module"
        proc, payload = self.scan_project_json(
            project, out_dir, extra=("--module", "packages/catalog"))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        facts = json.loads(self.resolve_payload_path(payload, "facts_path").read_text(encoding="utf-8"))
        self.assertEqual(facts["module"]["path"], "packages/catalog")
        self.assertEqual(facts["module"]["name"], "@mono/catalog")
        self.assertTrue(facts["project"]["monorepo"]["is_monorepo"])
        self.assertEqual(facts["project"]["monorepo"]["tool"], "pnpm")
        self.assertEqual(len(facts["project"]["monorepo"]["packages"]), 2)
        for rel in facts["file_tree"]:
            self.assertTrue(rel.startswith("packages/catalog/"), rel)
        self.assertTrue(any(item["name"] == "main" for item in facts["entry_points"]))
        self.assertIn(
            "packages/catalog",
            [item["cwd"] for item in facts["commands"]],
        )
        self.assertNotIn(
            "packages/other",
            [item["cwd"] for item in facts["commands"]],
        )
        internal_deps = facts["dependencies"]["internal"]
        self.assertTrue(any(item["name"] == "@mono/other" and item["path"] == "packages/other"
                            for item in internal_deps), internal_deps)

    def test_scan_max_files_truncates(self):
        project = self.tmp / "many-files"
        project.mkdir()
        for index in range(12):
            (project / ("file-%02d.txt" % index)).write_text("content %d\n" % index,
                                                            encoding="utf-8")
        out_dir = self.tmp / "out-max"
        proc, payload = self.scan_project_json(project, out_dir, extra=("--max-files", "5"))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        facts = json.loads(self.resolve_payload_path(payload, "facts_path").read_text(encoding="utf-8"))
        self.assertLessEqual(len(facts["file_tree"]), 5)
        self.assertTrue(any("max-files" in warning for warning in facts["warnings"]),
                        facts["warnings"])

    def test_scan_is_deterministic(self):
        project = self.make_js_project()
        first, first_payload = self.scan_project_json(project, self.tmp / "out-a")
        second, second_payload = self.scan_project_json(project, self.tmp / "out-b")
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        facts_a = json.loads(self.resolve_payload_path(first_payload, "facts_path")
                             .read_text(encoding="utf-8"))
        facts_b = json.loads(self.resolve_payload_path(second_payload, "facts_path")
                             .read_text(encoding="utf-8"))
        facts_a.pop("generated_at")
        facts_b.pop("generated_at")
        self.assertEqual(facts_a, facts_b)

    def test_fact_pack_renders_full_relative_paths(self):
        project = self.tmp / "deep-shop"
        (project / "pkg" / "src").mkdir(parents=True)
        (project / "pkg" / "tests").mkdir()
        (project / "package.json").write_text(
            json.dumps({"name": "deep-shop", "private": True}), encoding="utf-8")
        (project / "pkg" / "src" / "a.ts").write_text(
            "export const a = 1;\n", encoding="utf-8")
        (project / "pkg" / "tests" / "a.test.ts").write_text(
            "it('a', () => {});\n", encoding="utf-8")
        (project / "README.md").write_text("# deep-shop\n", encoding="utf-8")
        proc, payload = self.scan_project_json(project, self.tmp / "out-deep")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        pack_text = self.resolve_payload_path(payload, "fact_pack_path").read_text(
            encoding="utf-8")
        # 文件树必须是完整相对路径，不能退化成只剩 basename
        self.assertIn("pkg/src/a.ts", pack_text)
        self.assertIn("pkg/tests/a.test.ts", pack_text)
        self.assertIn("## 10. 文件树（完整相对路径", pack_text)

    def test_scan_output_paths(self):
        project = self.make_js_project()
        # out 在项目内 -> 项目相对路径
        inside_out = project / ".dsh" / "forge" / "tiny-shop"
        _, payload = self.scan_project_json(project, inside_out)
        self.assertEqual(payload["facts_path"], ".dsh/forge/tiny-shop/facts.json")
        self.assertEqual(payload["fact_pack_path"], ".dsh/forge/tiny-shop/fact-pack.md")
        # out 在项目外 -> 绝对路径
        outside_out = self.tmp / "outside-out"
        _, payload = self.scan_project_json(project, outside_out)
        self.assertTrue(Path(payload["facts_path"]).is_absolute(), payload["facts_path"])
        self.assertEqual(Path(payload["facts_path"]).resolve(),
                         (outside_out / "facts.json").resolve())

    def test_env_vars_deduplicated_by_name(self):
        project = self.tmp / "env-shop"
        (project / "src").mkdir(parents=True)
        (project / "package.json").write_text(
            json.dumps({"name": "env-shop", "private": True}), encoding="utf-8")
        (project / "src" / "a.ts").write_text(
            "const url = process.env.SHOP_TOKEN;\n", encoding="utf-8")
        (project / "src" / "b.ts").write_text(
            "export const TOKEN_ENV = 'SHOP_TOKEN';\n", encoding="utf-8")
        proc, payload = self.scan_project_json(project, self.tmp / "out-env")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        facts = json.loads(self.resolve_payload_path(payload, "facts_path")
                           .read_text(encoding="utf-8"))
        occurrences = [item for item in facts["signals"]["env_vars"]
                       if item["name"] == "SHOP_TOKEN"]
        self.assertEqual(len(occurrences), 2, occurrences)
        # 摘要按变量名去重计数，但保留多处 evidence
        self.assertEqual(payload["summary"]["env_vars"], 1)
        self.assertEqual(payload["summary"]["env_vars_occurrences"], 2)
        pack_text = self.resolve_payload_path(payload, "fact_pack_path").read_text(
            encoding="utf-8")
        self.assertIn("环境变量（1 个唯一变量，2 处引用）", pack_text)
        self.assertIn("src/a.ts", pack_text)
        self.assertIn("src/b.ts", pack_text)

    def test_scan_missing_project_exits_2(self):
        proc = run([SCAN, "--project", self.tmp / "missing", "--out", self.tmp / "out"],
                   cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("不存在", proc.stderr)

    def test_scan_help_mentions_contract(self):
        proc = run([SCAN, "--help"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--project", proc.stdout)
        self.assertIn("--max-files", proc.stdout)
        self.assertIn("退出码", proc.stdout)

    def test_validate_help_mentions_rules(self):
        proc = run([VALIDATE, "--help"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--strict", proc.stdout)
        self.assertIn("--facts", proc.stdout)
        self.assertIn("--skill", proc.stdout)
        self.assertIn("退出码", proc.stdout)


class RefreshTest(TempWorkspaceTest):
    """refresh.py 的变更检测（check）/ 基线（index）/ 增量重扫（scan）。"""

    def make_project(self):
        project = self.tmp / "shop"
        (project / "packages" / "catalog" / "src").mkdir(parents=True)
        (project / "package.json").write_text(
            json.dumps({"name": "shop", "private": True}), encoding="utf-8")
        (project / "packages" / "catalog" / "package.json").write_text(
            json.dumps({"name": "@shop/catalog", "scripts": {"test": "vitest run"}}),
            encoding="utf-8")
        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const a = 1;\n", encoding="utf-8")
        self.write_facts(project)
        return project

    def write_facts(self, project):
        facts_path = project / ".dsh" / "forge" / "catalog" / "facts.json"
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        facts_path.write_text(
            json.dumps({"schema_version": 1, "module": {"path": "packages/catalog"}}),
            encoding="utf-8")
        return facts_path

    def make_skills_root(self):
        skills = self.tmp / "skills"
        skills.mkdir()
        return skills

    def write_tracked_skill(self, skills_root, *, name="demo-catalog-dev",
                            module="packages/catalog",
                            facts=".dsh/forge/catalog/facts.json",
                            head="none", marker=True, scanned="2026-11-01"):
        skill_dir = Path(skills_root) / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        text = "---\nname: %s\ndescription: %s\n---\n" % (name, VALID_DESC)
        if marker:
            text += ("<!-- forge: module=%s facts=%s scanned=%s head=%s -->\n"
                     % (module, facts, scanned, head))
        text += "# Demo skill\n\nUse this for the catalog module.\n"
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        return skill_dir

    def refresh(self, *args):
        return run([REFRESH] + list(args), cwd=REPO_ROOT)

    def refresh_json(self, *args):
        if "--json" not in args:
            args = tuple(args) + ("--json",)
        proc = self.refresh(*args)
        return proc, json.loads(proc.stdout)

    def git(self, project, *args):
        proc = subprocess.run(
            ["git", "-C", str(project)] + list(args),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    # -- check / index -----------------------------------------------------

    def test_index_then_check_ok(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills)
        proc = self.refresh("--project", project, "--skills", skills, "--mode", "index")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("索引已写出", proc.stdout)
        index = json.loads((project / ".dsh" / "forge" / "index.json").read_text(
            encoding="utf-8"))
        self.assertEqual(index["schema_version"], 1)
        self.assertEqual(index["project"]["head"], "none")
        self.assertEqual(len(index["modules"]), 1)
        self.assertEqual(index["modules"][0]["status"], "ok")
        self.assertEqual(len(index["modules"][0]["baseline"]["fingerprint"]), 64)
        self.assertGreaterEqual(index["modules"][0]["baseline"]["file_count"], 1)

        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["modules"][0]["status"], "ok")
        self.assertEqual(payload["summary"]["ok"], 1)

    def test_nongit_modified_file_reports_stale(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills)
        self.assertEqual(self.refresh("--project", project, "--skills", skills,
                                      "--mode", "index").returncode, 0)
        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const a = 2;\n", encoding="utf-8")
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        self.assertFalse(payload["ok"])
        module = payload["modules"][0]
        self.assertEqual(module["status"], "stale")
        self.assertIn("packages/catalog/src/index.ts", module["changed_files"])
        self.assertEqual(payload["summary"]["stale"], 1)

    @unittest.skipUnless(shutil.which("git"), "需要 git 才能跑该用例")
    def test_git_new_commit_in_module_reports_stale(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.git(project, "init", "-q")
        self.git(project, "add", "-A")
        self.git(project, "-c", "user.email=test@example.com", "-c", "user.name=test",
                 "commit", "-qm", "init")
        head = self.git(project, "rev-parse", "--short", "HEAD").stdout.strip()
        self.write_tracked_skill(skills, head=head)

        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["modules"][0]["status"], "ok")

        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const a = 3;\n", encoding="utf-8")
        self.git(project, "add", "packages/catalog")
        self.git(project, "-c", "user.email=test@example.com", "-c", "user.name=test",
                 "commit", "-qm", "change catalog")
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        module = payload["modules"][0]
        self.assertEqual(module["status"], "stale")
        self.assertEqual(module.get("commits"), 1)
        self.assertIn("packages/catalog/src/index.ts", module["changed_files"])

    def test_marker_missing_is_untracked_and_strict_fails(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills, marker=False)
        proc = self.refresh("--project", project, "--skills", skills, "--mode", "index")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        index = json.loads((project / ".dsh" / "forge" / "index.json").read_text(
            encoding="utf-8"))
        self.assertEqual(index["modules"][0]["status"], "untracked")

        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["modules"][0]["status"], "untracked")
        self.assertTrue(payload["ok"])

        strict_proc, strict_payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check", "--strict")
        self.assertEqual(strict_proc.returncode, 1)
        self.assertFalse(strict_payload["ok"])
        self.assertEqual(strict_payload["modules"][0]["status"], "untracked")

    def test_check_without_git_or_index_exits_3(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills)
        proc = self.refresh("--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("--mode index", proc.stderr)

    # -- scan --------------------------------------------------------------

    def test_scan_refreshes_facts_without_touching_skill(self):
        project = self.make_project()
        skills = self.make_skills_root()
        skill_dir = self.write_tracked_skill(skills)
        self.assertEqual(self.refresh("--project", project, "--skills", skills,
                                      "--mode", "index").returncode, 0)
        facts_path = project / ".dsh" / "forge" / "catalog" / "facts.json"
        facts_path.unlink()
        # facts 缺失 → check 报 missing_facts
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(payload["modules"][0]["status"], "missing_facts")

        skill_md_before = (skill_dir / "SKILL.md").read_bytes()
        proc = self.refresh("--project", project, "--skills", skills, "--mode", "scan")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("事实已刷新，待更新技能", proc.stdout)
        self.assertIn("demo-catalog-dev", proc.stdout)
        self.assertTrue(facts_path.is_file())
        self.assertEqual((skill_dir / "SKILL.md").read_bytes(), skill_md_before,
                         "refresh.py --mode scan 不能改写 SKILL.md")
        # 再跑一次 --json：已无待刷新项，JSON 仍可解析
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "scan")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["refreshed"], [])

    def test_global_module_star_check_ok_and_review_hint(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills)
        self.write_tracked_skill(skills, name="global-overview", module="*", facts="none")
        self.assertEqual(self.refresh("--project", project, "--skills", skills,
                                      "--mode", "index").returncode, 0)

        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertTrue(payload["ok"])
        global_entry = next(item for item in payload["modules"]
                            if item["skill"] == "global-overview")
        self.assertEqual(global_entry["status"], "ok")
        self.assertEqual(global_entry["scope"], "global")
        self.assertEqual(payload["review_globals"], [])
        # --strict 下全局技能也不应算失败
        strict_proc, strict_payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check", "--strict")
        self.assertEqual(strict_proc.returncode, 0, strict_proc.stderr + strict_proc.stdout)
        self.assertTrue(strict_payload["ok"])

        # 模块变化 → 模块 stale，但全局技能仍为 ok，并给出复核提示
        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const a = 2;\n", encoding="utf-8")
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        module_entry = next(item for item in payload["modules"]
                            if item["skill"] == "demo-catalog-dev")
        self.assertEqual(module_entry["status"], "stale")
        global_entry = next(item for item in payload["modules"]
                            if item["skill"] == "global-overview")
        self.assertEqual(global_entry["status"], "ok")
        self.assertEqual(payload["review_globals"], ["global-overview"])
        human = self.refresh("--project", project, "--skills", skills, "--mode", "check")
        self.assertIn("全局技能 global-overview 建议在执行模块更新时同步复核", human.stdout)

        # 恢复文件后回到全部 ok
        (project / "packages" / "catalog" / "src" / "index.ts").write_text(
            "export const a = 1;\n", encoding="utf-8")
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["review_globals"], [])

    def test_global_module_skipped_by_scan(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills, name="global-overview", module="*", facts="none")
        self.assertEqual(self.refresh("--project", project, "--skills", skills,
                                      "--mode", "index").returncode, 0)
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "scan")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(payload["refreshed"], [])
        self.assertEqual(payload["failed"], [])
        self.assertIn("global-overview", payload["skipped_global"])
        # 不应对 module=* 调用 scanner：facts 目录里不会出现 * 相关产物
        for path in (project / ".dsh" / "forge").iterdir():
            self.assertNotIn("*", path.name)
        self.assertFalse((project / "*").exists())

    def test_module_none_equivalent_to_global(self):
        project = self.make_project()
        skills = self.make_skills_root()
        self.write_tracked_skill(skills, name="global-none", module="none", facts="none")
        self.assertEqual(self.refresh("--project", project, "--skills", skills,
                                      "--mode", "index").returncode, 0)
        proc, payload = self.refresh_json(
            "--project", project, "--skills", skills, "--mode", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        entry = payload["modules"][0]
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["scope"], "global")
        self.assertIn("全局技能", entry["reason"])

    def test_refresh_help_mentions_modes(self):
        proc = run([REFRESH, "--help"], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--mode", proc.stdout)
        self.assertIn("--strict", proc.stdout)
        self.assertIn("退出码", proc.stdout)
        self.assertIn("--mode index", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
