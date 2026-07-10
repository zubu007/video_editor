import { useEffect, useRef, useState } from 'react';
import styles from './ChatPanel.module.css';

// One entry in the chat feed. 'log' entries are editor activity notes
// (things the app did); 'user'/'assistant' are the actual conversation.
function ChatEntry({ message }) {
  if (message.role === 'log') {
    return (
      <div className={styles.logEntry}>
        <span className={styles.logTime}>{message.time}</span>
        <span>{message.content}</span>
      </div>
    );
  }

  const isUser = message.role === 'user';
  return (
    <div className={isUser ? styles.userRow : styles.assistantRow}>
      <div className={isUser ? styles.userBubble : styles.assistantBubble}>
        {message.content}
      </div>
    </div>
  );
}

export default function ChatPanel({
  messages,
  isSending,
  error,
  hasProject,
  onSend,
}) {
  const [draft, setDraft] = useState('');
  const feedRef = useRef(null);

  // Keep the newest entry in view as logs and replies arrive.
  useEffect(() => {
    const feed = feedRef.current;
    if (feed) {
      feed.scrollTop = feed.scrollHeight;
    }
  }, [messages, isSending]);

  const canSend = hasProject && !isSending && draft.trim().length > 0;

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!canSend) return;
    onSend(draft.trim());
    setDraft('');
  };

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <h3>Assistant</h3>
        <p>Project activity and answers about your current edit.</p>
      </div>

      <div className={styles.feed} ref={feedRef}>
        {messages.length === 0 && (
          <div className={styles.empty}>
            Editor updates will appear here. Ask about the current project or
            tell the assistant what to do — e.g. &ldquo;cut the first 5
            seconds&rdquo;, &ldquo;zoom in at 42s&rdquo;, or &ldquo;find and
            remove the silences&rdquo;.
          </div>
        )}
        {messages.map((message) => (
          <ChatEntry key={message.id} message={message} />
        ))}
        {isSending && (
          <div className={styles.assistantRow}>
            <div className={`${styles.assistantBubble} ${styles.pending}`}>
              Thinking…
            </div>
          </div>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <form className={styles.inputRow} onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          placeholder={
            hasProject ? 'Ask about this project…' : 'Load a video to chat'
          }
          disabled={!hasProject || isSending}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" disabled={!canSend}>
          Send
        </button>
      </form>
    </section>
  );
}
