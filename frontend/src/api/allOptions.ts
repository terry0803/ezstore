import type { PaginatedResponse } from '../types';

export async function allOptions<T extends { id: number }>(list: (page: number, size: number) => Promise<PaginatedResponse<T>>): Promise<T[]> {
  const rows = new Map<number, T>();
  for (let page = 1; ; page++) {
    const result = await list(page, 100);
    const before = rows.size;
    result.data.forEach(row => rows.set(row.id, row));
    if (rows.size >= result.total) return [...rows.values()];
    if (rows.size === before) throw new Error('清單未完整載入，請重新整理');
  }
}

