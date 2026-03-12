import { ThemeProvider } from './contexts/ThemeContext';
import { ChatProvider, useChat } from './contexts/ChatContext';
import { AuthProvider } from './contexts/AuthContext';
import { VoiceProvider } from './contexts/VoiceContext';
import Layout from './components/Layout/Layout';
import LoginOverlay from './components/Auth/LoginOverlay';

function AppInner() {
  const { selectConversation } = useChat();

  return (
    <VoiceProvider onSessionEnd={(convId) => selectConversation(convId)}>
      <Layout />
      <LoginOverlay />
    </VoiceProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ChatProvider>
          <AppInner />
        </ChatProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
