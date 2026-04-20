import { useState, useCallback } from 'react';
import type { Message } from '../types';
import { sendMessage, resetConversation } from '../api/client';
import MessageList from './MessageList';
import InputBar from './InputBar';

const WELCOME_MSG: Message = {
  id: 'welcome',
  role: 'assistant',
  content:
    '您好！我是 Juniper 酒店预定助手。\n\n' +
    '您可以告诉我想去哪里、什么时候入住，我来帮您找到合适的酒店。\n\n' +
    '试试说：**"帮我找巴塞罗那的酒店"**',
  contentType: 'text',
  timestamp: new Date(),
};

interface Props {
  userId: string;
  userName: string;
  onSwitchUser: () => void;
}

export default function ChatWindow({ userId, userName, onSwitchUser }: Props) {
  const [messages, setMessages] = useState<Message[]>([WELCOME_MSG]);
  const [isTyping, setIsTyping] = useState(false);

  const handleSend = useCallback(async (text: string) => {
    const userMsg: Message = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      contentType: 'text',
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    try {
      const resp = await sendMessage(text);

      const assistantMsg: Message = {
        id: `assistant_${Date.now()}`,
        role: 'assistant',
        content: resp.text,
        contentType: 'text',
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: Message = {
        id: `error_${Date.now()}`,
        role: 'assistant',
        content: `连接后端失败：${err instanceof Error ? err.message : '未知错误'}\n\n请确认后端服务已启动 (uvicorn juniper_ai.app.main:app --port 8000)`,
        contentType: 'text',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  }, []);

  const handleSelectHotel = useCallback((index: number) => {
    handleSend(String(index));
  }, [handleSend]);

  const handleReset = useCallback(() => {
    resetConversation();
    setMessages([WELCOME_MSG]);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-blue-500 flex items-center justify-center text-white font-bold text-lg">
            J
          </div>
          <div className="text-left">
            <h1 className="text-base font-semibold text-gray-900">Juniper 酒店助手</h1>
            <p className="text-xs text-green-500">在线</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Current user badge */}
          <div className="flex items-center gap-1.5 px-3 py-1 bg-blue-50 rounded-full">
            <div className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs font-bold">
              {userName[0].toUpperCase()}
            </div>
            <span className="text-xs text-blue-700 font-medium max-w-[80px] truncate">{userName}</span>
          </div>
          <button
            onClick={onSwitchUser}
            className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded-full border border-gray-200 hover:border-gray-300 transition-colors"
            title="切换用户"
          >
            切换
          </button>
          <button
            onClick={handleReset}
            className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1 rounded-full border border-gray-200 hover:border-gray-300 transition-colors"
          >
            新对话
          </button>
        </div>
      </div>

      {/* Messages */}
      <MessageList
        messages={messages}
        isTyping={isTyping}
        onSelectHotel={handleSelectHotel}
      />

      {/* Input */}
      <InputBar onSend={handleSend} disabled={isTyping} />
    </div>
  );
}
