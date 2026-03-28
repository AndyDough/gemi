import asyncio
import os
import sys
import json
import logging
from typing import Dict, Any, Optional

# Initialize logging immediately to ensure startup messages are captured.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("🚀 Starting Minescript Gemini Orchestrator...")

# Attempt to import Minescript. This script is intended to run inside Minescript.
try:
    import minescript
    # Check if this is the REAL minescript library. 
    # If we're running in the project root, 'import minescript' might just import the folder.
    if not hasattr(minescript, 'press_key_bind'):
        logging.warning("Imported 'minescript' is missing 'press_key_bind'. Falling back to mock.")
        raise ImportError
except (ImportError, AttributeError):
    logging.info("Minescript library not found or incomplete. Running in standalone/mock mode.")
    class MockMinescript:
        def execute(self, cmd: str):
            print(f"[MINESCRIPT MOCK] Executing Command: /{cmd}")
        def player_position(self):
            return (0, 0, 0)
        def player_look_at(self, x, y, z):
            print(f"[MINESCRIPT MOCK] Looking at: {x}, {y}, {z}")
            return True
        def press_key_bind(self, key: str, pressed: bool):
            state = "PRESSED" if pressed else "RELEASED"
            print(f"[MINESCRIPT MOCK] Key {key} set to {state}")
    minescript = MockMinescript()

# Try importing google-genai
try:
    from google import genai
    from google.genai import types
except ImportError:
    logging.error("google-genai is required. Please install it: pip install google-genai")
    sys.exit(1)

# --- 1. Function Declarations (Tools) ---

# Schema definitions for Gemini Live API
MOVE_PLAYER_SCHEMA = {
    "name": "move_player",
    "description": "Moves the player in a specified direction for a given duration.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "direction": {
                "type": "STRING",
                "description": "The direction to move. Options: 'forward', 'backward', 'left', 'right'.",
                "enum": ["forward", "backward", "left", "right"]
            },
            "duration": {
                "type": "NUMBER",
                "description": "Duration in seconds to hold the movement key."
            }
        },
        "required": ["direction", "duration"]
    }
}

INTERACT_SCHEMA = {
    "name": "interact",
    "description": "Performs an interaction action.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "The action to perform. Options: 'mine' (break blocks), 'use' (place block/interact), 'attack' (hit entities).",
                "enum": ["mine", "use", "attack"]
            }
        },
        "required": ["action"]
    }
}

LOOK_AT_SCHEMA = {
    "name": "look_at",
    "description": "Directs the player's gaze towards specific coordinates.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "coordinates": {
                "type": "OBJECT",
                "properties": {
                    "x": {"type": "NUMBER"},
                    "y": {"type": "NUMBER"},
                    "z": {"type": "NUMBER"}
                },
                "required": ["x", "y", "z"]
            }
        },
        "required": ["coordinates"]
    }
}

TOOLS = [
    {"function_declarations": [MOVE_PLAYER_SCHEMA, INTERACT_SCHEMA, LOOK_AT_SCHEMA]}
]


# --- 2 & 4. Minescript Integration & Safety Layer ---

