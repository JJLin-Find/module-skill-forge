# module-skill-forge — 设计规格（内部构建文档）

> 状态：构建期规格，所有实现与文档以本文件为准。用户侧说明见根 `README.md`。

## 1. 目标与非目标

**目标**：交付一个「技能铸造 agent」。它在任意目标项目里被调用后：

1. **自己检索代码**，把模块事实（入口、公开 API、依赖、命令、测试、热点、坑）沉淀成可复查的事实包；
2. **用代码驱动的问题引导用户**回答代码里读不出来的语义（业务边界、不变式、常见故障、术语、评审约定）；
3. **产出可集成的交付件**：一个项目级总览技能 + 每个子模块一个技能（`SKILL.md` + `references/`），直接放进目标项目的 `.dsh/skills/`，在 DeepSeek Harness 中可被 `/技能名` 或模型自动调用。

**非目标**：不做代码生成/重构；不替代真实评审；不联网；不在目标项目里写入 `.dsh/skills/` 以外的内容（事实包写在 `.dsh/forge/`）。

## 2. DSH 技能契约（硬约束，违反即不可用）

| 约束 | 规则 |
|---|---|
| 发现根 | `<projectRoot>/.dsh/skills`（项目，rank 100）优先，其次 `~/.dsh/skills`（用户，rank 400）；`projectRoot` = 最近含 `.git` 的祖先，否则 cwd |
| 发现深度 | 只识别 `<root>/<name>/SKILL.md` 与 `<root>/<name>.md`；**不支持嵌套** `**/SKILL.md` |
| 目录名 | 与 frontmatter `name` 一致，kebab-case：`^[a-z0-9]+(?:-[a-z0-9]+)*$` |
| frontmatter | 必填 `name`、`description`；可选 `whenToUse`、`metadata`、`disable-model-invocation`、`user-invocable` |
| description | 参与目录路由，**≤500 字符**；只写「何时用/解决什么」，不写正文 |
| 正文 | 纯 Markdown；`references/`、`scripts/`、`assets/` 中的文件由 base 目录相对路径解析、按需加载 |
| 调用 | 模型 `skill(name)` 工具；用户 `/name` 手势注入；两者都走同一份正文 |
| 生效 | 文件系统有 watcher：新增/改 frontmatter 会自动刷新目录；正文改动下次加载即生效 |

## 3. 交付物目录（本仓库）

```
PersonalStationApp/
├── README.md                                  # 用户侧：是什么 / 怎么集成 / 怎么用 / 产出长什么样
├── docs/design.md                             # 本文件（内部）
├── .dsh/skills/                               # 项目级技能根（DSH 直接发现）
│   └── module-skill-forge/                    # ★ 元技能（agent 本体）
│       ├── SKILL.md                           #   行为规范：6 阶段流程 + 红线
│       ├── references/                        #   按需加载的深度材料
│       │   ├── interview-playbook.md          #     提问策略 + 分场景题库
│       │   ├── artifact-spec.md               #     交付件逐节规格 + 反例
│       │   ├── evidence-rules.md              #     证据链与防编造
│       │   ├── scan-and-facts.md              #     事实包读法 / 扫描后必须补的点
│       │   └── validation-and-maintenance.md  #     校验、修复、安装、演进
│       ├── scripts/
│       │   ├── scan_module.py                 #   只读扫描 → facts.json + fact-pack.md
│       │   └── validate_skills.py             #   技能契约与质量校验器
│       └── assets/templates/                  #   骨架模板（复制填写）
│           ├── project-overview.SKILL.md.tmpl
│           ├── module.SKILL.md.tmpl
│           └── references/*.tmpl              #   architecture / file-map / workflows / pitfalls / verification / business-spec / faq
├── fixtures/sample-shop/                      # 合成自测仓库（非真实项目，勿当业务代码）
├── examples/sample-shop-skills/               # 黄金输出示例：从 fixture 生成的技能长什么样
└── tests/test_scripts.py                      # 脚本回归测试（stdlib unittest）
```

## 4. 生成物规格（每个模块技能 bundle）

```
<project>-<module>-dev/                 # 或 <module>-dev；必须带项目前缀防全局重名
├── SKILL.md                            # ≤120 行：路由 + 3 条主流程 + 读取指引
└── references/
    ├── architecture.md                 # 职责边界、调用链、数据流、关键不变量
    ├── file-map.md                     # 「我要改 X 就去哪」的文件/符号地图
    ├── workflows.md                    # 需求开发 / 修 bug / 答疑 三条操作流程
    ├── pitfalls.md                     # 常见故障、易踩坑、错误日志对照
    └── verification.md                 # 真实存在的构建/测试/复现命令及前置条件
```

`knowledge` 取向（模块已实现稳定、面向新人答疑与业务沉淀）再追加两份：

```
    ├── business-spec.md                # 已实现需求清单、业务规则、字段口径、历史决策、术语
    └── faq.md                          # 新手 30 分钟路线 + 四类问答 + 维护约定
```

分档：`quick`（只 SKILL.md）/ `dev`（5 份 dev references）/ `dev + knowledge`（7 份，推荐用于稳定模块）。

