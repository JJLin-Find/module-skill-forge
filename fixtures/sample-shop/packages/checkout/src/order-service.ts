import { CatalogError, ProductStore, quote, type QuoteLine } from '@sample/catalog';

import { Cart } from './cart';

/** 未配置时的兜底税率。 */
export const DEFAULT_TAX_RATE = 0.08;

/**
 * 解析税率。入参默认取环境变量 `SAMPLE_SHOP_TAX_RATE`（小数形式，`0.08` = 8%），
 * 便于测试直接注入字符串而不污染真实环境。
 */
export function resolveTaxRate(
  raw: string | undefined = process.env.SAMPLE_SHOP_TAX_RATE,
): number {
  if (raw === undefined || raw.trim() === '') {
    return DEFAULT_TAX_RATE;
  }

  const parsed = Number(raw);
  // FIXME: 配置非法（"8%"、负数、>1）时静默回退默认税率，日志里区分不出
  // 「没配」和「配错了」。应在启动期校验并直接抛错，避免按错误税率出单。
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
    return DEFAULT_TAX_RATE;
  }
  return parsed;
}

export interface Order {
  id: string;
  createdAt: string;
  lines: QuoteLine[];
  subtotalCents: number;
  discountCents: number;
  taxRate: number;
  taxCents: number;
  totalCents: number;
}

export class OrderService {
  constructor(
    private readonly store: ProductStore,
    private readonly env: NodeJS.ProcessEnv = process.env,
    private readonly now: () => Date = () => new Date(),
  ) {}

  createOrder(cart: Cart): Order {
    if (cart.isEmpty()) {
      throw new RangeError('购物车为空，无法创建订单');
    }
    this.assertPurchasable(cart);

    const priced = quote(cart.lines());
    const taxRate = resolveTaxRate(this.env.SAMPLE_SHOP_TAX_RATE);
    const taxableCents = priced.subtotalCents - priced.discountCents;
    const taxCents = Math.round(taxableCents * taxRate);
    const createdAt = this.now();

    return {
      id: `ord_${createdAt.getTime().toString(36)}`,
      createdAt: createdAt.toISOString(),
      lines: priced.lines,
      subtotalCents: priced.subtotalCents,
      discountCents: priced.discountCents,
      taxRate,
      taxCents,
      totalCents: taxableCents + taxCents,
    };
  }

  /**
   * 下单前校验：商品必须仍存在、未下架、库存够。
   * 注意这里只校验不扣库存 —— 扣减由履约流程通过 catalog 的 reserve() 完成。
   */
  private assertPurchasable(cart: Cart): void {
    for (const line of cart.lines()) {
      const current = this.store.get(line.product.id);
      if (current.archived) {
        throw new CatalogError('ARCHIVED', `商品已下架: ${current.sku}`);
      }
      if (current.stock < line.quantity) {
        throw new CatalogError(
          'OUT_OF_STOCK',
          `库存不足: ${current.sku} 需要 ${line.quantity}，剩余 ${current.stock}`,
        );
      }
    }
  }
}
