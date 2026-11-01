# module-skill-forge — 把模块知识铸造成 DSH 技能

一个可集成的「技能铸造 agent」：在任意项目里被调用后，它**自己扫描代码**取事实、**用带代码证据的问题访谈你**补齐代码读不出的语义，最后产出**项目总览技能 + 每子模块一个技能**，放进 `.dsh/skills/` 即可在 DeepSeek Harness（或任何支持 `SKILL.md` 的 agent 运行时）中按需加载。

> 目标不是生成文档，而是让模型在「给这个模块加需求 / 修 bug / 答疑」时，自动加载正确的改动地图、验证命令和踩坑清单。

## 产出长什么样

```
<你的项目>/.dsh/skills/
├── acme-overview/              # 项目总览：模块路由表 + 全局命令 + 工程约定
│   ├── SKILL.md
│   └── references/{module-map,conventions}.md
└── acme-billing-dev/           # 每个子模块一个：改动地图 + 流程 + 坑 + 验证
    ├── SKILL.md
    └── references/{architecture,file-map,workflows,pitfalls,verification}.md
```

加载后模型看到的是「先做什么」而不是一篇架构散文：三条主流程（加需求 / 修 bug / 答疑）每步都带真实路径和可复制的命令。

## 目录结构（本仓库）

| 路径 | 作用 |
|---|---|
| [`.dsh/skills/module-skill-forge/SKILL.md`](.dsh/skills/module-skill-forge/SKILL.md) | agent 本体：六阶段流程与红线 |
| `references/` | 按需加载的深度材料：访谈手册、交付件规格、证据规则、事实包读法、校验与维护 |
| `scripts/scan_module.py` | 只读扫描目标项目 → `facts.json` + `fact-pack.md`（事实包） |
| `scripts/validate_skills.py` | 校验技能是否符合 DSH 契约与质量标准 |
| `scripts/refresh.py` | 变更检测与增量重扫：判断技能是否过期、重建指纹索引、只重扫变化模块 |
| `assets/templates/` | 生成交付件用的骨架模板 |
| [`fixtures/sample-shop/`](fixtures/sample-shop/) | 合成自测仓库（pnpm workspaces，非真实业务） |
| [`examples/sample-shop-skills/`](examples/sample-shop-skills/) | 黄金输出示例：从 fixture 生成的技能应达到的样子 |
| [`tests/test_scripts.py`](tests/test_scripts.py) | 脚本回归测试 |
| [`docs/design.md`](docs/design.md) | 设计规格（内部） |

## 5 分钟集成

1. **复制技能包**到目标项目根目录：

   ```bash
   mkdir -p <目标项目>/.dsh/skills
   cp -R <本仓库>/.dsh/skills/module-skill-forge <目标项目>/.dsh/skills/
   ```

   （也可只把本仓库当作模板：`.dsh/skills/module-skill-forge` 是唯一必须随项目走的部分。）

2. **确认发现路径**：DSH 的项目根 = 最近含 `.git` 的祖先目录；没有 git 时取当前工作目录。因此用 DSH 打开目标项目根即可，技能会出现在会话技能目录里（本工作区已验证生效）。

3. **调用**：对话里输入 `/module-skill-forge`，或直接说「把 billing 模块做成技能」，模型会按 description 自动加载。首次使用建议先加载 `examples/sample-shop-skills/` 对照预期产出。

4. **校验**：

   ```bash
   python3 <目标项目>/.dsh/skills/module-skill-forge/scripts/validate_skills.py --root <目标项目>/.dsh/skills
   ```

## 一次完整使用（用户视角）

```
你：/module-skill-forge 把 packages/billing 做成技能，最近要在这里加分期支付

agent：扫描中… 事实包 → .dsh/forge/billing/fact-pack.md
       入口 3 个（HTTP 路由 2、定时任务 1）、公开 API 9 个、测试 4 个、
       命令来自根 package.json；发现 2 处 TODO、1 个环境变量 BILLING_GATEWAY_URL
       访谈（每题都带我的推断和证据）：
       1. `src/charge.ts:88` 重试 3 次后仍失败会抛错，上游是直接失败还是进补偿队列？
       2. 金额用整数分，但 `src/refund.ts` 有一次 /100，这是展示层还是口径不一致？
       3. 加分期支付，最该先看的是哪份契约/谁负责风控？
       …

agent：产出 6 个文件（acme-billing-dev 5 个 + 总览路由更新），校验 0 error
       触发示例 / TODO(待确认) 清单 / 维护建议 …
```

## 质量标准（写入技能时强制）

1. **证据优先**：每条代码事实带相对路径（可加行号）；无依据的推断标 `TODO(待确认)`。
2. **不编造命令**：命令只能来自事实包或用户确认。
3. **渐进披露**：`SKILL.md` ≤120 行，只放路由和主流程；细节进 `references/`。
4. **可路由**：`description` 以「当…时使用」开头，40–300 字符，写任务不写模块介绍。
5. **可移植**：无绝对宿主路径、无密钥、不复制大段源码。