项目总览技能 `<project>-overview`：`SKILL.md` + `references/module-map.md`（模块表 + 路由表：什么任务加载哪个技能）+ `references/conventions.md`（跨模块约定、环境、发布、术语）。

**硬性质量红线**：

1. **证据优先**：任何代码事实必须给相对路径（可选 `:行号`）；无证据的推断写成 `TODO(待确认)`，不得陈述为事实。
2. **不编造命令**：命令只能来自扫描事实包（`package.json` scripts、Makefile、`pyproject` 等）或用户确认。
3. **渐进披露**：`SKILL.md` ≤120 行，只放路由、最常用流程、指针；细节进 `references/`，每个 reference 在 SKILL.md 里标「何时读」。
4. **可移植**：禁止绝对宿主路径（`/Users/...`）、禁止复制大段源码（引用路径即可）、不写密钥。
5. **面向任务**：描述按「何时用」写，不按「这个模块是什么」写；能让模型在 30 秒内判断该不该加载。

## 5. agent 行为流程（SKILL.md 必须实现）

| 阶段 | 动作 | 通过条件 |
|---|---|---|
| P0 定界 | 确认项目根、模块（路径或名）、深浅（`quick`/`full`）与取向（`dev`/`knowledge`：新人熟悉业务、沉淀需求规格时用） | 三者明确或可由 cwd/参数推断 |
| P1 扫描 | 运行 `scripts/scan_module.py --project <root> --module <path>`，读 `fact-pack.md`，必要时点读入口/测试/README | facts.json 产出，关键字段非空 |
| P2 定向补读 | 只读实际被入口/公开 API 引用的文件，少量高价值文件 | 能画出调用链 |
| P3 访谈 | 用 `ask_user_question`（不可用时列为编号问题）1–2 轮、共 ≤8 问；每问附「我的推断 + 代码证据」，让用户确认/纠正/补充 | 无关键未知项，或全部标 `TODO(待确认)` |
| P4 生成 | 按模板写总览技能 + 模块技能；占用文件清单先声明再写 | 文件齐全 |
| P5 校验 | 跑 `validate_skills.py --root <project>/.dsh/skills`；可选 `--skill <bundle> --facts <该模块 facts.json>` 做命令核对；修到 0 error | 0 error |
| P6 交付 | 报告：产出清单、每个技能的触发示例、`TODO(待确认)` 列表、如何验证 | 用户可复制即用 |

**访谈纪律**：先扫描后提问；只问代码里读不出来的；每轮批量；给选项；用户答「不知道」不纠缠，转成 `TODO(待确认)`；绝不问「你想让我怎么组织目录」这类工程问题。

## 6. 脚本契约

### 6.1 `scan_module.py`

```bash
python3 scan_module.py --project <dir> [--module <path|name>] [--out <dir>] [--json] [--max-files N]
```

- `--project` 默认：`git rev-parse --show-toplevel`，失败则 cwd；必须存在，否则 exit 2。
- `--module`：相对 project 的路径 / 绝对路径 / monorepo 包名；省略则扫描整个项目并列出候选模块。
- `--out` 默认 `<project>/.dsh/forge/<slug>/`；产出 `facts.json`（schema_version=1）+ `fact-pack.md`（人/模型可读摘要）。
- 只读：不得修改被扫描项目；只写 `--out`。
- 排除：`.git`、`node_modules`、`dist`、`build`、`out`、`target`、`coverage`、`.venv`、`__pycache__`、`.next`、`vendor`、锁文件、>1MB 文件、二进制。
- 支持：JS/TS（含 pnpm/yarn/npm workspaces）、Python、Go、Java/Maven、Rust/Cargo 的基本识别；无 git / 无包管理器时降级并写 `warnings`。
- `facts.json` 字段：`schema_version, generated_at, project{root,name,git{...},languages,package_managers,monorepo{is_monorepo,tool,packages[]}}, module{path,name,candidates[]}, entry_points[], public_api[], commands[], tests[], configs[], docs[], dependencies{internal[],external_top[]}, signals{todos[],fixmes[],env_vars[],routes[]}, file_tree[], hotspots[], warnings[]`。
- 每条事实自带 `evidence`（相对路径，可选行号）。
- stdout：≤20 行摘要（输出路径 + 关键发现 + 下一步建议）；`--json` 时输出单一 JSON 对象（含 `facts_path, fact_pack_path, summary`）。
- exit：0 成功；2 参数/项目不存在。

### 6.2 `validate_skills.py`

```bash
python3 validate_skills.py (--root <skills-root> | --skill <bundle-dir>) [--facts <facts.json>] [--json] [--strict]
```

校验每个 bundle/扁平技能：

