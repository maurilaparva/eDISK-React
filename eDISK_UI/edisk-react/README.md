# eDISK React UI

React-based frontend for the eDISK AI Agent, converted from the original `chat.html` single-file template.

## Project Structure

```
edisk-react/
├── index.html                  # Vite entry HTML
├── package.json
├── vite.config.js              # Proxy + build config
├── src/
│   ├── main.jsx                # React entry point
│   ├── App.jsx                 # Root component — state + API orchestration
│   ├── api.js                  # Django API wrappers (/api/chat, /api/progress)
│   ├── steps.js                # Timeline step definitions + alias map
│   ├── hooks/
│   │   └── useProgress.js      # Polling hook (replaces the setInterval logic)
│   ├── components/
│   │   ├── ChatPanel.jsx       # Left panel: messages + input
│   │   ├── ChatMessage.jsx     # Single chat bubble
│   │   ├── FileUpload.jsx      # Drag-and-drop / click image upload
│   │   ├── TimelinePanel.jsx   # Right panel: task flow
│   │   └── TimelineStep.jsx    # Single step card
│   └── styles/
│       └── global.css          # All styles (ported from chat.html)
```

## Quick Start (Development)

```bash
cd edisk-react
npm install
npm run dev          # starts Vite on http://localhost:3000
```

Vite proxies all `/api/*` requests to `http://127.0.0.1:8000` (your Django dev server), so run both in parallel.

## Building for Production (Django Integration)

### 1. Build the React app

```bash
npm run build
```

This outputs to `../ui_agent/static/react/` (configured in `vite.config.js`). Adjust the `outDir` path to match your Django project layout.

### 2. Create a Django template to serve the built app

Create `ui_agent/templates/index.html`:

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>eDISK AI Agent</title>
  <!-- Vite build outputs a CSS file here -->
  <link rel="stylesheet" href="{% static 'react/assets/index-HASH.css' %}" />
</head>
<body>
  <div id="root"></div>
  <script type="module" src="{% static 'react/js/index-HASH.js' %}"></script>
</body>
</html>
```

> **Tip:** To avoid manually updating hashes, use
> [django-vite](https://github.com/MrBin99/django-vite) which reads
> Vite's `manifest.json` and injects the correct asset paths automatically.

### 3. Point your Django view at the new template

```python
# ui_agent/views.py
from django.shortcuts import render

def chat_view(request):
    return render(request, 'index.html')
```

### 4. Make sure Django knows about the static files

```python
# settings.py
STATICFILES_DIRS = [
    BASE_DIR / 'ui_agent' / 'static',
]
```

That's it — the React app talks to the same `/api/chat` and `/api/progress/<run_id>` endpoints as before.

## Adding React Flow (Next Step)

React Flow is already included in `package.json`. To add the graph view:

```jsx
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// Parse the final answer into nodes/edges from your other project's format,
// then render:
<ReactFlow nodes={nodes} edges={edges}>
  <Background />
  <Controls />
</ReactFlow>
```

A natural place to add this is either:
- **Replace** the bot message bubble with a graph panel when a graph response is detected
- **Add a third panel** or modal that shows the graph alongside the chat
- **Embed it inside TimelinePanel** once the final answer arrives