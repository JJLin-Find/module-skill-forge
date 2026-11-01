# catalog 架构：职责边界、调用链、数据流、不变量

读这个文件是为了：回答「这块该不该 catalog 管」「一次存储/报价操作经过哪些函数」「哪些约束不能破」。下文路径均相对项目根。

## 1. 职责边界

| 负责 | 不负责 |
|---|---|
| 商品模型 `Product`/`ProductInput` 与录入校验 | 购物车、下单、税费（`@sample/checkout` 的 `Cart`/`OrderService`） |
| 内存存储 `ProductStore` 的新增、查询、库存增减、归档 | 持久化（无数据库、无文件，进程重启即丢） |
| 库存预占（`reserve`）与库存修正（`updateStock`） | 并发控制 / 分布式锁（当前同步内存实现，见第 8 节） |
| 报价与折扣纯函数 `quote`/`lineDiscountRate` | 展示、货币换算、营销活动编排 |
| 公开 API 出口 `index.ts` | 对外 HTTP/CLI 入口（仓库内没有） |

## 2. 入口与公开 API

| 符号 | 文件 | 说明 | 契约稳定性 |
|---|---|---|---|
| `ProductStore` | `packages/catalog/src/product-store.ts` | 内存存储，方法：`add`/`get`/`getBySku`/`list`/`reserve`/`updateStock`/`archive` | 高：下游 checkout 直接使用 |
| `validateProductInput` | `packages/catalog/src/product-store.ts` | 录入校验（SKU 格式、名称非空、金额区间、库存非负） | 高 |
| `CatalogError` + `CatalogErrorCode` | `packages/catalog/src/product-store.ts` | 领域错误与错误码 | 高：下游按 code 分支 |
| `quote` | `packages/catalog/src/pricing.ts` | 报价纯函数：行小计、行折扣、合计、`appliedRules` | 高 |
| `lineDiscountRate` | `packages/catalog/src/pricing.ts` | 单行折扣率（满 10 件 5% + 清仓 10%，封顶 20%） | 中：可被外部直接调用 |
| 折扣常量 | `packages/catalog/src/pricing.ts` | `VOLUME_DISCOUNT_THRESHOLD`/`VOLUME_DISCOUNT_RATE`/`CLEARANCE_DISCOUNT_RATE`/`MAX_LINE_DISCOUNT_RATE` | 中 |
| `Product`/`ProductInput`/`Quote`/`QuoteLine`/`QuoteRequestLine` 等类型 | 上述两个文件，经 `index.ts` 导出 | 数据结构 | 高：字段变化影响下游 |

包外只允许从 `packages/catalog/src/index.ts` import。

## 3. 调用链（文字版时序）

**报价（本模块内部）**

```
quote(request: QuoteRequestLine[])
├─ request.map(...)
│  ├─ assertQuantity(quantity)               → 非正整数抛 RangeError
│  ├─ lineDiscountRate(product, quantity)    → 阈值 0.05 + clearance 0.1，Math.min(..., 0.2)
│  └─ Math.round(subtotal * rate)            → 行折扣额
├─ reduce → subtotalCents / discountCents
└─ collectAppliedRules(request)              → ['volume_10', 'clearance']
```

**存储写入**

```
ProductInput
└─ ProductStore.add(input)
   ├─ validateProductInput(input)            → CatalogError('INVALID_PRODUCT')
   ├─ idBySku 查重                          → CatalogError('DUPLICATE_SKU')
   ├─ 生成 id = prd_0001, prd_0002, ...
   └─ 写入 byId / idBySku，返回 cloneProduct(product)
```

**下游 checkout 如何调用本模块**（只读了解，改动本模块时要回归）

```
Cart.lines()
└─ OrderService.createOrder(cart)             # packages/checkout/src/order-service.ts
   ├─ store.get(product.id)                   # 本模块 ProductStore.get，可能 NOT_FOUND
   ├─ 校验 archived / stock                   # 可能 ARCHIVED / OUT_OF_STOCK
   ├─ quote(cart.lines())                     # 本模块报价
   └─ resolveTaxRate(process.env.SAMPLE_SHOP_TAX_RATE) → Order
```

