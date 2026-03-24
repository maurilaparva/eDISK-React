import React, { useRef, useEffect } from 'react';
import ChatMessage from './ChatMessage';
import FileUpload from './FileUpload';

const DEMO_QUERY = 'Can Ginkgo prevent memory loss?';
const DEMO_RESPONSE = `The mapped entities are Ginkgo (Ginkgo biloba) and memory loss. Ginkgo biloba is one of the oldest living tree species, known for its medicinal properties and use in traditional Chinese medicine. In eDISK, a direct relationship exists indicating that Ginkgo is effective for memory loss (source: MSKCC). Contextually, Ginkgo is associated with various disease and drugs, including inflammation and Alzheimer's disease. Link prediction suggests Ginkgo may also be effective for conditions like insomnia and interacts with several drugs and genes. Verification findings support that Ginkgo is effective for inflammation and insomnia, with references including PMID: 17110111 and 27852128. Additionally, memory loss is linked to substances like cocaine and nicotine-containing products, with supporting evidence from multiple studies. Verification references: PMID: 17110111, 24054487, 28707415, 20731354|20731354|23566359,26975469.`;

export default function ChatPanel({ messages, inputValue, onInputChange, file, onFileChange, onSubmit, onDemoLoad }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handleRecommendationSelect = (question) => {
    onInputChange(question);
    setTimeout(() => {
      const input = document.querySelector('.chat-input input[type="text"]');
      if (input) { input.focus(); input.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
    }, 50);
  };

  const getQueryForMessage = (messages, botIndex) => {
    for (let i = botIndex - 1; i >= 0; i--) {
      if (messages[i].role === 'me') return messages[i].text;
    }
    return '';
  };

  return (
    <section className="panel chat-panel">
      <div className="chat-header">
        <h2>eDISK AI Agent</h2>
        <div className="header-actions">
          <button className="demo-btn" onClick={() => onDemoLoad && onDemoLoad(DEMO_QUERY, DEMO_RESPONSE)}>Demo</button>
          <span className="badge">Instant Health Insights</span>
        </div>
      </div>
      <div className="messages" ref={scrollRef}>
        {messages.map((m, i) => (
          <ChatMessage
            key={i}
            role={m.role}
            text={m.text}
            graphData={m.graphData || null}
            entityTags={m.entityTags || null}
            query={m.role === 'bot' ? getQueryForMessage(messages, i) : undefined}
            onRecommendationSelect={m.role === 'bot' ? handleRecommendationSelect : undefined}
          />
        ))}
      </div>
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
        <FileUpload file={file} onFileChange={onFileChange} />
        <input type="text" placeholder="Ask me anything about supplements, diseases, genes..."
          autoComplete="off" value={inputValue} onChange={(e) => onInputChange(e.target.value)} />
        <button type="submit" className="send-btn">Send</button>
      </form>
    </section>
  );
}