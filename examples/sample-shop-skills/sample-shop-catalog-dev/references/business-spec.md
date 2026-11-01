# 业务规格：已实现需求、规则口径与不能动的东西

读这个文件是为了：回答「这个模块现在到底承诺了什么、字段边界与计算公式是什么、哪些是既定契约不能动」，让需求评审和新同学答疑有统一口径。下文路径相对项目根（本示例源仓库 `fixtures/sample-shop/`）。

## 1. 已实现需求清单

| 需求 | 一句话目标 | 关键规则 | 验收标准 | 代码落点 | 状态 |
|---|---|---|---|---|---|
| R1 商品录入与校验 | 挡住脏数据，保证入库字段合法 | SKU 正则、名称 trim 后非空、`priceCents` 为整数分且 (0, 10_000_000]、`stock` 非负整数 | 非法 SKU / 空名称抛 `CatalogError('INVALID_PRODUCT')`；见 `packages/catalog/tests/product-store.test.ts` 的 `validateProductInput()` 组 | `packages/catalog/src/product-store.ts` 的 `validateProductInput` | 已实现 |
| R2 商品存储与查询 | 内存里维护商品唯一真相源 | `add` 查重 SKU；`get`/`getBySku` 未命中抛 `NOT_FOUND`；返回值是副本 | `add()` 归一化/自增 id、重复 SKU、副本、`list()` 返回全部；见同名测试 | `packages/catalog/src/product-store.ts` 的 `ProductStore` | 已实现 |
| R3 库存预占与修正 | 支持下单前占库存、运营修库存 | `reserve` 只收正整数，归档/库存不足分别抛 `ARCHIVED`/`OUT_OF_STOCK`，成功才扣减；`updateStock` 不许负库存 | 「`reserve()` 扣减库存，库存不足抛 OUT_OF_STOCK」「`updateStock()` 不允许把库存改成负数」 | 同文件 `reserve` / `updateStock` | 已实现 |
| R4 商品归档 | 下架但不删除历史商品 | `archive` 置 `archived=true`；归档后不可 `reserve`，仍可 `get`/`list` | 「归档后不能再预占」 | 同文件 `archive` | 已实现 |
| R5 报价 | 下单前算出逐行小计/折扣/合计 | `quote` 纯函数：逐行 `priceCents*quantity`，折扣按行取整后汇总，`totalCents = subtotalCents - discountCents` | `quote()` 两组折扣用例 | `packages/catalog/src/pricing.ts` 的 `quote` | 已实现 |
| R6 行级折扣 | 执行满件与清仓两类折扣 | 数量 ≥ 10 加 0.05；`tags` 含 `clearance` 加 0.1；单行折扣率封顶 0.2 | 「满 10 件应用 95 折」「清仓商品叠加 10% 折扣」 | `packages/catalog/src/pricing.ts` 的 `lineDiscountRate` 与相关常量 | 已实现 |
| R7 报价规则标识 | 让下游知道本次命中了哪些规则 | `appliedRules` 为去重集合，可能含 `volume_10`、`clearance` | 上述两条用例分别断言 `appliedRules` | `packages/catalog/src/pricing.ts` 的 `collectAppliedRules` | 已实现 |
| R8 公开 API 出口 | 对外只暴露稳定契约 | 包外只允许从 `index.ts` import；导出类/函数/常量/类型 | 下游 `@sample/checkout` 可按包名 import 并编译，无深路径 import | `packages/catalog/src/index.ts` | 已实现 |
| R9 商品列表 | 提供目录页读取 | 返回全部商品副本；无分页、无 `tags`/`archived` 过滤 | 「`list()` 返回全部商品」 | `packages/catalog/src/product-store.ts` 的 `list` | 部分（缺分页/过滤，见第 4 节） |

## 2. 业务规则

