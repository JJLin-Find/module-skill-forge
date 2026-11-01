# @sample/checkout

结算模块：购物车、下单、税费。依赖 `@sample/catalog`（workspace 依赖），调用它的 `quote()` 报价与 `ProductStore` 读取商品。

## 公开 API

| 符号 | 位置 | 说明 |
|---|---|---|
| `Cart` | `packages/checkout/src/cart.ts` | 购物车；`add` / `remove` / `setQuantity` / `lines` / `totalQuantity` / `isEmpty` / `clear`，不计算金额 |
| `OrderService` | `packages/checkout/src/order-service.ts` | `createOrder(cart)`：校验可购 → 调 catalog 报价 → 叠加税率 → 返回 `Order` |
| `resolveTaxRate` | `packages/checkout/src/order-service.ts` | 默认读环境变量 `SAMPLE_SHOP_TAX_RATE`（也可注入原始字符串），非法/缺省回退 `DEFAULT_TAX_RATE` |
| `DEFAULT_TAX_RATE` | `packages/checkout/src/order-service.ts` | 默认税率 `0.08` |

## 数据流

```
Cart.lines()
  → OrderService.assertPurchasable()  # store.get() 校验存在/未下架/库存
  → catalog.quote()                   # 行小计 + 折扣（满 10 件 5%，clearance 10%，单行封顶 20%）
  → resolveTaxRate(process.env.SAMPLE_SHOP_TAX_RATE)   # 默认 0.08
  → Order { subtotalCents, discountCents, taxCents, totalCents }
```

金额全部是整数分；`totalCents = subtotalCents - discountCents + taxCents`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SAMPLE_SHOP_TAX_RATE` | `0.08` | 税率小数（`0.06` = 6%），读取处 `packages/checkout/src/order-service.ts` |

## 命令

在仓库根执行：

```bash
pnpm test -- order-service      # 本模块单测（根 vitest 配置提供 @sample/catalog alias）
pnpm build                      # 全量构建；checkout 依赖 catalog 先产出 dist
pnpm lint
```

> 单包直接跑 `pnpm --filter @sample/checkout test` 会缺少根 `vitest.config.ts` 的 alias，`@sample/catalog` 解析失败；请从根目录跑并加文件名过滤。

## 已知缺口

- `packages/checkout/src/order-service.ts`：`SAMPLE_SHOP_TAX_RATE` 非法时静默回退默认税率，线上无法区分「没配」与「配错」（源码中有待办注释）。
