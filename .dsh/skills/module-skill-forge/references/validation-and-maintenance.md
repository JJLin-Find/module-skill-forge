# 校验、安装与维护

## 1. 校验器规则与修复

```bash
# 全根契约校验
python3 scripts/validate_skills.py --root <项目根>/.dsh/skills
python3 scripts/validate_skills.py --root <项目根>/.dsh/skills --json     # 给机器读
python3 scripts/validate_skills.py --root <项目根>/.dsh/skills --strict   # warning 也当 error

# 单技能校验 + 用该模块事实包核对命令（防编造）
python3 scripts/validate_skills.py --skill <项目根>/.dsh/skills/<技能名> \
    --facts <项目根>/.dsh/forge/<slug>/facts.json
```

命令核对口径：`pnpm [run] <script>` / `npm run <script>` / `yarn <script>` 按脚本名与事实包比对（`--` 后参数忽略）；`install`/`ci`/`add` 等安装类命令直接放行；非包管理器命令（python/go/make）按整条命令是否出现在事实包里判断，口径偏保守。

| 报告项 | 含义 | 修复 |
|---|---|---|
| `missing frontmatter` | 文件开头没有 `---` 块 | 补 `name`/`description` |
| `name not kebab-case` | 出现大写、下划线、空格 | 改成 `sample-shop-catalog-dev` |
| `dir/name mismatch` | 目录名与 `name` 不一致 | 改目录名（推荐）或改 `name` |
| `description too long` | >500 字符（目录会截断） | 删到 300 以内 |
| `description looks like summary` | 写成模块介绍而非任务 | 改成「当…时使用」 |
| `empty body` | frontmatter 后无内容 | 至少写定位 + 三条流程 |
| `nested SKILL.md` | `.dsh/skills` 下出现多层嵌套 | 展平目录，DSH 只发现一层 |
| `duplicate name` | 同根两个技能重名 | 改名，模块级加项目前缀 |
| `absolute path` | 出现宿主绝对路径（主目录或盘符开头） | 改成项目根相对路径 |
| `broken link` | 相对链接目标不存在 | 修正路径或删链接 |
| `unreferenced reference` | references 下文件没被 SKILL.md 提到 | 在读取指引里加一句，或删文件 |
| `SKILL.md too long` | 超过 120 行 | 细节下沉到 references |
| `unknown frontmatter key` | 用了未定义键 | 只保留 `name`/`description`/`whenToUse` |
| `command not in facts` | 命令不在事实包里 | 核对 `package.json` 或标 `TODO(待确认)` |
| `possible secret` | 疑似密钥/token | 删除，改写成配置项名 |

校验通过标准：**0 error**；warning 逐条判断，剩余的在交付报告里说明。

## 2. 安装位置

| 目标 | 位置 | 适用 |
|---|---|---|
| 项目级（默认） | `<项目根>/.dsh/skills/` | 随仓库走、团队共享、和代码同版本 |
| 用户级 | `~/.dsh/skills/` | 跨项目复用同一套技能 |

注意：

- 项目根 = 最近含 `.git` 的祖先目录；没有 `.git` 时取当前工作目录，所以无 git 的工程必须在**打开 DSH 的工作目录**下建 `.dsh/skills`。
- `.dsh/skills` 只被发现一层：`<name>/SKILL.md` 或 `<name>.md`，不要再套目录。
- 项目级与用户级重名时，项目级胜出；两处同名技能行为不同会造成困惑，复制到用户级前先合并。

## 3. 生效与验证

1. 保存文件后，DSH 的文件监听会刷新技能目录；本会话新出现的技能会以替换目录的形式通知模型。
2. 验证方式：在对话里输入 `/<技能名>`（用户显式调用）或让模型按描述自动加载；能返回技能正文即成功。
3. 若目录没刷新：确认 `.dsh/skills/<name>/SKILL.md` 路径拼写、frontmatter 合法（用校验器）、当前会话 cwd 是否在该项目根下。

## 4. 更新流程

- **代码演进后**：重跑扫描 → 比对 `fact-pack.md` 与现有 references → 只改事实变化的部分（`file-map.md`、`verification.md` 最易过期）→ 再校验。
- **纯文字改进**：直接改正文即可，frontmatter 不变时目录摘要不变。
- **加新模块**：不需要重做总览，新增 `<项目>-<模块>-dev` 后在 `module-map.md` 加一行路由。
- **模块合并/拆分**：先改目录名与 `name`，再更新所有交叉引用，最后全根校验。

