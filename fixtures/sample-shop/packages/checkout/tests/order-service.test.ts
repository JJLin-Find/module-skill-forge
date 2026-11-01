import { beforeEach, describe, expect, it } from 'vitest';

import { CatalogError, ProductStore } from '@sample/catalog';

import { Cart } from '../src/cart';
import { DEFAULT_TAX_RATE, OrderService, resolveTaxRate } from '../src/order-service';

function createStore(): ProductStore {
  const store = new ProductStore();
  store.add({
    sku: 'ELEC-1024',
    name: '机械键盘',
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

const fixedNow = (): Date => new Date('2024-05-01T10:00:00.000Z');

describe('resolveTaxRate()', () => {
  it('未配置时使用默认税率', () => {
    expect(resolveTaxRate(undefined)).toBe(DEFAULT_TAX_RATE);
  });

  it('读取 SAMPLE_SHOP_TAX_RATE', () => {
    expect(resolveTaxRate('0.06')).toBe(0.06);
  });

  it('非法值回退默认税率（已知缺口）', () => {
    expect(resolveTaxRate('8%')).toBe(DEFAULT_TAX_RATE);
  });
});

describe('OrderService.createOrder()', () => {
  let store: ProductStore;

  beforeEach(() => {
    store = createStore();
  });

  it('按 catalog 报价 + 税率计算订单总额', () => {
    const cart = new Cart();
    cart.add(store.get('prd_0001'), 10);

    const order = new OrderService(store, {}, fixedNow).createOrder(cart);

    expect(order.subtotalCents).toBe(19990);
    expect(order.discountCents).toBe(1000);
    expect(order.taxRate).toBe(DEFAULT_TAX_RATE);
    expect(order.taxCents).toBe(1519);
    expect(order.totalCents).toBe(20509);
    expect(order.createdAt).toBe('2024-05-01T10:00:00.000Z');
  });

  it('购物车为空时拒绝下单', () => {
    const service = new OrderService(store, {}, fixedNow);
    expect(() => service.createOrder(new Cart())).toThrowError(RangeError);
  });

  it('数量超过库存时抛 OUT_OF_STOCK', () => {
    const cart = new Cart();
    cart.add(store.get('prd_0002'), 4);

    const service = new OrderService(store, {}, fixedNow);
    try {
      service.createOrder(cart);
    } catch (error) {
      expect(error).toBeInstanceOf(CatalogError);
      expect((error as CatalogError).code).toBe('OUT_OF_STOCK');
      return;
    }
    throw new Error('期望抛出 OUT_OF_STOCK，但下单成功');
  });
});
