import sys
import os
import time
import threading
import asyncio
import pyaudio
import minescript as m
from google import genai
from google.genai import types

# Configurations for Audio (16kHz, 16-bit PCM, Little-Endian)
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512

# Events for control flow
emergency_stop = threading.Event()
cancel_movement = threading.Event()

def monitor_emergency_stop():
    """Listens for the Left Shift key (code 340) to trigger an emergency stop."""
    try:
        with m.EventQueue() as event_queue:
            event_queue.register_key_listener()
            while not emergency_stop.is_set():
                try:
                    event = event_queue.get(block=True, timeout=0.1)
                    if event.type == "KEY" and event.key == 340 and event.action == 1:
                        m.echo_json({"text": "Emergency Stop Triggered!", "color": "red"})
                        emergency_stop.set()
                        cancel_movement.set()
                except Exception:
                    pass
    except Exception as e:
        m.log(f"Key listener failed: {e}")

def do_move(direction: str, duration: float):
    cancel_movement.clear()
    
    # Turn on movement
    if direction == "forward": m.player_press_forward(True)
    elif direction == "backward": m.player_press_backward(True)
    elif direction == "left": m.player_press_left(True)
    elif direction == "right": m.player_press_right(True)
    
    # Sleep with barge-in support
    start_time = time.time()
    while time.time() - start_time < duration:
        if cancel_movement.is_set() or emergency_stop.is_set():
            break
        time.sleep(0.05)
        
    # Turn off movement
    m.player_press_forward(False)
    m.player_press_backward(False)
    m.player_press_left(False)
    m.player_press_right(False)

def do_action(action_type: str):
    if action_type == "attack":
        m.player_press_attack(True)
        time.sleep(0.1)
        m.player_press_attack(False)
    elif action_type == "use":
        m.player_press_use(True)
        time.sleep(0.1)
        m.player_press_use(False)

def do_look(pitch: float, yaw: float):
    m.player_set_orientation(yaw, pitch)

import math
import struct

async def audio_stream_task(session):
    p = pyaudio.PyAudio()
    
    # Get default input device info
    try:
        default_device = p.get_default_input_device_info()
        m.echo(f"Using Audio Device: {default_device.get('name')}")
    except Exception as e:
        m.echo(f"Warning: Could not get default audio device: {e}")

    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    
    last_level_check = time.time()
    max_rms = 0

    try:
        while not emergency_stop.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            
            # Calculate RMS for voice level detection
            count = len(data) / 2
            format = "%dh" % count
            shorts = struct.unpack(format, data)
            sum_squares = 0.0
            for sample in shorts:
                n = sample / 32768.0
                sum_squares += n * n
            rms = math.sqrt(sum_squares / count)
            if rms > max_rms:
                max_rms = rms

            # Every 2 seconds, show the max voice level if it was significant
            if time.time() - last_level_check > 2.0:
                if max_rms > 0.01: # Threshold for 'hearing' something
                    level_bar = "|" * int(max_rms * 50)
                    m.echo(f"Mic Level: {level_bar}")
                max_rms = 0
                last_level_check = time.time()

            await session.send_realtime_input(
                audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000")
            )
            await asyncio.sleep(0)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

async def receive_from_gemini(session):
    async for response in session.receive():
        if emergency_stop.is_set():
            break
            
        m.log(f"Received from Gemini: {response}")

        # 1. Handle Tool Calls (Top-level in Gemini 3.1 Live API)
        if response.tool_call is not None:
            responses = []
            for fc in response.tool_call.function_calls:
                name = fc.name
                args = fc.args
                call_id = fc.id
                
                m.echo(f"Tool Call: {name}({args})")
                m.log(f"Executing Tool Call: {name}({args})")
                
                if name == "move_player":
                    direction = args.get("direction", "forward")
                    duration = float(args.get("duration", 1.0))
                    threading.Thread(target=do_move, args=(direction, duration), daemon=True).start()
                
                elif name == "action":
                    action_type = args.get("type", "attack")
                    threading.Thread(target=do_action, args=(action_type,), daemon=True).start()
                    
                elif name == "look":
                    pitch = float(args.get("pitch", 0.0))
                    yaw = float(args.get("yaw", 0.0))
                    threading.Thread(target=do_look, args=(pitch, yaw), daemon=True).start()
                
                responses.append(types.FunctionResponse(
                    name=name,
                    id=call_id,
                    response={"status": "ok"}
                ))
            
            # Send tool responses back to Gemini
            if responses:
                await session.send_tool_response(function_responses=responses)

        # 2. Handle Server Content (Audio/Transcription/Barge-in)
        server_content = response.server_content
        if server_content is not None:
            # If there is a model turn (audio/text), it triggers a barge-in (cancel movement)
            if server_content.model_turn is not None:
                cancel_movement.set()
                
                # Check for nested tool calls in parts (legacy/fallback support)
                for part in server_content.model_turn.parts:
                    if part.function_call:
                        fc = part.function_call
                        name = fc.name
                        args = fc.args
                        
                        m.echo(f"Nested Tool Call: {name}({args})")
                        if name == "move_player":
                            direction = args.get("direction", "forward")
                            duration = float(args.get("duration", 1.0))
                            threading.Thread(target=do_move, args=(direction, duration), daemon=True).start()
                        elif name == "action":
                            action_type = args.get("type", "attack")
                            threading.Thread(target=do_action, args=(action_type,), daemon=True).start()
                        elif name == "look":
                            pitch = float(args.get("pitch", 0.0))
                            yaw = float(args.get("yaw", 0.0))
                            threading.Thread(target=do_look, args=(pitch, yaw), daemon=True).start()