| 规则 | 触发条件 | 结果 | 来源 | 代码证据 |
|---|---|---|---|---|
| SKU 格式 | 新增/校验商品时 | 不匹配 `^[A-Z]{2,4}-\d{4,8}$` 抛 `INVALID_PRODUCT` | 代码 | `packages/catalog/src/product-store.ts` 的 `SKU_PATTERN` |
| SKU 唯一 | `add` 的 SKU 已存在 | 抛 `DUPLICATE_SKU` | 代码 | `packages/catalog/src/product-store.ts` 的 `idBySku` |
| 名称归一化 | `add` 时 | 名称 trim 后入库；trim 后为空则抛 `INVALID_PRODUCT` | 代码 | 同文件 `add` 与 `validateProductInput` |
| 单价范围 | 校验/新增商品时 | `priceCents` 非整数、≤0、>10_000_000 均抛 `INVALID_PRODUCT` | 代码 | 同文件 `MAX_PRICE_CENTS` |
| 库存默认与校验 | 新增商品 / 修库存 | `stock` 省略默认 0；负数抛 `INVALID_PRODUCT` | 代码 | 同文件 `add` / `validateProductInput` |
| 商品 id | 每次 `add` | 生成 `prd_` + 4 位自增序号，不复用 | 代码 | 同文件 `sequence` |
| 查询未命中 | `get` / `getBySku` | 抛 `NOT_FOUND` | 代码 | 同文件 `get` / `getBySku` |
| 归档 | `archive` | 置 `archived=true`，不删除；`reserve` 拒绝 | 代码 | 同文件 `archive` / `reserve` |
| 预占库存 | `reserve` | 数量非正整数抛 `INVALID_PRODUCT`；已归档抛 `ARCHIVED`；库存不足抛 `OUT_OF_STOCK`；成功则扣减并返回快照 | 代码 | 同文件 `reserve` |
| 库存修正 | `updateStock` | delta 须为整数；扣减后为负抛 `INVALID_PRODUCT` | 代码 | 同文件 `updateStock` |
| 报价数量 | `quote` / `lineDiscountRate` | 非正整数抛 `RangeError` | 代码 | `packages/catalog/src/pricing.ts` 的 `assertQuantity` |
| 满件折扣 | 行数量 ≥ 10 | 行折扣率加 0.05 | 代码 | 同文件 `lineDiscountRate` |
| 清仓折扣 | 商品 `tags` 含 `clearance` | 行折扣率加 0.1 | 代码 | 同文件 `lineDiscountRate` |
| 折扣封顶 | 行折扣率叠加后 | 取 `Math.min(rate, 0.2)`；当前规则实际最大 0.15 | 代码 | 同文件 `MAX_LINE_DISCOUNT_RATE` |
| 折扣取整 | 单行计算折扣额 | `Math.round(subtotalCents * rate)`，按行取整 | 代码 | 同文件 `quote` |
| 报价合计 | `quote` 汇总 | `totalCents = subtotalCents - discountCents` | 代码 | 同文件 `quote` |
| 规则标识 | `quote` 汇总 | 命中满件记 `volume_10`、命中清仓记 `clearance`，Set 去重 | 代码 | 同文件 `collectAppliedRules` |

## 3. 字段与口径

| 字段/概念 | 单位/类型 | 默认值/范围 | 边界与语义 | 代码证据 |
|---|---|---|---|---|
| `sku` | string | 必填 | `^[A-Z]{2,4}-\d{4,8}$`，如 `ELEC-1024` | `packages/catalog/src/product-store.ts` 的 `SKU_PATTERN` |
| `priceCents` | 整数（分） | 必填，(0, 10_000_000] | 禁止小数分；10_000_000 分 = 10 万元；展示层负责换算 | 同文件 `MAX_PRICE_CENTS` |
| `currency` | `'CNY' \| 'USD'` | `'CNY'` | 仅类型约束，无汇率换算逻辑 | 同文件 `Product.currency` |
| `stock` | 整数 | 0 | ≥ 0；`reserve` 会真实扣减 | 同文件 `Product.stock` |
| `tags` | string[] | `[]` | `clearance` 有折扣语义，其余标签原样保存 | `packages/catalog/src/pricing.ts` 的 `lineDiscountRate` |
| `archived` | boolean | `false` | 归档标记；不删除数据 | `packages/catalog/src/product-store.ts` 的 `archive` |
| `id` | string | 自增 | `prd_0001` 起，只增不复用 | 同文件 `sequence` |
| `quantity` | 正整数 | 必填 | 0/小数/负数抛 `RangeError` | `packages/catalog/src/pricing.ts` 的 `assertQuantity` |
| `VOLUME_DISCOUNT_THRESHOLD` | 件 | 10 | 数量「达到」10 即触发 | 同文件常量 |
| `VOLUME_DISCOUNT_RATE` / `CLEARANCE_DISCOUNT_RATE` | 小数 | 0.05 / 0.1 | 行内叠加 | 同文件常量 |
| `MAX_LINE_DISCOUNT_RATE` | 小数 | 0.2 | 当前不可达（最大叠加 0.15），见第 4 节 | 同文件常量 |
| 取整方式 | `Math.round` | — | 按行取整，不是整单取整 | 同文件 `quote` |
| `totalCents` | 整数（分） | — | `subtotalCents - discountCents` | 同文件 `quote` |

