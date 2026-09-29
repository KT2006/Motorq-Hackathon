import { useState, useRef, useEffect } from 'react';
import { Bot, User, Send, Loader2, Sparkles, Terminal } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import api from '../api';

export default function AIAssistant() {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Hello! I am your AI Fleet Assistant. You can ask me to analyze the worst offenders, check a specific vehicle, or summarize your fleet costs.' }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userQuery = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userQuery }]);
    setIsLoading(true);

    try {
      const response = await api.post('/chat', {
        query: userQuery,
        from_date: new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10),
        to_date: new Date().toISOString().slice(0, 10)
      });

      const { answer, tool_calls } = response.data;
      
      setMessages(prev => [
        ...prev, 
        { 
          role: 'assistant', 
          content: answer, 
          tool_calls: tool_calls 
        }
      ]);
    } catch (err) {
      setMessages(prev => [...prev, { 
        role: 'system', 
        content: err.response?.data?.detail || 'Error connecting to the AI layer. Please make sure OPENAI_API_KEY is configured in the backend.' 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fade-in" style={{ height: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
      <header className="page-header">
        <h1>AI Fleet Assistant</h1>
        <p>Ask plain-English questions about your fleet data.</p>
      </header>

      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {messages.map((msg, idx) => (
            <div key={idx} style={{ 
              display: 'flex', 
              gap: '16px',
              flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
            }}>
              <div style={{
                width: '40px',
                height: '40px',
                borderRadius: '50%',
                background: msg.role === 'user' ? 'var(--accent)' : (msg.role === 'assistant' ? 'rgba(76, 175, 80, 0.1)' : 'rgba(255, 255, 255, 0.05)'),
                color: msg.role === 'user' ? '#fff' : (msg.role === 'assistant' ? '#4CAF50' : 'var(--text-secondary)'),
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0
              }}>
                {msg.role === 'user' ? <User size={20} /> : (msg.role === 'assistant' ? <Bot size={20} /> : <Sparkles size={20} />)}
              </div>
              
              <div style={{
                maxWidth: '85%',
                background: msg.role === 'user' ? 'var(--accent)' : 'rgba(255, 255, 255, 0.03)',
                padding: '16px',
                borderRadius: '16px',
                borderTopRightRadius: msg.role === 'user' ? '4px' : '16px',
                borderTopLeftRadius: msg.role === 'assistant' ? '4px' : '16px',
                border: msg.role === 'assistant' ? '1px solid rgba(255, 255, 255, 0.05)' : 'none',
                overflowX: 'auto'
              }}>
                <div className="markdown-body" style={{ color: 'inherit' }}>
                  {msg.role === 'user' ? (
                    <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>{msg.content}</div>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                  )}
                </div>
                
                {msg.tool_calls && msg.tool_calls.length > 0 && (
                  <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid rgba(255, 255, 255, 0.05)' }}>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Terminal size={12} />
                      Tools Executed ({msg.tool_calls.length})
                    </div>
                    {msg.tool_calls.map((tc, tcIdx) => (
                      <div key={tcIdx} style={{ fontSize: '12px', fontFamily: 'monospace', color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.2)', padding: '8px', borderRadius: '4px', marginBottom: '4px' }}>
                        &gt; {tc.name}({JSON.stringify(tc.args)})
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {isLoading && (
            <div style={{ display: 'flex', gap: '16px' }}>
              <div style={{
                width: '40px', height: '40px', borderRadius: '50%',
                background: 'rgba(76, 175, 80, 0.1)', color: '#4CAF50',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
              }}>
                <Bot size={20} />
              </div>
              <div style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)' }}>
                <Loader2 size={16} className="spin" /> Thinking...
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
        
        <div style={{ padding: '24px', borderTop: '1px solid var(--border)' }}>
          <form onSubmit={handleSubmit} style={{ position: 'relative' }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about your fleet... (e.g. 'Which vehicles should we investigate this week?')"
              disabled={isLoading}
              style={{
                width: '100%',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border)',
                borderRadius: '24px',
                padding: '16px 48px 16px 24px',
                color: 'var(--text-primary)',
                fontSize: '15px',
                outline: 'none',
                transition: 'border-color 0.2s ease'
              }}
              onFocus={(e) => e.target.style.borderColor = 'var(--accent)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
            />
            <button 
              type="submit" 
              disabled={isLoading || !input.trim()}
              style={{
                position: 'absolute',
                right: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'var(--accent)',
                color: 'white',
                border: 'none',
                width: '36px',
                height: '36px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: isLoading || !input.trim() ? 'not-allowed' : 'pointer',
                opacity: isLoading || !input.trim() ? 0.5 : 1
              }}
            >
              <Send size={16} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
