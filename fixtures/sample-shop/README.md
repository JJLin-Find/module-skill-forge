# sample-shop（合成样例仓库）

> ⚠️ 本仓库是 `module-skill-forge` 的自测 fixture，不是真实业务项目。
> 结构、命令与依赖方向刻意对齐一个真实的 pnpm workspaces 商城项目，并埋了
> 2 处待办标记与 1 组环境变量，用于验证技能铸造 agent 的扫描能力。
> 不要在这里安装依赖、提交改动或当作业务代码参考。

## 目录结构

```
sample-shop/
├── package.json              # 根工作区：脚本入口 + 共享 devDependencies
├── pnpm-workspace.yaml       # pnpm 的 workspace 清单（唯一真相源）
├── tsconfig.base.json        # 共享 TS 编译选项（各包 extends）
├── tsconfig.json             # 根级类型检查：paths 指源码 + include 全部 src/tests
├── vitest.config.ts          # 根级测试配置：include + workspace 包 alias
└── packages/
    ├── catalog/              # 商品目录：商品模型、内存存储、报价与折扣
    │   ├── src/{index,product-store,pricing}.ts
    │   └── tests/product-store.test.ts
    └── checkout/             # 结算：购物车、下单、税费
        ├── src/{index,cart,order-service}.ts
        └── tests/order-service.test.ts
```

依赖方向：`@sample/checkout` → `@sample/catalog`（单向，catalog 不感知 checkout）。

## 常用命令

所有命令都在本目录（仓库根）执行，需要 Node >= 20.11 与 pnpm 9（`packageManager` 字段已锁定）。

| 命令 | 作用 | 来源 |
|---|---|---|
| `pnpm install` | 安装依赖（首次运行前必须执行，仓库不提交 `node_modules`） | 前置条件 |
| `pnpm test` | 跑全部 workspace 单测（vitest） | `package.json` → `scripts.test` |
| `pnpm test -- product-store` | 只跑文件名匹配 `product-store` 的单测（vitest 位置参数过滤） | 派生自 `scripts.test` |
| `pnpm build` | 逐包 `tsc` 产出 `dist/`；按 workspace 拓扑先 catalog 后 checkout（checkout 的类型解析依赖 catalog 的 `dist/index.d.ts`） | `package.json` → `scripts.build` |
| `pnpm lint` | 全量类型检查（含测试；根 `tsconfig.json` 用 paths 直接解析 workspace 源码，无需先 build） | `package.json` → `scripts.lint` |
| `pnpm dev` | 先构建一次，再逐包 `tsc --watch`（checkout 的 `tsc -w` 需要 catalog 已产出 `dist/`） | `package.json` → `scripts.dev` |

## 环境变量

| 变量 | 含义 | 默认值 | 读取处 |
|---|---|---|---|
| `SAMPLE_SHOP_TAX_RATE` | 订单税率，小数形式（`0.08` = 8%） | `0.08` | `packages/checkout/src/order-service.ts` |

## 已知问题

- `packages/catalog/src/product-store.ts`：`list()` 一次性返回全部商品，没有分页，商品量大时目录页会变慢。
- `packages/checkout/src/order-service.ts`：非法 `SAMPLE_SHOP_TAX_RATE` 会静默回退默认税率，线上无法区分「没配」与「配错」。
