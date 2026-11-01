#!/usr/bin/env python3
"""scan_module.py — module-skill-forge 的只读项目扫描器。

用途
    在目标项目里收集模块事实（入口、公开 API、命令、测试、依赖、TODO/FIXME、
    环境变量、路由、热点等），产出两个文件：
      * facts.json   —— schema_version=1 的结构化事实包（每条事实带相对 evidence）
      * fact-pack.md —— 面向人/模型的 Markdown 摘要（项目画像、候选模块、入口、
                        公开 API、命令、测试、依赖、TODO/FIXME、热点、警告、
                        建议下一步）
    扫描严格只读：除了 --out 目录，不会修改被扫描项目的任何文件；不联网；
    不写绝对宿主路径（evidence / file_tree 一律相对 project 根）。

用法
    python3 scan_module.py --project <dir> [--module <path|name>] [--out <dir>]
                           [--json] [--max-files N]

参数
    --project <dir>   要扫描的项目根。省略时先尝试 `git rev-parse --show-toplevel`，
                      失败则用当前目录。目录不存在时退出码 2。
    --module <path|name>
                      只聚焦某个模块：相对 project 的路径（packages/catalog）、
                      绝对路径，或 monorepo 的包名（@scope/catalog、catalog）。
                      省略时扫描整个项目，并在 module.candidates 里列出候选模块。
    --out <dir>       输出目录。默认 <project>/.dsh/forge/<slug>/。
                      只写 facts.json 与 fact-pack.md。
    --json            stdout 只输出一个 JSON 对象
                      {ok, facts_path, fact_pack_path, summary}，详细报告看文件。
    --max-files N     最多收集/读取多少个文件（默认 5000），防止大仓库卡死；
                      触顶时写 warning 并截断。

支持的项目类型
    JS/TS（含 npm / yarn / pnpm workspaces）、Python、Go、Java/Maven、Rust/Cargo
    的基本识别。没有 git、没有包管理器清单时会降级：事实照常产出，但写入
    warnings 说明缺了什么。

退出码
    0  成功（facts.json 与 fact-pack.md 已写出）
    2  参数错误、项目不存在、模块无法解析、或扫描内部失败

示例
    python3 scan_module.py --project fixtures/sample-shop --module packages/catalog
    python3 scan_module.py --project . --out /tmp/facts --json
    python3 scan_module.py --project . --max-files 800
"""

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DEFAULT_MAX_FILES = 5000
MAX_FILE_SIZE = 1024 * 1024          # >1MB 的文件跳过
SNIFF_SIZE = 8192                    # 二进制探测字节数
GIT_TIMEOUT = 15                     # 秒

# 扫描时整目录排除（小写比较）。.dsh 也排除：避免把 forge 自己的产出/技能扫回来。
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out", "target",
    "coverage", ".venv", "venv", "env", "__pycache__", ".next", ".nuxt",
    "vendor", ".dsh", ".idea", ".vscode", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".gradle", ".terraform", ".cache", "bower_components",
}

LOCK_FILE_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "cargo.lock", "poetry.lock", "uv.lock", "pipfile.lock", "go.sum",
    "composer.lock", "gemfile.lock", "pdm.lock",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".psd",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".avi",
    ".wav", ".flac", ".ogg", ".webm", ".woff2", ".wasm", ".jar", ".class",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin", ".dat", ".sqlite",
    ".sqlite3", ".db", ".parquet", ".avro", ".xlsx", ".xls", ".docx", ".doc",
    ".pptx", ".ppt", ".key", ".sketch", ".fig", ".heic",
}

LANG_BY_EXT = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".hpp": "C++",
    ".m": "Objective-C", ".mm": "Objective-C", ".sh": "Shell", ".bash": "Shell",
    ".zsh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".vue": "Vue",
    ".svelte": "Svelte", ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir",
    ".lua": "Lua", ".r": "R", ".pl": "Perl", ".clj": "Clojure", ".hs": "Haskell",
}

CONFIG_NAMES = {
    "tsconfig.json", "jsconfig.json", "package.json", "pnpm-workspace.yaml",
    "yarn.lock", "package-lock.json", "pnpm-lock.yaml", ".npmrc", ".nvmrc",
    ".node-version", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
    "requirements.txt", "requirements-dev.txt", "pipfile", "poetry.toml",
    "uv.lock", "go.mod", "go.sum", "go.work", "cargo.toml", "rust-toolchain",
    "rust-toolchain.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "makefile", "justfile", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", ".editorconfig", ".prettierrc", ".prettierrc.json",
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
    "eslint.config.js", "eslint.config.mjs", "jest.config.js", "jest.config.ts",
    "vitest.config.ts", "vitest.config.js", "vite.config.ts", "vite.config.js",
    "webpack.config.js", "rollup.config.js", "babel.config.js", ".babelrc",
    "next.config.js", "next.config.mjs", "turbo.json", "nx.json", "lerna.json",
    ".env", ".env.example", ".env.local", ".env.development", ".env.production",
    "mkdocs.yml", "docusaurus.config.js", "angular.json", "composer.json",
    "gemfile", "rakefile", "pubspec.yaml", "build.sbt",
}
CONFIG_PREFIXES = (
    ".eslintrc", "tsconfig.", "requirements", "docker-compose", ".env.",
    "vitest.config.", "jest.config.", "vite.config.", "webpack.config.",
)
CI_PATH_RE = re.compile(r"(?:^|/)(?:\.github/workflows|\.gitlab-ci|\.circleci)/")

DOC_NAMES = {
    "readme.md", "readme.rst", "readme.txt", "changelog.md", "changelog",
    "contributing.md", "architecture.md", "adr.md", "design.md",
}

