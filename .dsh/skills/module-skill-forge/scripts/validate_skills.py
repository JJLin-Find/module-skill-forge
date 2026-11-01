#!/usr/bin/env python3
"""validate_skills.py — module-skill-forge 的技能契约 / 质量校验器。

用途
    校验一个 DSH 技能根目录（例如 <project>/.dsh/skills）下的所有 bundle 与
    扁平技能，按 docs/design.md §2 / §6.2 的规则报 error / warning，并给出人类
    可读报告。用于 module-skill-forge 的 P5 阶段「修到 0 error」。

    error（违反即不可用）：
      * frontmatter 缺失或不可解析
      * name 缺失、非 kebab-case、或与目录名/文件名不一致
      * description 缺失或超过 500 字符
      * 正文为空
      * 嵌套 SKILL.md（深度 > 2，DSH 不会发现）
      * 同根重名
      * 绝对宿主路径（/Users/、/home/、C:\\ 等）
      * 相对链接目标不存在
    warning（质量建议）：
      * description 少于 40 字符或超过 300 字符
      * description 缺少「何时用」语气（Use when / 当 / 何时）
      * SKILL.md 超过 120 行
      * references/ 里有未被 SKILL.md 引用的文件
      * 未知 frontmatter 键
      * 疑似密钥
      * 给定 --facts 时，技能里写的命令未出现在事实包中

用法
    python3 validate_skills.py --root <skills-root> [--facts <facts.json>]
                               [--json] [--strict]
    python3 validate_skills.py --skill <bundle-dir> [--facts <facts.json>]
                               [--json] [--strict]

参数
    --root <dir>    技能根目录：识别 <root>/<name>/SKILL.md（bundle）和
                    <root>/<name>.md（扁平技能）。目录不存在时退出码 2。
    --skill <dir>   只校验指定 bundle 目录（必须含 SKILL.md），用于单模块命令
                    核对；与 --root 二选一。目录非法时退出码 2。
    --facts <path>  扫描器产出的 facts.json。给出后会检查技能里的命令是否来自
                    事实包（脚本名命中、安装命令白名单、或整条命令出现即通过；
                    其余只警告，不阻断）。
    --json          stdout 只输出一个 JSON 对象
                    {ok, strict, root, focus, errors[], warnings[], skills[], summary}。
    --strict        warning 视同 error：有 warning 也返回退出码 1、ok=false。

退出码
    0  无 error（--strict 下：无 error 且无 warning）
    1  有 error（--strict 下：有 error 或有 warning）
    2  参数错误、技能根不存在、--facts 文件不可读

示例
    python3 validate_skills.py --root .dsh/skills
    python3 validate_skills.py --root examples/sample-shop-skills --strict
    python3 validate_skills.py --skill examples/sample-shop-skills/sample-shop-catalog-dev
    python3 validate_skills.py --root .dsh/skills --facts .dsh/forge/sample-shop/facts.json --json
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import unquote

ALLOWED_FRONTMATTER_KEYS = {
    "name", "description", "whenToUse", "metadata",
    "disable-model-invocation", "user-invocable",
}
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$")
LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
REF_LINK_RE = re.compile(
    r"^\s{0,3}\[[^\]]+\]:\s*<?([^>\s]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*$",
    re.M,
)
FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

HOST_PATH_PATTERNS = [
    (re.compile(r"(?<![\w.])/Users/"), "绝对宿主路径 /Users/"),
    (re.compile(r"(?<![\w.])/home/"), "绝对宿主路径 /home/"),
    (re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:\\"), "绝对宿主路径 C:\\\\（Windows）"),
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
]
KNOWN_COMMAND_PREFIXES = {
    "pnpm", "npm", "npx", "yarn", "bun", "node", "deno", "python", "python3",
    "pytest", "pip", "pip3", "uv", "poetry", "go", "cargo", "mvn", "gradle",
    "gradlew", "make", "just", "docker", "docker-compose", "tsc", "vitest",
    "jest", "vite", "bash", "sh", "zsh", "git", "rg", "ruff", "black", "mypy",
    "eslint", "prettier", "turbo", "nx", "pnpx", "uvx",
}
EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out", "target",
    "coverage", ".venv", "venv", "env", "__pycache__", ".next", ".nuxt",
    "vendor", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".gradle", ".cache", "bower_components",
}
MAX_LINES = 120
MAX_DESCRIPTION = 500
DESCRIPTION_WARN_MIN = 40
DESCRIPTION_WARN_MAX = 300


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def display_path(path):
    """输出中避免绝对宿主路径：尽量相对当前目录。"""
    try:
        rel = os.path.relpath(path, os.getcwd())
    except ValueError:
        return path
    return rel.replace(os.sep, "/") if rel != "." else "."


def _short(text, limit=160):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def read_text(abs_path):
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _issue(skill, path, code, message, severity="error"):
    return {
        "skill": skill,
        "path": path,
        "code": code,
        "message": message,
        "severity": severity,
    }


# ---------------------------------------------------------------------------
# frontmatter 解析（极简 YAML 子集：标量 / 引号 / >- | 块 / 缩进续行）
# ---------------------------------------------------------------------------

def _strip_inline_comment(raw):
    if " #" in raw:
        return raw.split(" #", 1)[0].rstrip()
    return raw


def _unquote(raw, parse_errors, line_no):
    if raw.startswith('"'):
        if raw.endswith('"') and len(raw) >= 2:
            body = raw[1:-1]
            try:
                return json.loads('"%s"' % body)
            except ValueError:
                return body.replace('\\"', '"').replace("\\n", "\n")
        parse_errors.append("frontmatter 第 %d 行双引号没有闭合" % line_no)
        return raw[1:]
    if raw.startswith("'"):
        if raw.endswith("'") and len(raw) >= 2:
            return raw[1:-1].replace("''", "'")
        parse_errors.append("frontmatter 第 %d 行单引号没有闭合" % line_no)
        return raw[1:]
    return raw


def parse_frontmatter_lines(lines):
    data = {}
    parse_errors = []
    current_key = None
    block_mode = None
    for index, line in enumerate(lines):
        line_no = index + 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] in " \t":
            if current_key is None:
                parse_errors.append("frontmatter 第 %d 行缩进异常（没有对应的键）" % line_no)
                continue
            existing = data.get(current_key)
            if block_mode == "|":
                data[current_key] = (existing + "\n" + stripped) if existing else stripped
            elif block_mode == ">":
                data[current_key] = (existing + " " + stripped) if existing else stripped
            else:
                data[current_key] = (existing + " " + stripped) if existing else stripped
            continue
        match = FRONTMATTER_KEY_RE.match(line)
        if not match:
            parse_errors.append("frontmatter 第 %d 行无法解析：%s" % (line_no, _short(stripped, 60)))
            current_key = None
            block_mode = None
            continue
        key, raw = match.group(1), match.group(2).strip()
        current_key = key
        block_mode = None
        if raw in (">", "|", ">-", "|-", ">+", "|+"):
            block_mode = "|" if raw.startswith("|") else ">"
            data[key] = ""
        elif raw.startswith('"') or raw.startswith("'"):
            data[key] = _unquote(raw, parse_errors, line_no)
        else:
            data[key] = _strip_inline_comment(raw)
    return data, parse_errors


def split_frontmatter(text):
    """返回 (data|None, parse_errors, body)。data=None 表示没有 frontmatter。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    first = 0
    while first < len(lines) and not lines[first].strip():
        first += 1
    if first >= len(lines) or lines[first].strip() != "---":
        return None, ["文件开头缺少 frontmatter 分隔符 `---`（DSH 无法读取技能元数据）"], ""
    closing = None
    for index in range(first + 1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            closing = index
            break
    if closing is None:
        return None, ["frontmatter 没有结束分隔符 `---`（文件可能被截断）"], ""
    data, parse_errors = parse_frontmatter_lines(lines[first + 1:closing])
    body = "\n".join(lines[closing + 1:])
    return data, parse_errors, body


# ---------------------------------------------------------------------------
# 技能发现
# ---------------------------------------------------------------------------

def _iter_files(base_dir):
    """按稳定顺序遍历目录下的文件（排除 .git/node_modules 等）。"""
    for dirpath, dirnames, filenames in os.walk(base_dir, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name.lower() not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def discover_skills(root):
    """返回 (skills, nested_skill_paths)。skills 按路径排序。"""
    skills = []
    nested = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for entry in entries:
        if entry.startswith("."):
            continue
        abs_path = os.path.join(root, entry)
        if os.path.isdir(abs_path):
            skill_md = os.path.join(abs_path, "SKILL.md")
            if os.path.isfile(skill_md):
                skills.append({
                    "name": entry,
                    "kind": "bundle",
                    "dir": abs_path,
                    "skill_md": skill_md,
                })
        elif os.path.isfile(abs_path) and entry.lower().endswith(".md"):
            skills.append({
                "name": entry[:-3],
                "kind": "flat",
                "dir": root,
                "skill_md": abs_path,
            })
    for file_path in _iter_files(root):
        if os.path.basename(file_path) != "SKILL.md":
            continue
        rel = os.path.relpath(file_path, root).replace(os.sep, "/")
        if rel.count("/") > 1:
            nested.append(rel)
    skills.sort(key=lambda item: item["skill_md"])
    nested.sort()
    return skills, nested


def discover_focused_skills(root, focus_dir):
    """--skill 单技能模式：只返回指定 bundle，并检测它内部的嵌套 SKILL.md。"""
    focus_dir = os.path.abspath(focus_dir)
    name = os.path.basename(focus_dir.rstrip(os.sep)) or "skill"
    skill = {
        "name": name,
        "kind": "bundle",
        "dir": focus_dir,
        "skill_md": os.path.join(focus_dir, "SKILL.md"),
    }
    nested = []
    for file_path in _iter_files(focus_dir):
        if os.path.basename(file_path) != "SKILL.md":
            continue
        if os.path.abspath(file_path) == os.path.abspath(skill["skill_md"]):
            continue
        nested.append(_rel_to_root(file_path, root))
    nested.sort()
    return [skill], nested


def _rel_to_root(path, root):
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


# ---------------------------------------------------------------------------
# 单个技能校验
# ---------------------------------------------------------------------------

def _collect_markdown_files(skill):
    """SKILL.md + references/ 下的 markdown 文件（按稳定顺序）。"""
    files = [skill["skill_md"]]
    if skill["kind"] == "bundle":
        refs_dir = os.path.join(skill["dir"], "references")
        if os.path.isdir(refs_dir):
            for file_path in _iter_files(refs_dir):
                if file_path.lower().endswith((".md", ".mdx", ".markdown")):
                    files.append(file_path)
    return files


def _iter_reference_files(skill):
    if skill["kind"] != "bundle":
        return []
    refs_dir = os.path.join(skill["dir"], "references")
    if not os.path.isdir(refs_dir):
        return []
    result = []
    for file_path in _iter_files(refs_dir):
        if os.path.isfile(file_path):
            result.append(file_path)
    return result


def _link_targets(text):
    targets = []
    for match in LINK_RE.finditer(text):
        targets.append(match.group(1))
    for match in REF_LINK_RE.finditer(text):
        targets.append(match.group(1))
    return targets


def _is_relative_link(target):
    if not target:
        return False
    if target.startswith(("#", "/", "\\", "~")):
        return False
    if re.match(r"^[A-Za-z]:", target):
        return False
    if SCHEME_RE.match(target):
        return False
    if any(char in target for char in "{}<>") or "{{" in target:
        return False
    return True


def _normalize_link_target(target):
    clean = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not clean:
        return None
    return unquote(clean)


def _check_host_paths(skill, root, errors):
    for file_path in _collect_markdown_files(skill):
        text = read_text(file_path)
        if text is None:
            continue
        rel = _rel_to_root(file_path, root)
        for index, line in enumerate(text.splitlines()):
            for pattern, label in HOST_PATH_PATTERNS:
                if pattern.search(line):
                    errors.append(_issue(
                        skill["name"], "%s:%d" % (rel, index + 1),
                        "absolute_host_path",
                        "%s（技能必须可移植，改成项目内相对路径）：%s"
                        % (label, _short(line.strip(), 100)),
                    ))
                    break


def _check_links(skill, root, errors, referenced):
    for file_path in _collect_markdown_files(skill):
        text = read_text(file_path)
        if text is None:
            continue
        rel_file = _rel_to_root(file_path, root)
        base_dir = os.path.dirname(file_path)
        for target in _link_targets(text):
            if not _is_relative_link(target):
                continue
            clean = _normalize_link_target(target)
            if not clean:
                continue
            abs_target = os.path.normpath(os.path.join(base_dir, clean.replace("/", os.sep)))
            if file_path == skill["skill_md"]:
                try:
                    referenced.add(os.path.relpath(abs_target, skill["dir"]).replace(os.sep, "/"))
                except ValueError:
                    pass
            if not os.path.exists(abs_target):
                errors.append(_issue(
                    skill["name"], rel_file,
                    "missing_link_target",
                    "相对链接目标不存在：`%s`（解析为 %s）"
                    % (target, _rel_to_root(abs_target, skill["dir"])),
                ))


def _check_references_referenced(skill, root, warnings, referenced):
    if skill["kind"] != "bundle":
        return
    for file_path in _iter_reference_files(skill):
        rel_in_skill = os.path.relpath(file_path, skill["dir"]).replace(os.sep, "/")
        if rel_in_skill not in referenced:
            warnings.append(_issue(
                skill["name"], _rel_to_root(file_path, root),
                "unreferenced_reference",
                "references/ 里的文件没有被 SKILL.md 引用（渐进披露要求每个 reference 标注「何时读」）",
                severity="warning",
            ))


def _check_secrets(skill, root, warnings):
    for file_path in _collect_markdown_files(skill):
        text = read_text(file_path)
        if text is None:
            continue
        rel = _rel_to_root(file_path, root)
        for index, line in enumerate(text.splitlines()):
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                warnings.append(_issue(
                    skill["name"], "%s:%d" % (rel, index + 1),
                    "suspected_secret",
                    "疑似密钥/凭据：%s（不要写进技能文件）" % _short(line.strip(), 100),
                    severity="warning",
                ))


def _extract_doc_commands(skill):
    commands = []
    seen = set()
    for file_path in _collect_markdown_files(skill):
        text = read_text(file_path)
        if text is None:
            continue
        candidates = []
        for block in FENCE_RE.findall(text):
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("$ "):
                    line = line[2:].strip()
                elif line.startswith(("#", "//")):
                    continue
                candidates.append(line)
        for span in INLINE_CODE_RE.findall(text):
            candidates.append(span.strip())
        for candidate in candidates:
            if "\n" in candidate or len(candidate) > 160:
                continue
            if not _looks_like_command(candidate):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            commands.append(candidate)
    return commands


def _looks_like_command(text):
    tokens = text.split()
    if not tokens:
        return False
    first = tokens[0]
    if first.startswith("./"):
        first = first[2:]
    if first.startswith("-"):
        return False
    return first in KNOWN_COMMAND_PREFIXES


INSTALL_SUBCOMMANDS = {
    "pnpm": {"install", "i", "add"},
    "npm": {"install", "i", "ci", "add"},
    "yarn": {"install", "i", "add"},
    "bun": {"install", "i", "add"},
}
PACKAGE_MANAGERS = {"pnpm", "npm", "yarn", "bun"}
# 包管理器里「吃掉一个值」的过滤参数，如 pnpm --filter <pkg> test
FLAGS_WITH_VALUE = {
    "--filter", "-F", "--workspace", "-w", "--prefix", "--dir", "-C",
    "--reporter", "--loglevel", "--registry", "--store-dir",
}


def _package_manager_command(text):
    """解析 `pnpm [run] <script> ...` 这类命令，返回 (包管理器, 子命令/脚本名)。

    跳过 `run`、`--filter <pkg>` 等前缀参数；`--` 之后的参数忽略。
    不是包管理器命令时返回 (None, None)。
    """
    tokens = text.split()
    if not tokens:
        return None, None
    manager = tokens[0]
    if manager.startswith("./"):
        manager = manager[2:]
    if manager not in PACKAGE_MANAGERS:
        return None, None
    args = tokens[1:]
    if "--" in args:
        args = args[:args.index("--")]
    while args:
        head = args[0]
        if head in ("run", "run-script"):
            args = args[1:]
            break
        if head.startswith("-"):
            args = args[1:]
            if head in FLAGS_WITH_VALUE and args:
                args = args[1:]
            continue
        break
    return manager, (args[0] if args else None)


def _check_commands_in_facts(skill, root, warnings, facts):
    if not isinstance(facts, dict):
        return
    known_names = set()
    known_commands = []
    for command in facts.get("commands") or []:
        if not isinstance(command, dict):
            continue
        name = command.get("name")
        value = command.get("command")
        if isinstance(name, str) and name:
            known_names.add(name)
        if isinstance(value, str) and value:
            known_commands.append(value)
    haystack = json.dumps(facts, ensure_ascii=False)

    for command in _extract_doc_commands(skill):
        if command in haystack:
            continue
        manager, subcommand = _package_manager_command(command)
        if manager is not None:
            # 1) 安装类命令不是 script，直接放行
            if subcommand in INSTALL_SUBCOMMANDS.get(manager, set()):
                continue
            # 2) `pnpm test` / `pnpm run test` 按 script 名命中事实包即视为真实
            if subcommand in known_names:
                continue
        if manager is None and any(
            value and value in command for value in known_commands
        ):
            continue
        warnings.append(_issue(
            skill["name"], _rel_to_root(skill["skill_md"], root),
            "command_not_in_facts",
            "命令未出现在事实包中，可能不真实：`%s`" % _short(command, 100),
            severity="warning",
        ))


def validate_skill(skill, root, facts):
    """校验单个技能，返回 (errors, warnings)。"""
    errors = []
    warnings = []
    rel_skill_md = _rel_to_root(skill["skill_md"], root)
    text = read_text(skill["skill_md"])
    if text is None:
        return [_issue(skill["name"], rel_skill_md, "read_error",
                       "SKILL.md 无法读取（权限或编码问题）")], []

    data, parse_errors, body = split_frontmatter(text)

    if data is None:
        for message in parse_errors:
            errors.append(_issue(skill["name"], rel_skill_md, "missing_frontmatter", message))
        # frontmatter 不可用时，后续结构校验没有意义，直接返回
        return errors, warnings

    for message in parse_errors:
        errors.append(_issue(skill["name"], rel_skill_md, "invalid_frontmatter", message))

    # name
    name = data.get("name")
    if not name:
        errors.append(_issue(skill["name"], rel_skill_md, "missing_name",
                             "frontmatter 缺少必填字段 `name`"))
    elif not isinstance(name, str) or not KEBAB_RE.match(name):
        errors.append(_issue(skill["name"], rel_skill_md, "invalid_name",
                             "name 必须是非空 kebab-case（^[a-z0-9]+(?:-[a-z0-9]+)*$）：%r"
                             % (name,)))
    elif name != skill["name"]:
        errors.append(_issue(skill["name"], rel_skill_md, "dir_name_mismatch",
                             "技能目录/文件名 %r 与 frontmatter name %r 不一致"
                             % (skill["name"], name)))

    # description
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(_issue(skill["name"], rel_skill_md, "missing_description",
                             "frontmatter 缺少必填字段 `description`（参与技能路由，必须写）"))
    else:
        description = description.strip()
        if len(description) > MAX_DESCRIPTION:
            errors.append(_issue(
                skill["name"], rel_skill_md, "description_too_long",
                "description %d 字符，超过上限 %d 字符" % (len(description), MAX_DESCRIPTION),
            ))
        elif len(description) < DESCRIPTION_WARN_MIN:
            warnings.append(_issue(
                skill["name"], rel_skill_md, "description_short",
                "description 只有 %d 字符（建议 >=%d），路由信号可能不足"
                % (len(description), DESCRIPTION_WARN_MIN), severity="warning",
            ))
        elif len(description) > DESCRIPTION_WARN_MAX:
            warnings.append(_issue(
                skill["name"], rel_skill_md, "description_long",
                "description %d 字符（建议 <=%d，超过 500 会直接报错）"
                % (len(description), DESCRIPTION_WARN_MAX), severity="warning",
            ))
        if not re.search(r"(?i)use when|何时|当", description):
            warnings.append(_issue(
                skill["name"], rel_skill_md, "description_no_when_use",
                "description 缺少「何时用」语气（建议含 `Use when` / `当…` / `何时`）",
                severity="warning",
            ))

    # 未知 frontmatter 键
    for key in sorted(data):
        if key not in ALLOWED_FRONTMATTER_KEYS:
            warnings.append(_issue(
                skill["name"], rel_skill_md, "unknown_frontmatter_key",
                "未知 frontmatter 键 `%s`（允许：%s）"
                % (key, ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))), severity="warning",
            ))

    # 正文
    if not body.strip():
        errors.append(_issue(skill["name"], rel_skill_md, "empty_body",
                             "frontmatter 之后正文为空：技能加载后没有内容"))

    # 行数
    line_count = len(text.splitlines())
    if line_count > MAX_LINES:
        warnings.append(_issue(
            skill["name"], rel_skill_md, "too_many_lines",
            "SKILL.md 有 %d 行，超过建议上限 %d（细节应移入 references/）"
            % (line_count, MAX_LINES), severity="warning",
        ))

    # 绝对路径 / 相对链接 / 密钥
    _check_host_paths(skill, root, errors)
    referenced = set()
    _check_links(skill, root, errors, referenced)
    _check_references_referenced(skill, root, warnings, referenced)
    _check_secrets(skill, root, warnings)

    if facts is not None:
        _check_commands_in_facts(skill, root, warnings, facts)

    return errors, warnings


