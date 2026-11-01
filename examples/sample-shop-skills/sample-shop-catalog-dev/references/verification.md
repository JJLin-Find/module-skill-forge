# verification：命令、前置条件与预期结果

读这个文件是为了：用仓库里真实存在的命令验证改动，知道每条命令的前置条件和预期输出，不跑「看起来像」的假命令。

## 1. 前置条件

| 项 | 要求 | 证据 |
|---|---|---|
| Node.js | ≥ 20.11 | 根 `package.json` → `engines.node` |
| 包管理器 | pnpm 9（`pnpm@9.12.0`） | 根 `package.json` → `packageManager` |
| 依赖 | 先执行 `pnpm install`（仓库不含 `node_modules`、不含锁文件） | `packages/*/package.json` 只有声明；根目录无 `pnpm-lock.yaml` |
| 执行目录 | 仓库根（测试依赖根 `vitest.config.ts` 的 alias） | 根 `vitest.config.ts` → `resolve.alias` |
| 环境变量 | 跑测试不需要；手工验证税率时可设 `SAMPLE_SHOP_TAX_RATE` | `packages/checkout/src/order-service.ts` |

## 2. 命令表（全部来自 `package.json`）

| 目的 | 命令 | 来源 | 预期 |
|---|---|---|---|
| 跑 catalog 单测 | `pnpm test -- product-store` | 派生自根 `scripts.test` = `vitest run` | 1 个文件、12 个用例全部通过 |
| 跑 checkout 单测（联动回归） | `pnpm test -- order-service` | 派生自根 `scripts.test` | 1 个文件、6 个用例全部通过 |
| 全量单测 | `pnpm test` | 根 `package.json` → `scripts.test` | 2 个文件、18 个用例全部通过 |
| 构建 | `pnpm build` | 根 `package.json` → `scripts.build` | 逐包产出 `packages/*/dist/`（先 catalog 后 checkout），退出码 0 |
| 类型检查（lint） | `pnpm lint` | 根 `package.json` → `scripts.lint` = `tsc -p tsconfig.json --noEmit` | 两个包 src 与 tests 全部通过类型检查，无输出、退出码 0；无需先 `pnpm build` |
| 监听编译 | `pnpm dev` | 根 `package.json` → `scripts.dev` | 先执行一次 `pnpm build`，再逐包 `tsc -w` 进入 watch（本地开发用，CI 不用） |

过滤语法说明：`pnpm test -- <关键字>` 等价于 `vitest run <关键字>`，按测试**文件路径**做子串过滤；`product-store` 只命中 catalog 的测试文件，`order-service` 只命中 checkout 的。

包级命令（存在但测试别单包跑）：`packages/catalog/package.json` 与 `packages/checkout/package.json` 各自有 `test`/`build`，如 `pnpm --filter @sample/catalog build` 可用；`pnpm --filter @sample/checkout test` 会因缺少根 alias 解析失败（见 pitfalls）。checkout 的单包 build 需要 catalog 先产出 `dist/`。

## 3. 预期输出样例

```text
$ pnpm test -- product-store
 ✓ packages/catalog/tests/product-store.test.ts (12 tests)
 Test Files  1 passed (1)
      Tests  12 passed (12)
```

```text
$ pnpm test -- order-service
 ✓ packages/checkout/tests/order-service.test.ts (6 tests)
 Test Files  1 passed (1)
      Tests  6 passed (6)
```

## 4. 手工验证场景

**场景 A：折扣规则。** 在 `packages/catalog/tests/product-store.test.ts` 临时改一条断言：单价 1999 分、数量 10 → 小计 `19990`、折扣 `1000`、合计 `18990`。恢复前确认这正是 `quote()` 现有行为。

**场景 B：税率环境变量（需先构建，仓库无应用入口）。**

```bash
pnpm build
SAMPLE_SHOP_TAX_RATE=0.06 node -e "console.log(require('./packages/checkout/dist/index.js').resolveTaxRate(process.env.SAMPLE_SHOP_TAX_RATE))"
```

预期输出 `0.06`；把值换成 `8%` 再跑，预期仍是 `0.08`（这是已知 `FIXME`，不是配置生效）。

**场景 C：归档商品行为。** 在单测里 `store.archive(id)` 后断言 `store.get(id).archived === true`、`store.reserve(id, 1)` 抛 `ARCHIVED`、`list()` 仍包含该商品（当前设计如此）。

## 5. 已知局限

- fixture 无 `.git` 目录：无法做热点（hotspots）与「最近改动」分析；本技能未引用任何提交历史结论。
- 本示例未在「已安装依赖」环境中实际执行上述命令；预期输出依据测试文件中的用例数量与断言推导。首次接入真实项目时，先跑一遍 `pnpm install && pnpm test` 校准。
- 事实基线：2026-11-01（扫描时点），无 git HEAD 可记录。代码大改后需重跑扫描并更新本文件。
- 仓库内的 `pnpm test` 只覆盖两个模块的单测，没有集成测试、没有类型测试、没有覆盖率门槛；变更影响面仍需人工判断。
- 测试覆盖缺口（见 [file-map](file-map.md) §4），尤其是分页、封顶与多行混合折扣路径。
