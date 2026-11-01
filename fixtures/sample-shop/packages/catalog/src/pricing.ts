import type { Product } from './product-store';

export interface QuoteRequestLine {
  product: Product;
  quantity: number;
}

export interface QuoteLine {
  productId: string;
  sku: string;
  quantity: number;
  unitPriceCents: number;
  subtotalCents: number;
  discountCents: number;
}

export interface Quote {
  lines: QuoteLine[];
  subtotalCents: number;
  discountCents: number;
  totalCents: number;
  appliedRules: string[];
}

/** 单行满 10 件打 95 折。 */
export const VOLUME_DISCOUNT_THRESHOLD = 10;
export const VOLUME_DISCOUNT_RATE = 0.05;

/** 带 `clearance` 标签的清仓商品再打 9 折。 */
export const CLEARANCE_DISCOUNT_RATE = 0.1;

/** 单行折扣上限 20%，防止折扣叠加出负价。 */
export const MAX_LINE_DISCOUNT_RATE = 0.2;

function assertQuantity(quantity: number): void {
  if (!Number.isInteger(quantity) || quantity <= 0) {
    throw new RangeError(`quantity 必须是正整数: ${quantity}`);
  }
}

/** 计算单个报价行的折扣率；按行叠加，封顶后返回。 */
export function lineDiscountRate(product: Product, quantity: number): number {
  assertQuantity(quantity);

  let rate = 0;
  if (quantity >= VOLUME_DISCOUNT_THRESHOLD) {
    rate += VOLUME_DISCOUNT_RATE;
  }
  if (product.tags.includes('clearance')) {
    rate += CLEARANCE_DISCOUNT_RATE;
  }
  return Math.min(rate, MAX_LINE_DISCOUNT_RATE);
}

/**
 * 报价：纯函数，不读环境变量、不碰存储。
 * 输入是「商品快照 + 数量」，输出逐行小计/折扣与订单合计，便于下单前预览。
 */
export function quote(request: QuoteRequestLine[]): Quote {
  const lines: QuoteLine[] = request.map(({ product, quantity }) => {
    assertQuantity(quantity);

    const lineSubtotalCents = product.priceCents * quantity;
    const rate = lineDiscountRate(product, quantity);

    return {
      productId: product.id,
      sku: product.sku,
      quantity,
      unitPriceCents: product.priceCents,
      subtotalCents: lineSubtotalCents,
      discountCents: Math.round(lineSubtotalCents * rate),
    };
  });

  const subtotalCents = lines.reduce((sum, line) => sum + line.subtotalCents, 0);
  const discountCents = lines.reduce((sum, line) => sum + line.discountCents, 0);

  return {
    lines,
    subtotalCents,
    discountCents,
    totalCents: subtotalCents - discountCents,
    appliedRules: collectAppliedRules(request),
  };
}

function collectAppliedRules(request: QuoteRequestLine[]): string[] {
  const rules = new Set<string>();
  for (const { product, quantity } of request) {
    if (quantity >= VOLUME_DISCOUNT_THRESHOLD) rules.add('volume_10');
    if (product.tags.includes('clearance')) rules.add('clearance');
  }
  return [...rules];
}