ENV_PATTERNS = [
    re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"os\.environ\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    re.compile(r"System\.getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"os\.Getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"env::var\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    re.compile(r"getenv\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
]
DOTENV_RE = re.compile(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=")
# 间接环境变量：const TAX_RATE_ENV = 'SAMPLE_SHOP_TAX_RATE' 之后通过 env[TAX_RATE_ENV] 读取
ENV_CONST_RE = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*['\"]([A-Z][A-Z0-9_]{2,})['\"]"
)

ROUTE_PATTERNS = [
    re.compile(r"\b(?:app|router|server|api)\.(get|post|put|patch|delete|options|all)\(\s*['\"`]([^'\"`]+)['\"`]"),
    re.compile(r"@(?:app|router|api)\.(get|post|put|patch|delete|options)\(\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"HandleFunc\(\s*\"([^\"]+)\""),
    re.compile(r"Handle\(\s*\"([^\"]+)\",\s*\w+\("),
]
NEXT_PAGES_API_RE = re.compile(r"(?:^|/)pages/api/(.+)\.(?:t|j)sx?$")
NEXT_APP_PAGE_RE = re.compile(r"(?:^|/)app/(.+)/page\.(?:t|j)sx?$")

MANIFEST_NAMES = {
    "package.json", "pnpm-workspace.yaml", "pyproject.toml", "setup.py",
    "go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "gemfile", "pubspec.yaml", "build.sbt", "mix.exs",
    "requirements.txt",
}
PACKAGE_MAIN_FIELDS = ("main", "module", "browser", "types", "typings")
CONVENTIONAL_ENTRY_NAMES = {
    "index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs", "index.cjs",
    "index.py", "__init__.py", "main.py", "__main__.py", "app.py", "manage.py",
    "wsgi.py", "asgi.py", "main.rs", "lib.rs", "main.go", "main.java",
    "application.java", "main.kt", "program.cs", "index.rb", "index.php",
}
INDEXISH_NAMES = {"index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
                  "index.cjs", "__init__.py", "api.py", "public.py", "mod.rs",
                  "lib.rs"}

TODO_RE = re.compile(r"\bTODO\b")
FIXME_RE = re.compile(r"\bFIXME\b")
JS_EXPORT_DECL_RE = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
)
JS_EXPORT_DEFAULT_RE = re.compile(r"^\s*export\s+default\s+([A-Za-z_$][\w$]*)\s*;?\s*$")
JS_EXPORT_LIST_RE = re.compile(r"^\s*export\s*\{([^}]*)\}")
JS_EXPORT_STAR_RE = re.compile(r"^\s*export\s+\*\s+from\s+['\"]([^'\"]+)['\"]")
PY_DEF_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")
PY_CLASS_RE = re.compile(r"^class\s+([A-Za-z_]\w*)\s*[:(]")
PY_ALL_RE = re.compile(r"__all__\s*=\s*\[([^\]]*)\]", re.S)
TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:test_[^/]+\.py|[^/]+_test\.py|[^/]+_test\.go|"
    r"[^/]+\.(?:test|spec)\.[cm]?[jt]sx?|conftest\.py)$"
)
TEST_DIR_RE = re.compile(r"(?:^|/)(?:tests?|__tests__|spec|specs)(?:/|$)")
FRAMEWORK_TOKENS = [
    ("vitest", "vitest"), ("jest", "jest"), ("mocha", "mocha"),
    ("playwright", "playwright"), ("cypress", "cypress"), ("pytest", "pytest"),
    ("unittest", "unittest"), ("testing.T", "go test"), ("testify", "go test"),
    ("junit", "junit"), ("@Test", "junit"), ("rspec", "rspec"), ("phpunit", "phpunit"),
]
SECRET_RE = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
GIT_HOTSPOT_COMMITS = 800
MAX_PUBLIC_API = 200
MAX_SIGNAL_ITEMS = 200
MAX_COMMANDS = 300
MAX_CANDIDATES = 60
MAX_DEPENDENCIES = 40


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_rel(path, root):
    """把绝对路径转成相对 root 的 POSIX 风格路径（"." 表示 root 本身）。"""
    rel = os.path.relpath(path, root)
    if rel == ".":
        return "."
    return rel.replace(os.sep, "/")


def display_path(path):
    """输出里的路径一律尽量相对当前工作目录，避免把宿主绝对路径写进结果。"""
    try:
        rel = os.path.relpath(path, os.getcwd())
    except ValueError:  # Windows 跨盘符
        return path
    return rel.replace(os.sep, "/") if rel != "." else "."


def display_out_path(path, project_root):
    """输出产物路径：--out 在项目内用项目相对路径，在项目外用绝对路径（方便复制）。"""
    path_abs = os.path.abspath(path)
    root_abs = os.path.abspath(project_root)
    try:
        inside = os.path.commonpath([path_abs, root_abs]) == root_abs
    except ValueError:  # Windows 跨盘符
        inside = False
    if inside:
        return norm_rel(path_abs, root_abs)
    return path_abs.replace(os.sep, "/")


def _run(cmd, cwd=None, timeout=GIT_TIMEOUT):
    """执行只读命令；任何异常都降级为 (False, '', 原因)，绝不抛给调用方。"""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return False, "", "命令不存在: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return False, "", "命令超时: %s" % " ".join(cmd)
    except OSError as exc:
        return False, "", "命令执行失败: %s" % exc
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return proc.returncode == 0, out, err


def read_text_file(abs_path):
    """读取文本文件；二进制/过大/不可读返回 None。"""
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read(MAX_FILE_SIZE + 1)
    except OSError:
        return None
    if len(data) > MAX_FILE_SIZE:
        return None
    if b"\x00" in data[:SNIFF_SIZE]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace")


def read_json_file(abs_path):
    text = read_text_file(abs_path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _short(text, limit=160):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cell(text):
    return _short(text).replace("|", "\\|")


# ---------------------------------------------------------------------------
# 项目遍历
# ---------------------------------------------------------------------------

def walk_files(project_root, max_files, out_abs=None):
    """稳定顺序遍历项目文件，返回 (files, stats)。

    files: [{"rel","abs","size"}]
    stats: {"truncated", "skipped_large", "skipped_binary", "skipped_symlink",
            "unreadable", "lock_files"}
    """
    files = []
    stats = Counter()
    truncated = False
    for dirpath, dirnames, filenames in os.walk(project_root, followlinks=False):
        if out_abs:
            real_dir = os.path.abspath(dirpath)
            out_abs_norm = os.path.abspath(out_abs)
            if real_dir == out_abs_norm or real_dir.startswith(out_abs_norm + os.sep):
                dirnames[:] = []
                continue
        kept_dirs = []
        for name in dirnames:
            if name.lower() in EXCLUDED_DIRS:
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode):
                continue
            kept_dirs.append(name)
        dirnames[:] = sorted(kept_dirs)
        for name in sorted(filenames):
            if name.lower() in LOCK_FILE_NAMES:
                stats["lock_files"] += 1
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in BINARY_EXTENSIONS:
                stats["skipped_binary"] += 1
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
            except OSError:
                stats["unreadable"] += 1
                continue
            if stat.S_ISLNK(st.st_mode):
                stats["skipped_symlink"] += 1
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_size > MAX_FILE_SIZE:
                stats["skipped_large"] += 1
                continue
            files.append({
                "rel": norm_rel(full, project_root),
                "abs": full,
                "size": st.st_size,
            })
            if len(files) >= max_files:
                truncated = True
                break
        if truncated:
            break
    files.sort(key=lambda item: item["rel"])
    stats["truncated"] = truncated
    return files, dict(stats)


def _walk_module_extra(project_root, module_rel, known_rels, max_files):
    """项目遍历被 max_files 截断、且模块文件缺失时，优先补齐模块目录。"""
    module_abs = os.path.join(project_root, module_rel)
    extra_files, stats = walk_files(module_abs, max_files)
    added = []
    for item in extra_files:
        rel = norm_rel(item["abs"], project_root)
        if rel in known_rels or rel in {x["rel"] for x in added}:
            continue
        added.append({"rel": rel, "abs": item["abs"], "size": item["size"]})
    added.sort(key=lambda item: item["rel"])
    return added, stats


# ---------------------------------------------------------------------------
# git 信息
# ---------------------------------------------------------------------------

def collect_git(project_root):
    """返回 (git_facts, warnings)。无 git 不报错，只降级。"""
    info = {
        "available": False,
        "toplevel": None,
        "head": None,
        "branch": None,
        "dirty": None,
        "commits": None,
    }
    warnings = []
    ok, out, _err = _run(["git", "-C", project_root, "rev-parse", "--show-toplevel"])
    if not ok or not out.strip():
        warnings.append("未检测到 git 仓库（git rev-parse 失败）：变更历史类事实缺失，hotspots 改用静态信号近似")
        return info, warnings
    top_abs = os.path.realpath(out.strip().splitlines()[0].strip())
    info["available"] = True
    # 用 realpath 归一：macOS 的 /tmp 是 /private/tmp 的符号链接，否则会算出怪路径
    info["toplevel"] = norm_rel(top_abs, os.path.realpath(project_root))

    ok, out, _err = _run(["git", "-C", project_root, "rev-parse", "--short", "HEAD"])
    if ok and out.strip():
        info["head"] = out.strip().splitlines()[0].strip()
        ok, out, _err = _run(["git", "-C", project_root, "rev-parse", "--abbrev-ref", "HEAD"])
        if ok and out.strip():
            info["branch"] = out.strip().splitlines()[0].strip()
        ok, out, _err = _run(["git", "-C", project_root, "rev-list", "--count", "HEAD"])
        if ok and out.strip().isdigit():
            info["commits"] = int(out.strip())
        ok, out, _err = _run(["git", "-C", project_root, "status", "--porcelain"])
        if ok:
            info["dirty"] = bool(out.strip())
    else:
        warnings.append("git 仓库存在但尚无提交（HEAD 无法解析）：hotspots 改用静态信号近似")
        info["commits"] = 0
    return info, warnings


def git_hotspots(project_root, git_info, scope_rels, top=20):
    """用 git 提交历史统计热点；失败返回空列表。"""
    if not git_info.get("available") or not git_info.get("commits"):
        return []
    ok, out, _err = _run(["git", "-C", project_root, "rev-parse", "--show-toplevel"])
    top_abs = os.path.realpath(out.strip()) if ok and out.strip() else os.path.realpath(project_root)
    project_real = os.path.realpath(project_root)
    ok, out, _err = _run([
        "git", "-C", project_root, "log", "--name-only", "--pretty=format:",
        "--max-count=%d" % GIT_HOTSPOT_COMMITS,
    ])
    if not ok or not out:
        return []
    scope_set = set(scope_rels)
    counts = Counter()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        abs_path = os.path.join(top_abs, line.replace("/", os.sep))
        try:
            rel = norm_rel(os.path.realpath(abs_path), project_real)
        except ValueError:
            continue
        if rel.startswith("../") or rel == "..":
            continue
        if rel in scope_set:
            counts[rel] += 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [{"path": p, "score": c, "reason": "git_changes", "evidence": p}
            for p, c in ordered if c > 0]


# ---------------------------------------------------------------------------
# 清单 / monorepo / 候选模块
# ---------------------------------------------------------------------------

def _read_package_json(project_root):
    return read_json_file(os.path.join(project_root, "package.json"))


def _parse_pnpm_workspace(text):
    """从 pnpm-workspace.yaml 里提取 packages 列表（足够用的极简 YAML 解析）。"""
    patterns = []
    in_packages = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line[0].isspace() and stripped.endswith(":") and stripped[:-1].strip() == "packages":
            in_packages = True
            continue
        if in_packages:
            if stripped.startswith("-"):
                value = stripped[1:].strip().strip("'\"")
                if value:
                    patterns.append(value)
            elif not line[0].isspace():
                in_packages = False
    return patterns


def _parse_cargo_workspace(text):
    patterns = []
    match = re.search(r"\[workspace\](.*?)(?:\n\[|\Z)", text, re.S)
    if not match:
        return patterns
    block = match.group(1)
    members = re.search(r"members\s*=\s*\[(.*?)\]", block, re.S)
    if members:
        for token in re.findall(r"['\"]([^'\"]+)['\"]", members.group(1)):
            patterns.append(token)
    return patterns


def _parse_go_work(text):
    return [token for token in re.findall(r"^\s*use\s+(?:\(\s*)?(\S+?)\s*$", text, re.M)]


def _glob_to_regex(pattern):
    pattern = pattern.strip().replace("\\", "/").rstrip("/")
    out = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _matches_workspace(dir_rel, patterns):
    positive = [_glob_to_regex(p) for p in patterns if p and not p.startswith("!")]
    negative = [_glob_to_regex(p[1:]) for p in patterns if p.startswith("!")]
    if any(regex.match(dir_rel) for regex in negative):
        return False
    return any(regex.match(dir_rel) for regex in positive)


def detect_monorepo(project_root, package_index, warnings):
    """识别 monorepo；返回 dict 并就地补 warnings。"""
    result = {"is_monorepo": False, "tool": None, "packages": []}
    patterns = []
    tool = None

    pnpm_ws_abs = os.path.join(project_root, "pnpm-workspace.yaml")
    if os.path.isfile(pnpm_ws_abs):
        text = read_text_file(pnpm_ws_abs)
        if text is not None:
            patterns = _parse_pnpm_workspace(text)
            tool = "pnpm"

    root_pkg = _read_package_json(project_root)
    if tool is None and isinstance(root_pkg, dict):
        workspaces = root_pkg.get("workspaces")
        if isinstance(workspaces, list):
            patterns = [w for w in workspaces if isinstance(w, str)]
        elif isinstance(workspaces, dict):
            raw = workspaces.get("packages")
            if isinstance(raw, list):
                patterns = [w for w in raw if isinstance(w, str)]
        if patterns:
            if os.path.isfile(os.path.join(project_root, "yarn.lock")):
                tool = "yarn"
            elif os.path.isfile(os.path.join(project_root, "pnpm-lock.yaml")):
                tool = "pnpm"
            else:
                tool = "npm"

    if tool is None:
        cargo_abs = os.path.join(project_root, "Cargo.toml")
        if os.path.isfile(cargo_abs):
            text = read_text_file(cargo_abs)
            if text is not None and "[workspace]" in text:
                patterns = _parse_cargo_workspace(text)
                if patterns:
                    tool = "cargo"

    if tool is None:
        go_work_abs = os.path.join(project_root, "go.work")
        if os.path.isfile(go_work_abs):
            text = read_text_file(go_work_abs)
            if text is not None:
                patterns = _parse_go_work(text)
                if patterns:
                    tool = "go"

    if not tool:
        return result

    result["is_monorepo"] = True
    result["tool"] = tool
    packages = []
    for entry in package_index:
        dir_rel = entry["dir_rel"]
        if dir_rel == "." or dir_rel.startswith("../"):
            continue
        if not _matches_workspace(dir_rel, patterns):
            continue
        name = entry.get("name") or os.path.basename(dir_rel)
        packages.append({
            "path": dir_rel,
            "name": name,
            "evidence": entry["rel"],
        })
    packages.sort(key=lambda item: item["path"])
    result["packages"] = packages
    if tool in ("cargo", "go") and not packages:
        warnings.append("检测到 %s workspace 声明，但没有匹配到成员清单：依赖/模块候选可能不完整" % tool)
    return result


def _collect_package_index(files, project_root):
    """读取所有 package.json，得到 [{"rel","dir_rel","name","data"}]，按路径排序。"""
    index = []
    for item in files:
        if os.path.basename(item["rel"]) != "package.json":
            continue
        data = read_json_file(item["abs"])
        dir_rel = os.path.dirname(item["rel"]) or "."
        name = None
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            name = data["name"]
        index.append({
            "rel": item["rel"],
            "dir_rel": dir_rel,
            "name": name,
            "data": data if isinstance(data, dict) else {},
        })
    index.sort(key=lambda entry: entry["rel"])
    return index


def _manifest_name(abs_path):
    """尽力读取清单里的包名。"""
    name = os.path.basename(os.path.dirname(abs_path)) or "."
    data = read_json_file(abs_path)
    if isinstance(data, dict) and isinstance(data.get("name"), str):
        return data["name"]
    if os.path.basename(abs_path) == "pyproject.toml":
        text = read_text_file(abs_path) or ""
        match = re.search(r"^\s*name\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if match:
            return match.group(1)
    if os.path.basename(abs_path) == "Cargo.toml":
        text = read_text_file(abs_path) or ""
        match = re.search(r"^\s*name\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
        if match:
            return match.group(1)
    if os.path.basename(abs_path) == "go.mod":
        text = read_text_file(abs_path) or ""
        match = re.search(r"^module\s+(\S+)", text, re.M)
        if match:
            return match.group(1)
    return name


def find_candidates(project_root, files, monorepo):
    """列出候选模块（monorepo 包优先，其次含清单的浅层目录，再次一级源码目录）。"""
    candidates = []
    seen = set()
    for pkg in monorepo["packages"]:
        candidates.append({
            "path": pkg["path"],
            "name": pkg["name"],
            "kind": "workspace_package",
            "evidence": pkg["evidence"],
        })
        seen.add(pkg["path"])
    if not candidates:
        for item in files:
            rel = item["rel"]
            base = os.path.basename(rel).lower()
            if base not in MANIFEST_NAMES:
                continue
            dir_rel = os.path.dirname(rel) or "."
            if dir_rel == "." or dir_rel.startswith("../"):
                continue
            depth = dir_rel.count("/") + 1
            if depth > 3 or dir_rel in seen:
                continue
            candidates.append({
                "path": dir_rel,
                "name": _manifest_name(item["abs"]),
                "kind": "manifest_dir",
                "evidence": rel,
            })
            seen.add(dir_rel)
        candidates.sort(key=lambda item: item["path"])
        candidates = candidates[:MAX_CANDIDATES]
    if not candidates:
        top_dirs = Counter()
        top_first_file = {}
        source_files = [item for item in files if os.path.splitext(item["rel"])[1].lower() in LANG_BY_EXT]
        for item in source_files:
            first = item["rel"].split("/")[0]
            if "/" not in item["rel"] or first.lower() in {
                "src", "lib", "app", "tests", "test", "docs", "doc", "scripts",
                "script", "assets", "static", "public", "examples", "example",
                "benchmarks", "tools", "config", "configs", ".github",
            }:
                continue
            top_dirs[first] += 1
            top_first_file.setdefault(first, item["rel"])
        for name, _count in sorted(top_dirs.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_CANDIDATES]:
            candidates.append({
                "path": name,
                "name": name,
                "kind": "directory",
                "evidence": top_first_file[name],
            })
    return candidates


# ---------------------------------------------------------------------------
# 模块解析
# ---------------------------------------------------------------------------

class ModuleResolveError(Exception):
    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = candidates


def resolve_module(project_root, module_arg, candidates, package_index):
    """把 --module 参数解析成目录（返回相对 project 的路径）。"""
    if not module_arg:
        return "."
    project_abs = os.path.abspath(project_root)
    raw = module_arg.strip()
    possible_abs = raw if os.path.isabs(raw) else os.path.join(project_abs, raw)
    possible_abs = os.path.abspath(possible_abs)
    if os.path.isdir(possible_abs):
        rel = os.path.relpath(possible_abs, project_abs)
        if rel == ".":
            return "."
        if not rel.startswith(".."):
            return rel.replace(os.sep, "/")

    normalized = raw.strip("./").replace("\\", "/")
    if normalized == "":
        return "."
    for pkg in package_index:
        pkg_name = pkg.get("name") or ""
        short_name = pkg_name.split("/")[-1] if pkg_name else ""
        if normalized in (pkg_name, short_name, pkg["dir_rel"]):
            return pkg["dir_rel"]
        if pkg["dir_rel"].endswith("/" + normalized) or pkg["dir_rel"] == normalized:
            return pkg["dir_rel"]
    for cand in candidates:
        if normalized in (cand["path"], cand["name"]) or cand["path"].endswith("/" + normalized):
            return cand["path"]
    raise ModuleResolveError(
        "无法把 --module %r 解析成项目内的目录或包名" % module_arg,
        candidates,
    )


# ---------------------------------------------------------------------------
# 各类事实提取
# ---------------------------------------------------------------------------

def detect_languages(files):
    counter = Counter()
    first_evidence = {}
    for item in files:
        ext = os.path.splitext(item["rel"])[1].lower()
        language = LANG_BY_EXT.get(ext)
        if not language:
            continue
        counter[language] += 1
        first_evidence.setdefault(language, item["rel"])
    result = []
    for language, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        result.append({
            "name": language,
            "files": count,
            "evidence": first_evidence[language],
        })
    return result


def detect_package_managers(project_root, files):
    present = set()
    root_names = set()
    try:
        root_names = {name.lower() for name in os.listdir(project_root)}
    except OSError:
        pass
    all_names = root_names | {os.path.basename(item["rel"]).lower() for item in files}
    if "pnpm-lock.yaml" in all_names or "pnpm-workspace.yaml" in all_names or "pnpm" in _read_pkg_manager_field(project_root):
        present.add("pnpm")
    if "yarn.lock" in all_names:
        present.add("yarn")
    if "package-lock.json" in all_names:
        present.add("npm")
    if "bun.lockb" in all_names:
        present.add("bun")
    if "cargo.toml" in all_names:
        present.add("cargo")
    if "go.mod" in all_names:
        present.add("go")
    if "pom.xml" in all_names:
        present.add("maven")
    if "build.gradle" in all_names or "build.gradle.kts" in all_names or "gradlew" in all_names:
        present.add("gradle")
    if "poetry.lock" in all_names:
        present.add("poetry")
    if "uv.lock" in all_names:
        present.add("uv")
    if "pyproject.toml" in all_names or "setup.py" in all_names or "requirements.txt" in all_names:
        present.add("pip")
    if "composer.json" in all_names:
        present.add("composer")
    if "gemfile" in all_names:
        present.add("bundler")
    return sorted(present)


def _read_pkg_manager_field(project_root):
    data = _read_package_json(project_root) or {}
    value = data.get("packageManager")
    return value if isinstance(value, str) else ""


def _depth_in_scope(rel, scope_rel):
    if scope_rel in (".", ""):
        return rel.count("/")
    if rel == scope_rel:
        return 0
    inner = rel[len(scope_rel) + 1:] if rel.startswith(scope_rel + "/") else rel
    return inner.count("/")


def extract_entry_points(project_root, scope_files, scope_rel, pkg_data, pkg_rel,
                         workspace_packages=None):
    entries = []
    seen = set()
    workspace_dirs = [
        entry["dir_rel"] for entry in (workspace_packages or [])
        if entry.get("dir_rel") not in (None, ".", "")
    ]

    def add(kind, path, evidence, name=None):
        if not path:
            return
        path = os.path.normpath(path.replace("\\", "/")).replace(os.sep, "/")
        if path.startswith("/") or path.startswith("../") or "/../" in path:
            return
        key = (kind, path)
        if key in seen:
            return
        seen.add(key)
        abs_path = os.path.join(project_root, path.replace("/", os.sep))
        entries.append({
            "kind": kind,
            "path": path,
            "name": name,
            "exists": os.path.isfile(abs_path),
            "evidence": evidence,
        })

    if isinstance(pkg_data, dict):
        pkg_dir = os.path.dirname(pkg_rel) if pkg_rel and pkg_rel != "package.json" else ""
        for field in PACKAGE_MAIN_FIELDS:
            value = pkg_data.get(field)
            if isinstance(value, str) and value:
                add("package_" + field, os.path.join(pkg_dir, value), "%s (%s)" % (pkg_rel, field), name=field)
        bin_value = pkg_data.get("bin")
        if isinstance(bin_value, str):
            add("package_bin", os.path.join(pkg_dir, bin_value), "%s (bin)" % pkg_rel)
        elif isinstance(bin_value, dict):
            for name in sorted(bin_value):
                value = bin_value[name]
                if isinstance(value, str):
                    add("package_bin", os.path.join(pkg_dir, value),
                        "%s (bin.%s)" % (pkg_rel, name), name=name)
        exports = pkg_data.get("exports")
        targets = []
        if isinstance(exports, str):
            targets.append(exports)
        elif isinstance(exports, dict):
            for key in sorted(exports):
                value = exports[key]
                if isinstance(value, str):
                    targets.append(value)
                elif isinstance(value, dict):
                    for sub in sorted(value):
                        if isinstance(value[sub], str):
                            targets.append(value[sub])
        for target in targets:
            if target.startswith("./"):
                add("package_exports", os.path.join(pkg_dir, target[2:]),
                    "%s (exports)" % pkg_rel)

    # 整项目扫描时，把 monorepo 各包的包入口也纳入，避免总览技能缺少入口事实。
    if scope_rel in (".", "") and workspace_packages:
        for entry in workspace_packages[:40]:
            data = entry.get("data")
            pkg_dir = entry.get("dir_rel")
            if not isinstance(data, dict) or pkg_dir in (None, ".", ""):
                continue
            for field in PACKAGE_MAIN_FIELDS:
                value = data.get(field)
                if isinstance(value, str) and value:
                    add("workspace_" + field, os.path.join(pkg_dir, value),
                        "%s (%s)" % (entry["rel"], field), name=field)

    for item in scope_files:
        rel = item["rel"]
        base = os.path.basename(rel).lower()
        if scope_rel in (".", ""):
            depth = rel.count("/")
            for pkg_dir in workspace_dirs:
                if rel.startswith(pkg_dir + "/"):
                    depth = rel[len(pkg_dir) + 1:].count("/")
                    break
        else:
            depth = _depth_in_scope(rel, scope_rel)
        if rel in (".", "") or base not in CONVENTIONAL_ENTRY_NAMES:
            continue
        if depth > 2:
            continue
        if base in {"index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs",
                    "index.cjs", "index.py", "__init__.py"} and depth > 1:
            continue
        if base == "main.go" or base.endswith("main.go"):
            add("go_main", rel, rel)
        elif base in ("main.rs", "lib.rs"):
            add("rust_entry", rel, rel)
        elif base.endswith("application.java") or base.endswith("main.java") or base == "main.kt":
            add("java_main", rel, rel)
        elif base in ("__init__.py", "app.py", "manage.py", "wsgi.py", "asgi.py",
                      "__main__.py", "main.py"):
            add("python_entry", rel, rel)
        else:
            add("convention", rel, rel)

    entries.sort(key=lambda item: (item["kind"], item["path"]))
    return entries[:60]


def _api_source_files(scope_files, scope_rel, entry_points):
    chosen = []
    seen = set()

    def add(rel):
        if rel in seen:
            return
        seen.add(rel)
        chosen.append(rel)

    for entry in entry_points:
        if entry.get("exists") and entry["path"] in {item["rel"] for item in scope_files}:
            add(entry["path"])
    for item in scope_files:
        rel = item["rel"]
        base = os.path.basename(rel).lower()
        if base in INDEXISH_NAMES and _depth_in_scope(rel, scope_rel) <= 2:
            add(rel)
    return chosen


def extract_public_api(contents, scope_files, scope_rel, entry_points):
    files_by_rel = {item["rel"]: item for item in scope_files}
    api = []
    seen = set()

    def add(name, kind, rel, line):
        key = (name, rel)
        if not name or key in seen:
            return
        seen.add(key)
        api.append({
            "name": name,
            "kind": kind,
            "path": rel,
            "line": line,
            "evidence": "%s:%d" % (rel, line),
        })

    for rel in _api_source_files(scope_files, scope_rel, entry_points):
        if rel not in files_by_rel:
            continue
        text = contents.get(rel)
        if not text:
            continue
        ext = os.path.splitext(rel)[1].lower()
        lines = text.splitlines()
        for index, line in enumerate(lines):
            line_no = index + 1
            if ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"):
                match = JS_EXPORT_DECL_RE.match(line)
                if match:
                    add(match.group(1), "export", rel, line_no)
                    continue
                match = JS_EXPORT_DEFAULT_RE.match(line)
                if match:
                    add(match.group(1), "export_default", rel, line_no)
                    continue
                match = JS_EXPORT_LIST_RE.match(line)
                if match:
                    for token in re.split(r"[,\s]+", match.group(1)):
                        token = token.strip()
                        if not token:
                            continue
                        name = token.split(" as ")[-1].strip()
                        add(name, "export", rel, line_no)
                    continue
                match = JS_EXPORT_STAR_RE.match(line)
                if match:
                    add("* from %s" % match.group(1), "re_export", rel, line_no)
            elif ext == ".py":
                match = PY_DEF_RE.match(line)
                if match:
                    name = match.group(1)
                    if not name.startswith("_"):
                        add(name, "def", rel, line_no)
                    continue
                match = PY_CLASS_RE.match(line)
                if match:
                    name = match.group(1)
                    if not name.startswith("_"):
                        add(name, "class", rel, line_no)
                if "__all__" in line:
                    window = "\n".join(lines[index:index + 8])
                    for name in re.findall(r"['\"]([A-Za-z_]\w*)['\"]", window):
                        add(name, "__all__", rel, line_no)
    api.sort(key=lambda item: (item["path"], item["line"], item["name"]))
    return api


def extract_commands(project_root, scope_files, scope_rel, pkg_data, pkg_rel,
                     package_index, module_path):
    commands = []
    seen = set()

    def add(name, command, source, cwd, evidence):
        key = (name, command, cwd)
        if key in seen:
            return
        seen.add(key)
        commands.append({
            "name": name,
            "command": command,
            "source": source,
            "cwd": cwd,
            "evidence": evidence,
        })

    def add_package_json(rel, data):
        if not isinstance(data, dict):
            return
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            return
        cwd = os.path.dirname(rel) or "."
        for name in sorted(scripts):
            value = scripts[name]
            if isinstance(value, str):
                add(name, value, "package.json scripts", cwd, rel)

    if isinstance(pkg_data, dict) and pkg_rel:
        add_package_json(pkg_rel, pkg_data)
    root_pkg = _read_package_json(project_root)
    add_package_json("package.json", root_pkg)

    used_manifests = {pkg_rel} if pkg_rel else set()
    for entry in package_index:
        if entry["rel"] in used_manifests:
            continue
        if len(commands) >= MAX_COMMANDS:
            break
        if module_path not in (".", "") and not entry["dir_rel"].startswith(module_path):
            if entry["dir_rel"] != ".":
                continue
        add_package_json(entry["rel"], entry["data"])

    # Makefile / justfile
    makefile_rels = ["Makefile", "makefile"]
    if module_path not in (".", ""):
        for item in scope_files:
            if os.path.basename(item["rel"]) in ("Makefile", "makefile"):
                makefile_rels.append(item["rel"])
    for rel in sorted(set(makefile_rels)):
        abs_path = os.path.join(project_root, rel.replace("/", os.sep))
        if not os.path.isfile(abs_path):
            continue
        text = read_text_file(abs_path)
        if not text:
            continue
        cwd = os.path.dirname(rel) or "."
        for index, line in enumerate(text.splitlines()):
            match = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*:(?!=)", line)
            if not match:
                continue
            target = match.group(1)
            if target.lower() in ("phony",):
                continue
            add(target, "make %s" % target, "Makefile target", cwd,
                "%s:%d" % (rel, index + 1))

    # pyproject console scripts
    pyproject_rel = "pyproject.toml"
    pyproject_abs = os.path.join(project_root, pyproject_rel)
    if os.path.isfile(pyproject_abs):
        text = read_text_file(pyproject_abs)
        if text:
            for section_match in re.finditer(
                r"\[(project|tool\.poetry)\.scripts\](.*?)(?:\n\[|\Z)", text, re.S
            ):
                section = section_match.group(0)
                for line in section.splitlines():
                    script_match = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*=\s*['\"]([^'\"]+)['\"]", line)
                    if script_match:
                        add(script_match.group(1), script_match.group(1),
                            "pyproject scripts", ".", pyproject_rel)

    commands.sort(key=lambda item: (item["cwd"], item["name"], item["command"]))
    return commands[:MAX_COMMANDS]


def extract_tests(contents, scope_files, scope_rel, pkg_data):
    tests = []
    seen = set()
    dev_deps = set()
    if isinstance(pkg_data, dict):
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            value = pkg_data.get(key)
            if isinstance(value, dict):
                dev_deps.update(value.keys())

    def framework_for(rel, text):
        lowered = (text or "").lower()
        for token, framework in FRAMEWORK_TOKENS:
            if token.lower() in lowered:
                return framework
        ext = os.path.splitext(rel)[1].lower()
        if ext == ".py":
            return "pytest" if "pytest" in dev_deps else "python-test"
        if ext == ".go":
            return "go test"
        if "vitest" in dev_deps:
            return "vitest"
        if "jest" in dev_deps:
            return "jest"
        return "unknown"

    for item in scope_files:
        rel = item["rel"]
        base = os.path.basename(rel)
        is_test = bool(TEST_FILE_RE.search(rel))
        if not is_test and TEST_DIR_RE.search(rel) and os.path.splitext(rel)[1].lower() in LANG_BY_EXT:
            is_test = os.path.splitext(rel)[1].lower() in (".py", ".go", ".ts", ".tsx", ".js", ".jsx",
                                                          ".mts", ".cts", ".rs", ".java", ".kt")
        if not is_test:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        tests.append({
            "path": rel,
            "framework": framework_for(rel, contents.get(rel)),
            "kind": "test",
            "evidence": rel,
        })
    tests.sort(key=lambda item: item["path"])
    return tests


def extract_configs(scope_files):
    configs = []
    for item in scope_files:
        rel = item["rel"]
        base = os.path.basename(rel).lower()
        is_config = (
            base in CONFIG_NAMES
            or base.startswith(CONFIG_PREFIXES)
            or bool(CI_PATH_RE.search(rel))
        )
        if not is_config:
            continue
        if CI_PATH_RE.search(rel) or base.endswith((".yml", ".yaml")):
            kind = "ci" if CI_PATH_RE.search(rel) else "config"
        elif base.startswith(".env"):
            kind = "env"
        elif base in MANIFEST_NAMES:
            kind = "manifest"
        elif "docker" in base:
            kind = "docker"
        else:
            kind = "config"
        configs.append({"path": rel, "kind": kind, "evidence": rel})
    configs.sort(key=lambda item: item["path"])
    return configs


def extract_docs(scope_files, project_docs=None):
    docs = []
    seen = set()
    entries = list(scope_files)
    for item in project_docs or []:
        entries.append(item)
    for item in entries:
        rel = item["rel"]
        if rel in seen:
            continue
        base = os.path.basename(rel).lower()
        is_docs_dir = rel.startswith("docs/") or "/docs/" in rel
        if not (base in DOC_NAMES or (is_docs_dir and rel.lower().endswith((".md", ".rst", ".mdx")))):
            continue
        seen.add(rel)
        if base.startswith("readme"):
            kind = "readme"
        elif base.startswith("changelog"):
            kind = "changelog"
        elif base.startswith("contributing"):
            kind = "contributing"
        elif "adr" in rel.lower():
            kind = "adr"
        else:
            kind = "doc"
        docs.append({"path": rel, "kind": kind, "evidence": rel})
    docs.sort(key=lambda item: (item["kind"], item["path"]))
    return docs


def _find_manifest_for_scope(project_root, module_rel, filename):
    abs_path = os.path.join(project_root, module_rel.replace("/", os.sep), filename)
    if os.path.isfile(abs_path):
        return norm_rel(abs_path, project_root)
    return None


def _parse_pyproject_deps(text):
    deps = []
    match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.M | re.S)
    if match:
        for raw in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)):
            name = re.split(r"[<>=!~;\[\s]", raw.strip(), 1)[0]
            if name:
                deps.append((name, _short(raw.strip(), 60)))
    return deps