# ---------------------------------------------------------------------------
# 整体校验 / 输出
# ---------------------------------------------------------------------------

def validate(root, facts=None, focus_dir=None):
    root = os.path.abspath(root)
    if focus_dir:
        skills, nested = discover_focused_skills(root, focus_dir)
    else:
        skills, nested = discover_skills(root)
    all_errors = []
    all_warnings = []
    skill_results = []

    # 同根重名（目录/文件名层面）
    name_map = {}
    for skill in skills:
        name_map.setdefault(skill["name"], []).append(skill)
    duplicate_skills = set()
    for name in sorted(name_map):
        group = name_map[name]
        if len(group) > 1:
            duplicate_skills.update(item["skill_md"] for item in group)
            for item in group:
                all_errors.append(_issue(
                    item["name"], _rel_to_root(item["skill_md"], root),
                    "duplicate_name",
                    "同根重名：技能名 %r 出现了 %d 次（bundle 与扁平技能不能同名）"
                    % (name, len(group)),
                ))

    # 嵌套 SKILL.md：归属于最外层 bundle
    for rel in nested:
        owner = rel.split("/", 1)[0]
        all_errors.append(_issue(
            owner, rel, "nested_skill_md",
            "发现嵌套 SKILL.md（深度 %d）：DSH 只识别 <root>/<name>/SKILL.md 与 "
            "<root>/<name>.md，这个文件不会被发现" % (rel.count("/") + 1),
        ))

    for skill in skills:
        errors, warnings = validate_skill(skill, root, facts)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    known_names = {skill["name"] for skill in skills}
    for skill in skills:
        name = skill["name"]
        skill_errors = [item for item in all_errors if item["skill"] == name]
        skill_warnings = [item for item in all_warnings if item["skill"] == name]
        skill_results.append({
            "name": name,
            "path": _rel_to_root(skill["skill_md"], root),
            "kind": skill["kind"],
            "ok": len(skill_errors) == 0,
            "errors": len(skill_errors),
            "warnings": len(skill_warnings),
            "error_codes": [item["code"] for item in skill_errors],
            "warning_codes": [item["code"] for item in skill_warnings],
        })

    # 归属不到具体技能的全局问题（如根目录下孤立目录里的嵌套 SKILL.md）
    orphan_errors = [item for item in all_errors if item["skill"] not in known_names]
    orphan_warnings = [item for item in all_warnings if item["skill"] not in known_names]

    return {
        "root": root,
        "skills": skills,
        "skill_results": skill_results,
        "errors": all_errors,
        "warnings": all_warnings,
        "orphan_errors": orphan_errors,
        "orphan_warnings": orphan_warnings,
    }


