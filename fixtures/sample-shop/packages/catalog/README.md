# @sample/catalog

商品目录模块：商品模型、内存存储、报价与折扣。下游消费者是 `@sample/checkout`（通过 workspace 依赖引入）。

## 公开 API

包外只能从 `packages/catalog/src/index.ts` 引入。改动导出面 = 影响 `@sample/checkout` 的契约。

| 符号 | 位置 | 说明 |
|---|---|---|
| `ProductStore` | `packages/catalog/src/product-store.ts` | 内存存储；`add` / `get` / `getBySku` / `list` / `reserve` / `updateStock` / `archive` |
| `validateProductInput` | `packages/catalog/src/product-store.ts` | 商品录入校验（SKU 格式、名称、价格分、库存） |
| `CatalogError` | `packages/catalog/src/product-store.ts` | 领域错误，带 `code`：`INVALID_PRODUCT` / `DUPLICATE_SKU` / `NOT_FOUND` / `OUT_OF_STOCK` / `ARCHIVED` |
| `quote` | `packages/catalog/src/pricing.ts` | 报价纯函数；行小计、折扣、合计与 `appliedRules` |
| `lineDiscountRate` | `packages/catalog/src/pricing.ts` | 单行折扣率；满 10 件 5%，`clearance` 再 10%，封顶 20% |

## 约定

- 金额全部用**整数分**（`priceCents`），展示层负责换算。
- SKU 格式 `^[A-Z]{2,4}-\d{4,8}$`，例如 `ELEC-1024`。
- `ProductStore` 返回的 `Product` 都是副本，外部修改不影响内部状态。
- `quote()` 是纯函数：不读环境变量、不访问存储，可安全用于下单前预览。
- `reserve()` 会真实扣减库存；下单流程目前只用 `get()` 做校验，不扣库存（见 `@sample/checkout`）。

## 命令

在仓库根执行：

```bash
pnpm test -- product-store   # 本模块单测
pnpm --filter @sample/catalog test
pnpm --filter @sample/catalog build
pnpm lint                    # 全量类型检查（根 tsconfig，含测试）
```

## 已知缺口

- `packages/catalog/src/product-store.ts`：`list()` 无分页，SKU 量大时目录页会变慢；需要按 cursor 分页（源码中有待办注释）。