- error：frontmatter 缺失/不可解析、`name` 缺失或非 kebab-case、目录名≠name、`description` 缺失或 >500 字符、正文为空、嵌套 `**/SKILL.md`（深度>2）、同根重名、绝对宿主路径（`/Users/`、`/home/`、`C:\`）、相对链接目标不存在。
- warning：description <40 或 >300 字符、无「何时用」语气（不含 `Use when`/`当`/`何时`）、`SKILL.md` >120 行、`references/` 有未被 SKILL.md 引用的文件、未知 frontmatter 键、疑似密钥、给定 `--facts` 时命令未出现在事实包。
- `--strict`：warning 视同 error。
- `--skill <bundle-dir>`：只校验一个技能包，与 `--root` 二选一；配合该模块的 `--facts` 做命令核对。
- `--facts` 命令核对口径：按脚本名匹配（`pnpm <name>`、`npm run <name>`、`yarn <name>` 等，允许 `--` 过滤参数）或安装类命令白名单（`pnpm install/i/add`、`npm ci`…）即通过；仅真正对不上的命令报 `command_not_in_facts` warning。
- 退出码：0 = 无 error；1 = 有 error（`--strict` 下 warning 也算）；2 = 参数错误/路径不存在。`--json` 输出 `{ok, errors[], warnings[], skills[]}`。

两个脚本：仅标准库、Python ≥3.9、`--help` 可用、确定性输出（无随机、无时间戳参与比对）。

## 7. fixture 与黄金示例

- `fixtures/sample-shop/`：合成 pnpm workspaces 仓库，含 `packages/catalog`、`packages/checkout` 两个模块，各有 `package.json`、`src/*.ts`、测试、README；根有 `package.json`（scripts: `test`/`build`/`lint`/`dev`）、`pnpm-workspace.yaml`、`.git` 可无（扫描需降级正常）。刻意埋 2 处 `TODO`、1 组环境变量、1 条真实测试命令，供扫描识别。
- `examples/sample-shop-skills/`：`sample-shop-overview/` + `sample-shop-catalog-dev/`（含 knowledge 取向的 `business-spec.md`、`faq.md`），按第 4 节规格手写为「黄金输出」，必须通过 `validate_skills.py`。

## 8. 验收

```bash
cd <仓库根>
python3 .dsh/skills/module-skill-forge/scripts/scan_module.py --project fixtures/sample-shop --module packages/catalog --out /tmp/forge-check
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root .dsh/skills
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root examples/sample-shop-skills
python3 .dsh/skills/module-skill-forge/scripts/scan_module.py --project fixtures/sample-shop --module packages/checkout --out /tmp/forge-checkout
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root examples/sample-shop-skills --facts /tmp/forge-check/facts.json
python3 -m unittest discover -s tests -v
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project . --mode check
（另在临时 git/非 git 仓库验证：改模块文件 → check exit 1；scan 刷新 facts；更新标记 → exit 0）
```

- 上述全部通过；`.dsh/skills` 下只有 `module-skill-forge`（不污染目录）。
- README 能让用户 5 分钟内完成：复制到目标项目 → 调用 → 产出 → 校验。

## 6.3 `refresh.py` —— 变更检测与增量重扫

目的：**代码变了才重扫**，并且能用 CI/cron 定期发现「技能已过期」。

### 基线标记（生成技能时写入 SKILL.md）

模块技能的 `SKILL.md` 在 frontmatter 之后第一行写入机器可读标记（HTML 注释，不渲染）：

```markdown
<!-- forge: module=packages/catalog facts=.dsh/forge/catalog/facts.json scanned=2026-11-01 head=abc1234 -->
```

- `module`：相对项目根的模块路径；`facts`：相对项目根的事实包路径；`scanned`：生成日期；`head`：生成时 git HEAD（非 git 项目写 `none`）。
- 必须位于 SKILL.md 前 15 行内；缺失 → 状态 `untracked`（不阻断，但 `--strict` 下算失败）。
- 标记由生成方（agent/人）在更新技能正文后同步更新；`refresh.py` 只读，不改写技能。

### CLI

```bash
python3 refresh.py --project <root> [--skills <dir>] [--mode check|index|scan] [--module <path>] [--json] [--strict]
```

- `check`（默认）：git 项目用 `git rev-list <head>..HEAD -- <module>` + `git status --porcelain -- <module>` 判定；非 git 项目比对 `.dsh/forge/index.json` 的文件指纹。输出 `ok / stale / untracked / missing_facts`，exit 0（全部 ok）或 1（存在 stale/失败）；无 git 且无 index → exit 3 并提示先跑 `--mode index`。
- `index`：重建 `.dsh/forge/index.json`（模块、技能、facts、基线时间、HEAD、文件指纹），供非 git 项目与统计使用；exit 0。
- `scan`：对 stale/`missing_facts` 模块调用 `scan_module.py` 刷新事实包；**不修改技能正文与标记**，输出「事实已刷新，待更新技能的清单」；exit 0（扫描失败 1）。
- 只读、无网络、Python 3.9 stdlib、确定性输出。

### 定期触发

| 层 | 方式 | 频率 |
|---|---|---|
| CI | `refresh.py --mode check` + `validate_skills.py --strict`，exit 1 即失败 | 每次 PR / 每日 |
| 本地 | cron / launchd 定时 `check`，日志写 `.dsh/forge/` | 每周 |
| DSH | `schedule_create` 建周期提醒，提示 agent 跑 `check` 并更新过期技能 | 每周/按需 |

README 与 `references/validation-and-maintenance.md` 给出可直接复制的命令与 CI 样例。
