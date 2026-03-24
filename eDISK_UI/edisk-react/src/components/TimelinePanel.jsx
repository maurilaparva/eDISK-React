import React from 'react';
import { STEPS } from '../steps';
import TimelineStep from './TimelineStep';

export default function TimelinePanel({ highestCompletedIndex, detailsByStep }) {
  return (
    <aside className="panel timeline-panel">
      <div>
        <h3>Task Flow</h3>
        <p className="timeline-description">
          Follow the agent as it coordinates specialised tools. Each icon lights
          up once that capability has finished its work.
        </p>
      </div>

      <div className="timeline">
        {STEPS.map((step, idx) => {
          const completed = idx <= highestCompletedIndex;
          let detail = detailsByStep[step.key];
          if (completed && !detail) detail = 'Completed.';
          if (!completed) detail = step.placeholder;

          return (
            <TimelineStep
              key={step.key}
              icon={step.icon}
              title={step.key}
              detail={detail}
              completed={completed}
              isLast={idx === STEPS.length - 1}
            />
          );
        })}
      </div>
    </aside>
  );
}