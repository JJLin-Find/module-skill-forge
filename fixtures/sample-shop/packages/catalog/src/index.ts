/**
 * @sample/catalog 的公开 API。
 *
 * 包外代码只能从这里 import：不允许深路径访问 `src/product-store` 等内部模块，
 * 这样内部拆分（存储、定价）变化时不会波及其他 workspace 包。
 */

export { CatalogError, ProductStore, validateProductInput } from './product-store';
export type { CatalogErrorCode, Currency, Product, ProductInput } from './product-store';

export { CLEARANCE_DISCOUNT_RATE, MAX_LINE_DISCOUNT_RATE, VOLUME_DISCOUNT_RATE, VOLUME_DISCOUNT_THRESHOLD, lineDiscountRate, quote } from './pricing';
export type { Quote, QuoteLine, QuoteRequestLine } from './pricing';
