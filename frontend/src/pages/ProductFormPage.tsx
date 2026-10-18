import { useCallback } from 'react';
import FormRefreshGuard, { useFormRefreshGuard } from '../components/shared/FormRefreshGuard';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { productApi } from '../api/productApi';
import ErrorMessage, { apiErrorMessage } from '../components/shared/ErrorMessage';

interface FormData {
  product_number: string;
  name: string;
  description: string;
  cost: number;
  list_price: number;
  inventory: number;
  supplier: string;
}

export default function ProductFormPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isEdit = !!id;

  const { register, handleSubmit, reset, formState: { errors, isDirty } } = useForm<FormData>({
    defaultValues: { inventory: 0 },
  });

  const { data: product, error: loadError, isPending, refetch, isFetching } = useQuery({
    queryKey: ['product', id],
    queryFn: () => productApi.get(Number(id)),
    enabled: isEdit,
  });

  const applyRecord = useCallback((value: NonNullable<typeof product>) => {
    reset({ ...value, cost: Number(value.cost), list_price: Number(value.list_price) });
  }, [reset]);
  const refresh = useFormRefreshGuard(id, product, isDirty, applyRecord);

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      isEdit ? productApi.update(Number(id), data as never) : productApi.create(data as never),
    onSuccess: (saved) => {
      // 編輯頁和詳情頁用 ['product', id] 快取 30 秒；先換成剛存好的資料，馬上重開才不會看到舊值、存回舊值
      queryClient.setQueryData(['product', String(saved.id)], saved);
      queryClient.invalidateQueries({ queryKey: ['products'] });
      navigate('/products');
    },
  });

  // Do not expose an editable empty form when the record could not be read.
  if (isEdit && (isPending || !product)) {
    return <div>
      <h2 className="text-2xl font-bold mb-6">編輯產品</h2>
      <ErrorMessage error={loadError} action="讀取產品" />
      {!loadError && <p>載入中...</p>}
      {loadError && <button onClick={() => void refetch()} disabled={isFetching} className="text-blue-600 mr-4">重新載入資料</button>}
      <button onClick={() => navigate('/products')}>返回列表</button>
    </div>;
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-bold mb-6">{isEdit ? '編輯產品' : '新增產品'}</h2>

      <ErrorMessage error={loadError} action="重新讀取資料" />
      {loadError && <button type="button" onClick={() => void refetch()} disabled={isFetching} className="text-blue-600 mb-4">重新載入資料</button>}
      <FormRefreshGuard {...refresh} />
      <form onSubmit={handleSubmit(data => { if (!refresh.conflict && !loadError) mutation.mutate(data); })} className="space-y-4 bg-white p-6 rounded-lg shadow">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">產品編號 *</label>
            <input {...register('product_number', { required: '請輸入產品編號' })} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {errors.product_number && <p className="text-red-500 text-sm mt-1">{errors.product_number.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">產品名稱 *</label>
            <input {...register('name', { required: '請輸入產品名稱' })} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name.message}</p>}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">描述</label>
          <textarea {...register('description')} rows={3} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">成本 *</label>
            <input type="number" step="0.01" min={0} {...register('cost', { required: '請輸入成本', valueAsNumber: true })} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {errors.cost && <p className="text-red-500 text-sm mt-1">{errors.cost.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">牌價 *</label>
            <input type="number" step="0.01" min={0} {...register('list_price', { required: '請輸入牌價', valueAsNumber: true })} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {errors.list_price && <p className="text-red-500 text-sm mt-1">{errors.list_price.message}</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">庫存</label>
            <input type="number" min={0} {...register('inventory', { valueAsNumber: true })} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">供應商</label>
          <input {...register('supplier')} className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {mutation.error && (
          <p className="text-red-500 text-sm">{apiErrorMessage(mutation.error)}</p>
        )}

        <div className="flex gap-2 pt-4">
          <button type="submit" disabled={mutation.isPending || refresh.conflict || !!loadError} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {mutation.isPending ? '儲存中...' : '儲存'}
          </button>
          <button type="button" onClick={() => navigate('/products')} className="px-4 py-2 border rounded-lg hover:bg-gray-50">
            取消
          </button>
        </div>
      </form>
    </div>
  );
}
