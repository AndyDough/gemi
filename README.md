# Gemini Voice-Controlled Minecraft Bot

This project implements a real-time, voice-controlled Minecraft bot using the **Gemini 3.1 Flash Live API** and **Minescript**. The bot can listen to your voice commands, scan the environment for blocks (like trees), move to specific coordinates, and perform actions like chopping wood.

## Features

- **Live Voice Control**: Direct interaction with Gemini via your microphone.
- **Coordinate-Based Precision**: The bot uses mathematical scanning to find blocks, ensuring high accuracy.
- **Synchronous Execution**: Tasks like walking and chopping are queued and executed sequentially.
- **Instant Interruption**: If you speak while the bot is acting, it immediately stops and resets for your next command.
- **Silent Operation**: The bot responds only via Minecraft chat and actions (audio response is disabled for speed and focus).

## How it Works

1.  **Audio Streaming**: The script captures your microphone audio using `pyaudio` and streams it to Gemini.
2.  **Minescript Integration**: Commands are sent to Minecraft via the Minescript mod, which allows Python scripts to control the player avatar.
3.  **Coordinate Scanning**: Instead of slow video processing, the bot uses `getblocklist` to scan a 3D area around you for specific materials (logs, wood, etc.).
4.  **Action Queue**: Gemini issues "Tool Calls" (e.g., `move_to`, `chop_at`). These are placed in an asynchronous queue and executed one by one.
5.  **Feedback Loop**: Each tool call only returns "OK" once the physical action in Minecraft is finished, ensuring Gemini always knows exactly where you are in the task.

## Prerequisites

- **macOS** (Optimized for Mac, though portable to other systems with minor changes).
- **Minecraft** with the **Minescript 5.0+** mod installed.
- **Python 3.9+**.
- **PortAudio** (Required for audio processing).

## Setup Instructions

### 1. Install System Dependencies
On macOS, install PortAudio via Homebrew:
```bash
brew install portaudio
```

### 2. Set Up Python Environment
It is highly recommended to use a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install google-genai pyaudio websockets
```

### 3. Configure your API Key
Create a file named `gemini_key.txt` in the project root or the `minescript` folder and paste your key:
```text
GEMINI_API_KEY=your_actual_api_key_here
```
Alternatively, set it as an environment variable: `export GEMINI_API_KEY='...'`

### 4. Install the Script in Minecraft
Copy the `minecraft/minescript/voice_control.py` file to your Minescript scripts folder:
`~/Library/Application Support/minecraft/minescript/`

## Usage

1.  Launch Minecraft and enter a world.
2.  Open the chat console by pressing `\` (or your configured Minescript key).
3.  Run the command: `\voice_control`
4.  Once you see **"Robot Ready"**, speak a command:
    - *"Chop down the tree in front of me."*
    - *"Stop what you're doing!"*
    - *"Find some wood nearby."*

## Troubleshooting

Before launching Minecraft, you can test your connection and API key using the included validation script:
```bash
python3 validate_voice_control.py
```
If this script returns **"SUCCESS"**, your environment is correctly configured for the Live API.
