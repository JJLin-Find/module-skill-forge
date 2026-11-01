# 新人答疑库（FAQ）

读这个文件是为了：新人带着问题来时不从零查代码；先在这里找标准答案，答完按末尾「维护约定」回写新问题。下文路径相对项目根（本示例源仓库 `fixtures/sample-shop/`）。

## 新手 30 分钟路线

1. 读 `references/architecture.md` 的「职责边界」——先知道这个模块管什么、不管什么。
2. 读 `references/file-map.md` 前三条——知道要改东西时去哪。
3. 按 `references/verification.md` 跑一次 `pnpm test -- product-store`——确认环境和基线通过。
4. 读 `references/business-spec.md` 的需求清单与规则表——知道已实现范围和业务口径。

## 一、入门问题

**Q: 这个模块是干什么的？我该从哪开始看？**
- 简答：商品目录的真相源：商品模型与校验、内存存储、报价与折扣。
- 细节：先看 `packages/catalog/src/index.ts`（公开面），再看 `packages/catalog/src/product-store.ts` 与 `packages/catalog/src/pricing.ts`；边界见 [architecture](architecture.md)。
- 相关需求：R1–R9（business-spec 第 1 节）。

**Q: 为什么金额一律用整数分，不用元？**
- 简答：避免浮点误差，全链路统一最小单位「分」。
- 细节：`packages/catalog/src/product-store.ts` 的 `priceCents` 注释；`packages/catalog/src/pricing.ts` 的 `subtotalCents`/`discountCents` 均为整数，行级 `Math.round`。
- 相关需求：R1、R5。

**Q: ProductStore 里的数据存在哪里？重启会丢吗？**
- 简答：存在内存 Map 里，重启即丢；当前没有持久化。
- 细节：`packages/catalog/src/product-store.ts` 的 `byId`/`idBySku`；`packages/catalog/package.json` 无运行时依赖；持久化预期见 architecture 第 8 节。
- 相关需求：R2。

**Q: @sample/catalog 和 @sample/checkout 什么关系？为什么 checkout 能直接用 catalog 的类型？**
- 简答：checkout 单向依赖 catalog，按包名 import 其公开 API。
- 细节：`packages/checkout/package.json` 的 `dependencies["@sample/catalog"] = workspace:*`；根 `vitest.config.ts` 的 alias 与根 `tsconfig.json` 的 paths 让测试/类型检查直接解析源码，构建时解析 catalog 的 `dist/*.d.ts`。
- 相关需求：R8。

## 二、业务规则问题

**Q: 折扣是单行算还是整单算？**
- 简答：按行算，逐行折扣后相加；没有整单满减。
- 细节：`packages/catalog/src/pricing.ts` 的 `quote` 对每行算 `discountCents` 再汇总；`appliedRules` 也是逐行收集。
- 相关需求：R5、R6。

**Q: 满 10 件 95 折和清仓 9 折能叠加吗？封顶 20% 会生效吗？**
- 简答：能叠加；同时命中时折扣率是 0.15，20% 封顶当前不会触发。
- 细节：`lineDiscountRate` 里 `rate += 0.05`（数量 ≥ 10）与 `+= 0.1`（`tags` 含 `clearance`），再 `Math.min(rate, 0.2)`；见 `packages/catalog/src/pricing.ts`。
- 相关需求：R6。

**Q: 为什么单价上限是 10 万元（10_000_000 分）？**
- 简答：代码按「分」校验上限，挡住把元当分的脏数据；业务依据待确认。
- 细节：`packages/catalog/src/product-store.ts` 的 `MAX_PRICE_CENTS`；边界含 10_000_000、不含 0。
- 相关需求：R1；依据见 business-spec 第 4 节待确认清单。

**Q: 商品能删除吗？下架怎么做？**
- 简答：没有删除接口，只有归档；归档后仍可 get/list，但不能 reserve。
- 细节：`packages/catalog/src/product-store.ts` 的 `archive`/`reserve`；用例在 `packages/catalog/tests/product-store.test.ts` 的「归档后不能再预占」。
- 相关需求：R4。