async def run_websocket():
    # Try to get the API key from:
    # 1. Command-line argument: \voice_control <key>
    # 2. Environment variables (Prism Launcher settings)
    # 3. Local file 'gemini_key.txt' in the same folder
    api_key = sys.argv[1] if len(sys.argv) > 1 else None

    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    if not api_key:
        try:
            key_file_path = os.path.join(os.path.dirname(__file__), "gemini_key.txt")
            if os.path.exists(key_file_path):
                with open(key_file_path, "r") as f:
                    content = f.read().strip()
                    if "=" in content:
                        # Extract value after '=' and strip any quotes
                        api_key = content.split("=", 1)[1].strip().strip("'").strip('"')
                    else:
                        api_key = content
        except Exception as e:
            m.log(f"Failed to read gemini_key.txt: {e}")

    if not api_key:
        m.echo_json({"text": "Error: GEMINI_API_KEY not found. Use '\voice_control <key>' or create 'gemini_key.txt'.", "color": "red"})
        emergency_stop.set()
        return

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    
    tools = [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="move_player",
                description="Moves the player in a given direction for a specified duration in seconds.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "direction": types.Schema(type="STRING", description="forward, backward, left, right"),
                        "duration": types.Schema(type="NUMBER", description="Duration to move in seconds")
                    },
                    required=["direction", "duration"]
                )
            ),
            types.FunctionDeclaration(
                name="action",
                description="Performs an action like attack or use.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "type": types.Schema(type="STRING", description="attack or use")
                    },
                    required=["type"]
                )
            ),
            types.FunctionDeclaration(
                name="look",
                description="Changes player orientation.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "pitch": types.Schema(type="NUMBER", description="degrees rotation from the x-z plane"),
                        "yaw": types.Schema(type="NUMBER", description="degrees rotation around the y axis")
                    },
                    required=["pitch", "yaw"]
                )
            )
        ])
    ]
    
    config = types.LiveConnectConfig(
        tools=tools, 
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text="You are a Minecraft voice controller. When the user gives a command like 'walk forward', 'attack', or 'look around', you MUST use the provided tools (move_player, action, look) to execute the action. Do not explain what you are doing; just call the tool.")]
        )
    )
    
    try:
        # Connect to the live API using the Gemini 3.1 Flash Live preview model
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
            m.echo_json({"text": "Connected to Gemini 3.1 Live API.", "color": "green"})
            send_task = asyncio.create_task(audio_stream_task(session))
            receive_task = asyncio.create_task(receive_from_gemini(session))
            
            await asyncio.gather(send_task, receive_task)
    except Exception as e:
        m.echo_json({"text": f"Error connecting to Gemini: {e}", "color": "red"})
        emergency_stop.set()

def main():
    m.echo("Starting Voice Control for Minecraft... (Press Shift to Stop)")
    
    # Start emergency stop monitor
    stop_thread = threading.Thread(target=monitor_emergency_stop, daemon=True)
    stop_thread.start()
    
    # Run the asyncio event loop in a dedicated thread
    def run_loop():
        asyncio.run(run_websocket())
        
    ws_thread = threading.Thread(target=run_loop, daemon=True)
    ws_thread.start()
    
    # Main thread block
    while not emergency_stop.is_set():
        time.sleep(0.5)
        
    m.echo("Voice Control terminated.")

if __name__ == "__main__":
    main()
