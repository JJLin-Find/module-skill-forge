import { describe, expect, it } from 'vitest';

import {
  CatalogError,
  ProductStore,
  quote,
  validateProductInput,
} from '../src/index';

function seedStore(): ProductStore {
  const store = new ProductStore();
  store.add({
    sku: 'ELEC-1024',
    name: ' 机械键盘 ',
    priceCents: 1999,
    stock: 12,
    tags: ['hot'],
  });
  store.add({
    sku: 'HOME-2048',
    name: '香薰蜡烛',
    priceCents: 500,
    stock: 3,
    tags: ['clearance'],
  });
  return store;
}

function expectCatalogError(fn: () => unknown, code: string): void {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(CatalogError);
    expect((error as CatalogError).code).toBe(code);
    return;
  }
  throw new Error('期望抛出 CatalogError，但调用没有抛错');
}

describe('ProductStore', () => {
  it('add() 归一化字段并生成递增 id', () => {
    const store = seedStore();
    const first = store.get('prd_0001');
    const second = store.getBySku('HOME-2048');

    expect(first.id).toBe('prd_0001');
    expect(first.name).toBe('机械键盘');
    expect(first.currency).toBe('CNY');
    expect(first.archived).toBe(false);
    expect(second.id).toBe('prd_0002');
  });

  it('重复 sku 抛 DUPLICATE_SKU', () => {
    const store = seedStore();
    expectCatalogError(
      () => store.add({ sku: 'ELEC-1024', name: '重复商品', priceCents: 100 }),
      'DUPLICATE_SKU',
    );
  });

  it('get() 返回副本，修改返回值不影响存储', () => {
    const store = seedStore();
    const snapshot = store.get('prd_0001');
    snapshot.tags.push('被外部改坏');
    snapshot.priceCents = 1;

    const fresh = store.get('prd_0001');
    expect(fresh.tags).toEqual(['hot']);
    expect(fresh.priceCents).toBe(1999);
  });

  it('list() 返回全部商品', () => {
    const store = seedStore();
    expect(store.list().map((product) => product.sku)).toEqual([
      'ELEC-1024',
      'HOME-2048',
    ]);
  });

  it('reserve() 扣减库存，库存不足抛 OUT_OF_STOCK', () => {
    const store = seedStore();
    expect(store.reserve('prd_0001', 2).stock).toBe(10);
    expectCatalogError(() => store.reserve('prd_0001', 99), 'OUT_OF_STOCK');
  });

  it('归档后不能再预占', () => {
    const store = seedStore();
    store.archive('prd_0002');
    expectCatalogError(() => store.reserve('prd_0002', 1), 'ARCHIVED');
  });

  it('updateStock() 不允许把库存改成负数', () => {
    const store = seedStore();
    expectCatalogError(() => store.updateStock('prd_0002', -10), 'INVALID_PRODUCT');
  });
});

describe('quote()', () => {
  it('满 10 件应用 95 折', () => {
    const store = seedStore();
    const result = quote([{ product: store.get('prd_0001'), quantity: 10 }]);

    expect(result.subtotalCents).toBe(19990);
    expect(result.discountCents).toBe(1000);
    expect(result.totalCents).toBe(18990);
    expect(result.appliedRules).toContain('volume_10');
  });

  it('清仓商品叠加 10% 折扣', () => {
    const store = seedStore();
    const result = quote([{ product: store.get('prd_0002'), quantity: 2 }]);

    expect(result.lines[0].subtotalCents).toBe(1000);
    expect(result.discountCents).toBe(100);
    expect(result.totalCents).toBe(900);
    expect(result.appliedRules).toContain('clearance');
  });

  it('数量非正整数时抛 RangeError', () => {
    const store = seedStore();
    expect(() => quote([{ product: store.get('prd_0001'), quantity: 0 }])).toThrowError(
      RangeError,
    );
  });
});

describe('validateProductInput()', () => {
  it('拒绝非法 sku', () => {
    expectCatalogError(
      () => validateProductInput({ sku: 'bad-sku', name: 'x', priceCents: 100 }),
      'INVALID_PRODUCT',
    );
  });

  it('拒绝空名称', () => {
    expectCatalogError(
      () => validateProductInput({ sku: 'ELEC-1024', name: '   ', priceCents: 100 }),
      'INVALID_PRODUCT',
    );
  });
});