**Q: quote() 返回的 appliedRules 怎么用？**
- 简答：标识本次命中的规则，下游可据此展示活动标签或做埋点。
- 细节：`packages/catalog/src/pricing.ts` 的 `collectAppliedRules`；取值 `volume_10`/`clearance`，Set 去重。仓库内暂无消费方（见 business-spec 第 4 节待确认清单第 5 条）。
- 相关需求：R7。

**Q: 订单金额怎么算？税率算在报价里吗？**
- 简答：报价只算商品小计与折扣；税额由 checkout 在折后金额上另加。
- 细节：`packages/checkout/src/order-service.ts` 的 `createOrder`：`taxableCents = subtotalCents - discountCents`，`taxCents = Math.round(taxableCents * taxRate)`，`totalCents = taxableCents + taxCents`。
- 相关需求：R5；税率变量 `SAMPLE_SHOP_TAX_RATE` 见 overview 的 conventions。

## 三、改代码问题

**Q: 加一个商品字段要改哪些文件？**
- 简答：`Product`/`ProductInput` + `add` 默认值 + 测试；若经公开 API 暴露还要回归 checkout。
- 细节：`packages/catalog/src/product-store.ts`；测试 `packages/catalog/tests/product-store.test.ts`；联动清单见 [file-map](file-map.md) 第 2 节。
- 相关需求：R1、R2。

**Q: 想改折扣规则，动哪里、回归什么？**
- 简答：改 `pricing.ts` 的常量或 `lineDiscountRate`；回归 `quote()` 用例，确认 `appliedRules`。
- 细节：`packages/catalog/src/pricing.ts`；先 `pnpm test -- product-store`，若改了返回结构再跑 `pnpm test -- order-service`。
- 相关需求：R5、R6、R7。

**Q: 想给 list() 加分页，从哪里下手？**
- 简答：先定接口（cursor/limit/过滤）再改实现；这是公开 API 变更。
- 细节：`packages/catalog/src/product-store.ts` 的 `TODO(pagination)` 与 `list`；下游消费方未知，见 architecture 第 8 节第 1 条。
- 相关需求：R9（部分实现）。

**Q: 改完代码怎么验证？**
- 简答：单测 → 全量 → 类型检查。
- 细节：`pnpm test -- product-store` → `pnpm test` → `pnpm lint`；命令来源与前置条件见 [verification](verification.md)。
- 相关需求：全部。

## 四、排障问题

**Q: 测试报 Cannot find module '@sample/catalog' 怎么办？**
- 简答：多半是在包目录里直接跑了 vitest，没加载根配置的 alias。
- 细节：回仓库根跑 `pnpm test -- product-store`；alias 在根 `vitest.config.ts`，类型解析在根 `tsconfig.json` 的 paths；详见 [pitfalls](pitfalls.md)。
- 相关需求：R8。

**Q: 下单抛 OUT_OF_STOCK，但库存看着够？**
- 简答：先分清「下单校验用的 store 实例」和「真实库存」；下单只校验、不扣库存。
- 细节：`packages/checkout/src/order-service.ts` 的 `assertPurchasable` 用 `store.get` 校验；`reserve` 才扣减；两个 `ProductStore` 实例不共享数据。
- 相关需求：R3。

**Q: 金额和手工计算差一分？**
- 简答：折扣按行 `Math.round`，不是整单取整；复算时全程用「分」。
- 细节：`packages/catalog/src/pricing.ts` 的 `quote`。
- 相关需求：R5。

**Q: 环境变量 SAMPLE_SHOP_TAX_RATE 配错了为什么没报错？**
- 简答：checkout 的 `resolveTaxRate` 对非法值静默回退 0.08（已知缺口）。
- 细节：`packages/checkout/src/order-service.ts` 的 `FIXME`；这不是 catalog 的问题，修复属于 checkout 模块。
- 相关需求：R5（报价不含税，税额在 checkout 叠加）。

## 维护约定

- 同一个问题被问第二次，就补进本文件对应分组，保持同样格式。
- 每条答案必须带 fixture 内相对路径（可加符号名）；无代码依据的按 business-spec 第 4 节的格式登记，不要凭印象回答。
- 新增问题后重新跑一次技能校验，确保 0 error / 0 warning；本文件被 SKILL.md 引用，不要改名。
