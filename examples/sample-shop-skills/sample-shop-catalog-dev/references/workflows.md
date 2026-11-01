# workflows：三条操作流程

读这个文件是为了：按步骤完成一次需求开发 / 修 bug / 答疑，并知道每步的验证命令。

约定：项目根执行所有命令；命令均来自根或包 `package.json`，「派生」标注表示由已登记命令组合而来。首次使用先 `pnpm install`。

## 流程 1：需求开发（加字段 / 改校验 / 改折扣）

| 步骤 | 动作 | 读/改 | 命令 |
|---|---|---|---|
| 1. 定界 | 确认改动属于 catalog 而非 checkout | `packages/catalog/src/index.ts` | — |
| 2. 查证据 | 查「改什么去哪」与不变量 | [file-map](file-map.md)、[architecture](architecture.md) §5 | — |
| 3. 改实现 | 字段/校验改 `product-store.ts`；报价改 `pricing.ts` | 对应文件 | — |
| 4. 补测试 | 在 `packages/catalog/tests/product-store.test.ts` 加用例；报价改动补 `quote()` 断言 | 测试文件 | `pnpm test -- product-store` |
| 5. 影响面 | 触碰公开 API 时，确认下游 checkout 是否编译/断言失败 | `packages/checkout/src/order-service.ts` | `pnpm test`（全量） |
| 6. 提交前 | 类型检查 + 全量测试 | — | `pnpm lint` && `pnpm test` |

提交前自检清单：

- [ ] 新增/变更的符号已从 `packages/catalog/src/index.ts` 导出（若需外部使用），并核对下游 import。
- [ ] 金额相关改动有具体断言（元/分、取整方式写清预期值）。
- [ ] 失败路径（非法输入、重复 SKU、库存不足）有用例。
- [ ] `pnpm lint`、`pnpm test` 均通过；命令未在 `package.json` 之外新增。

## 流程 2：修 bug（报错 / 金额不对 / 库存异常）

| 步骤 | 动作 | 细节 |
|---|---|---|
| 1. 复现 | 先带着线索跑单测 | `pnpm test -- product-store`；错误为「金额差一分」时先看 [pitfalls](pitfalls.md) 取整条目 |
| 2. 分类 | 区分参数错误（`RangeError`）与领域错误（`CatalogError.code`） | 错误码含义见 [architecture](architecture.md) §6 |
| 3. 定位 | 按现象查表，找到最小改动点 | [pitfalls](pitfalls.md) 的「排查命令」列 + [file-map](file-map.md) |
| 4. 加回归 | 先写一条能复现原 bug 的失败用例，再修 | `packages/catalog/tests/product-store.test.ts` |
| 5. 验证 | 单测 → 全量 → 类型检查 | `pnpm test -- product-store` → `pnpm test` → `pnpm lint` |
| 6. 影响面 | 公开 API 行为变化时回归 checkout | `pnpm test -- order-service` |

修 bug 红线：

- 不要靠改断言让测试变绿；断言反映的是「期望行为」，行为变了要说明为什么。
- 不要吞掉 `CatalogError`：下游按 `code` 分支，改 `message` 安全、改 `code` 属契约变更。
- 库存相关 bug 先确认是 `reserve`（会扣减）还是 `get`（只读校验）—— 两者语义不同。

## 流程 3：答疑（这个模块怎么工作）

| 步骤 | 动作 | 输出 |
|---|---|---|
| 1. 判断意图 | 是「是什么/为什么」「改哪」还是「怎么跑」 | — |
| 2. 取证据 | 「怎么工作」→ [architecture](architecture.md)；「改哪」→ [file-map](file-map.md)；「怎么跑」→ [verification](verification.md) | 结论 + 相对路径/符号名 |
| 3. 划边界 | 问题属于 checkout/根配置时，指到对应位置，不硬答 | 归属文件 |
| 4. 标不确定 | 代码读不出的业务语义（折扣上限依据、持久化预期）记为待确认（格式见 architecture 第 8 节） | 待确认清单 |
| 5. 可选验证 | 需要证明行为时补跑单测 | `pnpm test -- product-store`（前置：`pnpm install`） |

答疑纪律：每条结论带路径或符号；不能给出「应该」「可能」式不带证据的断言。

## 提交前统一自检

1. `pnpm lint` → 无类型错误（根 `tsc -p tsconfig.json --noEmit`，覆盖 src 与 tests）。
2. `pnpm test` → 全部通过；新增行为有新用例。
3. 变更涉及 `packages/catalog/src/index.ts` → 回归 `pnpm test`（含 checkout 用例）。
4. 变更涉及命令或配置 → 同步更新 [verification](verification.md)；命令必须能在 `package.json` 找到出处。
