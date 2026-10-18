import { useEffect, useState } from 'react';

// Background refreshes may hydrate a pristine form, but never replace a draft.
// A changed server snapshot must be acknowledged before saving that draft.
export function useFormRefreshGuard<T>(
  id: string | undefined, data: T | undefined, dirty: boolean, apply: (value: T) => void,
) {
  const [baseline, setBaseline] = useState<{ id: string | undefined; value: string }>();
  const value = JSON.stringify(data);
  const changed = !!data && (baseline?.id !== id || baseline?.value !== value);
  const conflict = !!baseline && baseline.id === id && changed && dirty;

  useEffect(() => {
    if (data && changed && !conflict) {
      apply(data);
      setBaseline({ id, value });
    }
  }, [id, data, value, changed, conflict, apply]);

  const reload = () => {
    if (!data) return;
    apply(data);
    setBaseline({ id, value });
  };
  return { conflict, reload };
}

export default function FormRefreshGuard({ conflict, reload }: { conflict: boolean; reload: () => void }) {
  if (!conflict) return null;
  return <div role="alert" className="mb-4 p-3 bg-amber-50 text-amber-900 border rounded">
    伺服器資料已變更，您的未儲存編輯已保留。為避免覆蓋新版資料，請先複製需要保留的內容，再重新載入並編輯。
    <button type="button" className="ml-2 underline" onClick={reload}>捨棄未儲存編輯並載入新版</button>
  </div>;
}
