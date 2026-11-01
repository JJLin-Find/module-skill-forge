# 模块地图与路由

读这个文件是为了：定位「某任务属于哪个包/技能」，以及跨模块改动会波及谁。

## 1. workspace 模块表

| 包名 | 路径 | 技能 | 职责 | 公开入口 | 上游（谁依赖它） | 下游（它依赖谁） | 测试 | 风险 |
|---|---|---|---|---|---|---|---|---|
| `@sample/catalog` | `packages/catalog` | `sample-shop-catalog-dev` | 商品模型与校验、内存存储、报价与折扣 | `packages/catalog/src/index.ts` | `@sample/checkout` | 无（仅 devDependencies） | `packages/catalog/tests/product-store.test.ts` | 报价规则敏感；`list()` 无分页（TODO） |
| `@sample/checkout` | `packages/checkout` | 待生成（本次黄金示例未覆盖） | 购物车、下单、按税率出单 | `packages/checkout/src/index.ts` | 应用层消费者（仓库内无） | `@sample/catalog`（`workspace:*`） | `packages/checkout/tests/order-service.test.ts` | 税率环境变量非法时静默回退（FIXME） |

版本：catalog `0.3.1`、checkout `0.2.0`（各自 `package.json`）。

## 2. 依赖拓扑（文字图）

```
@sample/checkout
   │  dependencies: { "@sample/catalog": "workspace:*" }
   ▼
@sample/catalog
```

方向单向：catalog 不感知 checkout。新增跨包 import 前先确认方向；catalog 反向依赖 checkout 即架构违规。

根级共享配置：

| 文件 | 作用 |
|---|---|
| `pnpm-workspace.yaml` | workspace 包清单（唯一真相源） |
| 根 `package.json` | 全局脚本、锁定 pnpm 版本、共享 devDependencies |
| `tsconfig.base.json` | 共享 TS 编译选项（各包 `extends`） |
| `tsconfig.json` | 根级类型检查入口：`paths` 把 `@sample/catalog` 指到源码 + `include` 全部 src/tests（`pnpm lint` 用它） |
| `vitest.config.ts` | 测试 include 范围 + workspace 包 alias（测试直接跑源码） |

## 3. 跨模块任务路由

| 任务 | 改哪个包 | 先加载 | 连带影响 |
|---|---|---|---|
| 新增/修改商品字段 | catalog | `sample-shop-catalog-dev` | `packages/catalog/src/product-store.ts` 的 `Product`/`ProductInput`；checkout 若用到该字段需同步 |
| 改折扣/报价规则 | catalog | `sample-shop-catalog-dev` | `packages/catalog/src/pricing.ts`；checkout 的订单金额断言会变 |
| 改 SKU 校验 | catalog | `sample-shop-catalog-dev` | `packages/catalog/src/product-store.ts` 的 `SKU_PATTERN`/`validateProductInput`；录入方需回归 |
| 改购物车交互 | checkout | 本技能 + 直接读代码 | `packages/checkout/src/cart.ts` |
| 改税率或下单金额 | checkout | 本技能 + 直接读代码 | `packages/checkout/src/order-service.ts` + 环境变量 `SAMPLE_SHOP_TAX_RATE` |
| 加新 workspace 包 | 根 | 本技能 | 需同步 4 处：`pnpm-workspace.yaml`、根 `package.json` 的 `workspaces`、根 `tsconfig.json` 的 `paths`、`vitest.config.ts` 的 `resolve.alias` |

## 4. 模块边界判定（取证结论）

- catalog 可独立成技能：有公开入口 `packages/catalog/src/index.ts`、独立 README、独立测试，改动常成组出现（`product-store.ts` + `pricing.ts` + 测试）。
- checkout 同样具备入口/README/测试，但本次黄金示例只生成 catalog 技能，故总览里 checkout 暂按「直读代码」处理。
- 两个包都是 2–3 个源文件的小模块，粒度过细不拆；不需要把 `pricing.ts` 单独成技能。

## 5. 待确认

- TODO(待确认)：`@sample/checkout` 的上层消费者 —— 仓库内没有应用/服务代码，无法确认调用方。
- 维护者、发布/回滚流程待确认：见 `conventions.md` 第 6 节（仓库内无 `CODEOWNERS`、CI 配置、`CHANGELOG`）。
