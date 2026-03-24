import React, { useRef, useState, useCallback } from 'react';

export default function FileUpload({ file, onFileChange }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  const handleClick = useCallback(
    (e) => {
      // Don't open file picker when clicking the clear button
      if (e.target.closest('.clear-btn')) return;
      inputRef.current?.click();
    },
    []
  );

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragging(false), []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer.files?.[0];
      if (f && f.type.startsWith('image/')) onFileChange(f);
    },
    [onFileChange]
  );

  const handleInputChange = useCallback(
    (e) => {
      const f = e.target.files?.[0];
      onFileChange(f && f.type.startsWith('image/') ? f : null);
    },
    [onFileChange]
  );

  const handleClear = useCallback(
    (e) => {
      e.stopPropagation();
      if (inputRef.current) inputRef.current.value = '';
      onFileChange(null);
    },
    [onFileChange]
  );

  const className = [
    'upload-area',
    dragging && 'dragging',
    file && 'has-file',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      className={className}
      title="Click or drop an image"
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <span className="clip-icon">📎</span>
      {file && <span className="file-name">{file.name}</span>}
      {file && (
        <button
          type="button"
          className="clear-btn"
          aria-label="Remove image"
          onClick={handleClear}
        >
          ✕
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={handleInputChange}
      />
    </div>
  );
}