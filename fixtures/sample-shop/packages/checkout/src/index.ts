/**
 * @sample/checkout 的公开 API。
 *
 * 结算只消费 catalog 的公开 API（`@sample/catalog`），不直接读商品存储内部结构。
 */

export { Cart } from './cart';
export type { CartLine } from './cart';

export { DEFAULT_TAX_RATE, OrderService, resolveTaxRate } from './order-service';
export type { Order } from './order-service';
