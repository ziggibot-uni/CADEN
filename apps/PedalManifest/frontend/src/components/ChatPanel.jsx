import React, { useState, useRef, useEffect } from 'react';
import { sendChat } from '../utils/api';

export default function ChatPanel({ onDesignUpdate }) {
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Welcome to PedalForge. Describe the pedal you want to build.' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEnd = useRef(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setInput('');
    setLoading(true);

    try {
      const data = await sendChat(text);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.response || data.message || JSON.stringify(data) },
      ]);
      if (data.circuit || data.simulation || data.pots) {
        onDesignUpdate?.({
          circuit: data.circuit,
          plan: data.plan,
          simulation: data.simulation,
          pots: data.pots,
          frequency_response: data.simulation?.frequency_response || [],
        });
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {loading && <div className="chat-loading">Thinking...</div>}
        <div ref={messagesEnd} />
      </div>
      <div className="chat-input-area">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe your pedal circuit..."
          rows={2}
        />
        <button className="btn-send" onClick={handleSend} disabled={loading || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}
