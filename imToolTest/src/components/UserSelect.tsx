import { useState } from 'react';

const PRESET_USERS = [
  { id: 'user-alice', name: 'Alice', avatar: 'A', desc: '商务出差，偏好四星含早' },
  { id: 'user-bob', name: 'Bob', avatar: 'B', desc: '家庭旅游，预算充足' },
  { id: 'user-charlie', name: 'Charlie', avatar: 'C', desc: '背包客，追求性价比' },
  { id: 'user-diana', name: 'Diana', avatar: 'D', desc: '高端客户，五星全膳' },
];

interface Props {
  onSelect: (userId: string, userName: string) => void;
}

export default function UserSelect({ onSelect }: Props) {
  const [customId, setCustomId] = useState('');

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="w-full max-w-md px-6">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 rounded-2xl bg-blue-500 flex items-center justify-center text-white font-bold text-2xl mx-auto mb-4 shadow-lg">
            J
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Juniper 酒店助手</h1>
          <p className="text-sm text-gray-500 mt-2">选择用户身份进入测试</p>
        </div>

        {/* Preset Users */}
        <div className="space-y-3 mb-6">
          {PRESET_USERS.map((user) => (
            <button
              key={user.id}
              onClick={() => onSelect(user.id, user.name)}
              className="w-full flex items-center gap-4 p-4 bg-white rounded-xl border border-gray-200 hover:border-blue-400 hover:shadow-md transition-all text-left"
            >
              <div className="w-12 h-12 rounded-full bg-blue-500 flex items-center justify-center text-white font-bold text-lg flex-shrink-0">
                {user.avatar}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-gray-900">{user.name}</div>
                <div className="text-xs text-gray-500 truncate">{user.desc}</div>
                <div className="text-xs text-gray-400 font-mono mt-0.5">OpenID: {user.id}</div>
              </div>
              <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-gray-300" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
              </svg>
            </button>
          ))}
        </div>

        {/* Divider */}
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1 h-px bg-gray-200" />
          <span className="text-xs text-gray-400">或输入自定义 OpenID</span>
          <div className="flex-1 h-px bg-gray-200" />
        </div>

        {/* Custom Input */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const id = customId.trim();
            if (id) onSelect(id, id);
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            value={customId}
            onChange={(e) => setCustomId(e.target.value)}
            placeholder="输入 OpenID..."
            className="flex-1 px-4 py-3 bg-white border border-gray-200 rounded-xl text-sm outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            type="submit"
            disabled={!customId.trim()}
            className="px-6 py-3 bg-blue-500 text-white rounded-xl text-sm font-medium hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            进入
          </button>
        </form>
      </div>
    </div>
  );
}
