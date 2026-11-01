#!/usr/bin/env python3
"""refresh.py — module-skill-forge 的「代码变更后重扫」检测与增量刷新工具。

用途
    技能生成后，代码还会变。refresh.py 根据 SKILL.md 里的 forge 基线标记判断
    「技能是否已过期」，并在需要时只刷新事实包（facts.json），不改写技能正文。
    同时可以把技能与模块的基线登记到 <project>/.dsh/forge/index.json，供非 git
    项目做文件指纹比对，也供 CI/cron 做定期检查。

    基线标记（生成技能时由 agent/人写入 SKILL.md，frontmatter 之后、前 15 行内）：
        <!-- forge: module=packages/catalog facts=.dsh/forge/catalog/facts.json scanned=2026-11-01 head=abc1234 -->
    module / facts 是相对项目根的路径；head 是生成时的 git HEAD，非 git 项目写 none。
    module=*（或 module=none）表示全局技能（如项目总览）：status 恒为 ok、不参与
    scan，facts=none 时不做 missing_facts 检查；变更由 check 里各模块项的 stale 提示。
    标记缺失或不可解析 → 状态 untracked（不阻断 check，但 --strict 下算失败）。

    check（默认）：git 项目用 `git rev-list <head>..HEAD -- <module>` +
    `git status --porcelain -- <module>` 判断模块是否变化；非 git 项目比对
    index.json 里的 sha256 文件指纹。输出模块状态、影响到的技能、变更文件示例；
    每项带 scope=module|global|untracked，存在 stale 模块时额外提示复核全局技能。
    index：扫描 --skills 下所有 SKILL.md 的标记，重建 index.json（基线指纹）。
    scan：对 stale / missing_facts（或 --module 指定）的模块调用同目录
    scan_module.py 刷新事实包；绝不改写 SKILL.md 与标记。

用法
    python3 refresh.py --project <root> [--skills <dir>] [--mode check|index|scan]
                       [--module <path>] [--json] [--strict] [--max-files N]

参数
    --project <dir>  项目根。省略时用 `git rev-parse --show-toplevel`，失败则当前目录。
    --skills <dir>   技能根目录（识别 <dir>/<name>/SKILL.md 与 <dir>/<name>.md）。
                     默认 <project>/.dsh/skills。
    --mode <mode>    check（默认）| index | scan。
    --module <path>  只看/只扫某个模块（相对项目根），如 packages/catalog。
    --json           stdout 只输出一个 JSON 对象。
    --strict         check 时把 untracked / unknown 也算失败（退出码 1）。
    --max-files N    计算文件指纹时最多处理的文件数（默认 20000），超限截断并 warning。

退出码
    0  成功（check：所有模块 ok；index：索引已写出；scan：刷新成功）
    1  check 存在 stale/missing_facts（--strict 下含 untracked/unknown）；scan 失败；
       index 写盘失败
    2  参数错误 / 项目或技能目录不存在 / --module 无法解析
    3  check 时项目既不是 git 仓库，也没有 .dsh/forge/index.json（先跑 --mode index）

示例
    python3 refresh.py --project . --skills .dsh/skills --mode index
    python3 refresh.py --project . --mode check
    python3 refresh.py --project . --mode check --strict --json
    python3 refresh.py --project . --mode scan --module packages/catalog
    python3 refresh.py --project . --mode scan
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = 1
MARKER_WINDOW = 15
MARKER_RE = re.compile(r"<!--\s*forge:\s*(.*?)\s*-->")
MAX_CHANGED_EXAMPLES = 5
DEFAULT_MAX_FILES = 20000
GIT_TIMEOUT = 20
SCAN_TIMEOUT = 300

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNTRACKED = "untracked"
STATUS_MISSING_FACTS = "missing_facts"
STATUS_UNKNOWN = "unknown"
STATUSES = (STATUS_OK, STATUS_STALE, STATUS_UNTRACKED, STATUS_MISSING_FACTS, STATUS_UNKNOWN)
BLOCKING_STATUSES = (STATUS_STALE, STATUS_MISSING_FACTS)
NON_BLOCKING_STRICT_STATUSES = (STATUS_UNTRACKED, STATUS_UNKNOWN)
# 全局技能（项目总览等）用 module=* 或 module=none 标记；没有单一模块归属，
# status 恒为 ok（变更由模块项的 stale 提示人工复核），且不参与 --mode scan。
GLOBAL_MODULE_TOKENS = ("*", "none")
GLOBAL_MODULE_REASON = "全局技能（跟随任意模块变更，由 check 报告中的模块项提示）"
SCOPE_MODULE = "module"
SCOPE_GLOBAL = "global"
SCOPE_UNTRACKED = "untracked"

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
try:  # scan_module.py 与本脚本同目录，复用它的遍历/排除规则
    import scan_module as _scan_module
except Exception:  # noqa: BLE001 - 缺同目录扫描器时降级为显式报错
    _scan_module = None

SCAN_SCRIPT = os.path.join(_HERE, "scan_module.py")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_rel(path, root):
    rel = os.path.relpath(path, root)
    if rel == ".":
        return "."
    return rel.replace(os.sep, "/")


def display_path(path):
    """输出路径一律相对当前目录，避免把宿主绝对路径写进结果。"""
    try:
        rel = os.path.relpath(path, os.getcwd())
    except ValueError:  # Windows 跨盘符
        return path
    return rel.replace(os.sep, "/") if rel != "." else "."


def display_project_relative(path, project_root):
    try:
        rel = os.path.relpath(path, project_root)
    except ValueError:
        return path
    return rel.replace(os.sep, "/") if rel != "." else "."


def normalize_rel_path(value):
    """把标记里的 module/facts 归一成相对 POSIX 路径。"""
    text = (value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.rstrip("/")
    return text or "."


def is_global_module(module_rel):
    """module=* / module=none：全局技能，没有单一模块归属。"""
    return (module_rel or "").strip().lower() in GLOBAL_MODULE_TOKENS


def is_global_facts(facts_rel):
    """facts=none：全局技能没有事实包，不做 missing_facts 检查。"""
    return not (facts_rel or "").strip() or (facts_rel or "").strip().lower() in GLOBAL_MODULE_TOKENS


def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _short(text, limit=200):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _run(cmd, cwd=None, timeout=GIT_TIMEOUT):
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except FileNotFoundError:
        return 127, "", "命令不存在: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时: %s" % " ".join(cmd[:3])
    except OSError as exc:
        return 126, "", "命令执行失败: %s" % exc
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


def _slugify(value):
    slug = (value or "").strip().lower()
    if "/" in slug:
        slug = slug.split("/")[-1]
    slug = re.sub(r"[^a-z0-9._-]+", "-", slug).strip("-._")
    return slug or "module"


# ---------------------------------------------------------------------------
# 技能发现 / 标记解析
# ---------------------------------------------------------------------------

def discover_skills(skills_root):
    """按稳定顺序返回 [{"name","kind","abs_path","rel"}]。"""
    skills = []
    try:
        entries = sorted(os.listdir(skills_root))
    except OSError:
        return skills
    for entry in entries:
        if entry.startswith("."):
            continue
        abs_path = os.path.join(skills_root, entry)
        if os.path.isdir(abs_path):
            skill_md = os.path.join(abs_path, "SKILL.md")
            if os.path.isfile(skill_md):
                skills.append({
                    "name": entry,
                    "kind": "bundle",
                    "abs_path": skill_md,
                    "rel": entry + "/SKILL.md",
                })
        elif os.path.isfile(abs_path) and entry.lower().endswith(".md"):
            skills.append({
                "name": entry[:-3],
                "kind": "flat",
                "abs_path": abs_path,
                "rel": entry,
            })
    return skills


def parse_marker(skill_path):
    """返回 (marker_dict|None, 缺失原因|None)。标记必须在前 15 行内。"""
    text = read_text_file(skill_path)
    if text is None:
        return None, "SKILL.md 无法读取"
    for line in text.splitlines()[:MARKER_WINDOW]:
        match = MARKER_RE.search(line)
        if not match:
            continue
        pairs = dict(re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)=([^\s]+)", match.group(1)))
        module = normalize_rel_path(pairs.get("module"))
        facts = normalize_rel_path(pairs.get("facts"))
        if not pairs.get("module") or not pairs.get("facts"):
            return None, "forge 标记不完整（必须含 module= 与 facts=）"
        return {
            "module": module,
            "facts": facts,
            "scanned": pairs.get("scanned") or None,
            "head": (pairs.get("head") or "none"),
        }, None
    return None, "SKILL.md 前 %d 行内没有 <!-- forge: module=... facts=... scanned=... head=... --> 标记" \
        % MARKER_WINDOW


# ---------------------------------------------------------------------------
# 文件指纹
# ---------------------------------------------------------------------------

def fingerprint_module(project_root, module_rel, max_files):
    """对模块范围源码文件算 sha256 指纹；返回 {fingerprint,file_count,files,warnings}。"""
    warnings = []
    result = {"fingerprint": None, "file_count": 0, "files": {}, "warnings": warnings}
    module_abs = os.path.join(project_root, module_rel.replace("/", os.sep))
    if module_rel in (".", ""):
        module_abs = project_root
    if not os.path.isdir(module_abs):
        warnings.append("模块目录不存在，无法计算指纹：%s" % module_rel)
        return result
    if _scan_module is None:
        warnings.append("同目录缺少 scan_module.py，无法遍历模块文件（指纹为空）")
        return result

    files, stats = _scan_module.walk_files(module_abs, max_files)
    if stats.get("truncated"):
        warnings.append("模块文件数超过 --max-files=%d，指纹已截断（可能误报 stale）" % max_files)
    if stats.get("skipped_large"):
        warnings.append("跳过 %d 个大于 1MB 的文件（不参与指纹）" % stats["skipped_large"])

    hashes = {}
    skipped_binary = 0
    unreadable = 0
    for item in files:
        try:
            with open(item["abs"], "rb") as fh:
                data = fh.read()
        except OSError:
            unreadable += 1
            continue
        if b"\x00" in data[:8192]:
            skipped_binary += 1
            continue
        rel = item["rel"] if module_rel in (".", "") else "%s/%s" % (module_rel.rstrip("/"), item["rel"])
        hashes[rel] = hashlib.sha256(data).hexdigest()
    if skipped_binary:
        warnings.append("跳过 %d 个二进制文件（不参与指纹）" % skipped_binary)
    if unreadable:
        warnings.append("跳过 %d 个不可读文件（不参与指纹）" % unreadable)

    manifest = "\n".join("%s\0%s" % (rel, hashes[rel]) for rel in sorted(hashes))
    if hashes:
        result["fingerprint"] = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    result["file_count"] = len(hashes)
    result["files"] = hashes
    return result


def diff_file_maps(baseline_files, current_files, limit=MAX_CHANGED_EXAMPLES):
    """对比两份 {相对路径: sha256}，返回 (changed[:limit], changed_count)。"""
    changed = []
    for rel in sorted(set(baseline_files) | set(current_files)):
        if baseline_files.get(rel) != current_files.get(rel):
            changed.append(rel)
    return changed[:limit], len(changed)


# ---------------------------------------------------------------------------
# git 检测
# ---------------------------------------------------------------------------

def collect_git(project_root):
    state = {"repo": False, "available": False, "head": None, "error": None}
    code, out, _err = _run(["git", "-C", project_root, "rev-parse", "--is-inside-work-tree"])
    if code != 0 or out.strip().lower() != "true":
        return state
    state["repo"] = True
    code, out, err = _run(["git", "-C", project_root, "rev-parse", "--short", "HEAD"])
    if code != 0 or not out.strip():
        state["error"] = "git 仓库没有可用提交（HEAD 无法解析）"
        return state
    state["available"] = True
    state["head"] = out.strip().splitlines()[0].strip()
    return state


def _porcelain_paths(output):
    paths = []
    for line in output.splitlines():
        line = line.rstrip()
        if len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip().strip('"').replace("\\", "/")
        if raw:
            paths.append(raw)
    return paths


def git_module_changes(project_root, module_rel, marker_head):
    """用 commit 区间 + 工作区状态判断模块是否变化。"""
    result = {
        "status": STATUS_OK,
        "reason": None,
        "changed_files": [],
        "changed_file_count": 0,
        "commits": 0,
        "dirty": False,
    }
    head = (marker_head or "none").strip()
    if not head or head.lower() == "none":
        result["status"] = STATUS_UNKNOWN
        result["reason"] = "标记 head=none（生成时项目不是 git），无法用 commit 区间判断"
        return result
    code, _out, _err = _run(
        ["git", "-C", project_root, "rev-parse", "--verify", "--quiet", head + "^{commit}"])
    if code != 0:
        result["status"] = STATUS_UNKNOWN
        result["reason"] = "标记 head=%s 在当前仓库中不存在，需重建基线" % head
        return result
    code, _out, _err = _run(
        ["git", "-C", project_root, "merge-base", "--is-ancestor", head, "HEAD"])
    if code != 0:
        result["status"] = STATUS_UNKNOWN
        result["reason"] = "标记 head=%s 不是当前 HEAD 的祖先（可能 rebase/强推），需重建基线" % head
        return result

    code, out, _err = _run(
        ["git", "-C", project_root, "rev-list", "--count", "%s..HEAD" % head, "--", module_rel])
    if code == 0 and out.strip().isdigit():
        result["commits"] = int(out.strip())

    code, out, _err = _run(
        ["git", "-C", project_root, "status", "--porcelain", "--", module_rel])
    dirty_paths = _porcelain_paths(out) if code == 0 else []
    result["dirty"] = bool(dirty_paths)

    code, out, _err = _run(
        ["git", "-C", project_root, "diff", "--name-only", "%s..HEAD" % head, "--", module_rel])
    diff_paths = [line.strip().replace("\\", "/") for line in out.splitlines()
                  if line.strip()] if code == 0 else []

    # .dsh/ 是 forge 自己的产出目录，不算「代码变更」，避免 self-stale
    changed = sorted(path for path in set(diff_paths) | set(dirty_paths)
                     if path and path != ".dsh" and not path.startswith(".dsh/"))
    result["changed_file_count"] = len(changed)
    result["changed_files"] = changed[:MAX_CHANGED_EXAMPLES]

    if result["commits"] or dirty_paths:
        result["status"] = STATUS_STALE
        parts = []
        if result["commits"]:
            parts.append("模块内有 %d 个新 commit（%s..HEAD）" % (result["commits"], head))
        if dirty_paths:
            parts.append("工作区有 %d 个未提交变更" % len(dirty_paths))
        result["reason"] = "；".join(parts)
    return result


# ---------------------------------------------------------------------------
# 状态计算（check / scan 共用）
# ---------------------------------------------------------------------------

def _base_module_entry(skill):
    return {
        "skill": skill["name"],
        "skill_path": skill["rel"],
        "module": None,
        "facts": None,
        "status": STATUS_UNTRACKED,
        "reason": None,
        "changed_files": [],
        "changed_file_count": 0,
        "missing_facts": False,
        "fingerprint": None,
        "scope": SCOPE_MODULE,
    }


def _lookup_index_module(index_data, module_rel):
    if not isinstance(index_data, dict):
        return None
    for item in index_data.get("modules") or []:
        if isinstance(item, dict) and item.get("path") == module_rel:
            return item
    return None


def compute_statuses(project_root, skills, git_state, index_data, max_files):
    """返回 (modules, warnings)。check 与 scan 共用。"""
    modules = []
    warnings = []
    for skill in skills:
        entry = _base_module_entry(skill)
        marker, marker_error = parse_marker(skill["abs_path"])
        if marker is None:
            entry["status"] = STATUS_UNTRACKED
            entry["scope"] = SCOPE_UNTRACKED
            entry["reason"] = marker_error
            modules.append(entry)
            continue

        module_rel = marker["module"]
        facts_rel = marker["facts"]
        entry["module"] = module_rel
        entry["facts"] = facts_rel

        if is_global_module(module_rel):
            entry["scope"] = SCOPE_GLOBAL
            entry["status"] = STATUS_OK
            entry["reason"] = GLOBAL_MODULE_REASON
            entry["missing_facts"] = False
            modules.append(entry)
            continue

        module_abs = os.path.join(project_root, module_rel.replace("/", os.sep))
        if module_rel in (".", ""):
            module_abs = project_root
        if not os.path.isdir(module_abs):
            entry["status"] = STATUS_STALE
            entry["reason"] = "模块目录不存在：%s" % module_rel
            modules.append(entry)
            continue

        if not git_state.get("available"):
            index_entry = _lookup_index_module(index_data, module_rel)
            fingerprint = fingerprint_module(project_root, module_rel, max_files)
            warnings.extend(fingerprint["warnings"])
            entry["fingerprint"] = fingerprint["fingerprint"]
            baseline = (index_entry or {}).get("baseline") or {}
            if index_entry is None:
                entry["status"] = STATUS_UNKNOWN
                entry["reason"] = "index.json 中没有该模块基线（先运行 --mode index）"
            elif not baseline.get("fingerprint"):
                entry["status"] = STATUS_UNKNOWN
                entry["reason"] = "index.json 里的基线没有指纹（先运行 --mode index）"
            elif baseline.get("fingerprint") != fingerprint["fingerprint"]:
                changed, changed_count = diff_file_maps(
                    baseline.get("files") or {}, fingerprint["files"])
                entry["status"] = STATUS_STALE
                entry["reason"] = "文件指纹与基线不一致（基线时间 %s）" % (
                    baseline.get("scanned_at") or "未知")
                entry["changed_files"] = changed
                entry["changed_file_count"] = changed_count
            else:
                entry["status"] = STATUS_OK
        else:
            changes = git_module_changes(project_root, module_rel, marker["head"])
            entry["status"] = changes["status"]
            entry["reason"] = changes["reason"]
            entry["changed_files"] = changes["changed_files"]
            entry["changed_file_count"] = changes["changed_file_count"]
            if changes.get("commits"):
                entry["commits"] = changes["commits"]
            if changes.get("dirty"):
                entry["dirty"] = True

        facts_abs = os.path.join(project_root, facts_rel.replace("/", os.sep))
        if not os.path.isfile(facts_abs):
            entry["missing_facts"] = True
            if entry["status"] == STATUS_OK:
                entry["status"] = STATUS_MISSING_FACTS
                entry["reason"] = "facts 文件不存在：%s（需要 --mode scan 刷新）" % facts_rel
            elif entry["status"] == STATUS_STALE:
                entry["reason"] = "%s；同时 facts 文件不存在" % (entry["reason"] or "")
        modules.append(entry)
    return modules, warnings


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

def index_file_path(project_root):
    return os.path.join(project_root, ".dsh", "forge", "index.json")


def load_index(project_root):
    """返回 (index_data|None, error|None)。"""
    path = index_file_path(project_root)
    if not os.path.isfile(path):
        return None, None
    text = read_text_file(path)
    if text is None:
        return None, "index.json 无法读取"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, "index.json 不是合法 JSON（%s）" % exc
    if not isinstance(data, dict):
        return None, "index.json 内容不是 JSON 对象"
    return data, None


def build_index(project_root, skills_root, skills, git_state, max_files):
    modules = []
    warnings = []
    for skill in skills:
        marker, marker_error = parse_marker(skill["abs_path"])
        if marker is None:
            modules.append({
                "slug": _slugify(skill["name"]),
                "path": None,
                "skill": skill["name"],
                "skill_path": skill["rel"],
                "facts": None,
                "baseline": None,
                "status": STATUS_UNTRACKED,
                "scope": SCOPE_UNTRACKED,
                "reason": marker_error,
            })
            continue
        module_rel = marker["module"]
        facts_rel = marker["facts"]
        if is_global_module(module_rel):
            modules.append({
                "slug": _slugify(skill["name"]),
                "path": None,
                "skill": skill["name"],
                "skill_path": skill["rel"],
                "facts": None,
                "baseline": None,
                "status": STATUS_OK,
                "scope": SCOPE_GLOBAL,
                "reason": GLOBAL_MODULE_REASON,
            })
            continue
        fingerprint = fingerprint_module(project_root, module_rel, max_files)
        warnings.extend(fingerprint["warnings"])
        module_abs = os.path.join(project_root, module_rel.replace("/", os.sep))
        if module_rel in (".", ""):
            module_abs = project_root
        facts_abs = os.path.join(project_root, facts_rel.replace("/", os.sep))
        if not os.path.isdir(module_abs):
            status, reason = STATUS_STALE, "模块目录不存在：%s" % module_rel
        elif not os.path.isfile(facts_abs):
            status, reason = STATUS_MISSING_FACTS, "facts 文件不存在：%s" % facts_rel
        else:
            status, reason = STATUS_OK, None
        slug = _slugify(module_rel) if module_rel not in (".", "") else _slugify(skill["name"])
        modules.append({
            "slug": slug,
            "path": module_rel,
            "skill": skill["name"],
            "skill_path": skill["rel"],
            "facts": facts_rel,
            "baseline": {
                "scanned_at": marker["scanned"],
                "head": marker["head"],
                "fingerprint": fingerprint["fingerprint"],
                "file_count": fingerprint["file_count"],
                "files": fingerprint["files"],
            },
            "status": status,
            "scope": SCOPE_MODULE,
            "reason": reason,
        })
    project_name = os.path.basename(os.path.abspath(project_root)) or "project"
    index_data = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "project": {
            "name": project_name,
            "root": ".",
            "git": bool(git_state.get("available")),
            "head": git_state.get("head") if git_state.get("available") else "none",
        },
        "skills_root": display_path(skills_root),
        "modules": modules,
    }
    return index_data, warnings


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def _status_icon(status):
    return {
        STATUS_OK: "✓",
        STATUS_STALE: "✗",
        STATUS_MISSING_FACTS: "✗",
        STATUS_UNTRACKED: "⚠",
        STATUS_UNKNOWN: "⚠",
    }.get(status, "?")


def summarize(modules):
    summary = {status: 0 for status in STATUSES}
    for item in modules:
        status = item.get("status") or STATUS_UNKNOWN
        summary[status] = summary.get(status, 0) + 1
    summary["modules"] = len(modules)
    return summary


def next_steps_for(modules):
    steps = []
    stale = [item for item in modules if item.get("status") in (STATUS_STALE, STATUS_MISSING_FACTS)]
    untracked = [item for item in modules if item.get("status") == STATUS_UNTRACKED]
    unknown = [item for item in modules if item.get("status") == STATUS_UNKNOWN]
    if stale:
        targets = " ".join("--module %s" % item["module"] for item in stale[:3]
                           if item.get("module"))
        steps.append("运行 `refresh.py --mode scan %s` 刷新事实包，再更新对应 SKILL.md/references 与标记"
                     % targets)
    if untracked:
        steps.append("为 %d 个技能补 forge 标记（生成时写入 module/facts/scanned/head），否则无法做变更检测"
                     % len(untracked))
    if unknown:
        steps.append("标记 head 失效或 index 缺基线：重新生成事实并更新标记，或运行 `refresh.py --mode index`")
    if not steps:
        steps.append("所有模块均为最新，无需操作")
    return steps


def render_check(report):
    lines = []
    lines.append("refresh.py — 变更检测（check）")
    lines.append("项目: %s（git: %s%s）" % (
        report["project"],
        "是，HEAD %s" % report["git_head"] if report["git"] else "否",
        "；基线索引: %s" % report["index_path"] if report["index_path"] else "；无基线索引",
    ))
    lines.append("技能根: %s" % report["skills_root"])
    summary = report["summary"]
    lines.append("模块: %d 个 · ok %d · stale %d · untracked %d · missing_facts %d · unknown %d" % (
        summary["modules"], summary[STATUS_OK], summary[STATUS_STALE],
        summary[STATUS_UNTRACKED], summary[STATUS_MISSING_FACTS], summary[STATUS_UNKNOWN]))
    lines.append("")
    for item in report["modules"]:
        icon = _status_icon(item["status"])
        if item.get("scope") == SCOPE_GLOBAL:
            module_label = "*（全局技能）"
        else:
            module_label = item.get("module") or "（无 module）"
        lines.append("%s [%s] %s → %s" % (icon, item["status"], item["skill"], module_label))
        if item.get("facts") and item.get("scope") != SCOPE_GLOBAL \
                and not is_global_facts(item.get("facts")):
            lines.append("    facts: %s" % item["facts"])
        if item.get("reason"):
            lines.append("    原因: %s" % item["reason"])
        if item.get("changed_files"):
            lines.append("    变更示例（%d 个）: %s" % (
                item["changed_file_count"], ", ".join(item["changed_files"])))
        lines.append("")
    if report.get("review_globals"):
        lines.append("提示: 全局技能 %s 建议在执行模块更新时同步复核"
                     % "、".join(report["review_globals"]))
        lines.append("")
    if report["warnings"]:
        lines.append("警告:")
        for warning in report["warnings"]:
            lines.append("- ⚠️ %s" % warning)
        lines.append("")
    lines.append("下一步:")
    for index, step in enumerate(report["next_steps"], start=1):
        lines.append("%d. %s" % (index, step))
    lines.append("")
    if report["ok"]:
        lines.append("结果: 通过（退出码 0）")
    else:
        lines.append("结果: 存在过期或失败项（退出码 1）")
    return "\n".join(lines)


def render_index(report):
    lines = []
    lines.append("refresh.py — 索引重建（index）")
    lines.append("项目: %s（git: %s）" % (
        report["project"], "是，HEAD %s" % report["git_head"] if report["git"] else "否"))
    lines.append("技能根: %s" % report["skills_root"])
    lines.append("索引: %s" % report["index_path"])
    summary = report["summary"]
    lines.append("模块: %d 个 · ok %d · stale %d · untracked %d · missing_facts %d · unknown %d" % (
        summary["modules"], summary[STATUS_OK], summary[STATUS_STALE],
        summary[STATUS_UNTRACKED], summary[STATUS_MISSING_FACTS], summary[STATUS_UNKNOWN]))
    lines.append("")
    for item in report["modules"]:
        icon = _status_icon(item["status"])
        if item.get("scope") == SCOPE_GLOBAL:
            module_label = "*（全局技能）"
        else:
            module_label = item.get("module") or item.get("path") or "（无 module）"
        lines.append("%s [%s] %s → %s" % (icon, item["status"], item["skill"], module_label))
        if item.get("baseline"):
            baseline = item["baseline"]
            lines.append("    基线: scanned=%s head=%s 文件数=%s 指纹=%s" % (
                baseline.get("scanned_at") or "?",
                baseline.get("head") or "?",
                baseline.get("file_count"),
                (baseline.get("fingerprint") or "")[:12] or "无",
            ))
        if item.get("reason"):
            lines.append("    原因: %s" % item["reason"])
    lines.append("")
    if report["warnings"]:
        lines.append("警告:")
        for warning in report["warnings"]:
            lines.append("- ⚠️ %s" % warning)
    lines.append("")
    lines.append("结果: 索引已写出（退出码 0）")
    return "\n".join(lines)


def render_scan(report):
    lines = []
    lines.append("refresh.py — 增量重扫（scan）")
    lines.append("项目: %s（git: %s）" % (
        report["project"], "是，HEAD %s" % report["git_head"] if report["git"] else "否"))
    lines.append("技能根: %s" % report["skills_root"])
    lines.append("待刷新模块: %d 个" % len(report["refreshed"] + report["failed"]))
    lines.append("")
    if report["refreshed"]:
        for item in report["refreshed"]:
            lines.append("✓ %s → %s（facts: %s）" % (item["skill"], item["module"], item["facts"]))
    if report["failed"]:
        for item in report["failed"]:
            lines.append("✗ %s → %s（失败: %s）" % (item["skill"], item["module"], item["reason"]))
    if not report["refreshed"] and not report["failed"]:
        lines.append("- 没有 stale/missing_facts 模块，无需刷新")
    lines.append("")
    if report["refreshed"]:
        lines.append("事实已刷新，待更新技能：")
        for item in report["refreshed"]:
            lines.append("  - %s（module=%s）" % (item["skill"], item["module"]))
        lines.append("")
        lines.append("提示: refresh.py 不会改写 SKILL.md/标记；请更新技能正文后，"
                     "把标记里的 scanned / head 同步为最新值。")
        lines.append("非 git 项目请再运行 `refresh.py --mode index`，把新指纹登记为基线。")
    if report["skipped_untracked"]:
        lines.append("")
        lines.append("跳过 %d 个 untracked 技能（缺少 forge 标记）：%s" % (
            len(report["skipped_untracked"]),
            ", ".join(report["skipped_untracked"]),
        ))
    if report.get("skipped_global"):
        lines.append("")
        lines.append("跳过 %d 个全局技能（module=*，不单独重扫）：%s" % (
            len(report["skipped_global"]),
            ", ".join(report["skipped_global"]),
        ))
    if report["warnings"]:
        lines.append("")
        lines.append("警告:")
        for warning in report["warnings"]:
            lines.append("- ⚠️ %s" % warning)
    lines.append("")
    lines.append("结果: %s（退出码 %d）" % (
        "刷新成功" if report["ok"] else "存在刷新失败", 0 if report["ok"] else 1))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 三种模式
# ---------------------------------------------------------------------------

def mode_index(project_root, skills_root, skills, git_state, max_files):
    index_data, warnings = build_index(
        project_root, skills_root, skills, git_state, max_files)
    path = index_file_path(project_root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(index_data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        return {
            "ok": False,
            "mode": "index",
            "error": "无法写入索引 %s（%s）" % (display_project_relative(path, project_root), exc),
        }, 1
    modules = index_data["modules"]
    report = {
        "ok": True,
        "mode": "index",
        "project": index_data["project"]["name"],
        "project_root": ".",
        "git": bool(git_state.get("available")),
        "git_head": git_state.get("head"),
        "skills_root": display_path(skills_root),
        "index_path": display_project_relative(path, project_root),
        "modules": modules,
        "summary": summarize(modules),
        "warnings": warnings,
        "next_steps": next_steps_for(modules),
    }
    return report, 0


def _filter_modules(modules, module_filter):
    if not module_filter:
        return modules, None
    normalized = normalize_rel_path(module_filter)
    selected = [item for item in modules if item.get("module") == normalized]
    if not selected:
        return [], "没有找到 module=%s 的技能（检查 --module 或先 --mode index）" % normalized
    return selected, None


def mode_check(project_root, skills_root, skills, git_state, index_data, index_error,
               strict, module_filter, max_files):
    modules, warnings = compute_statuses(
        project_root, skills, git_state, index_data, max_files)
    modules, filter_error = _filter_modules(modules, module_filter)
    if filter_error:
        return {"ok": False, "mode": "check", "error": filter_error}, 2
    blocking = [item for item in modules if item["status"] in BLOCKING_STATUSES]
    if strict:
        blocking += [item for item in modules if item["status"] in NON_BLOCKING_STRICT_STATUSES]
    ok = not blocking
    stale_modules = [item for item in modules if item["status"] in BLOCKING_STATUSES]
    global_skills = [item for item in modules if item.get("scope") == SCOPE_GLOBAL]
    review_globals = [item["skill"] for item in global_skills] if stale_modules else []
    report = {
        "ok": ok,
        "mode": "check",
        "strict": strict,
        "project": os.path.basename(os.path.abspath(project_root)) or "project",
        "project_root": ".",
        "git": bool(git_state.get("available")),
        "git_head": git_state.get("head"),
        "skills_root": display_path(skills_root),
        "index_path": display_project_relative(index_file_path(project_root), project_root)
        if index_data is not None else None,
        "modules": modules,
        "review_globals": review_globals,
        "summary": summarize(modules),
        "warnings": ([index_error] if index_error else []) + warnings,
        "next_steps": next_steps_for(modules),
    }
    return report, 0 if ok else 1


def mode_scan(project_root, skills_root, skills, git_state, index_data, index_error,
              module_filter, max_files):
    modules, warnings = compute_statuses(
        project_root, skills, git_state, index_data, max_files)
    if index_error:
        warnings.insert(0, index_error)
    modules, filter_error = _filter_modules(modules, module_filter)
    if filter_error:
        return {"ok": False, "mode": "scan", "error": filter_error}, 2

    if module_filter:
        targets = [item for item in modules
                   if item.get("module") and item.get("scope") != SCOPE_GLOBAL]
    else:
        targets = [item for item in modules
                   if item["status"] in BLOCKING_STATUSES
                   and item.get("scope") != SCOPE_GLOBAL]
    skipped_untracked = [item["skill"] for item in modules
                         if item["status"] == STATUS_UNTRACKED]
    skipped_global = [item["skill"] for item in modules
                      if item.get("scope") == SCOPE_GLOBAL]

    refreshed = []
    failed = []
    for target in targets:
        module_rel = target.get("module")
        facts_rel = target.get("facts")
        if not module_rel or not facts_rel:
            failed.append({"skill": target["skill"], "module": module_rel or "?",
                           "reason": "缺少 module/facts 标记，无法定位刷新目标"})
            continue
        out_dir = os.path.join(project_root, os.path.dirname(facts_rel.replace("/", os.sep)))
        if os.path.dirname(facts_rel) in ("", "."):
            out_dir = os.path.join(project_root, ".dsh", "forge", _slugify(module_rel))
        cmd = [
            sys.executable, SCAN_SCRIPT,
            "--project", project_root,
            "--module", module_rel,
            "--out", out_dir,
        ]
        code, out, err = _run(cmd, cwd=project_root, timeout=SCAN_TIMEOUT)
        facts_abs = os.path.join(project_root, facts_rel.replace("/", os.sep))
        if code != 0:
            failed.append({
                "skill": target["skill"],
                "module": module_rel,
                "reason": _short(err.strip() or out.strip() or "scan_module.py 退出码 %d" % code),
            })
            continue
        if not os.path.isfile(facts_abs):
            failed.append({
                "skill": target["skill"],
                "module": module_rel,
                "reason": "扫描完成但 facts 文件未生成：%s" % facts_rel,
            })
            continue
        refreshed.append({
            "skill": target["skill"],
            "module": module_rel,
            "facts": facts_rel,
        })

    ok = not failed
    report = {
        "ok": ok,
        "mode": "scan",
        "project": os.path.basename(os.path.abspath(project_root)) or "project",
        "project_root": ".",
        "git": bool(git_state.get("available")),
        "git_head": git_state.get("head"),
        "skills_root": display_path(skills_root),
        "modules": modules,
        "refreshed": refreshed,
        "failed": failed,
        "skipped_untracked": skipped_untracked,
        "skipped_global": skipped_global,
        "summary": summarize(modules),
        "warnings": warnings,
        "next_steps": (["更新技能正文后同步刷新标记里的 scanned / head",
                        "非 git 项目再运行 `refresh.py --mode index`，把新指纹登记为基线"]
                       if refreshed else next_steps_for(modules)),
    }
    return report, 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="refresh.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "检测技能是否因代码变更而过期（check），重建基线索引（index），或对过期模块\n"
            "增量重扫事实包（scan）。基线来自 SKILL.md 前 15 行内的 forge 标记；\n"
            "refresh.py 只读技能文件，绝不改写 SKILL.md 或标记。"
        ),
        epilog=(
            "基线标记示例（SKILL.md 前 15 行内）\n"
            "  <!-- forge: module=packages/catalog facts=.dsh/forge/catalog/facts.json "
            "scanned=2026-11-01 head=abc1234 -->\n"
            "\n"
            "模式\n"
            "  check  git 项目用 commit 区间 + 工作区状态；非 git 项目比对 index.json 的文件指纹。\n"
            "         输出 ok / stale / untracked / missing_facts / unknown 与变更文件示例；\n"
            "         每项带 scope=module|global|untracked，有 stale 模块时提示复核全局技能。\n"
            "         全局技能用 module=* 或 module=none 标记，恒为 ok 且不参与 scan。\n"
            "  index  扫描 --skills 下所有 SKILL.md 的标记，重建 .dsh/forge/index.json。\n"
            "  scan   对 stale/missing_facts（或 --module 指定）的模块调用 scan_module.py\n"
            "         刷新 facts；不修改 SKILL.md/标记，结束时打印「事实已刷新，待更新技能」。\n"
            "\n"
            "退出码\n"
            "  0  成功 / 所有模块 ok\n"
            "  1  check 有 stale/missing_facts（--strict 下含 untracked/unknown）；scan 失败\n"
            "  2  参数错误、项目或技能目录不存在、--module 无法解析\n"
            "  3  check 时既无 git 也无 .dsh/forge/index.json（先跑 --mode index）\n"
            "\n"
            "示例\n"
            "  python3 refresh.py --project . --skills .dsh/skills --mode index\n"
            "  python3 refresh.py --project . --mode check --strict --json\n"
            "  python3 refresh.py --project . --mode scan --module packages/catalog\n"
        ),
    )
    parser.add_argument("--project", default=None,
                        help="项目根目录（默认：git rev-parse --show-toplevel，失败则当前目录）")
    parser.add_argument("--skills", default=None,
                        help="技能根目录（默认 <project>/.dsh/skills）")
    parser.add_argument("--mode", default="check", choices=("check", "index", "scan"),
                        help="check（默认）| index | scan")
    parser.add_argument("--module", default=None,
                        help="只处理某个模块（相对项目根，如 packages/catalog）")
    parser.add_argument("--json", action="store_true",
                        help="stdout 只输出一个 JSON 对象")
    parser.add_argument("--strict", action="store_true",
                        help="check 时把 untracked/unknown 也算失败（退出码 1）")
    parser.add_argument("--max-files", type=_positive_int, default=DEFAULT_MAX_FILES,
                        metavar="N",
                        help="计算文件指纹时最多处理的文件数（默认 %d）" % DEFAULT_MAX_FILES)
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
    code, out, _err = _run(["git", "rev-parse", "--show-toplevel"])
    if code == 0 and out.strip():
        candidate = out.strip().splitlines()[0].strip()
        if os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def _print_error(message, as_json):
    print("刷新失败：%s" % message, file=sys.stderr)
    if as_json:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = args.project if args.project else _resolve_default_project()
    project_root = os.path.abspath(os.path.expanduser(project_root))
    if not os.path.isdir(project_root):
        _print_error("项目目录不存在或不是目录：%s" % (args.project or project_root), args.json)
        return 2

    skills_root = args.skills if args.skills else os.path.join(project_root, ".dsh", "skills")
    skills_root = os.path.abspath(os.path.expanduser(skills_root))
    if not os.path.isdir(skills_root):
        _print_error("技能根目录不存在或不是目录：%s" % (args.skills or skills_root), args.json)
        return 2

    try:
        skills = discover_skills(skills_root)
        git_state = collect_git(project_root)
        index_data, index_error = load_index(project_root)

        if args.mode == "index":
            report, exit_code = mode_index(
                project_root, skills_root, skills, git_state, args.max_files)
        elif args.mode == "check":
            if not git_state.get("available") and index_data is None:
                message = (
                    "项目不是 git 仓库，也没有 .dsh/forge/index.json：无法判断变更。"
                    "请先运行 `refresh.py --mode index` 建立文件指纹基线。"
                )
                if index_error:
                    message += "（%s）" % index_error
                _print_error(message, args.json)
                return 3
            report, exit_code = mode_check(
                project_root, skills_root, skills, git_state, index_data, index_error,
                args.strict, args.module, args.max_files)
        else:
            report, exit_code = mode_scan(
                project_root, skills_root, skills, git_state, index_data, index_error,
                args.module, args.max_files)
    except KeyboardInterrupt:
        _print_error("已中断", args.json)
        return 2
    except Exception as exc:  # noqa: BLE001 - 不能对用户目录抛 traceback
        _print_error("内部错误（%s: %s）" % (type(exc).__name__, exc), args.json)
        return 2

    if exit_code == 2 and report.get("error"):
        _print_error(report["error"], args.json)
        return 2

    if args.json:
        payload = dict(report)
        payload.setdefault("ok", exit_code == 0)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if args.mode == "index":
            print(render_index(report))
        elif args.mode == "check":
            print(render_check(report))
        else:
            print(render_scan(report))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