def _render_report(result, root_arg, strict):
    skill_results = result["skill_results"]
    errors = result["errors"]
    warnings = result["warnings"]
    bundles = [item for item in skill_results if item["kind"] == "bundle"]
    flats = [item for item in skill_results if item["kind"] == "flat"]

    lines = []
    lines.append("技能校验：%s" % root_arg)
    if not skill_results:
        lines.append("未发现技能：请确认目录结构是 <root>/<name>/SKILL.md 或 <root>/<name>.md")
        lines.append("")
        lines.append("汇总：0 个技能 · 0 error · 0 warning")
        lines.append("结果：通过（没有可校验的技能）")
        return "\n".join(lines)

    lines.append("发现 %d 个技能（%d bundle / %d flat）"
                 % (len(skill_results), len(bundles), len(flats)))
    lines.append("")

    by_skill = {}
    for issue in errors:
        by_skill.setdefault(issue["skill"], {"errors": [], "warnings": []})["errors"].append(issue)
    for issue in warnings:
        by_skill.setdefault(issue["skill"], {"errors": [], "warnings": []})["warnings"].append(issue)

    for skill in skill_results:
        bucket = by_skill.get(skill["name"], {"errors": [], "warnings": []})
        ok = not bucket["errors"]
        lines.append("%s %s（%s）" % ("✓" if ok else "✗", skill["name"], skill["path"]))
        for issue in bucket["errors"]:
            location = issue["path"]
            lines.append("  ERROR [%s] %s" % (issue["code"], issue["message"]))
            lines.append("        位置：%s" % location)
        for issue in bucket["warnings"]:
            lines.append("  WARN  [%s] %s" % (issue["code"], issue["message"]))
            lines.append("        位置：%s" % issue["path"])
        lines.append("")

    orphan_errors = result.get("orphan_errors") or []
    orphan_warnings = result.get("orphan_warnings") or []
    if orphan_errors or orphan_warnings:
        lines.append("其他问题（不属于已发现的技能）")
        for issue in orphan_errors:
            lines.append("  ERROR [%s] %s" % (issue["code"], issue["message"]))
            lines.append("        位置：%s" % issue["path"])
        for issue in orphan_warnings:
            lines.append("  WARN  [%s] %s" % (issue["code"], issue["message"]))
            lines.append("        位置：%s" % issue["path"])
        lines.append("")

    lines.append("汇总：%d 个技能 · %d error · %d warning"
                 % (len(skill_results), len(errors), len(warnings)))
    if errors:
        lines.append("结果：失败（退出码 1）")
    elif strict and warnings:
        lines.append("结果：失败（--strict：%d 条 warning 视为 error，退出码 1）" % len(warnings))
    elif warnings:
        lines.append("结果：通过（有 %d 条 warning 建议修复，未加 --strict）" % len(warnings))
    else:
        lines.append("结果：通过（0 error / 0 warning）")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_skills.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "校验 DSH 技能根目录下的所有 bundle（<name>/SKILL.md）与扁平技能\n"
            "（<name>.md），按契约报 error / warning。module-skill-forge 的 P5 用它\n"
            "把技能修到 0 error。"
        ),
        epilog=(
            "error 规则（违反即不可用）\n"
            "  frontmatter 缺失/不可解析；name 缺失、非 kebab-case 或与目录名不一致；\n"
            "  description 缺失或 >500 字符；正文为空；嵌套 SKILL.md（深度>2）；\n"
            "  同根重名；绝对宿主路径（/Users/、/home/、C:\\ 等）；相对链接目标不存在。\n"
            "\n"
            "warning 规则（--strict 时视为 error）\n"
            "  description <40 或 >300 字符；缺少「何时用」语气；SKILL.md >120 行；\n"
            "  references/ 有未被 SKILL.md 引用的文件；未知 frontmatter 键；疑似密钥；\n"
            "  给定 --facts 时命令未出现在事实包（脚本名命中 / 安装命令白名单 / 整条\n"
            "  命令出现即通过，其余才警告）。\n"
            "\n"
            "退出码\n"
            "  0  无 error\n"
            "  1  有 error（--strict 下：有 error 或有 warning）\n"
            "  2  参数错误、技能根/技能目录不存在、--facts 不可读\n"
            "\n"
            "示例\n"
            "  python3 validate_skills.py --root .dsh/skills\n"
            "  python3 validate_skills.py --root examples/sample-shop-skills --strict\n"
            "  python3 validate_skills.py --skill examples/sample-shop-skills/sample-shop-catalog-dev\n"
            "  python3 validate_skills.py --root .dsh/skills --json\n"
        ),
    )
    parser.add_argument("--root", default=None,
                        help="技能根目录（识别 <root>/<name>/SKILL.md 与 <root>/<name>.md）；与 --skill 二选一")
    parser.add_argument("--skill", default=None,
                        help="只校验指定 bundle 目录（必须含 SKILL.md）；与 --root 二选一")
    parser.add_argument("--facts", default=None,
                        help="事实包 facts.json 路径；给出后校验技能里的命令是否来自事实包")
    parser.add_argument("--json", action="store_true",
                        help="stdout 只输出一个 JSON 对象（{ok, errors[], warnings[], skills[]}）")
    parser.add_argument("--strict", action="store_true",
                        help="warning 视同 error：有 warning 也返回退出码 1")
    return parser


