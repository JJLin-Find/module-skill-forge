# pitfalls：常见故障与已知坑

读这个文件是为了：遇到异常先对照「现象 → 原因 → 处理」，再决定改哪里，避免凭感觉改代码。

## 1. 快速对照表

| 错误现象 | 可能原因 | 排查命令 | 处理方向 |
|---|---|---|---|
| 目录页商品越多越慢，接口一次返回全量 | `list()` 无分页（`TODO(pagination)`，`packages/catalog/src/product-store.ts`） | `grep -n "TODO(pagination)" packages/catalog/src/product-store.ts` | 需新增 cursor 分页；属公开 API 变更，先与下游确认（待确认） |
| 订单税率改了不生效，配置写错也不报错 | `resolveTaxRate` 对非法 `SAMPLE_SHOP_TAX_RATE` 静默回退默认值（`FIXME`，`packages/checkout/src/order-service.ts`，属 checkout 模块） | `grep -n "FIXME" packages/checkout/src/order-service.ts` | 改为启动期校验并抛错；改 checkout，不在本模块 |
| 单测报 `Cannot find module '@sample/catalog'` | 在包目录直接跑 `vitest`，没加载根 `vitest.config.ts` 的 alias | 确认执行目录（`pwd`）与 vitest 配置 | 回仓库根执行 `pnpm test -- order-service` |
| 构建/类型检查报 `Cannot find module '@sample/catalog'` | 未 `pnpm install`，或 `tsconfig.base.json` 的 `paths`/`dist` 不一致 | `pnpm install` 后重跑 `pnpm lint` | 从根安装；不要绕过 paths 改相对路径 import |
| 折扣金额与手工计算差 1 分 | 行级 `Math.round(subtotalCents * rate)` 的取整口径；浮点乘法（如 `19990 * 0.05`） | 对照 `packages/catalog/src/pricing.ts` 的 `quote` | 以「分」为单位复算；若业务要求整单取整，先确认为变更（待确认） |
| 抛 `RangeError: quantity 必须是正整数` | `quote()`/`Cart.add` 收到 0、小数或字符串数量 | 看调用方传参 | 入口处校验并转成用户可读错误 |
| 商品刚 `add` 过，下单却抛 `NOT_FOUND` | `ProductStore` 是实例级内存存储，不是全局单例；两个实例不共享数据 | 检查 `OrderService` 注入的 store 与加购用的 store 是否同一实例 | 同一实例贯穿加购与下单 |
| 并发下单后库存被超卖（都成功了） | 下单只做 `get()` 校验，不扣库存；扣减在履约流程 `reserve()` | 读 `packages/checkout/src/order-service.ts` 的 `assertPurchasable` | 校验与扣减需在同一事务/流程；当前缺口，待确认（architecture 第 8 节） |
| 归档商品仍出现在 `list()` 里 | `list()` 不过滤 `archived`（当前为设计行为） | `packages/catalog/src/product-store.ts` 的 `list` | 调用方自行过滤；若要求默认过滤，属接口变更（待确认） |
| 新增的测试没被执行 | 测试不在 `packages/*/tests/**/*.test.ts` | 看根 `vitest.config.ts` 的 `include` | 移到 `packages/<pkg>/tests/` 并按 `*.test.ts` 命名 |
| 下游报 `has no exported member` | 新符号没从 `packages/catalog/src/index.ts` 导出 | `grep -n "export" packages/catalog/src/index.ts` | 补导出，并回归 `pnpm test` |
| `pnpm build` 时 checkout 先于 catalog 失败 | 绕过 workspace 拓扑手工执行 | `grep -n "workspace" packages/checkout/package.json` | 用根 `pnpm build`（按依赖拓扑执行） |

## 2. 两个已埋缺口的细节

### 2.1 `TODO(pagination)`：`list()` 无分页（本模块）

- 证据：`packages/catalog/src/product-store.ts` 中 `list()` 上方的 `TODO(pagination)` 注释。
- 现象：`list()` 返回全部商品，且不支持 `tags`/`archived` 过滤；SKU 数量大时目录页响应变慢。
- 影响面：`list()` 是公开 API（`packages/catalog/src/index.ts` 导出 `ProductStore`）。改签名前确认下游 checkout 是否使用（当前 checkout 只用 `get`，但外部消费者未知，待确认）。
- 修复方向：增加 `list({ cursor, limit, tags, includeArchived })`，保留旧调用兼容或一次性迁移；补分页边界测试。

### 2.2 `FIXME`：税率非法值静默回退（下游 checkout，供联动排查）

- 证据：`packages/checkout/src/order-service.ts` 的 `resolveTaxRate` 上方 `FIXME`。
- 现象：`SAMPLE_SHOP_TAX_RATE=8%`、`-0.1`、`1.5` 或空串都会回退 `0.08`，日志无法区分「没配」与「配错」。
- 与本模块的关系：本模块只产出报价（`quote`），税率由 checkout 叠加；排查「订单金额不对」时先分清是折扣错了还是税率错了。折扣用 `pnpm test -- product-store` 验证，税率用 `pnpm test -- order-service` 验证。
- 修复方向（checkout 模块）：启动期校验配置并抛错；补非法值用例。本模块技能不负责改。

## 3. 容易误判的点

- `lineDiscountRate` 的实际最大折扣是 15%（满 10 件 5% + 清仓 10%），`MAX_LINE_DISCOUNT_RATE = 0.2` 当前不可达；新增第三种折扣叠加前，先确认封顶是否仍按 20% 设计（待确认）。
- `reserve()` 会真实扣减库存，`get()` 不会；排查「库存莫名减少」时先找 `reserve` 调用方。
- `quote()` 多行折扣是逐行计算后相加，不是「整单满减」；跨行优惠目前不存在。
- `ProductStore` 无删除方法，只有归档；「商品消失」应查 `archived` 字段与实例一致性，而不是找 delete。
