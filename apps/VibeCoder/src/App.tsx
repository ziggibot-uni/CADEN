import React, { useState, useEffect, useRef, useCallback } from 'react'

interface Message {
  role: 'user' | 'agent' | 'system'
  content: string
  timestamp: number
}

interface Stats {
  episodes: number
  lessons: number
  model: string
  workspace: string
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [stats, setStats] = useState<Stats>({ episodes: 0, lessons: 0, model: '...', workspace: '' })
  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(scrollToBottom, [messages])

  const connect = useCallback(() => {
    const ws = new WebSocket('ws://localhost:5180')

    ws.onopen = () => {
      setConnected(true)
      setMessages(prev => [...prev, {
        role: 'system', content: 'Connected to VibeCoder backend.', timestamp: Date.now()
      }])
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'done':
            setThinking(false)
            setMessages(prev => [...prev, {
              role: 'agent', content: msg.content, timestamp: Date.now()
            }])
            break
          case 'status':
            setThinking(true)
            setMessages(prev => [...prev, {
              role: 'system', content: msg.content, timestamp: Date.now()
            }])
            break
          case 'error':
            setThinking(false)
            setMessages(prev => [...prev, {
              role: 'system', content: `Error: ${msg.content}`, timestamp: Date.now()
            }])
            break
          case 'stats':
            setStats(msg)
            break
        }
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = () => {
      setConnected(false)
      setMessages(prev => [...prev, {
        role: 'system', content: 'Disconnected. Reconnecting...', timestamp: Date.now()
      }])
      setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
    }

    wsRef.current = ws
  }, [])

  useEffect(() => {
    connect()
    return () => wsRef.current?.close()
  }, [connect])

  const send = (content: string) => {
    if (!content.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    setMessages(prev => [...prev, {
      role: 'user', content: content.trim(), timestamp: Date.now()
    }])

    if (content.startsWith('/')) {
      wsRef.current.send(JSON.stringify({ type: 'command', command: content.trim() }))
    } else {
      wsRef.current.send(JSON.stringify({ type: 'message', content: content.trim() }))
    }

    setInput('')
    setThinking(true)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-primary)' }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'var(--bg-secondary)',
      }}>
        <div>
          <span style={{ fontWeight: 'bold', fontSize: '1.1em', color: 'var(--accent)' }}>
            VibeCoder
          </span>
          <span style={{ color: 'var(--text-secondary)', marginLeft: 12, fontSize: '0.85em' }}>
            {stats.model}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: '0.8em', color: 'var(--text-secondary)' }}>
          <span>{stats.episodes} episodes</span>
          <span>{stats.lessons} lessons</span>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: connected ? 'var(--success)' : 'var(--error)',
            display: 'inline-block', marginTop: 4,
          }} />
        </div>
      </div>

      {/* Messages */}
      <div className="scrollbar-thin" style={{
        flex: 1, overflow: 'auto', padding: '16px 20px',
      }}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            marginBottom: 12,
            display: 'flex',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth: msg.role === 'system' ? '100%' : '80%',
              padding: msg.role === 'system' ? '4px 0' : '10px 14px',
              borderRadius: msg.role === 'system' ? 0 : 8,
              background: msg.role === 'user' ? 'var(--accent)'
                : msg.role === 'system' ? 'transparent'
                : 'var(--bg-tertiary)',
              color: msg.role === 'system' ? 'var(--text-secondary)' : 'var(--text-primary)',
              fontSize: msg.role === 'system' ? '0.8em' : '0.9em',
              fontStyle: msg.role === 'system' ? 'italic' : 'normal',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {msg.content}
            </div>
          </div>
        ))}
        {thinking && (
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.85em', fontStyle: 'italic' }}>
            thinking...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={{
        padding: '12px 20px',
        borderTop: '1px solid var(--border)',
        background: 'var(--bg-secondary)',
        display: 'flex',
        gap: 8,
      }}>
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={connected ? 'Type a message or /command...' : 'Connecting...'}
          disabled={!connected || thinking}
          style={{
            flex: 1,
            padding: '10px 14px',
            borderRadius: 8,
            border: '1px solid var(--border)',
            background: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            outline: 'none',
            fontSize: '0.9em',
          }}
          autoFocus
        />
        <button
          onClick={() => send(input)}
          disabled={!connected || thinking || !input.trim()}
          style={{
            padding: '10px 20px',
            borderRadius: 8,
            border: 'none',
            background: 'var(--accent)',
            color: 'white',
            cursor: 'pointer',
            opacity: (!connected || thinking || !input.trim()) ? 0.5 : 1,
            fontSize: '0.9em',
          }}
        >
          Send
        </button>
      </div>
    </div>
  )
}
