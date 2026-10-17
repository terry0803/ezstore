import axios from 'axios';

// 後端錯誤回 { error: { code, message } }。有訊息就顯示後端給的，不要只顯示 axios 的「Request failed with status code 400」。
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const message = (error.response?.data as { error?: { message?: string } } | undefined)?.error?.message;
    if (message) return message;
    if (!error.response) return '連不到後端服務，請稍後再試';
    return `後端回應 ${error.response.status}`;
  }
  return error instanceof Error ? error.message : String(error);
}