def extract_dependencies(project_root, scope_files, scope_rel, pkg_data, pkg_rel,
                         monorepo):
    internal = []
    external = []
    seen_ext = set()
    internal_names = {pkg["name"]: pkg for pkg in monorepo.get("packages", [])}

    def add_external(name, version, kind, evidence):
        if not name or name in seen_ext:
            return
        seen_ext.add(name)
        external.append({
            "name": name,
            "version": _short(version, 60) if version else None,
            "kind": kind,
            "evidence": evidence,
        })

    if isinstance(pkg_data, dict):
        for kind in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            value = pkg_data.get(kind)
            if not isinstance(value, dict):
                continue
            for name in sorted(value):
                version = value[name]
                version = version if isinstance(version, str) else ""
                if name in internal_names and internal_names[name]["path"] != scope_rel:
                    internal.append({
                        "name": name,
                        "path": internal_names[name]["path"],
                        "kind": "workspace",
                        "evidence": pkg_rel,
                    })
                else:
                    add_external(name, version, kind, pkg_rel)

    if not external:
        pyproject_rel = _find_manifest_for_scope(project_root, scope_rel, "pyproject.toml")
        if pyproject_rel:
            text = read_text_file(os.path.join(project_root, pyproject_rel.replace("/", os.sep))) or ""
            for name, version in _parse_pyproject_deps(text):
                if name in internal_names:
                    internal.append({"name": name, "path": internal_names[name]["path"],
                                     "kind": "workspace", "evidence": pyproject_rel})
                else:
                    add_external(name, version, "python", pyproject_rel)
        req_rel = _find_manifest_for_scope(project_root, scope_rel, "requirements.txt")
        if req_rel:
            text = read_text_file(os.path.join(project_root, req_rel.replace("/", os.sep))) or ""
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-", "git+", "http")):
                    continue
                name = re.split(r"[<>=!~;\[\s]", line, 1)[0]
                if name:
                    add_external(name, line, "pip", req_rel)

    go_mod_rel = _find_manifest_for_scope(project_root, scope_rel, "go.mod")
    if go_mod_rel:
        text = read_text_file(os.path.join(project_root, go_mod_rel.replace("/", os.sep))) or ""
        for match in re.finditer(r"^\s*([a-zA-Z0-9_.\-/]+\.[a-zA-Z]{2,}[^\s]*)\s+(v[0-9][^\s]*)", text, re.M):
            add_external(match.group(1), match.group(2), "go", go_mod_rel)

    cargo_rel = _find_manifest_for_scope(project_root, scope_rel, "Cargo.toml")
    if cargo_rel:
        text = read_text_file(os.path.join(project_root, cargo_rel.replace("/", os.sep))) or ""
        section = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
        if section:
            for match in re.finditer(
                r"^\s*([A-Za-z0-9_-]+)\s*=\s*(?:\"([^\"]*)\"|\{[^}]*version\s*=\s*\"([^\"]*)\")",
                section.group(1), re.M,
            ):
                add_external(match.group(1), match.group(2) or match.group(3) or "", "rust", cargo_rel)

    internal = sorted({(item["name"], item["path"]): item for item in internal}.values(),
                      key=lambda item: (item["path"], item["name"]))
    external.sort(key=lambda item: item["name"])
    return {"internal": internal, "external_top": external[:MAX_DEPENDENCIES]}


