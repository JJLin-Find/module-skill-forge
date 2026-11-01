# file-map：改 X 去哪

读这个文件是为了：把「我要改的东西」映射到文件、符号与对应测试，避免全仓乱翻。路径均相对项目根。

## 1. 按意图查表

| 我要改… | 文件 | 符号 | 先看哪个测试 |
|---|---|---|---|
| SKU 格式规则 | `packages/catalog/src/product-store.ts` | `SKU_PATTERN`、`validateProductInput` | `packages/catalog/tests/product-store.test.ts` → `validateProductInput()` 组 |
| 商品字段（增/删/改名） | `packages/catalog/src/product-store.ts` | `Product`、`ProductInput`、`add`、`cloneProduct` | `ProductStore` → `add()` 用例 |
| 商品名归一化（trim 等） | `packages/catalog/src/product-store.ts` | `add` 中的 `input.name.trim()` | `add()` 用例 |
| 单价上限 / 金额校验 | `packages/catalog/src/product-store.ts` | `MAX_PRICE_CENTS`、`validateProductInput` | `validateProductInput()` 组 |
| 商品 id 生成规则 | `packages/catalog/src/product-store.ts` | `sequence`、`add` 中 `prd_` 拼接 | `add()` 用例 |
| 存储查询行为（`get`/`getBySku`） | `packages/catalog/src/product-store.ts` | `get`、`getBySku` | `ProductStore` → 副本用例 |
| 库存预占规则 | `packages/catalog/src/product-store.ts` | `reserve` | `reserve()` 用例 |
| 库存修正规则 | `packages/catalog/src/product-store.ts` | `updateStock` | `updateStock()` 用例 |
| 归档行为 | `packages/catalog/src/product-store.ts` | `archive` | 「归档后不能再预占」用例 |
| 商品列表（含分页 TODO） | `packages/catalog/src/product-store.ts` | `list` | `list()` 用例；新用例需先补接口 |
| 清仓/满件折扣率 | `packages/catalog/src/pricing.ts` | `lineDiscountRate`、`VOLUME_DISCOUNT_THRESHOLD`、`VOLUME_DISCOUNT_RATE`、`CLEARANCE_DISCOUNT_RATE` | `quote()` → 折扣两组用例 |
| 单行折扣封顶 | `packages/catalog/src/pricing.ts` | `MAX_LINE_DISCOUNT_RATE` | 暂无覆盖（需新增） |
| 折扣取整方式 | `packages/catalog/src/pricing.ts` | `quote` 中的 `Math.round` | 折扣用例的金额断言 |
| 报价返回结构 | `packages/catalog/src/pricing.ts` | `Quote`、`QuoteLine`、`Quote` 构造 | `quote()` 组；同时回归 checkout 的 `packages/checkout/tests/order-service.test.ts` |
| 报价规则标识 | `packages/catalog/src/pricing.ts` | `collectAppliedRules`、`appliedRules` | 折扣用例的 `appliedRules` 断言 |
| 公开导出面 | `packages/catalog/src/index.ts` | `export ...` | 全量 `pnpm test`（下游 checkout 也会编译） |
| 包脚本 / 构建配置 | `packages/catalog/package.json`、`packages/catalog/tsconfig.json` | `scripts`、`outDir`/`include` | `pnpm build` + `pnpm lint` |
| 全局命令 / 质量门 | 根 `package.json`、根 `vitest.config.ts` | `scripts`、`test.include`、`resolve.alias` | `pnpm test` |
| 新增 workspace 包 | 根 `pnpm-workspace.yaml`、根 `package.json`、`tsconfig.base.json`、`vitest.config.ts` | `packages`、`workspaces`、`compilerOptions.paths`、`resolve.alias` | `pnpm install` 后 `pnpm test` |

## 2. 改公开 API 时的联动清单

改动 `packages/catalog/src/index.ts` 的导出（增删改签名）后，按序检查：

1. `packages/checkout/src/order-service.ts`：`ProductStore`、`quote`、`CatalogError` 的使用点。
2. `packages/checkout/src/cart.ts`：`Product` 类型的字段使用。
3. `packages/checkout/tests/order-service.test.ts`：金额与错误码断言。
4. 本模块测试与 README（`packages/catalog/README.md` 的公开 API 表）。

## 3. 不要在这里改

| 需求 | 归属 |
|---|---|
| 购物车行合并、数量修改 | `packages/checkout/src/cart.ts`（`@sample/checkout`） |
| 下单税率、订单总额 | `packages/checkout/src/order-service.ts`（`@sample/checkout`） |
| 环境变量 `SAMPLE_SHOP_TAX_RATE` | `packages/checkout/src/order-service.ts`，本模块不读环境变量 |
| 测试框架/alias 配置 | 根 `vitest.config.ts` |

## 4. 测试覆盖缺口（改相关代码时补上）

- `getBySku` 的 `NOT_FOUND` 分支。
- `list()` 的归档过滤/分页（接口尚未提供）。
- `lineDiscountRate` 封顶路径（清仓 + 满 10 件应为 15%，不会触顶；20% 封顶实际不可达，见 pitfalls）。
- `quote()` 多行混合折扣的合计断言。