## 命令速查

```bash
# 扫描（生成事实包）
python3 .dsh/skills/module-skill-forge/scripts/scan_module.py --project <项目根> --module <模块路径>

# 先看候选模块（不传 --module）
python3 .dsh/skills/module-skill-forge/scripts/scan_module.py --project <项目根>

# 校验技能根（0 error 才能交付；--strict 把 warning 当 error）
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root <项目根>/.dsh/skills

# 只校验单个技能，并用该模块事实包核对命令（防止编造命令）
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py \
  --skill <项目根>/.dsh/skills/<技能名> --facts <项目根>/.dsh/forge/<模块>/facts.json

# 只读某一类问题
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root <项目根>/.dsh/skills --json

# 判断技能是否过期（0=最新，1=有 stale，3=无法判定需先 index）
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project <项目根> --mode check

# 非 git 项目：记录基线指纹；过期模块只重扫事实包（不改技能正文）
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project <项目根> --mode index
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project <项目根> --mode scan --module <模块路径>

# 自测
python3 -m unittest discover -s tests -v
```

## 给新人用：业务规格与答疑库

已实现、不会大改的模块最值得沉淀。生成时说明「给新人熟悉业务用」，agent 切到 **knowledge 取向**，在原有 5 份 references 之外再产出：

- `references/business-spec.md`：已实现需求清单、业务规则、字段口径、状态流转、历史决策与不能动的部分
- `references/faq.md`：新手 30 分钟路线 + 四组常见问答（每条带代码位置）

```text
/module-skill-forge 把 billing 模块整理成新人知识库，它已经稳定了
```

之后新人直接问 AI「这个模块为什么…」，命中技能后按 FAQ 和业务规格回答；AI 答完的新问题回写 `faq.md`，库越用越厚。**注意**：只对稳定模块做，需求还在频繁变的模块先别做。

## 设计取舍

- **先扫描后访谈**：避免把「读代码」的工作推给用户；问题必须建立在证据上，用户只需纠正和补语义。
- **事实包独立于技能**：`facts.json` 是可复查的事实基线，技能是可读的结论；代码变了只需重扫比对，不必从头访谈。
- **每模块一个技能**：路由更准（description 只覆盖一个模块的任务），上下文更省（只加载需要的模块），维护边界清晰。
- **项目级而非用户级**：技能与代码同版本、随仓库走，避免跨项目知识串味；需要复用时再复制到 `~/.dsh/skills/`。
- **模板 + 校验器**：把「格式正确」交给确定性脚本，把「判断力」留给模型和用户。

## 维护：代码变了才重扫

技能里有一条机器可读的基线标记（`<!-- forge: module=... head=<git HEAD> -->`），所以不用每次全量扫描：

```bash
# 1) 看哪些模块的技能过期（只读，exit 1 表示有过期）
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project . --mode check

# 2) 只重扫过期模块的事实包
python3 .dsh/skills/module-skill-forge/scripts/refresh.py --project . --mode scan --module <模块路径>

# 3) 对照新事实改 file-map/verification → 更新 SKILL.md 里的标记 → 再校验
python3 .dsh/skills/module-skill-forge/scripts/validate_skills.py --root .dsh/skills --strict
```

**定期触发**（三选一或组合）：

- **CI**：加一步 `refresh.py --mode check`（非 0 即失败）+ `validate_skills.py --strict`，样例见 `examples/ci/skills-freshness.yml`。
- **本地 cron**：`0 9 * * 1 cd <项目根> && python3 .dsh/skills/module-skill-forge/scripts/refresh.py --mode check --json >> .dsh/forge/refresh.log 2>&1`
- **DSH 提醒**：用 `schedule_create` 建周期提醒，到点让 agent 跑 `check` 并更新过期技能。

纯文字改进直接改正文即可；frontmatter 变化会自动刷新技能目录。细节见 [validation-and-maintenance](.dsh/skills/module-skill-forge/references/validation-and-maintenance.md)。

## 局限

- 静态扫描不执行代码：运行时注册的路由/命令、动态依赖可能漏。
- 依赖只有声明，没有调用图：调用链仍需点读核心文件。
- 热点分析依赖 git 历史：浅克隆/大重构会失真。
- 生成的技能是「起点」不是「终稿」：语义部分建议维护者过一次评审。

## 兼容性

技能格式是 `SKILL.md` + YAML frontmatter（`name`/`description`），与 DSH 技能契约一致；`references/` 采用相对路径引用，可被同类 agent 运行时按需读取。DSH 侧要求：目录名 = `name`（kebab-case）、只发现一层、`description` ≤500 字符。
