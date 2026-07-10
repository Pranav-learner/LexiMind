// The message input. Auto-growing textarea; Enter sends, Shift+Enter inserts a newline. The Send
// button flips to a Stop button while a reply is streaming (cancels via the parent's onStop). Send
// is disabled when the input is empty.

import { useEffect, useRef, useState } from "react";

interface Props {
  onSend: (text: string) => void;
  onStop: () => void;
  streaming: boolean;
  disabled?: boolean;
}

const MAX_HEIGHT = 200;

export default function ChatComposer({ onSend, onStop, streaming, disabled }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-grow the textarea up to MAX_HEIGHT.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  function send() {
    const text = value.trim();
    if (!text || streaming || disabled) return;
    onSend(text);
    setValue("");
  }

  return (
    <div className="chat-composer">
      <textarea
        ref={ref}
        className="chat-composer-input"
        rows={1}
        placeholder="Ask anything about your documents…"
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        aria-label="Message input"
      />
      {streaming ? (
        <button className="chat-send stop" onClick={onStop} title="Stop generating" aria-label="Stop generating">
          ⏹ Stop
        </button>
      ) : (
        <button
          className="chat-send"
          onClick={send}
          disabled={!value.trim() || disabled}
          title="Send message"
          aria-label="Send message"
        >
          ➤
        </button>
      )}
    </div>
  );
}
