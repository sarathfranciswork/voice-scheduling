import { useState, useEffect } from 'react';
import { useChat } from '../../contexts/ChatContext';
import Header from '../Header/Header';
import Sidebar from '../Sidebar/Sidebar';
import ChatArea from '../Chat/ChatArea';
import ChatInput from '../Input/ChatInput';

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { loadConversations } = useChat();

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  return (
    <div className="flex h-screen bg-white overflow-hidden">
      {/* Sidebar */}
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0">
        <Header
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          sidebarOpen={sidebarOpen}
        />

        <ChatArea />

        <ChatInput />
      </div>
    </div>
  );
}
