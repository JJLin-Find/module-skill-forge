---
name: module-skill-forge
description: 当用户想把某个项目/子模块的隐性知识固化成可复用的 DSH 技能，或因需求开发、修 bug、代码答疑需要先建立模块认知时使用。它先扫描代码取事实，再用带代码证据的问题访谈用户，最后产出项目总览技能与每模块一个技能（SKILL.md + references），可直接放入目标项目 .dsh/skills 在 DeepSeek Harness 中调用。
---

<!-- forge: module=* facts=none scanned=2026-11-01 head=none -->

# 模块技能铸造

把「一个模块的隐性知识」变成「模型可加载的技能」。核心不是写文档，而是：**先拿到事实 → 再问出事实之外的东西 → 按契约产出可路由、可校验的技能包**。

## 三条红线

1. **证据优先**：任何代码事实必须带相对路径（可加 `:行号`）；没有证据的推断写成 `TODO(待确认)`，不得写成事实。
2. **不编造命令**：构建/测试/运行命令只能来自扫描事实包或用户确认；拿不准就标 `TODO(待确认)`。
3. **先扫描后提问**：没有事实包之前不许向用户提问；问题必须建立在代码证据上，而不是让用户替你读代码。

## 输入（P0 定界，先确认三件事）

| 项 | 默认 | 确认方式 |
|---|---|---|
| 项目根 | cwd 的 git 根，否则 cwd | 与 cwd 不一致时问一次 |
| 模块 | 用户点名的路径或包名 | 未点名时先扫描列出候选，让用户单选 |
| 深浅 | `full`（总览 + 模块技能 + 全部 references） | 用户说「先快速看看」→ `quick`（只写两个 SKILL.md） |
| 取向 | `dev`（面向开发：改动地图/流程/坑） | 用户提到「新人熟悉业务、沉淀需求规格、答疑」→ `knowledge`（额外写 `business-spec.md`、`faq.md`） |

一次最多问 3 个问题，三项都缺才问三个。用户没耐心时按默认值推进，并在报告里声明假设。

## 六阶段

### P0.5 变更检查（项目里已有技能时必做）

```bash
python3 scripts/refresh.py --project <项目根> --mode check
```

exit 0 = 无过期；exit 1 = 列出的模块技能已过期，先按 [validation-and-maintenance](references/validation-and-maintenance.md) 的「增量重扫」更新旧技能，再开始新任务；exit 3 = 非 git 且无索引，提示先 `--mode index`。本次任务是新建技能时跳过。

### P1 扫描（必须执行）

```bash
python3 scripts/scan_module.py --project <项目根> --module <模块路径>
```

读 `<项目根>/.dsh/forge/<slug>/fact-pack.md`；`facts.json` 用于核对命令与路径。扫描器不可用时按 [scan-and-facts](references/scan-and-facts.md) 手工取事实，不要跳过。

### P2 定向补读

只读：入口文件、公开 API 导出、调用链串起来的 1–3 个核心实现、测试与 README。目标：能画出「入口 → 核心逻辑 → 数据/外部依赖」一条链。禁止全库通读。

### P3 访谈（≤2 轮，共 ≤8 问）

按 [interview-playbook](references/interview-playbook.md) 选题，用 `ask_user_question`（不可用时在回复里列编号问题）。每问格式：**我的推断 + 代码证据 + 请你确认/纠正**。只问代码读不出来的：业务边界、不变量、故障表现、术语、评审/发布约定、易错点。用户答「不知道」→ 记 `TODO(待确认)` 并继续。

禁止问：目录怎么组织、要不要写测试、模块该怎么称呼。

### P4 生成

按 [artifact-spec](references/artifact-spec.md) 与 `assets/templates/` 写两类技能：

- `<项目>-overview`：`SKILL.md` + `references/module-map.md` + `references/conventions.md`
- `<项目>-<模块>-dev`：`SKILL.md` + `references/architecture.md`、`file-map.md`、`workflows.md`、`pitfalls.md`、`verification.md`
- `knowledge` 取向再加 2 份：`references/business-spec.md`（已实现需求的规则/口径/历史决策）与 `references/faq.md`（新人问答库）。模块已实现且不会频繁改时优先用 knowledge 取向

写入 `<项目根>/.dsh/skills/`。动手前先在回复里列文件清单与每份职责（一屏以内）。每个技能的 `SKILL.md` 必须带基线标记（模块技能 `module=<路径> facts=<事实包>`，总览技能 `module=* facts=none`），详见 [artifact-spec](references/artifact-spec.md)。

### P5 校验（必须到 0 error）

```bash
# 1) 全根契约校验：frontmatter、命名、链接、行数、重复名
python3 scripts/validate_skills.py --root <项目根>/.dsh/skills

# 2) 单技能命令核对：把技能里的命令与该模块事实包比对，防编造
python3 scripts/validate_skills.py --skill <项目根>/.dsh/skills/<技能名> --facts <项目根>/.dsh/forge/<slug>/facts.json
```

按报告修复；warning 逐条判断，能改则改。报 `command_not_in_facts` 的命令：要么确实是事实包里的脚本（按脚本名匹配，安装类命令自动放行），要么补进项目脚本，要么标 `TODO(待确认)`。校验不通过不得交付。规则与修复对照见 [validation-and-maintenance](references/validation-and-maintenance.md)。

### P6 交付报告

≤25 行：①产出文件清单 + 一句话职责；②每个技能的触发示例（用户怎么说会命中）；③`TODO(待确认)` 汇总；④维护建议；⑤提醒：正文可继续手改，frontmatter 改动会自动刷新目录；本次答疑中出现的通用知识应回写 `faq.md`（知识库靠这个越来越厚）。

## 质量预算

| 对象 | 预算 |
|---|---|
| 每个 `SKILL.md` | ≤120 行；只放路由、3 条主流程、指针 |
| 每个 `references/*.md` | ≤200 行；一个文件一个主题 |
| `description` | 40–300 字符，以「当…时使用」开头，写任务不写模块介绍 |
| 事实密度 | 每个「改哪里」都给路径；每条命令都能直接复制执行 |

## 何时读 references

- 准备提问 → [interview-playbook](references/interview-playbook.md)（六类题库 + 追问技巧 + 反例）
- 准备动笔 → [artifact-spec](references/artifact-spec.md)（逐节规格 + 正反例）配合 `assets/templates/`
- 拿不准某条结论的依据 → [evidence-rules](references/evidence-rules.md)
- 扫描失败/事实不足/超大仓 → [scan-and-facts](references/scan-and-facts.md)
- 校验报错、安装/更新/删除技能、判断技能是否过期 → [validation-and-maintenance](references/validation-and-maintenance.md)

## 不做

不生成业务代码、不重构、不替用户做架构决策、不写与任务无关的项目介绍、不在 `.dsh/skills` 之外写文件（事实包固定在 `.dsh/forge/`）。
