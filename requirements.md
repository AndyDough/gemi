# Requirements for Gemini Voice-Controlled Minecraft Mod (macOS)

This project is optimized for **macOS**. To run the `minescript_gemini_orchestrator.py` script, follow these steps to set up your environment.

## 1. System Dependencies (Required for Audio)

On macOS, you must install **PortAudio** via Homebrew. This library is essential for `pyaudio` to access your MacBook's microphone.

```bash
# If you don't have Homebrew, install it from brew.sh first
brew install portaudio
```

## 2. Python Environment Setup

It is strongly recommended to use a virtual environment to avoid conflicts with system Python.

### 1. Create and Activate
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

### 2. Install google-genai and websockets
```bash
pip install google-genai websockets
```

### 3. Install PyAudio (macOS Troubleshooting)
If you get a `MIDIReceiveBlock` or `CoreMIDI` error when installing `pyaudio`, it's because the compiler (often Homebrew GCC) is conflicting with the macOS SDK. Use the system `clang` and point to the Homebrew PortAudio paths instead:

```bash
env CC=clang LDFLAGS="-L$(brew --prefix)/lib" CPPFLAGS="-I$(brew --prefix)/include" pip install pyaudio
```

### Summary of Libraries:
*   **`google-genai`**: Official SDK for Gemini Live API (Bimodal).
*   **`pyaudio`**: Real-time microphone capture.
*   **`websockets`**: High-performance bimodal communication.

## 3. macOS Permissions

When you first run the script, macOS may prompt you for permissions:
*   **Microphone Access:** Required for the voice commands to work.
*   **Accessibility/Input Monitoring:** If you use a global keyboard listener for the Emergency Stop, you may need to grant your Terminal/IDE accessibility permissions in *System Settings > Privacy & Security*.

## 4. Environment Variables

Set your Gemini API key in your terminal session:

```bash
export GEMINI_API_KEY='your_actual_api_key_here'
```

## 5. Minescript Integration

Ensure you have the **Minescript 5.0** mod installed in your Minecraft instance.
1.  Place `minescript_gemini_orchestrator.py` in your Minescript scripts folder (usually `~/Library/Application Support/minecraft/minescript/`).
2.  Run the script from the Minecraft chat: `\minescript_gemini_orchestrator.py`