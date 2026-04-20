import { useState, useCallback } from 'react';
import { setUserId } from './api/client';
import UserSelect from './components/UserSelect';
import ChatWindow from './components/ChatWindow';

export default function App() {
  const [user, setUser] = useState<{ id: string; name: string } | null>(null);

  const handleSelect = useCallback((userId: string, userName: string) => {
    setUserId(userId);
    setUser({ id: userId, name: userName });
  }, []);

  const handleSwitchUser = useCallback(() => {
    setUser(null);
  }, []);

  if (!user) {
    return <UserSelect onSelect={handleSelect} />;
  }

  return (
    <ChatWindow
      key={user.id}
      userId={user.id}
      userName={user.name}
      onSwitchUser={handleSwitchUser}
    />
  );
}
