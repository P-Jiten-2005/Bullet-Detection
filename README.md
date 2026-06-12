# 🎯 Precision Impact Localization and Scoring System (PILSS)

PILSS is a professional-grade, computer-vision-powered target analysis and scoring platform. Built to detect, align, and grade bullet impacts on paper shooting targets, PILSS translates raw digital coordinates into millimeter-accurate positions, calculates official ISSF integer and decimal scores, and provides line-break boundary reviews in real time.

---

## 📚 Technical Documentation

For in-depth guides on the system internals, algorithms, and modules, refer to the following:
*   [**Architecture & Design**](file:///D:/Gitam/CXR_Internship/Precision-Impact-Localization-and-Scoring-System/docs/architecture.md): High-level architecture, real-time WebSocket telemetry, and database schemas.
*   [**Module Directory Reference**](file:///D:/Gitam/CXR_Internship/Precision-Impact-Localization-and-Scoring-System/docs/module_details.md): Breakdown of the Python backend structures, APIs, and scoring engines.
*   [**Computer Vision Pipeline**](file:///D:/Gitam/CXR_Internship/Precision-Impact-Localization-and-Scoring-System/docs/cv_docs.md): Frame registration, AprilTag homography scale alignment, change detection, and sub-pixel localization.

---

## 💻 Tech Stack

*   **Backend Services**: Python 3.12+, FastAPI, Uvicorn, SQLite (async via `aiosqlite` and SQLAlchemy 2.0), OpenCV, and NumPy.
*   **Frontend Client**: Next.js 15+ (React 19), Zustand state management, HTML5 Canvas API, and Tailwind CSS.

---

## 📁 Repository Structure

```
precision-impact-localization-and-scoring-system/
├── backend/                       # Python Backend Service
│   ├── app/                       # FastAPI Web Application & Services
│   │   ├── main.py                # REST endpoints & WebSocket routing
│   │   └── services/              # CV Engine, Camera, AprilTag, WS Manager
│   ├── src/                       # Core Algorithmic Engines
│   │   ├── scoring/               # ISSF scoring & boundary verification
│   │   ├── target_definition/     # Target ring geometry definitions
│   │   └── transformation/        # Raw-pixel to mm coordinate mapping
│   ├── configs/                   # Target ring dimension JSON files
│   ├── data/                      # SQLite database files
│   ├── uploads/                   # Baseline and capture image files
│   └── tests/                     # Backend Python unit tests
├── docs/                          # Developer Documentation
│   ├── architecture.md            # System architecture details
│   ├── module_details.md          # File-by-file module lookup
│   └── cv_docs.md                 # Computer Vision explanation
├── frontend/                      # Next.js React Dashboard
│   ├── src/
│   │   ├── app/                   # Client routing and page entrypoint
│   │   ├── components/            # UI components (Canvas, tables, panels)
│   │   └── store/                 # Zustand store (useStore.ts)
│   └── package.json               # Node.js frontend dependencies
├── start_platform.py              # Unified single-command launcher
└── README.md                      # Quick-start documentation
```

---

## 🚀 Key Features

1.  **Approach B (Detect-then-Transform)**: Directly projects raw bullet hole centroids using homography mapping ($H$) to avoid pixel distortion and interpolation artifacts.
2.  **AprilTag Homography & Scale Calibration**: Reconstructs physical paper corners and dynamically aligns target zones (using threshold sweeps and aspect ratio filters) to compensate for printed target paper scale variances.
3.  **Dual-Method Change Detection**: Merges Otsu-based **Directed Binary Differencing** and **Structural Similarity Index (SSIM)** diff maps inside a paper mask, completely ignoring background noise.
4.  **Sub-Pixel Bullet Hole Localization**: Combines four algorithms (**Moment Centroid**, **Ellipse Fit**, **Caliber-Constrained Circle Fit**, and **Weighted Intensity Center**) to achieve sub-millimeter centroid precision.
5.  **Trainer & Trainee Roles**: Built-in header role toggler backed by the Zustand store to allow switching between trainer configurations (target creation, calibrations) and trainee telemetry logs.
6.  **Uncertainty & Boundary Verification**: Calculates standard deviation spread across localization methods and highlights line-break shots requiring manual verification.

---

## 🛠️ Quick Installation & Setup

PILSS includes a unified Python launcher script (`start_platform.py`) that handles creating the virtual environment, installing dependencies, and running both the frontend dev server and FastAPI concurrently.

### Prerequisites
Ensure you have the following installed on your system:
*   [**Python 3.12+**](https://www.python.org/downloads/)
*   [**Node.js 18+ (with npm)**](https://nodejs.org/)

### Installation Steps

1.  **Clone and Navigate to the Repository**:
    ```bash
    git clone https://github.com/Joel-GJA/Precision-Impact-Localization-and-Scoring-System.git
    cd Precision-Impact-Localization-and-Scoring-System
    ```
2.  **Run the Unified Platform Launcher**:
    On your first run, the launcher will automatically:
    *   Initialize a Python virtual environment (`pilssVenv`).
    *   Install all backend Python requirements (`backend/requirements.txt`).
    *   Install all frontend Node.js packages (`frontend/package.json`).
    *   Bootstrap the SQLite database schemas.
    *   Start both the FastAPI backend (port `8000`) and the Next.js frontend (port `3000`).

    To start, run:
    ```bash
    python start_platform.py
    ```
3.  **Access the Dashboard**:
    Open your browser and navigate to **[http://localhost:3000](http://localhost:3000)**.

---

## 🧪 Testing the Modules

Verify the algorithmic accuracy and code compliance using Python's built-in `unittest` runner:

*   **Run All Backend Unit Tests**:
    ```bash
    .\pilssVenv\Scripts\python.exe -m unittest discover -s backend/tests
    ```
*   **Run Core Scoring Rules Tests**:
    ```bash
    .\pilssVenv\Scripts\python.exe -m unittest backend/tests/test_scoring.py
    ```
*   **Run CV Engine Localization Tests**:
    ```bash
    .\pilssVenv\Scripts\python.exe -m unittest backend/tests/test_cv_engine.py
    ```
*   **Run Synthetic Localization Benchmark**:
    Generates simulated target frames with predefined shifts/rotations, evaluates localization offsets, and outputs a report in `backend/experiments/localization/benchmark_report.md`:
    ```bash
    .\pilssVenv\Scripts\python.exe backend/src/evaluation/evaluation_runner.py
    ```
