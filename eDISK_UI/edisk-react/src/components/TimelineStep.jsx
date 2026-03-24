import React from 'react';

export default function TimelineStep({ icon, title, detail, completed, isLast }) {
  return (
    <div className={`step${completed ? ' completed' : ''}`}>
      {/* connector line hidden via CSS on :last-child, but we also skip for isLast */}
      <div className="step-icon" aria-hidden="true">
        {icon}
      </div>
      <div className="step-content">
        <h4>{title}</h4>
        <p className="step-detail">{detail}</p>
      </div>
    </div>
  );
}