import { useChat } from '../../contexts/ChatContext';
import ConversationItem from './ConversationItem';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { conversations, activeConversationId, createConversation, selectConversation, deleteConversation } = useChat();

  const handleNew = async () => {
    await createConversation();
    onClose();
  };

  const handleSelect = async (id: string) => {
    await selectConversation(id);
    onClose();
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-20 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`
          fixed lg:relative z-30 top-0 left-0 h-full w-72 bg-white border-r border-cvs-border
          flex flex-col transition-transform duration-200 ease-in-out
          ${isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* New chat button */}
        <div className="p-3 border-b border-cvs-border">
          <button
            onClick={handleNew}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
                       bg-cvs-primary text-white font-medium text-sm
                       hover:bg-cvs-primary-hover transition-colors shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Conversation
          </button>
        </div>

        {/* Conversation list */}
        <div className="flex-1 overflow-y-auto scrollbar-thin py-2">
          {conversations.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-sm text-cvs-text-tertiary">No conversations yet</p>
              <p className="text-xs text-cvs-text-tertiary mt-1">
                Start a new conversation to schedule your vaccine appointment
              </p>
            </div>
          ) : (
            conversations.map((conv) => (
              <ConversationItem
                key={conv.id}
                conversation={conv}
                isActive={conv.id === activeConversationId}
                onSelect={() => handleSelect(conv.id)}
                onDelete={() => deleteConversation(conv.id)}
              />
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-cvs-border">
          <p className="text-[10px] text-cvs-text-tertiary text-center">
            Powered by CVS Health AI
          </p>
        </div>
      </aside>
    </>
  );
}