def extract_signals(contents):
    todos = []
    fixmes = []
    env_vars = []
    routes = []
    seen_env = set()
    seen_route = set()

    for rel in sorted(contents):
        text = contents[rel]
        if not text:
            continue
        lines = text.splitlines()
        is_dotenv = os.path.basename(rel).lower().startswith(".env")
        for index, line in enumerate(lines):
            line_no = index + 1
            if TODO_RE.search(line):
                todos.append({
                    "text": _short(line.strip()),
                    "path": rel,
                    "line": line_no,
                    "evidence": "%s:%d" % (rel, line_no),
                })
            if FIXME_RE.search(line):
                fixmes.append({
                    "text": _short(line.strip()),
                    "path": rel,
                    "line": line_no,
                    "evidence": "%s:%d" % (rel, line_no),
                })
            if is_dotenv:
                match = DOTENV_RE.match(line)
                if match:
                    key = (match.group(1), rel, line_no)
                    if key not in seen_env:
                        seen_env.add(key)
                        env_vars.append({
                            "name": match.group(1),
                            "path": rel,
                            "line": line_no,
                            "evidence": "%s:%d" % (rel, line_no),
                        })
            else:
                for pattern in ENV_PATTERNS:
                    for match in pattern.finditer(line):
                        key = (match.group(1), rel, line_no)
                        if key in seen_env:
                            continue
                        seen_env.add(key)
                        env_vars.append({
                            "name": match.group(1),
                            "path": rel,
                            "line": line_no,
                            "evidence": "%s:%d" % (rel, line_no),
                        })
                for match in ENV_CONST_RE.finditer(line):
                    const_name, env_name = match.group(1), match.group(2)
                    if "ENV" not in const_name.upper():
                        continue
                    key = (env_name, rel, line_no)
                    if key in seen_env:
                        continue
                    seen_env.add(key)
                    env_vars.append({
                        "name": env_name,
                        "via": const_name,
                        "path": rel,
                        "line": line_no,
                        "evidence": "%s:%d" % (rel, line_no),
                    })
                for pattern in ROUTE_PATTERNS[:2]:
                    for match in pattern.finditer(line):
                        key = (match.group(1).upper(), match.group(2), rel, line_no)
                        if key in seen_route:
                            continue
                        seen_route.add(key)
                        routes.append({
                            "method": match.group(1).upper(),
                            "path": match.group(2),
                            "file": rel,
                            "line": line_no,
                            "evidence": "%s:%d" % (rel, line_no),
                        })
                for pattern_idx, pattern in enumerate(ROUTE_PATTERNS[2:]):
                    for match in pattern.finditer(line):
                        method = "GET" if pattern_idx == 0 else "ANY"
                        key = (method, match.group(1), rel, line_no)
                        if key in seen_route:
                            continue
                        seen_route.add(key)
                        routes.append({
                            "method": method,
                            "path": match.group(1),
                            "file": rel,
                            "line": line_no,
                            "evidence": "%s:%d" % (rel, line_no),
                        })
        base = os.path.basename(rel)
        pages_match = NEXT_PAGES_API_RE.search(rel)
        if pages_match:
            route = "/api/" + re.sub(r"\[([^\]]+)\]", r":\1", pages_match.group(1))
            key = ("ANY", route, rel, 0)
            if key not in seen_route:
                seen_route.add(key)
                routes.append({"method": "ANY", "path": route, "file": rel, "line": 0,
                               "evidence": rel})
        if base in ("page.tsx", "page.jsx", "page.ts", "page.js"):
            app_match = NEXT_APP_PAGE_RE.search(rel)
            if app_match:
                route = "/" + re.sub(r"\([^)]*\)/?", "", app_match.group(1))
                route = re.sub(r"\[([^\]]+)\]", r":\1", route)
                key = ("GET", route, rel, 0)
                if key not in seen_route:
                    seen_route.add(key)
                    routes.append({"method": "GET", "path": route, "file": rel, "line": 0,
                                   "evidence": rel})

    todos.sort(key=lambda item: (item["path"], item["line"]))
    fixmes.sort(key=lambda item: (item["path"], item["line"]))
    env_vars.sort(key=lambda item: (item["name"], item["path"], item["line"]))
    routes.sort(key=lambda item: (item["path"], item["line"], item["method"]))
    return {
        "todos": todos[:MAX_SIGNAL_ITEMS],
        "fixmes": fixmes[:MAX_SIGNAL_ITEMS],
        "env_vars": env_vars[:MAX_SIGNAL_ITEMS],
        "routes": routes[:MAX_SIGNAL_ITEMS],
    }


