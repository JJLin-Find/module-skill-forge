---
name: sample-shop-catalog-dev
description: 何时用：当你要在 sample-shop 的商品目录模块（@sample/catalog）做需求开发、修 bug、补测试或答疑时。它给出入口与调用链、改什么去哪、真实验证命令，以及分页缺失、折扣叠加等已知坑，帮你 10 分钟内定位改动点并跑通验证。
---

<!-- forge: module=packages/catalog facts=.dsh/forge/catalog/facts.json scanned=2026-11-01 head=none -->

# @sample/catalog 模块技能

下文路径相对项目根（本示例的源仓库为 `fixtures/sample-shop/`）。

**职责**：商品模型与录入校验、内存存储、报价与折扣计算；它是商品数据的唯一真相源。
**不负责**：购物车、下单、税费（属 `@sample/checkout`）；持久化（内存 Map，进程重启即丢）。
**最大风险**：折扣/取整规则牵一发动全身，改完必须回归 `packages/catalog/tests/product-store.test.ts` 中全部 `quote()` 用例。

## 先做什么：三条主流程

### 1. 需求开发（加字段、改校验、改折扣）
1. 读 `packages/catalog/src/index.ts`：确认改动是否触碰公开导出面（触碰即契约变更，需同步 `@sample/checkout` 与测试）。
2. 按 [file-map](references/file-map.md) 定位：字段/校验在 `packages/catalog/src/product-store.ts`；价格/折扣在 `packages/catalog/src/pricing.ts`。
3. 改实现，在 `packages/catalog/tests/product-store.test.ts` 补用例；报价改动补 `quote()` 用例。
4. 验证：`pnpm test -- product-store`，再 `pnpm lint`；完整步骤见 [workflows](references/workflows.md)。

### 2. 修 bug（报错 / 金额不对 / 库存异常）
1. 复现：`pnpm test -- product-store`，先看是 `CatalogError.code` 还是 `RangeError`。
2. 读 [pitfalls](references/pitfalls.md)，按「错误现象 → 原因」表对照，再改代码。
3. 按 [file-map](references/file-map.md) 找到符号与对应测试，最小改动 + 补一条能复现原 bug 的用例。
4. 验证同上；若行为变化涉及公开 API，跑全量 `pnpm test` 做影响面检查。

### 3. 答疑（这个模块怎么工作）
1. 读 [architecture](references/architecture.md) 的调用链与不变量，先给结论再给路径。
2. 问「改哪」转 [file-map](references/file-map.md)；问「怎么跑」转 [verification](references/verification.md)。
3. 问业务含义（为什么单行封顶 20%、清仓标签谁维护）→ 记为待确认（清单见 architecture 第 8 节），不要猜。

## 关键事实速查

| 事实 | 位置 |
|---|---|
| 公开入口 | `packages/catalog/src/index.ts`（只从这里导出） |
| 商品存储/校验 | `packages/catalog/src/product-store.ts` |
| 报价/折扣 | `packages/catalog/src/pricing.ts` |
| 单测 | `packages/catalog/tests/product-store.test.ts` |
| 包脚本 | `packages/catalog/package.json` → `test` = `vitest run` |
| 金额单位 | 整数分（`priceCents`） |
| 错误模型 | `CatalogError.code`：`INVALID_PRODUCT` / `DUPLICATE_SKU` / `NOT_FOUND` / `OUT_OF_STOCK` / `ARCHIVED` |
| 下游 | `@sample/checkout`（消费 `quote()` 与 `ProductStore`） |
| 已知缺口 | `list()` 无分页，`TODO(pagination)`：`packages/catalog/src/product-store.ts` |
| 环境变量 | 本模块不读环境变量；税率在 checkout 的 `SAMPLE_SHOP_TAX_RATE` |

## 业务规格与新人答疑

- 需要确认「这个模块已实现哪些需求、字段/折扣口径、哪些是不能动的契约」→ 读 [business-spec](references/business-spec.md)；需求评审和改代码前先对照它的「历史决策与不能动」。
- 新人来问问题、或同一问题第二次出现 → 先读 [faq](references/faq.md) 找标准答案，再按它末尾的维护约定回写。

## references 何时读

- [architecture.md](references/architecture.md)：需要职责边界、调用链、不变量、错误码语义时读；改公开 API 前必读。
- [file-map.md](references/file-map.md)：要动手改具体东西、找对应测试时读；按意图查表，不按目录查。
- [workflows.md](references/workflows.md)：需要三条流程的完整步骤（含影响面检查、提交前自检）时读。
- [pitfalls.md](references/pitfalls.md)：遇到报错、金额差一分、跨包解析失败等异常时先读。
- [verification.md](references/verification.md)：要跑测试/构建/类型检查，或确认前置条件与过滤语法时读。
- [business-spec.md](references/business-spec.md)：需求评审、确认字段/折扣/金额口径、判断某项改动是否越界时读；与「已实现需求清单」「不能动」逐条对照。
- [faq.md](references/faq.md)：新人答疑或问题重复出现时读；先查是否有标准答案，答完按维护约定补新条目。

## 边界

- 不改 checkout 的购物车/税率逻辑 → 交 `sample-shop-overview` 路由到 checkout（模块技能待生成，待确认）。
- 不做持久化与并发改造：当前设计就是内存存储，相关需求先确认业务预期（待确认，见 business-spec 第 4 节）。
- 命令只认 [verification](references/verification.md) 里列出的；新增脚本先改 `package.json`，再更新该文件。
