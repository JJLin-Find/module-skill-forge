---
name: sample-shop-overview
description: 何时用：当你刚进入 sample-shop 仓库，需要判断某个任务该改哪个包、该加载哪个模块技能，或要查全局命令、workspace 依赖方向与环境变量时。它给出模块路由表与跨模块约定，避免在错误的包里找代码。
---

<!-- forge: module=* facts=none scanned=2026-11-01 head=none -->

# sample-shop 项目总览

pnpm workspaces 的商城样例：两个包 `@sample/catalog`（商品目录/报价）与 `@sample/checkout`（购物车/下单/税费），TypeScript + vitest，没有运行时服务、没有数据库。
本技能只做路由，不写实现细节。下文代码路径相对项目根（本示例的源仓库为 `fixtures/sample-shop/`）。

**第一步**：按下面路由表决定加载哪个模块技能；不确定就先读 [module-map](references/module-map.md)。

## 模块路由表

| 你的任务 | 加载技能 | 落点 |
|---|---|---|
| 改商品字段、SKU 校验、库存、商品列表 | `sample-shop-catalog-dev` | `packages/catalog/src/product-store.ts` |
| 改折扣规则、报价、金额计算 | `sample-shop-catalog-dev` | `packages/catalog/src/pricing.ts` |
| 改购物车交互、下单流程、税费 | 本技能 + 直接读代码（checkout 模块技能尚未生成） | `packages/checkout/src/cart.ts`、`packages/checkout/src/order-service.ts` |
| 跨模块改动（字段/契约从 catalog 传到 checkout） | 本技能 → 两个模块技能 | 影响面见 [module-map](references/module-map.md) 第 3 节 |
| 加 workspace 包、改根配置 | 本技能 | `pnpm-workspace.yaml`、根 `package.json`、`tsconfig.base.json`、根 `tsconfig.json`、`vitest.config.ts` |

## 全局命令（来源：根 `package.json` → `scripts`）

| 目的 | 命令 | 前置条件 |
|---|---|---|
| 安装依赖 | `pnpm install` | Node ≥ 20.11、pnpm 9（`packageManager: pnpm@9.12.0`）；仓库不含 `node_modules` |
| 全部单测 | `pnpm test` | 已安装依赖；根 `vitest.config.ts` 提供 `@sample/catalog` alias |
| 过滤单测 | `pnpm test -- catalog` | 同上；参数是 vitest 的文件名过滤 |
| 构建 | `pnpm build` | 已安装依赖；按 workspace 拓扑先 catalog 后 checkout |
| 类型检查（lint） | `pnpm lint` | 已安装依赖；根 `tsc -p tsconfig.json --noEmit`（paths 直接解析 workspace 源码，无需先 build） |
| 监听编译 | `pnpm dev` | 已安装依赖；根脚本先 `pnpm build` 再逐包 `tsc -w` |

## 跨模块硬约定

- 依赖方向单向：`@sample/checkout` → `@sample/catalog`（`packages/checkout/package.json` 的 `workspace:*`）；catalog 不得反向 import checkout。
- 包外只能从 `packages/<pkg>/src/index.ts` import，禁止深路径。
- 金额一律整数分（`priceCents`），展示层再换算；完整约定见 [conventions](references/conventions.md)。
- 改公开导出面（`src/index.ts`）视为契约变更：同步下游调用方与测试。

## 环境变量

| 变量 | 默认 | 读取处 |
|---|---|---|
| `SAMPLE_SHOP_TAX_RATE` | `0.08` | `packages/checkout/src/order-service.ts` |

## references 何时读

- [module-map.md](references/module-map.md)：需要完整模块表（包名/路径/职责/上下游/风险），或判断跨模块任务影响哪些包时读。
- [conventions.md](references/conventions.md)：动手改代码、加包、跑命令前读，尤其是 workspace 依赖写法、命令参数、环境变量与术语。

## 边界

- 不写模块内部函数与调用链细节 —— 那属于模块技能；总览里出现具体函数名说明内容放错了位置。
- checkout 的深度答疑暂缺技能：TODO(待确认) —— 生成 `sample-shop-checkout-dev` 后，把上面路由表对应行改为指向它。