def static_hotspots(contents, signals, public_api, top=20):
    scores = Counter()
    for rel in contents:
        scores[rel] += 0
    for bucket in ("todos", "fixmes"):
        for item in signals[bucket]:
            scores[item["path"]] += 2
    for item in public_api:
        scores[item["path"]] += 1
    for item in signals["env_vars"]:
        scores[item["path"]] += 1
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return [
        {"path": path, "score": score, "reason": "static_signals", "evidence": path}
        for path, score in ordered if score > 0
    ]


# ---------------------------------------------------------------------------
# 汇总与渲染
# ---------------------------------------------------------------------------

def build_next_steps(facts):
    steps = []
    existing_entries = []
    for entry in facts["entry_points"]:
        if entry.get("exists") and entry["path"] not in existing_entries:
            existing_entries.append(entry["path"])
    if not existing_entries:
        for entry in facts["entry_points"]:
            if entry["path"] not in existing_entries:
                existing_entries.append(entry["path"])
    if existing_entries:
        steps.append("点读入口：%s" % ", ".join(existing_entries[:3]))
    if facts["tests"]:
        steps.append("点读测试：%s" % facts["tests"][0]["path"])
    docs = [item["path"] for item in facts["docs"] if item["kind"] == "readme"]
    if docs:
        steps.append("快速读文档：%s" % docs[0])
    if facts["signals"]["todos"] or facts["signals"]["fixmes"]:
        steps.append("确认 TODO/FIXME 是否属于本次任务范围（共 %d 条）"
                     % (len(facts["signals"]["todos"]) + len(facts["signals"]["fixmes"])))
    if facts["module"]["candidates"]:
        steps.append("如做项目总览，从 module.candidates 里挑选要生成的模块技能")
    steps.append("按 SKILL.md 的 P2/P3 定向补读，并向用户提问业务边界、不变式、常见故障")
    if facts["warnings"]:
        steps.append("先看 warnings（共 %d 条），确认哪些事实因降级而缺失" % len(facts["warnings"]))
    return steps[:6]