class ActionController:
    def __init__(self):
        self.emergency_stop_event = asyncio.Event()
        self.active_tasks = set()
        
    async def trigger_emergency_stop(self):
        logging.warning("🚨 EMERGENCY STOP TRIGGERED 🚨")
        self.emergency_stop_event.set()
        
        # Cancel all active movement tasks
        for task in self.active_tasks:
            task.cancel()
            
        # Release all keys immediately via native Minescript API
        keys_to_release = ["key.forward", "key.back", "key.left", "key.right", "key.attack", "key.use"]
        for key in keys_to_release:
            try:
                minescript.press_key_bind(key, False)
            except Exception:
                pass
        
        logging.info("All keys released. Movement stopped.")
        await asyncio.sleep(1)
        self.emergency_stop_event.clear()

    async def _track_task(self, coro):
        task = asyncio.create_task(coro)
        self.active_tasks.add(task)
        try:
            await task
        except asyncio.CancelledError:
            logging.info("Task cancelled due to emergency stop.")
        finally:
            self.active_tasks.remove(task)

    async def _move_player_impl(self, direction: str, duration: float):
        if self.emergency_stop_event.is_set():
            return
            
        key_map = {
            "forward": "key.forward",
            "backward": "key.back",
            "left": "key.left",
            "right": "key.right"
        }
        key = key_map.get(direction)
        if not key:
            logging.error(f"Invalid direction: {direction}")
            return
            
        logging.info(f"Moving {direction} ({key}) for {duration} seconds.")
        minescript.press_key_bind(key, True)
        
        try:
            await asyncio.wait_for(
                self.emergency_stop_event.wait(), 
                timeout=duration
            )
        except asyncio.TimeoutError:
            pass
        finally:
            minescript.press_key_bind(key, False)

    async def move_player(self, direction: str, duration: float):
        await self._track_task(self._move_player_impl(direction, duration))

    async def interact(self, action: str):
        if self.emergency_stop_event.is_set():
            return
            
        key_map = {
            "mine": "key.attack",
            "attack": "key.attack",
            "use": "key.use"
        }
        key = key_map.get(action)
        if not key:
             logging.error(f"Invalid interact action: {action}")
             return
             
        logging.info(f"Performing interaction: {action} ({key})")
        minescript.press_key_bind(key, True)
        await asyncio.sleep(0.1)
        minescript.press_key_bind(key, False)

    async def look_at(self, coordinates: dict):
        if self.emergency_stop_event.is_set():
            return
        x, y, z = coordinates.get("x", 0), coordinates.get("y", 0), coordinates.get("z", 0)
        logging.info(f"Looking at coordinates: ({x}, {y}, {z})")
        # Using Minecraft command via Minescript for precise rotation
        minescript.execute(f"tp @s ~ ~ ~ facing {x} {y} {z}")

    def execute_tool_call(self, tool_call: types.FunctionCall):
        name = tool_call.name
        args = tool_call.args
        
        mode_str = " [MOCK MODE]" if "MockMinescript" in str(type(minescript)) else ""
        logging.info(f"Executing tool{mode_str}: {name} with args {args}")
        
        if name == "move_player":
            asyncio.create_task(self.move_player(args.get("direction"), args.get("duration", 1.0)))
        elif name == "interact":
            asyncio.create_task(self.interact(args.get("action")))
        elif name == "look_at":
            asyncio.create_task(self.look_at(args.get("coordinates", {})))
        else:
            logging.warning(f"Unknown tool call: {name}")


# --- 3. WebSocket Boilerplate (Gemini Live API) ---