def _print_error(message, as_json):
    print("校验失败：%s" % message, file=sys.stderr)
    if as_json:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if bool(args.root) == bool(args.skill):
        _print_error("必须且只能指定 --root <skills-root> 或 --skill <bundle-dir> 二选一", args.json)
        return 2

    focus_dir = None
    if args.skill:
        focus_dir = os.path.abspath(os.path.expanduser(args.skill))
        if not os.path.isdir(focus_dir):
            _print_error("--skill 目录不存在或不是目录：%s" % args.skill, args.json)
            return 2
        if not os.path.isfile(os.path.join(focus_dir, "SKILL.md")):
            _print_error("--skill 目录里没有 SKILL.md，不是合法的技能 bundle：%s" % args.skill,
                         args.json)
            return 2
        root = os.path.dirname(focus_dir)
    else:
        root = os.path.abspath(os.path.expanduser(args.root))
        if not os.path.isdir(root):
            _print_error("技能根目录不存在或不是目录：%s" % args.root, args.json)
            return 2

    facts = None
    if args.facts:
        facts_path = os.path.abspath(os.path.expanduser(args.facts))
        if not os.path.isfile(facts_path):
            _print_error("--facts 文件不存在：%s" % args.facts, args.json)
            return 2
        text = read_text(facts_path)
        try:
            facts = json.loads(text) if text is not None else None
        except ValueError as exc:
            _print_error("--facts 不是合法 JSON（%s）：%s" % (exc, args.facts), args.json)
            return 2
        if not isinstance(facts, dict):
            _print_error("--facts 的内容不是 JSON 对象：%s" % args.facts, args.json)
            return 2

    try:
        result = validate(root, facts, focus_dir)
    except KeyboardInterrupt:
        _print_error("已中断", args.json)
        return 2
    except Exception as exc:  # noqa: BLE001 - 校验器不能对用户目录抛 traceback
        _print_error("内部错误（%s: %s）" % (type(exc).__name__, exc), args.json)
        return 2

    errors = result["errors"]
    warnings = result["warnings"]
    ok = not errors and not (args.strict and warnings)
    exit_code = 0 if ok else 1
    root_arg = args.skill if args.skill else args.root
    focus_arg = os.path.abspath(focus_dir) if focus_dir else None

    if args.json:
        payload = {
            "ok": ok,
            "strict": args.strict,
            "root": root_arg,
            "focus": os.path.basename(focus_arg) if focus_arg else None,
            "errors": errors,
            "warnings": warnings,
            "skills": result["skill_results"],
            "summary": {
                "skills": len(result["skill_results"]),
                "bundles": len([item for item in result["skill_results"] if item["kind"] == "bundle"]),
                "flat": len([item for item in result["skill_results"] if item["kind"] == "flat"]),
                "errors": len(errors),
                "warnings": len(warnings),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_report(result, root_arg, args.strict))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
