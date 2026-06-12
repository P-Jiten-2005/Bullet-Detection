# 🎯 PILSS Dashboard Frontend Client

This is the Next.js React client application for the **Precision Impact Localization and Scoring System (PILSS)**. It displays live webcam video, highlights dynamic target rings, provides interactive calibration overlays, and renders tabular statistics of bullet impacts in real time.

## 🚀 Getting Started

To launch both this frontend application and the backend API together, use the unified launcher script in the root directory:

```bash
# Run from the root directory of the project
python start_platform.py
```

This will automatically verify your local packages, compile assets, and boot the frontend at **http://localhost:3000** and the backend at **http://localhost:8000**.

## 📁 Key Directories

*   `src/app/`: The page routes and layouts (React 19 App Router).
*   `src/components/`: Modular dashboard widgets (HTML5 Canvas Visualizers, calibration modals, statistics cards, and shot tables).
*   `src/store/`: The Zustand state management store linking frontend controls to WebSocket connections.

---

For architectural details and database schemas, please refer to the main [Root README.md](../README.md).
