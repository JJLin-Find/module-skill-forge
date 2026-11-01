# 事实包：怎么读、怎么用、出问题怎么办

扫描器产出两份文件（默认在 `<项目根>/.dsh/forge/<模块名>/`）：

- `facts.json`：结构化事实，schema_version=1，用于核对路径与命令。
- `fact-pack.md`：给人/模型看的摘要，先读它。

## 1. 字段怎么用

| facts.json 字段 | 拿来干什么 | 落到交付件的哪 |
|---|---|---|
| `project.languages` / `package_managers` | 判断技术栈与包管理命令 | 总览 `conventions.md`、`verification.md` |
| `project.monorepo.packages` | 模块候选与依赖方向 | 总览 `module-map.md` |
| `module.path` / `candidates` | 定界；模块没点名时让用户选 | 模块技能标题、路由 |
| `entry_points` | 调用链起点、主路径 | `architecture.md` 入口清单 |
| `public_api` | 契约面；改它就影响下游 | `architecture.md`、`file-map.md` |
| `commands` | 唯一合法命令来源 | `verification.md` |
| `tests` | 验证命令与覆盖范围 | `verification.md`、`workflows.md` |
| `dependencies.internal` | 上下游影响面 | `architecture.md`、`pitfalls.md` |
| `signals.todos/fixmes` | 已知缺口，访谈追问素材 | `pitfalls.md` 或 `TODO(待确认)` |
| `signals.env_vars` | 运行前置条件 | `verification.md`、`conventions.md` |
| `file_tree` | 「改什么去哪」的候选 | `file-map.md` |
| `hotspots` | 最常改/最易坏的文件 | `pitfalls.md`、总览风险 |
| `warnings` | 扫描局限，必须在交付报告里复述 | 报告「已知局限」 |

**扫描器只提供事实，不提供语义**：它知道哪些文件导出什么符号，不知道「为什么这样拆」；不知道的业务含义必须来自访谈。

## 2. 模块边界怎么定

优先级：用户点名的路径 > monorepo 包目录 > 用户口述的「我们这块」> 按入口/依赖聚类。

判断模块是否可独立成技能：

- 有明确入口或公开 API（`index.ts`、`__init__.py`、路由注册）；
- 有独立测试或独立 README；
- 改动通常成组出现（同一批文件一起改）；
- 与兄弟模块的耦合可以通过路径说清（不要求解耦）。

粒度过大（>50 个源文件）就再拆一层；过小（<3 个文件）就并入父模块技能，在 `file-map.md` 里单列。

## 3. 扫描器不可用时的手工路径

按顺序补齐等价事实，结果写进事实包同目录的 `manual-facts.md`：

```bash
# 1. 项目画像
ls -1; cat package.json 2>/dev/null; cat pnpm-workspace.yaml 2>/dev/null; git log --oneline -5

# 2. 模块文件与语言分布
find <模块路径> -type f -not -path "*/node_modules/*" | head -100

# 3. 入口与导出
grep -rn "export " <模块路径>/src --include=*.ts | head -30
grep -rn "main|exports" <模块路径>/package.json

# 4. 命令
python3 -c "import json;d=json.load(open('package.json'));print(d.get('scripts'))"

# 5. 测试
find <模块路径> -name "*.test.*" -o -name "*_test.*" | head -20

# 6. 信号
grep -rn "TODO\|FIXME\|HACK" <模块路径> | head -20
grep -rn "process.env\|os.environ" <模块路径> | head -20
```

没有 git 时跳过热点分析，改用「最近修改时间」粗排，并在技能里声明。

## 4. 大仓与单仓多包

- 先在根目录扫描（不加 `--module`）拿候选列表，再对目标模块单独扫描，避免全仓遍历。
- 超大仓库用 `--max-files` 限制；超出上限时扫描器会写 warning，技能里必须声明「file-tree 不完整」。
- monorepo 的依赖方向以 `package.json` 的 workspace 依赖为准，不要靠目录形状猜。
- 跨多个包的共享代码（`packages/shared`）单独说明归属，别在两个模块技能里各写一份。

## 5. 事实包的局限（要在交付报告中转述）

- 只做静态识别，不执行代码：动态注册、反射、运行时拼装的路由/命令可能漏。
- 依赖只有声明，没有调用关系图：调用链仍需点读核心文件确认。
- `hotspots` 依赖 git 历史：浅克隆、最近重构、单体仓库会失真。
- TODO/FIXME 是线索不是结论：要判断是否仍然有效，无效的不要写进技能。
- 多语言项目可能只覆盖主语言，其它语言的工具链需要人工补。

## 6. 扫描后必须做的三件事

1. 打开每个 `entry_points` 文件，确认它真的是入口（不是废弃代码）。
2. 打开 `commands[]` 对应的脚本定义，确认命令可以原样执行。
3. 把 `warnings[]` 抄进交付报告的「已知局限」一节。
