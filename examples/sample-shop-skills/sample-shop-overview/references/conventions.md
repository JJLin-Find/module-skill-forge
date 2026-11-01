# 跨模块约定（workspace / 命令 / 环境 / 依赖方向）

读这个文件是为了：按仓库既有约定改代码、跑命令、加包，而不是自己发明一套结构。

## 1. workspace 约定

- 包清单唯一真相源：`pnpm-workspace.yaml`（`packages/*`）；根 `package.json` 的 `workspaces` 是兼容镜像，改包目录时两处同步。
- 包管理器锁定：根 `package.json` → `packageManager: pnpm@9.12.0`；Node `>=20.11`（`engines`）。
- 包名一律 `@sample/<目录名>`：`packages/catalog` → `@sample/catalog`。
- 跨包依赖写 `workspace:*`（示例：`packages/checkout/package.json` 的 `dependencies["@sample/catalog"]`），不要写死版本号。
- 包外只能从 `packages/<pkg>/src/index.ts` import；深路径 import 视为违规。
- 新增包需同步 5 处：`pnpm-workspace.yaml`、根 `package.json` 的 `workspaces`、`packages/<pkg>/tsconfig.json`（extends `../../tsconfig.base.json`）、根 `tsconfig.json` 的 `paths`（类型检查）、根 `vitest.config.ts` 的 `resolve.alias`（测试解析源码）。

## 2. 命令与前置条件

| 目的 | 命令 | 说明 |
|---|---|---|
| 安装 | `pnpm install` | 首次必须；仓库不含 `node_modules`、不含锁文件 |
| 全部单测 | `pnpm test` | 根 `package.json` → `scripts.test` = `vitest run` |
| 过滤单测 | `pnpm test -- catalog` | 派生自 `scripts.test`；参数是 vitest 的文件名过滤 |
| 构建 | `pnpm build` | 逐包 `tsc`；拓扑顺序 catalog → checkout |
| 类型检查 | `pnpm lint` | 根 `tsc -p tsconfig.json --noEmit`；paths 直接解析源码，无需先 build |
| 监听编译 | `pnpm dev` | 先 `pnpm build` 再逐包 `tsc -w`（checkout 需要 catalog 的 `dist/`） |

- 各包也有自己的 `test`/`build`（`packages/*/package.json`），但**测试必须从仓库根跑**：`@sample/catalog` 的解析依赖根 `vitest.config.ts` 的 alias，在包目录内直接 `vitest run` 会找不到该包。排查见 `sample-shop-catalog-dev` 的 pitfalls。
- 类型检查统一用根 `pnpm lint`：跨包 import 由根 `tsconfig.json` 的 `paths` 指到源码，所以不要求先 `pnpm build`。
- 命令只认 `package.json` 里登记过的；不要手写未登记的命令或全局工具。

## 3. 环境变量

| 变量 | 默认 | 读取处 | 说明 |
|---|---|---|---|
| `SAMPLE_SHOP_TAX_RATE` | `0.08` | `packages/checkout/src/order-service.ts` 的 `resolveTaxRate` | 小数税率（`0.06` = 6%）；非法值静默回退（FIXME） |

单测不需要设置环境变量：测试向 `resolveTaxRate` 注入原始字符串。本地手工验证环境变量时可用：

```bash
SAMPLE_SHOP_TAX_RATE=0.06 pnpm test -- order-service
```

## 4. 代码与测试约定

- 金额一律整数分（`priceCents`），禁止 float 元；展示层负责换算。
- 错误：领域错误用 `CatalogError` + `code`；参数错误用 `RangeError`；不要抛裸 `Error` 字符串。
- 时间：`OrderService` 构造参数注入 `now()`（`packages/checkout/tests/order-service.test.ts` 的 `fixedNow`），实现里只通过注入的时钟取时间。
- 测试位置固定：`packages/<pkg>/tests/*.test.ts`；根 `vitest.config.ts` 的 `include` 只认这个位置，放到别处不会被跑。
- TypeScript：`tsconfig.base.json` 开 `strict`，`module: CommonJS` + `moduleResolution: Node`（各包构建用）；根 `tsconfig.json` 覆盖为 `module: ESNext` + `moduleResolution: Bundler`，只做类型检查（`noEmit` + `paths` 指源码）。包内 tsconfig 只设 `rootDir`/`outDir`/`include`，构建时 workspace 包解析到对方 `dist/*.d.ts`。
- 存储类返回的都是副本（catalog 的 `cloneProduct`），调用方可以安全修改快照。

## 5. 术语

| 术语 | 含义 |
|---|---|
| SKU | 商品编码，`^[A-Z]{2,4}-\d{4,8}$`，如 `ELEC-1024` |
| priceCents | 单价，单位「分」 |
| clearance | 清仓标签，参与额外 10% 折扣 |
| volume_10 | 满 10 件 95 折规则标识（出现在 `Quote.appliedRules`） |

## 6. 待确认

- TODO(待确认)：分支/提交/评审约定、CI 流水线、发布流程 —— 仓库内无 `.github/`、`CODEOWNERS`、`CHANGELOG`，代码无法证明。
- TODO(待确认)：是否应提交 `pnpm-lock.yaml` —— 当前 fixture 刻意不含；真实项目应提交以锁定依赖。