def _render_tree(file_tree, limit=160):
    lines = []
    for rel in file_tree[:limit]:
        lines.append(rel)
    if len(file_tree) > limit:
        lines.append("…（其余 %d 个文件见 facts.json 的 file_tree）" % (len(file_tree) - limit))
    return lines


def _render_list(items, formatter, empty_text, limit=40):
    if not items:
        return ["- %s" % empty_text]
    lines = []
    for item in items[:limit]:
        lines.append("- " + formatter(item))
    if len(items) > limit:
        lines.append("- …（共 %d 条，完整内容见 facts.json）" % len(items))
    return lines


def render_fact_pack(facts):
    lines = []
    project = facts["project"]
    module = facts["module"]
    git = project["git"]
    module_label = module["path"] if module["path"] != "." else "（整个项目）"

    lines.append("# Fact Pack — %s / %s" % (project["name"], module_label))
    lines.append("")
    lines.append("> 由 `scan_module.py` 生成（%s）。只读扫描，未修改被扫描项目；" % facts["generated_at"])
    lines.append("> 完整结构化事实见同目录 `facts.json`（schema_version=%d）。" % facts["schema_version"])
    lines.append("> 所有路径均相对项目根 `%s`。" % project["root"])
    lines.append("")

    lines.append("## 1. 项目画像")
    lines.append("")
    lines.append("- 项目名：`%s`" % project["name"])
    lines.append("- 根：`%s`（相对路径）" % project["root"])
    if git.get("available"):
        lines.append("- git：可用；分支 `%s`，HEAD `%s`，提交 %s 个，工作区%s" % (
            git.get("branch") or "?",
            git.get("head") or "?",
            git.get("commits") if git.get("commits") is not None else "?",
            "有未提交改动" if git.get("dirty") else "干净",
        ))
    else:
        lines.append("- git：不可用（无仓库或 git 命令缺失）")
    langs = ", ".join("%s(%d)" % (item["name"], item["files"]) for item in project["languages"]) or "未识别"
    lines.append("- 语言：%s" % langs)
    lines.append("- 包管理器：%s" % (", ".join(project["package_managers"]) or "未识别"))
    monorepo = project["monorepo"]
    if monorepo["is_monorepo"]:
        lines.append("- monorepo：是（%s），%d 个包" % (monorepo["tool"], len(monorepo["packages"])))
    else:
        lines.append("- monorepo：否")
    lines.append("")

    lines.append("## 2. 模块候选")
    lines.append("")
    if module["candidates"]:
        lines.append("| 路径 | 名称 | 类型 | 证据 |")
        lines.append("|---|---|---|---|")
        for item in module["candidates"]:
            lines.append("| `%s` | %s | %s | `%s` |" % (
                item["path"], _cell(item["name"]), item["kind"], item["evidence"]))
    else:
        lines.append("- 未发现明确的模块候选（项目可能很小或没有清单文件）")
    lines.append("")

    lines.append("## 3. 入口（entry_points）")
    lines.append("")
    if facts["entry_points"]:
        lines.append("| 类型 | 路径 | 存在 | 证据 |")
        lines.append("|---|---|---|---|")
        for item in facts["entry_points"]:
            lines.append("| %s | `%s` | %s | `%s` |" % (
                item["kind"], item["path"], "是" if item.get("exists") else "否", item["evidence"]))
    else:
        lines.append("- 未识别到入口文件；请人工确认启动点/包入口")
    lines.append("")

    lines.append("## 4. 公开 API（public_api）")
    lines.append("")
    lines.extend(_render_list(
        facts["public_api"],
        lambda item: "`%s`（%s）— `%s`" % (item["name"], item["kind"], item["evidence"]),
        "未识别到导出符号（可能不是库，或 API 入口不在 index/入口文件里）",
    ))
    lines.append("")

    lines.append("## 5. 命令（commands）")
    lines.append("")
    if facts["commands"]:
        lines.append("| 名称 | 命令 | 来源 | cwd | 证据 |")
        lines.append("|---|---|---|---|---|")
        for item in facts["commands"]:
            lines.append("| %s | `%s` | %s | `%s` | `%s` |" % (
                _cell(item["name"]), _cell(item["command"]), item["source"],
                item["cwd"], item["evidence"]))
    else:
        lines.append("- 未从 package.json scripts / Makefile / pyproject 中发现命令；不要编造命令")
    lines.append("")

    lines.append("## 6. 测试（tests）")
    lines.append("")
    lines.extend(_render_list(
        facts["tests"],
        lambda item: "`%s`（框架：%s）" % (item["path"], item["framework"]),
        "未发现测试文件；verification 里只能写「需人工确认」",
    ))
    lines.append("")

    lines.append("## 7. 依赖（dependencies）")
    lines.append("")
    lines.append("**内部依赖（workspace）**")
    lines.append("")
    lines.extend(_render_list(
        facts["dependencies"]["internal"],
        lambda item: "`%s` → `%s`（%s）" % (item["name"], item["path"], item["evidence"]),
        "无",
        limit=20,
    ))
    lines.append("")
    lines.append("**外部依赖（Top %d）**" % len(facts["dependencies"]["external_top"]))
    lines.append("")
    lines.extend(_render_list(
        facts["dependencies"]["external_top"],
        lambda item: "`%s`%s（%s）" % (
            item["name"],
            (" " + item["version"]) if item.get("version") else "",
            item["evidence"],
        ),
        "无",
        limit=30,
    ))
    lines.append("")

    lines.append("## 8. TODO / FIXME")
    lines.append("")
    lines.append("**TODO（%d）**" % len(facts["signals"]["todos"]))
    lines.append("")
    lines.extend(_render_list(
        facts["signals"]["todos"],
        lambda item: "`%s` — %s" % (item["evidence"], item["text"]),
        "无",
        limit=30,
    ))
    lines.append("")
    lines.append("**FIXME（%d）**" % len(facts["signals"]["fixmes"]))
    lines.append("")
    lines.extend(_render_list(
        facts["signals"]["fixmes"],
        lambda item: "`%s` — %s" % (item["evidence"], item["text"]),
        "无",
        limit=30,
    ))
    lines.append("")
    env_groups = {}
    for item in facts["signals"]["env_vars"]:
        env_groups.setdefault(item["name"], []).append(item["evidence"])
    lines.append("**环境变量（%d 个唯一变量，%d 处引用）**"
                 % (len(env_groups), len(facts["signals"]["env_vars"])))
    lines.append("")
    if env_groups:
        for env_name in sorted(env_groups):
            evidence_list = ", ".join(sorted(set(env_groups[env_name])))
            lines.append("- `%s` — %s" % (env_name, evidence_list))
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("**路由（%d）**" % len(facts["signals"]["routes"]))
    lines.append("")
    lines.extend(_render_list(
        facts["signals"]["routes"],
        lambda item: "%s `%s` — `%s`" % (item["method"], item["path"], item["evidence"]),
        "无",
        limit=20,
    ))
    lines.append("")

    lines.append("## 9. 热点（hotspots）")
    lines.append("")
    if facts["hotspots"]:
        lines.append("| 路径 | 分数 | 依据 |")
        lines.append("|---|---|---|")
        for item in facts["hotspots"]:
            lines.append("| `%s` | %d | %s |" % (item["path"], item["score"], item["reason"]))
    else:
        lines.append("- 暂无可排序的热点（无 git 历史且无 TODO/API 信号）")
    lines.append("")

    lines.append("## 10. 文件树（完整相对路径，共 %d 个文件）" % len(facts["file_tree"]))
    lines.append("")
    lines.append("```")
    lines.extend(_render_tree(facts["file_tree"]))
    lines.append("```")
    lines.append("")

    lines.append("## 11. 警告（warnings）")
    lines.append("")
    if facts["warnings"]:
        for warning in facts["warnings"]:
            lines.append("- ⚠️ %s" % warning)
    else:
        lines.append("- 无")
    lines.append("")

    lines.append("## 12. 建议下一步")
    lines.append("")
    for index, step in enumerate(build_next_steps(facts), start=1):
        lines.append("%d. %s" % (index, step))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def scan(project_root, module_arg, max_files, out_dir):
    warnings = []
    files, walk_stats = walk_files(project_root, max_files, os.path.abspath(out_dir))
    if walk_stats.get("truncated"):
        warnings.append("文件数超过 --max-files=%d，扫描已截断：事实可能不完整" % max_files)
    if walk_stats.get("skipped_large"):
        warnings.append("跳过了 %d 个大于 1MB 的文件（不参与事实提取）" % walk_stats["skipped_large"])
    if walk_stats.get("skipped_symlink"):
        warnings.append("跳过了 %d 个符号链接（避免越出项目目录）" % walk_stats["skipped_symlink"])

    git_facts, git_warnings = collect_git(project_root)
    warnings.extend(git_warnings)

    package_index = _collect_package_index(files, project_root)
    monorepo = detect_monorepo(project_root, package_index, warnings)
    candidates = find_candidates(project_root, files, monorepo)

    module_path = resolve_module(project_root, module_arg, candidates, package_index)

    if module_arg and module_path not in (".", ""):
        known = {item["rel"] for item in files}
        scope_files = [item for item in files
                       if item["rel"] == module_path or item["rel"].startswith(module_path + "/")]
        if not scope_files and walk_stats.get("truncated"):
            extra_files, _extra_stats = _walk_module_extra(
                project_root, module_path, known, max_files)
            if extra_files:
                files = sorted(files + extra_files, key=lambda item: item["rel"])
                scope_files = [item for item in files
                               if item["rel"] == module_path or item["rel"].startswith(module_path + "/")]
                warnings.append("项目文件数超过 --max-files，已优先补齐模块目录的文件")
    else:
        scope_files = list(files)

    contents = {}
    read_failures = 0
    for item in scope_files:
        text = read_text_file(item["abs"])
        if text is None:
            read_failures += 1
            continue
        contents[item["rel"]] = text
    if read_failures:
        warnings.append("有 %d 个文件无法按文本读取（二进制或权限问题），未参与事实提取" % read_failures)

    # 模块清单（scope 根目录下的清单优先）
    pkg_rel = _find_manifest_for_scope(project_root, module_path, "package.json")
    pkg_data = None
    if pkg_rel:
        pkg_data = read_json_file(os.path.join(project_root, pkg_rel.replace("/", os.sep)))
    if pkg_rel is None and module_path not in (".", ""):
        warnings.append("模块目录内未找到 package.json：命令/依赖事实可能不完整（尝试从项目根清单提取）")

    root_pkg = _read_package_json(project_root)
    if not any(name in ("package.json", "pyproject.toml", "go.mod", "Cargo.toml",
                        "pom.xml", "requirements.txt", "build.gradle")
               for name in {os.path.basename(item["rel"]) for item in files}):
        warnings.append("未检测到任何包管理清单：命令、依赖、测试框架事实可能为空")

    project_docs = []
    for name in ("README.md", "README.rst", "README.txt", "CHANGELOG.md", "CONTRIBUTING.md"):
        abs_path = os.path.join(project_root, name)
        if os.path.isfile(abs_path):
            project_docs.append({"rel": name, "abs": abs_path, "size": os.path.getsize(abs_path)})

    entry_points = extract_entry_points(
        project_root, scope_files, module_path, pkg_data, pkg_rel, package_index)
    public_api = extract_public_api(contents, scope_files, module_path, entry_points)
    if len(public_api) >= MAX_PUBLIC_API:
        warnings.append("公开 API 超过 %d 条已截断，完整清单请点读入口文件" % MAX_PUBLIC_API)
    commands = extract_commands(
        project_root, scope_files, module_path, pkg_data, pkg_rel,
        package_index, module_path)
    tests = extract_tests(contents, scope_files, module_path, pkg_data or root_pkg)
    configs = extract_configs(scope_files)
    docs = extract_docs(scope_files, project_docs)
    dependencies = extract_dependencies(
        project_root, scope_files, module_path, pkg_data, pkg_rel, monorepo)
    signals = extract_signals(contents)
    file_tree = [item["rel"] for item in scope_files]

    if git_facts.get("available") and git_facts.get("commits"):
        hotspots = git_hotspots(project_root, git_facts, file_tree)
    else:
        hotspots = static_hotspots(contents, signals, public_api)
    if not hotspots and module_path in (".", ""):
        warnings.append("没有可用的热点信号（无 git 历史、无 TODO/FIXME/API）：hotspots 为空，属正常降级")

    project_name = os.path.basename(os.path.abspath(project_root)) or "project"
    manifest_name = None
    if isinstance(root_pkg, dict) and isinstance(root_pkg.get("name"), str):
        manifest_name = root_pkg["name"].split("/")[-1]
    if manifest_name:
        project_name = manifest_name
    module_name = os.path.basename(module_path) if module_path not in (".", "") else project_name
    if isinstance(pkg_data, dict) and isinstance(pkg_data.get("name"), str):
        module_name = pkg_data["name"]

    facts = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "project": {
            "root": ".",
            "name": project_name,
            "git": git_facts,
            "languages": detect_languages(files),
            "package_managers": detect_package_managers(project_root, files),
            "monorepo": monorepo,
        },
        "module": {
            "path": module_path,
            "name": module_name,
            "candidates": candidates,
        },
        "entry_points": entry_points,
        "public_api": public_api,
        "commands": commands,
        "tests": tests,
        "configs": configs,
        "docs": docs,
        "dependencies": dependencies,
        "signals": signals,
        "file_tree": file_tree,
        "hotspots": hotspots,
        "warnings": sorted(set(warnings)),
    }
    return facts


