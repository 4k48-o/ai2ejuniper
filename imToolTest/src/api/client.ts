const API_BASE = '/api/v1';
const API_KEY = 'test-api-key-1';

let currentUserId: string | null = null;
let conversationId: string | null = null;

interface ConversationResponse {
  id: string;
  status: string;
}

interface MessageResponse {
  text: string;
  data: Record<string, unknown> | null;
  status: string;
}

export function setUserId(userId: string): void {
  if (currentUserId !== userId) {
    currentUserId = userId;
    conversationId = null; // new user → new conversation
  }
}

export function getUserId(): string | null {
  return currentUserId;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if (!currentUserId) throw new Error('User not selected');

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
      'X-External-User-Id': currentUserId,
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }

  return res.json();
}

export async function ensureConversation(): Promise<string> {
  if (conversationId) return conversationId;

  const resp = await request<ConversationResponse>('/conversations', {
    method: 'POST',
    body: JSON.stringify({ external_user_id: currentUserId }),
  });

  conversationId = resp.id;
  return conversationId;
}

export async function sendMessage(content: string): Promise<MessageResponse> {
  const convId = await ensureConversation();
  return request<MessageResponse>(`/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export function resetConversation(): void {
  conversationId = null;
}