## 4. 历史决策与不能动

- **只从 `index.ts` 暴露公开 API**：包外禁止深路径 import（`packages/catalog/src/index.ts` 头注释；下游只按包名引用）。新增/修改导出须同步 `@sample/checkout` 与测试。
- **金额一律整数分**：`priceCents` 注释与整条报价链路都以 Cents 命名，不在本模块转「元」；展示层负责换算。
- **`quote()` 是纯函数**：不读环境变量、不碰存储（`packages/catalog/src/pricing.ts` 注释），因此可安全用于下单前预览；改动时保持该性质。
- **购物车不计算金额**：`packages/checkout/src/cart.ts` 注释明确金额交给 catalog 的 `quote()`；不要在 checkout 复制折扣逻辑。
- **下单只校验不扣库存**：`packages/checkout/src/order-service.ts` 的 `assertPurchasable` 注释说明扣减由履约流程走 `reserve`；不要在 `createOrder` 里静默扣库存。
- **存储返回副本**：`cloneProduct` 保证调用方拿到快照，改返回值不回写内部状态。
- **错误码是契约**：下游按 `CatalogError.code` 分支，不要改已有 code 的语义；新增 code 需同步下游与测试。
- **`list()` 无分页/过滤是已知缺口**（`TODO(pagination)`），不能当作「目录页只需全量」的规范；改它属公开 API 变更。
- **折扣封顶 0.2 当前不可达**：实际最高 0.15，不要假设存在 20% 折扣场景。

### 待确认清单（无代码/访谈依据，不编业务故事）

1. TODO(待确认)：`list()` 改分页接口对下游消费者的影响 —— 外部消费者不在仓库内，无法确认。
2. TODO(待确认)：折扣阈值与费率（10 件、5%、清仓 10%、封顶 20%）的业务来源与是否可由运营配置；是否计划跨行满减/优惠券。
3. TODO(待确认)：库存并发与持久化的业务预期 —— 当前是单进程内存实现，无事务/多实例保护，是否只是测试替身。
4. TODO(待确认)：归档商品是否应从 `list()` 默认过滤 —— 当前不过滤，属设计行为还是缺口。
5. TODO(待确认)：`Quote.appliedRules` 的下游消费方式（展示标签/埋点）—— 仓库内暂无消费方。

## 5. 业务术语表

| 业务词 | 代码符号/位置 | 口径说明 |
|---|---|---|
| 商品 | `Product`，`packages/catalog/src/product-store.ts` | 目录里的一个 SKU 条目 |
| SKU | `Product.sku` | 商品编码，格式见第 3 节 |
| 单价（分） | `Product.priceCents` | 整数分，不是元 |
| 清仓商品 | `Product.tags` 含 `clearance`，`packages/catalog/src/pricing.ts` | 额外 10% 行折扣 |
| 满件 | `quantity >= VOLUME_DISCOUNT_THRESHOLD`，同文件 | 达到 10 件触发 5% 行折扣 |
| 报价 | `quote()` → `Quote`，同文件 | 下单前试算结果，不含税 |
| 报价行 | `QuoteLine`，同文件 | 单个商品的量、单价、小计、折扣 |
| 小计 | `subtotalCents`，同文件 | 各行小计之和 |
| 折扣 | `discountCents`，同文件 | 各行折扣之和 |
| 合计 | `totalCents`，同文件 | 小计减折扣；税额由 checkout 另加 |
| 预占 | `ProductStore.reserve`，`packages/catalog/src/product-store.ts` | 真实扣减库存 |
| 归档 | `Product.archived`，同文件 | 下架标记，不删除数据 |
| 规则标识 | `Quote.appliedRules`，`packages/catalog/src/pricing.ts` | 本次命中的折扣规则名 |
| 公开 API | `packages/catalog/src/index.ts` | 包外唯一合法入口 |
