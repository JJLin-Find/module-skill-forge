/**
 * 商品目录的领域模型与内存存储。
 *
 * 这里是商品数据的唯一真相源：其他模块只能通过本文件的公开类/函数读写，
 * 不允许绕过 ProductStore 直接改内部 Map。
 */

export type Currency = 'CNY' | 'USD';

export interface Product {
  id: string;
  sku: string;
  name: string;
  /** 单价，整数分。全项目金额统一用「分」表示，展示层再换算。 */
  priceCents: number;
  currency: Currency;
  stock: number;
  tags: string[];
  archived: boolean;
}

export interface ProductInput {
  sku: string;
  name: string;
  priceCents: number;
  currency?: Currency;
  stock?: number;
  tags?: string[];
}

export type CatalogErrorCode =
  | 'INVALID_PRODUCT'
  | 'DUPLICATE_SKU'
  | 'NOT_FOUND'
  | 'OUT_OF_STOCK'
  | 'ARCHIVED';

export class CatalogError extends Error {
  readonly code: CatalogErrorCode;

  constructor(code: CatalogErrorCode, message: string) {
    super(message);
    this.name = 'CatalogError';
    this.code = code;
  }
}

/** SKU 约定：2-4 位大写字母 + 连字符 + 4-8 位数字，例如 `ELEC-1024`。 */
const SKU_PATTERN = /^[A-Z]{2,4}-\d{4,8}$/;

/** 单价上限 10 万元，挡住把「元」当成「分」录入的脏数据。 */
const MAX_PRICE_CENTS = 10_000_000;

export function validateProductInput(input: ProductInput): void {
  if (!SKU_PATTERN.test(input.sku)) {
    throw new CatalogError('INVALID_PRODUCT', `sku 格式不合法: ${input.sku}`);
  }
  if (input.name.trim().length === 0) {
    throw new CatalogError('INVALID_PRODUCT', '商品名不能为空');
  }
  if (
    !Number.isInteger(input.priceCents) ||
    input.priceCents <= 0 ||
    input.priceCents > MAX_PRICE_CENTS
  ) {
    throw new CatalogError(
      'INVALID_PRODUCT',
      `priceCents 必须是 (0, ${MAX_PRICE_CENTS}] 范围内的整数分`,
    );
  }
  if (input.stock !== undefined && (!Number.isInteger(input.stock) || input.stock < 0)) {
    throw new CatalogError('INVALID_PRODUCT', 'stock 必须是非负整数');
  }
}

export class ProductStore {
  private readonly byId = new Map<string, Product>();
  private readonly idBySku = new Map<string, string>();
  private sequence = 0;

  add(input: ProductInput): Product {
    validateProductInput(input);
    if (this.idBySku.has(input.sku)) {
      throw new CatalogError('DUPLICATE_SKU', `sku 已存在: ${input.sku}`);
    }

    const product: Product = {
      id: `prd_${String((this.sequence += 1)).padStart(4, '0')}`,
      sku: input.sku,
      name: input.name.trim(),
      priceCents: input.priceCents,
      currency: input.currency ?? 'CNY',
      stock: input.stock ?? 0,
      tags: [...(input.tags ?? [])],
      archived: false,
    };

    this.byId.set(product.id, product);
    this.idBySku.set(product.sku, product.id);
    return cloneProduct(product);
  }

  get(id: string): Product {
    const found = this.byId.get(id);
    if (found === undefined) {
      throw new CatalogError('NOT_FOUND', `商品不存在: ${id}`);
    }
    return cloneProduct(found);
  }

  getBySku(sku: string): Product {
    const id = this.idBySku.get(sku);
    if (id === undefined) {
      throw new CatalogError('NOT_FOUND', `商品不存在: sku=${sku}`);
    }
    return this.get(id);
  }

  // TODO(pagination): list() 一次性返回全部商品。SKU 超过约 5k 后目录页明显变慢，
  // 且无法按 tags/archived 过滤；需要补 cursor 分页（当前调用方都是小数据量）。
  list(): Product[] {
    return [...this.byId.values()].map(cloneProduct);
  }

  /** 预占库存：成功返回扣减后的商品快照。 */
  reserve(id: string, quantity: number): Product {
    if (!Number.isInteger(quantity) || quantity <= 0) {
      throw new CatalogError('INVALID_PRODUCT', `reserve 数量必须是正整数: ${quantity}`);
    }
    const stored = this.byId.get(id);
    if (stored === undefined) {
      throw new CatalogError('NOT_FOUND', `商品不存在: ${id}`);
    }
    if (stored.archived) {
      throw new CatalogError('ARCHIVED', `商品已下架: ${stored.sku}`);
    }
    if (stored.stock < quantity) {
      throw new CatalogError(
        'OUT_OF_STOCK',
        `库存不足: ${stored.sku} 需要 ${quantity}，剩余 ${stored.stock}`,
      );
    }
    stored.stock -= quantity;
    return cloneProduct(stored);
  }

  updateStock(id: string, delta: number): Product {
    if (!Number.isInteger(delta)) {
      throw new CatalogError('INVALID_PRODUCT', `stock delta 必须是整数: ${delta}`);
    }
    const stored = this.byId.get(id);
    if (stored === undefined) {
      throw new CatalogError('NOT_FOUND', `商品不存在: ${id}`);
    }
    if (stored.stock + delta < 0) {
      throw new CatalogError('INVALID_PRODUCT', '库存不能为负');
    }
    stored.stock += delta;
    return cloneProduct(stored);
  }

  archive(id: string): Product {
    const stored = this.byId.get(id);
    if (stored === undefined) {
      throw new CatalogError('NOT_FOUND', `商品不存在: ${id}`);
    }
    stored.archived = true;
    return cloneProduct(stored);
  }
}

function cloneProduct(product: Product): Product {
  return { ...product, tags: [...product.tags] };
}