def _slugify(value):
    slug = value.strip().lower()
    if "/" in slug:
        slug = slug.split("/")[-1]
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug or "project"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="scan_module.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "只读扫描目标项目，产出 facts.json（schema_version=1）与 fact-pack.md。\n"
            "用于 module-skill-forge 的 P1 阶段：先取事实，再定向补读、访谈、生成技能。"
        ),
        epilog=(
            "输出\n"
            "  facts.json         结构化事实包，字段：schema_version, generated_at,\n"
            "                     project{root,name,git,languages,package_managers,monorepo},\n"
            "                     module{path,name,candidates}, entry_points, public_api,\n"
            "                     commands, tests, configs, docs,\n"
            "                     dependencies{internal,external_top},\n"
            "                     signals{todos,fixmes,env_vars,routes}, file_tree,\n"
            "                     hotspots, warnings。每条事实带相对 evidence。\n"
            "  fact-pack.md       人/模型可读摘要（也包含「建议下一步」）。\n"
            "\n"
            "默认输出目录：<project>/.dsh/forge/<slug>/\n"
            "\n"
            "退出码\n"
            "  0  成功\n"
            "  2  参数错误、项目不存在、模块无法解析\n"
            "\n"
            "示例\n"
            "  python3 scan_module.py --project fixtures/sample-shop --module packages/catalog\n"
            "  python3 scan_module.py --project . --out /tmp/facts --json\n"
            "  python3 scan_module.py --project . --max-files 800\n"
        ),
    )
    parser.add_argument(
        "--project", default=None,
        help="项目根目录（默认：git rev-parse --show-toplevel，失败则当前目录）。目录必须存在。",
    )
    parser.add_argument(
        "--module", default=None,
        help="只聚焦的模块：相对 project 的路径、绝对路径或 monorepo 包名。省略则扫描整个项目。",
    )
    parser.add_argument(
        "--out", default=None,
        help="输出目录（只写这里）。默认 <project>/.dsh/forge/<slug>/。",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="stdout 只输出一个 JSON 对象（含 facts_path、fact_pack_path、summary）。",
    )
    parser.add_argument(
        "--max-files", type=_positive_int, default=DEFAULT_MAX_FILES, metavar="N",
        help="最多收集/读取的文件数，默认 %d；触顶会截断并写 warning。" % DEFAULT_MAX_FILES,
    )
    return parser


