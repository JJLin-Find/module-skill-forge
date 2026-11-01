import type { Product } from '@sample/catalog';

export interface CartLine {
  product: Product;
  quantity: number;
}

/**
 * 购物车只负责「用户选了哪些商品、各几件」，不计算价格。
 * 金额一律交给 catalog 的 quote()，避免结算与目录两套折扣逻辑。
 */
export class Cart {
  private readonly linesById = new Map<string, CartLine>();

  add(product: Product, quantity = 1): void {
    if (!Number.isInteger(quantity) || quantity <= 0) {
      throw new RangeError(`quantity 必须是正整数: ${quantity}`);
    }
    const existing = this.linesById.get(product.id);
    this.linesById.set(product.id, {
      product,
      quantity: (existing?.quantity ?? 0) + quantity,
    });
  }

  remove(productId: string): void {
    this.linesById.delete(productId);
  }

  setQuantity(productId: string, quantity: number): void {
    if (!Number.isInteger(quantity) || quantity <= 0) {
      throw new RangeError(`quantity 必须是正整数: ${quantity}`);
    }
    const existing = this.linesById.get(productId);
    if (existing === undefined) {
      throw new RangeError(`购物车中没有商品: ${productId}`);
    }
    this.linesById.set(productId, { ...existing, quantity });
  }

  lines(): CartLine[] {
    return [...this.linesById.values()].map((line) => ({ ...line }));
  }

  totalQuantity(): number {
    return this.lines().reduce((sum, line) => sum + line.quantity, 0);
  }

  isEmpty(): boolean {
    return this.linesById.size === 0;
  }

  clear(): void {
    this.linesById.clear();
  }
}
