# Gemini Voice-Controlled Minecraft Mod (Minescript)

This project provides an asynchronous Python orchestrator designed to run within the **Minescript 5.0** environment. It enables real-time voice control of a Minecraft player using the **Gemini Live API (WebSockets)**.

## Project Overview

*   **Main Script:** `minescript_gemini_orchestrator.py`
*   **Technologies:** Python 3.x, `google-genai` SDK, `minescript` (Minecraft Mod API), `asyncio`, `PyAudio`.
*   **Architecture:**
    *   **Bimodal Stream:** Handles real-time audio input and receives `ToolCall` responses from Gemini.
    *   **Action Controller:** Maps Gemini function calls (e.g., `move_player`, `interact`) to native Minescript API commands.
    *   **Safety Layer:** Implements an "Emergency Stop" mechanism to immediately halt all movement and release keys.
    *   **Modularity:** Designed to easily integrate future Vision (screen capture) support.

## Building and Running

### Prerequisites (macOS)
1.  **System Libraries:** Install PortAudio (required for audio capture):
    ```bash
    brew install portaudio
    ```
2.  **Environment Variables:** Set your Gemini API key:
    ```bash
    export GEMINI_API_KEY='your_api_key_here'
    ```

### Environment Setup
Create a virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install google-genai websockets

# Special install for PyAudio on macOS to avoid build errors:
env CC=clang LDFLAGS="-L$(brew --prefix)/lib" CPPFLAGS="-I$(brew --prefix)/include" pip install pyaudio
```

### Running the Orchestrator
1.  Ensure **Minescript 5.0** is installed in Minecraft.
2.  Place the script in your Minescript scripts folder.
3.  Execute from Minecraft chat:
    ```text
    \minescript_gemini_orchestrator.py
    ```

## Development Conventions

*   **Asynchronous Pattern:** Use `asyncio` for all networking and input/output tasks to prevent blocking the game thread.
*   **Tool Schema:** Function declarations for Gemini are defined in `minescript_gemini_orchestrator.py` using standard JSON schema.
*   **Safety First:** Any tool that triggers movement must be trackable and cancellable by the `ActionController.trigger_emergency_stop()` method.
*   **Native API Preference:** Always prefer `minescript.press_key_bind()` over general command execution for player movement and actions.