def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("必须是正整数：%r" % value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数：%r" % value)
    return number


def _resolve_default_project():
    ok, out, _err = _run(["git", "rev-parse", "--show-toplevel"])
    if ok and out.strip():
        candidate = out.strip().splitlines()[0].strip()
        if os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def _print_error(message, as_json):
    print("扫描失败：%s" % message, file=sys.stderr)
    if as_json:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))


def _summary_text(facts, facts_path, fact_pack_path, project_root):
    module = facts["module"]
    module_label = module["path"] if module["path"] != "." else "整个项目"
    command_names_seen = []
    for item in facts["commands"]:
        if item["name"] not in command_names_seen:
            command_names_seen.append(item["name"])
    command_names = ", ".join(command_names_seen[:6]) or "无"
    env_names = {item["name"] for item in facts["signals"]["env_vars"]}
    existing_entries = [entry for entry in facts["entry_points"] if entry.get("exists")]
    missing_entries = len(facts["entry_points"]) - len(existing_entries)
    entry_line = "入口: %d · 公开 API: %d · 测试: %d" % (
        len(existing_entries), len(facts["public_api"]), len(facts["tests"]))
    if missing_entries:
        entry_line += "（另有 %d 条构建产物/未生成入口，exists=false）" % missing_entries
    lines = [
        "扫描完成：%s / %s" % (facts["project"]["name"], module_label),
        "facts: %s" % display_out_path(facts_path, project_root),
        "fact-pack: %s" % display_out_path(fact_pack_path, project_root),
        "语言: %s" % (", ".join(item["name"] for item in facts["project"]["languages"]) or "未识别"),
        "包管理器: %s" % (", ".join(facts["project"]["package_managers"]) or "未识别"),
        "monorepo: %s" % (
            "%s（%d 包）" % (facts["project"]["monorepo"]["tool"],
                             len(facts["project"]["monorepo"]["packages"]))
            if facts["project"]["monorepo"]["is_monorepo"] else "否"),
        entry_line,
        "命令: %d 条（%s）" % (len(facts["commands"]), command_names),
        "TODO/FIXME: %d/%d · %s · 路由: %d" % (
            len(facts["signals"]["todos"]), len(facts["signals"]["fixmes"]),
            ("环境变量: 0" if not env_names else
             "环境变量: %d（%d 处引用）" % (len(env_names), len(facts["signals"]["env_vars"]))),
            len(facts["signals"]["routes"])),
        "警告: %d 条" % len(facts["warnings"]),
        "下一步: 读 fact-pack.md；点读入口与测试；再按 SKILL.md 访谈补语义",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = args.project if args.project else _resolve_default_project()
    project_root = os.path.abspath(os.path.expanduser(project_root))
    if not os.path.isdir(project_root):
        _print_error("项目目录不存在或不是目录：%s" % (args.project or project_root), args.json)
        return 2

    slug = _slugify(os.path.basename(project_root) or "project")
    if args.module:
        module_hint = args.module.strip().strip("./").replace("\\", "/")
        if module_hint and module_hint not in (".", ""):
            slug = "%s-%s" % (slug, _slugify(module_hint))

    out_dir = args.out if args.out else os.path.join(project_root, ".dsh", "forge", slug)
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    facts_path = os.path.join(out_dir, "facts.json")
    fact_pack_path = os.path.join(out_dir, "fact-pack.md")

    try:
        facts = scan(project_root, args.module, args.max_files, out_dir)
    except ModuleResolveError as exc:
        message = str(exc)
        if exc.candidates:
            preview = "、".join(item["path"] for item in exc.candidates[:10])
            message += "；候选模块：%s" % preview
        _print_error(message, args.json)
        return 2
    except KeyboardInterrupt:
        _print_error("已中断", args.json)
        return 2
    except Exception as exc:  # noqa: BLE001 - 对任意目录都不能抛 traceback
        _print_error("内部错误（%s: %s）" % (type(exc).__name__, exc), args.json)
        return 2

    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(facts_path, "w", encoding="utf-8") as fh:
            json.dump(facts, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        with open(fact_pack_path, "w", encoding="utf-8") as fh:
            fh.write(render_fact_pack(facts))
    except OSError as exc:
        _print_error("无法写入输出目录 %s（%s）"
                     % (display_out_path(out_dir, project_root), exc), args.json)
        return 2

    if args.json:
        summary = {
            "project": facts["project"]["name"],
            "module": facts["module"]["path"],
            "languages": [item["name"] for item in facts["project"]["languages"]],
            "package_managers": facts["project"]["package_managers"],
            "entry_points": len([entry for entry in facts["entry_points"] if entry.get("exists")]),
            "entry_points_declared": len(facts["entry_points"]),
            "public_api": len(facts["public_api"]),
            "commands": len(facts["commands"]),
            "command_names": list(dict.fromkeys(item["name"] for item in facts["commands"])),
            "tests": len(facts["tests"]),
            "todos": len(facts["signals"]["todos"]),
            "fixmes": len(facts["signals"]["fixmes"]),
            "env_vars": len({item["name"] for item in facts["signals"]["env_vars"]}),
            "env_vars_occurrences": len(facts["signals"]["env_vars"]),
            "warnings": len(facts["warnings"]),
            "next_steps": build_next_steps(facts),
        }
        payload = {
            "ok": True,
            "facts_path": display_out_path(facts_path, project_root),
            "fact_pack_path": display_out_path(fact_pack_path, project_root),
            "summary": summary,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_summary_text(facts, facts_path, fact_pack_path, project_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