## 5. 变更检测与定期重扫

代码变了才重扫，避免每次任务都全量扫描，也避免技能悄悄过期。

### 5.1 基线标记

模块技能 `SKILL.md` 的 frontmatter 之后第一行写：

```markdown
<!-- forge: module=packages/catalog facts=.dsh/forge/catalog/facts.json scanned=2026-11-01 head=abc1234 -->
```

- `head` 是生成该技能时的 git HEAD；非 git 项目写 `none`，改用 `.dsh/forge/index.json` 的文件指纹判定。
- 总览技能写 `module=* facts=none`：全局技能，不随单模块判定过期，`check` 里恒为 ok，`scan` 会跳过。
- 更新技能正文后必须同步更新 `scanned` 与 `head`；`refresh.py` 只读，不会替你改标记。

### 5.2 三个模式

```bash
# 判断是否过期（只读）：exit 0 全部最新；exit 1 有 stale；exit 3 无法判定（非 git 且无索引）
python3 scripts/refresh.py --project <项目根> --mode check

# 非 git 项目 / 需要 inventory：重建基线指纹索引（.dsh/forge/index.json）
python3 scripts/refresh.py --project <项目根> --mode index

# 只重扫过期模块的事实包；不改技能正文，列出待更新的技能
python3 scripts/refresh.py --project <项目根> --mode scan
python3 scripts/refresh.py --project <项目根> --mode scan --module packages/catalog
```

### 5.3 增量更新流程

1. `check` 拿到过期模块与 `changed_files`。
2. `scan --module <模块>` 刷新事实包（`.dsh/forge/<slug>/`）。
3. 对照新事实改 `file-map.md`、`verification.md`（最易过期），必要时更新 `architecture.md`/`pitfalls.md`。
4. 更新技能里的基线标记（`scanned`/`head`），再跑校验器到 0 error。

### 5.4 定期触发

| 层 | 做法 | 频率 |
|---|---|---|
| CI | 加一步 `refresh.py --mode check`（exit 1 即失败）+ `validate_skills.py --strict` | 每个 PR / 每日 |
| 本地 cron | `0 9 * * 1 cd <项目根> && python3 .dsh/skills/module-skill-forge/scripts/refresh.py --mode check --json >> .dsh/forge/refresh.log 2>&1` | 每周一 9 点 |
| DSH | 用 `schedule_create` 建周期提醒，到点让 agent 跑 `check` 并更新过期技能 | 每周/按需 |

CI 样例见交付仓 `examples/ci/skills-freshness.yml`（`fetch-depth: 0` 必须，否则 git 历史不可用）。

## 6. 删除与归档

- 删除：直接删 `<name>/` 目录，下一次目录刷新后模型不再看到它。
- 归档：移到 `.dsh/skills-archive/`（不会被发现），保留可追溯性；不要留在 `.dsh/skills/` 里改名成 `.md`。
- 废弃模块技能时，同步删掉 `module-map.md` 里的路由行，避免模型加载到过期知识。

## 8. 知识沉淀：答完就回写

知识库不是一次性写成的。每回答一次通用的业务/代码问题，就补一条进 `references/faq.md`：

- 问题用**新人原话**写（方便下次被搜到），答案 1–3 句 + 代码位置。
- 涉及业务规则/口径的，同时补进 `references/business-spec.md` 的对应表格。
- 同一问题被问第二次，说明它值得进 FAQ；被问第三次，说明 SKILL.md 的主流程该改。
- 回写后不用重跑扫描；只改正文即可，校验器可跑一遍确认链接仍有效。

这样知识库会随使用变厚，而不是随代码变旧。

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 模型始终不加载该技能 | `description` 太泛/写成介绍 | 重写为「当…时使用」+ 具体任务词 |
| 加载后不知道该干嘛 | SKILL.md 没有「先做什么」 | 补三条主流程，每步带路径与命令 |
| 技能内容与代码冲突 | 事实过期 | 重跑扫描并更新，记录基线日期 |
| 校验器报 broken link | 文件改名后没更新引用 | 全文替换旧路径 |
| 用户级技能遮蔽项目级 | 同名且项目级不存在 | 改名或补齐项目级版本 |