class GeminiOrchestrator:
    def __init__(self, action_controller: ActionController):
        self.action_controller = action_controller
        # FALLBACK: You can paste your key between the quotes below if the env var isn't working
        self.api_key = os.environ.get("GEMINI_API_KEY") or "PASTE_YOUR_KEY_HERE"
        
        if not self.api_key or self.api_key == "PASTE_YOUR_KEY_HERE":
             raise ValueError("GEMINI_API_KEY is missing. Please set the environment variable or paste your key into the script.")
        
        # Initialize GenAI Client with v1alpha for the latest Gemini 3.1 Live features
        self.client = genai.Client(
            api_key=self.api_key,
            http_options={'api_version': 'v1alpha'}
        )
        # Using gemini-3.1-flash-live-preview released March 26, 2026
        self.model_name = "gemini-3.1-flash-live-preview"
        
        # Share a single PyAudio instance to prevent segmentation faults on macOS
        import pyaudio
        self.pa = pyaudio.PyAudio()

    async def audio_input_loop(self, session):
        """
        Captures microphone audio using PyAudio and streams it to the Gemini Live API.
        Includes simple energy monitoring for debugging.
        """
        import math
        import struct
        import pyaudio
        
        CHUNK = 512
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000 # Gemini Live API expects 16kHz mono 16-bit PCM

        try:
            device_info = self.pa.get_default_input_device_info()
            logging.info(f"🎤 Using default input device: {device_info.get('name')} (Index: {device_info.get('index')})")
        except Exception as e:
            logging.warning(f"Could not determine default audio device name: {e}")

        stream = self.pa.open(format=FORMAT,
                              channels=CHANNELS,
                              rate=RATE,
                              input=True,
                              frames_per_buffer=CHUNK)

        logging.info(f"Microphone stream opened at {RATE}Hz. Listening...")
        
        chunk_count = 0
        try:
            while True:
                # Read audio data from the microphone
                data = await asyncio.to_thread(stream.read, CHUNK, exception_on_overflow=False)
                
                # Monitor audio energy level periodically
                chunk_count += 1
                if chunk_count % 60 == 0: # Roughly every 2 seconds
                    shorts = struct.unpack("%dh" % (len(data) / 2), data)
                    sum_squares = sum(s**2 for s in shorts)
                    rms = math.sqrt(sum_squares / len(shorts)) if shorts else 0
                    if rms < 10:
                        logging.warning("🎤 Audio level very low. Is the mic muted or correct device selected?")
                    else:
                        logging.info(f"🎤 Audio Level: {'█' * int(min(rms/200, 20))} ({rms:.1f})")

                # Use keyword 'audio' with send_realtime_input (required for the latest SDK)
                await session.send_realtime_input(
                    audio=types.Blob(mime_type="audio/pcm", data=data)
                )
        except asyncio.CancelledError:
             logging.info("Audio input loop stopped.")
        finally:
            stream.stop_stream()
            stream.close()

    async def vision_input_loop(self, session):
         """
         Modular structure for future Vision (screen capture) support.
         """
         logging.info("Vision input loop ready for future implementation.")
         try:
             while True:
                 # In the future, you would use:
                 # await session.send_realtime_input(video=types.Blob(mime_type="image/jpeg", data=frame_data))
                 await asyncio.sleep(1.0)
         except asyncio.CancelledError:
             pass

    async def receive_loop(self, session):
        """
        Listens for responses from Gemini, including ToolCalls and VAD events.
        """
        logging.info("Receive loop started.")
        setup_logged = False
        try:
            async for response in session.receive():
                # 1. Handle Setup Complete
                if hasattr(response, 'setup_complete') and response.setup_complete and not setup_logged:
                     logging.info("✅ Gemini Setup Complete. Ready for voice commands.")
                     setup_logged = True

                # 2. Handle Tool Calls (The "Modern" location)
                if response.tool_call:
                    tool_responses = []
                    for fc in response.tool_call.function_calls:
                        self.action_controller.execute_tool_call(fc)
                        tool_responses.append(
                            types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response={"result": "success"}
                            )
                        )
                    
                    if tool_responses:
                        await session.send_tool_response(function_responses=tool_responses)

                # 3. Handle Server Content (Text responses or alternative tool call location)
                if response.server_content:
                    model_turn = response.server_content.model_turn
                    if model_turn:
                        for part in model_turn.parts:
                            if part.function_call:
                                self.action_controller.execute_tool_call(part.function_call)
                                await session.send_tool_response(
                                    function_responses=[
                                        types.FunctionResponse(
                                            id=part.function_call.id,
                                            name=part.function_call.name,
                                            response={"result": "success"}
                                        )
                                    ]
                                )
                            elif part.text:
                                logging.info(f"💬 Gemini: {part.text}")
                
        except asyncio.CancelledError:
            logging.info("Receive loop stopped.")
        except Exception as e:
            logging.error(f"Error in receive loop: {e}")

    async def keyboard_listener(self):
        """
        Safety Layer: Monitors for a 'q' key press in the console 
        to trigger an immediate emergency stop.
        """
        logging.info("Safety Layer: Keyboard listener started. Press 'q' + ENTER in console to emergency stop.")
        
        while True:
            # We use asyncio.to_thread to run a blocking input() without freezing the loop
            user_input = await asyncio.to_thread(input, "")
            if user_input.lower().strip() == 'q':
                await self.action_controller.trigger_emergency_stop()
                logging.info("Emergency Stop confirmed via keyboard.")
            await asyncio.sleep(0.1)

    async def wait_for_voice(self):
        """
        Monitors the microphone locally while disconnected. 
        Returns when audio energy exceeds the threshold.
        """
        import math
        import struct
        import pyaudio

        logging.info("🔇 Connection idle. Waiting for voice activity to reconnect...")
        await asyncio.sleep(1) # Hardware breather
        
        CHUNK = 512
        stream = self.pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=CHUNK)
        
        THRESHOLD = 800 # Sensitivity for reconnection
        
        try:
            while True:
                data = await asyncio.to_thread(stream.read, CHUNK, exception_on_overflow=False)
                shorts = struct.unpack("%dh" % (len(data) / 2), data)
                rms = math.sqrt(sum(s**2 for s in shorts) / len(shorts)) if shorts else 0
                
                if rms > THRESHOLD:
                    logging.info(f"🎙️ Voice activity detected (Level: {rms:.1f}). Reconnecting to Gemini...")
                    return
                await asyncio.sleep(0.05)
        finally:
            stream.stop_stream()
            stream.close()

    async def run(self):
        # Build tool objects explicitly using SDK types
        tool_decl = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(**MOVE_PLAYER_SCHEMA),
                types.FunctionDeclaration(**INTERACT_SCHEMA),
                types.FunctionDeclaration(**LOOK_AT_SCHEMA),
            ]
        )

        config = types.LiveConnectConfig(
            tools=[tool_decl],
            system_instruction=types.Content(
                parts=[types.Part(text="You are a Minecraft controller bot. Listen to the user's audio commands and use the provided tools to move the player, interact, and look around. Keep responses brief.")]
            ),
            response_modalities=["AUDIO"]
        )
        
        # Start the safety task ONCE at the beginning
        safety_task = asyncio.create_task(self.keyboard_listener())
        
        while True:
            logging.info(f"Connecting to Gemini Live API ({self.model_name})...")
            try:
                async with self.client.aio.live.connect(model=self.model_name, config=config) as session:
                    logging.info("Connected successfully.")
                    
                    # Start bimodal tasks
                    audio_task = asyncio.create_task(self.audio_input_loop(session))
                    receive_task = asyncio.create_task(self.receive_loop(session))
                    
                    # Wait until tasks complete or connection fails
                    done, pending = await asyncio.wait(
                        [audio_task, receive_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel pending tasks to ensure a clean slate for reconnection
                    for task in pending:
                        task.cancel()
                    
                    # If we got here normally, check if it was a connection drop
                    for task in done:
                        if task.exception():
                            raise task.exception()
                            
            except Exception as e:
                error_str = str(e).lower()
                if "1011" in error_str or "timeout" in error_str or "1006" in error_str:
                    logging.warning(f"🔄 Connection lost ({e}). Switching to passive listener...")
                    # Wait for voice before trying to reconnect
                    await self.wait_for_voice()
                    continue
                else:
                    logging.error(f"❌ Critical Connection Error: {e}")
                    break
            finally:
                 logging.info("Session closed.")
                 await asyncio.sleep(1) # Cool down period to prevent segfaults

if __name__ == "__main__":
    controller = ActionController()
    orchestrator = GeminiOrchestrator(controller)
    
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logging.info("Program terminated by user.")
        # Trigger emergency stop synchronously before exiting
        asyncio.run(controller.trigger_emergency_stop())
