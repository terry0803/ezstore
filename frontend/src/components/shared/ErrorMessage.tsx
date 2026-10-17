import { apiErrorMessage } from '../../api/errors';

interface ErrorMessageProps {
  error: unknown;
  action: string;
}

export default function ErrorMessage({ error, action }: ErrorMessageProps) {
  if (!error) return null;
  return (
    <div role="alert" className="mb-4 px-4 py-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm">
      {action}失敗：{apiErrorMessage(error)}
    </div>
  );
}