## 4. 数据流

| 方向 | 数据形状 | 说明 |
|---|---|---|
| 录入 | `ProductInput` → `validateProductInput` → `Product` | 名称两端空白被 trim；`currency` 默认 `CNY`；`stock` 默认 0；`tags` 默认 `[]`；`archived` 默认 `false` |
| 读出 | `Product`（副本） | `cloneProduct` 复制 `tags` 数组，外部修改不回写 |
| 报价 | `QuoteRequestLine[]`（商品快照 + 数量）→ `Quote` | 纯函数：不读 env、不改入参、不查存储 |
| 错误 | `CatalogError{ code, message }` | 下游按 `code` 分支，不要匹配 message 文本 |

## 5. 关键不变量

改代码时逐条守住：

1. 金额单位是整数分，且 `0 < priceCents <= 10_000_000`（`MAX_PRICE_CENTS`，`packages/catalog/src/product-store.ts`）。
2. `sku` 全局唯一，格式 `^[A-Z]{2,4}-\d{4,8}$`；id 形如 `prd_0001`，单调递增、不复用。
3. 对外返回的 `Product` 一律是副本（`cloneProduct`），修改返回值不得影响存储。
4. 单行折扣率 =（数量 ≥ 10 ? 0.05 : 0）+（tags 含 `clearance` ? 0.1 : 0），再 `Math.min(rate, MAX_LINE_DISCOUNT_RATE=0.2)`。
5. 折扣额按行 `Math.round(subtotalCents * rate)` 计算；`Quote.totalCents = subtotalCents - discountCents`。
6. `reserve` 后库存不得为负；`updateStock` 使库存为负时抛 `INVALID_PRODUCT`。
7. 归档商品不可 `reserve`（`ARCHIVED`），但 `get`/`list` 仍可见（`archived: true`）。
8. `quote` 是纯函数：不读 `process.env`、不写存储；同一输入永远同一输出。

## 6. 错误码语义

| code | 抛出点 | 下游通常怎么处理 |
|---|---|---|
| `INVALID_PRODUCT` | `validateProductInput`、`updateStock`、`reserve` 参数非法 | 录入表单错误提示 |
| `DUPLICATE_SKU` | `ProductStore.add` | 提示 SKU 已存在 |
| `NOT_FOUND` | `get`/`getBySku`/`reserve`/`updateStock`/`archive` | 下游下单时商品快照过期 → 提示重新加购 |
| `OUT_OF_STOCK` | `reserve`、checkout 下单前校验 | 提示库存不足 |
| `ARCHIVED` | `reserve`、checkout 下单前校验 | 提示商品已下架 |

## 7. 外部依赖与配置

- 运行时依赖：无（`packages/catalog/package.json` 没有 `dependencies`）。
- 本模块不读环境变量。
- 构建产物：`packages/catalog/tsconfig.json` → `dist/`（`main`/`types` 指向 `dist/index.js`/`dist/index.d.ts`）。

## 8. 已知缺口与待确认

已知缺口（代码可证明）：

- `list()` 无分页、无过滤：`packages/catalog/src/product-store.ts` 的 `TODO(pagination)`，SKU 量大时目录页变慢，且不支持按 `tags`/`archived` 筛选。
- 测试覆盖缺口：未覆盖 `getBySku` 的 `NOT_FOUND`、`list` 的归档过滤/大数据量、`MAX_LINE_DISCOUNT_RATE` 封顶路径。
- 下游 `@sample/checkout` 的税率配置问题（`FIXME`，`packages/checkout/src/order-service.ts`）不属于本模块，但会一起出现在订单金额里。

待确认（业务语义，无代码/访谈依据）：

- 统一登记在 [business-spec](business-spec.md) 第 4 节的待确认清单（分页影响、折扣依据、持久化/并发、归档过滤、`appliedRules` 消费方），本文件不重复维护。
