import React, { useState, useCallback, useRef } from 'react';
import ChatPanel from './components/ChatPanel';
import TimelinePanel from './components/TimelinePanel';
import { sendChat, fetchProgress } from './api';
import { useProgress } from './hooks/useProgress';
import { STEPS, normaliseStep } from './steps';

const STEP_KEYS = STEPS.map((s) => s.key);

export default function App() {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [file, setFile] = useState(null);
  const [highestIndex, setHighestIndex] = useState(-1);
  const [detailsByStep, setDetailsByStep] = useState({});

  const { startPolling, stopPolling } = useProgress();
  const busyRef = useRef(false);

  const resetTimeline = useCallback(() => {
    setHighestIndex(-1);
    setDetailsByStep({});
  }, []);

  const handleSubmit = useCallback(async () => {
    const query = inputValue.trim();
    const attachedFile = file;
    if (!query && !attachedFile) return;
    if (busyRef.current) return;
    busyRef.current = true;

    const parts = [];
    if (query) parts.push(query);
    if (attachedFile) parts.push(`[Attached image: ${attachedFile.name}]`);
    const userText = parts.join('\n\n');

    setMessages((prev) => [...prev, { role: 'me', text: userText }]);
    setInputValue('');
    setFile(null);
    resetTimeline();
    setHighestIndex(0);
    setDetailsByStep({ 'Task Intake': 'Prompt received from the user.' });

    try {
      const { run_id } = await sendChat(query, attachedFile);
      startPolling(run_id, ({ highestIndex: hi, detailsByStep: dbs }) => {
        setHighestIndex(hi);
        setDetailsByStep(dbs);
      });

      let answer = '';
      let graphData = null;
      let entityTags = null;

      while (true) {
        const resp = await fetchProgress(run_id);
        const msgs = resp.messages || [];

        // Parse [DATA] — structured graph payload
        const dataEntry = msgs.find((m) => m.startsWith('[DATA]'));
        if (dataEntry && !graphData) {
          try {
            graphData = JSON.parse(dataEntry.replace(/^\[DATA\]/, ''));
          } catch (e) {
            console.warn('[App] Failed to parse [DATA] message:', e);
          }
        }

        // Parse [TAGS] — LLM entity annotations
        const tagsEntry = msgs.find((m) => m.startsWith('[TAGS]'));
        if (tagsEntry && !entityTags) {
          try {
            entityTags = JSON.parse(tagsEntry.replace(/^\[TAGS\]/, ''));
          } catch (e) {
            console.warn('[App] Failed to parse [TAGS] message:', e);
          }
        }

        const finalEntry = msgs.find((m) => m.startsWith('[FINAL]'));
        if (finalEntry) {
          answer = finalEntry.replace(/^\[FINAL\]\s*/, '').trim();
          break;
        }

        if (resp.finished) break;
        await new Promise((r) => setTimeout(r, 900));
      }

      stopPolling();
      setHighestIndex(STEP_KEYS.length - 1);
      setDetailsByStep((prev) => ({
        ...prev,
        'Final Response': answer ? 'Answer shared with the user.' : 'Unable to craft an answer.',
      }));

      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          text: answer || 'I was not able to generate a response.',
          graphData: graphData || null,
          entityTags: entityTags || null,
          query,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'bot', text: err.message, graphData: null, entityTags: null }]);
    } finally {
      busyRef.current = false;
    }
  }, [inputValue, file, resetTimeline, startPolling, stopPolling]);

  const handleDemoLoad = useCallback((query, response) => {
    setMessages([
      { role: 'me', text: query },
      { role: 'bot', text: response, graphData: null, entityTags: null, query },
    ]);
    setInputValue('');
    setFile(null);
    setHighestIndex(STEP_KEYS.length - 1);
    setDetailsByStep({
      'Task Intake': 'Demo query loaded.',
      'Entity Mapping': 'Ginkgo (DSI000108), Memory Loss (DIS000134)',
      'Evidence Retrieval': 'Direct relation found: Ginkgo → effective for → Memory Loss (MSKCC)',
      'Context Expansion': "Associations: inflammation, Alzheimer's disease, insomnia",
      'Inference Engine': 'Link prediction: insomnia, drug/gene interactions',
      'Cross-Checking': 'Verified via PMID: 17110111, 24054487, 28707415',
      'Final Response': 'Answer shared with the user.',
    });
  }, []);

  return (
    <div className="app-shell">
      <ChatPanel
        messages={messages}
        inputValue={inputValue}
        onInputChange={setInputValue}
        file={file}
        onFileChange={setFile}
        onSubmit={handleSubmit}
        onDemoLoad={handleDemoLoad}
      />
      <TimelinePanel
        highestCompletedIndex={highestIndex}
        detailsByStep={detailsByStep}
      />
    </div>
  );
}