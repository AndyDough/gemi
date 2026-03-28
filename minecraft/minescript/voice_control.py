import sys
import os
import time
import threading
import asyncio
import pyaudio
import minescript as m
from google import genai
from google.genai import types
import math
import struct

# Configurations for Audio (16kHz, 16-bit PCM, Little-Endian)
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512

# Events for control flow
emergency_stop = threading.Event()
cancel_movement = threading.Event()

# Action Queue for sequential execution
action_queue = asyncio.Queue()

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

async def action_executor():
    """Executes actions from the queue sequentially to avoid stepping on each other."""
    while not emergency_stop.is_set():
        try:
            func, args, kwargs = await asyncio.wait_for(action_queue.get(), timeout=0.5)
            # Run the synchronous function in a separate thread but wait for it to complete
            await asyncio.to_thread(func, *args, **kwargs)
            action_queue.task_done()
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            m.log(f"Action execution error: {e}")

def do_move(direction: str, duration: float):
    cancel_movement.clear()
    
    # Turn on movement
    if direction == "forward": m.player_press_forward(True)
    elif direction == "backward": m.player_press_backward(True)
    elif direction == "left": m.player_press_left(True)
    elif direction == "right": m.player_press_right(True)
    
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

def do_hold_action(action_type: str, duration: float):
    if action_type == "attack":
        m.player_press_attack(True)
        time.sleep(duration)
        m.player_press_attack(False)
    elif action_type == "use":
        m.player_press_use(True)
        time.sleep(duration)
        m.player_press_use(False)

def do_look(pitch: float, yaw: float):
    m.player_set_orientation(yaw, pitch)

def do_jump(duration: float):
    m.player_press_jump(True)
    time.sleep(duration)
    m.player_press_jump(False)

def do_inventory_action(action_type: str, slot: int = 0):
    if action_type == "select_slot":
        m.player_inventory_select_slot(slot)

def do_execute_command(command: str):
    m.execute(command)

async def audio_stream_task(session):
    p = pyaudio.PyAudio()
    
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
            fmt = "%dh" % count
            shorts = struct.unpack(fmt, data)
            sum_squares = 0.0
            for sample in shorts:
                n = sample / 32768.0
                sum_squares += n * n
            rms = math.sqrt(sum_squares / count)
            if rms > max_rms:
                max_rms = rms

            if time.time() - last_level_check > 2.0:
                if max_rms > 0.01: 
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

async def vision_stream_task(session):
    # Minescript saves to `.minecraft/screenshots`. Assuming __file__ is inside `.minecraft/minescript/`
    minecraft_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    screenshot_dir = os.path.join(minecraft_dir, "screenshots")
    screenshot_path = os.path.join(screenshot_dir, "gemini_vision.png")
    
    while not emergency_stop.is_set():
        try:
            m.screenshot("gemini_vision.png")
            await asyncio.sleep(1.0) # Give Java time to write the screenshot
            
            if os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as f:
                    image_data = f.read()
                
                # Send the image as a standard message. 
                # Bimodal API accepts Content parts in send()
                await session.send(input=types.Content(parts=[types.Part(inline_data=types.Blob(data=image_data, mime_type="image/png"))]))
                
                # Remove the screenshot to avoid sending stale data if next one fails
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass
        except Exception as e:
            m.log(f"Vision task error: {e}")
        
        await asyncio.sleep(4.0)

async def receive_from_gemini(session):
    async for response in session.receive():
        if emergency_stop.is_set():
            break
            
        m.log(f"Received from Gemini: {response}")

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
                    # Background movement doesn't block the sequential action queue
                    threading.Thread(target=do_move, args=(direction, duration), daemon=True).start()
                
                elif name == "hold_action":
                    action_type = args.get("type", "attack")
                    duration = float(args.get("duration", 1.0))
                    await action_queue.put((do_hold_action, (action_type, duration), {}))
                    
                elif name == "look":
                    pitch = float(args.get("pitch", 0.0))
                    yaw = float(args.get("yaw", 0.0))
                    await action_queue.put((do_look, (pitch, yaw), {}))
                
                elif name == "jump":
                    duration = float(args.get("duration", 0.5))
                    await action_queue.put((do_jump, (duration,), {}))
                    
                elif name == "inventory_action":
                    action_type = args.get("action_type", "select_slot")
                    slot = int(args.get("slot", 0))
                    await action_queue.put((do_inventory_action, (action_type, slot), {}))
                    
                elif name == "execute_minescript_command":
                    command = args.get("command", "")
                    await action_queue.put((do_execute_command, (command,), {}))

                responses.append(types.FunctionResponse(
                    name=name,
                    id=call_id,
                    response={"status": "queued"}
                ))
            
            if responses:
                await session.send_tool_response(function_responses=responses)

        server_content = response.server_content
        if server_content is not None:
            if server_content.model_turn is not None:
                # Optional: We could cancel_movement here, but it interrupts long multi-step actions.
                # Only explicitly handled stops should cancel movement now.
                pass

async def run_websocket():
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
                        api_key = content.split("=", 1)[1].strip().strip("'").strip('"')
                    else:
                        api_key = content
        except Exception as e:
            m.log(f"Failed to read gemini_key.txt: {e}")

    if not api_key:
        m.echo_json({"text": "Error: GEMINI_API_KEY not found. Use '\\voice_control <key>' or create 'gemini_key.txt'.", "color": "red"})
        emergency_stop.set()
        return

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    
    tools = [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="move_player",
                description="Moves the player in a given direction for a specified duration in seconds. Does not block other actions.",
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
                name="hold_action",
                description="Performs an action like attack (to break blocks, requires holding for >1s usually) or use (to place blocks/interact).",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "type": types.Schema(type="STRING", description="attack or use"),
                        "duration": types.Schema(type="NUMBER", description="Duration to hold the action in seconds")
                    },
                    required=["type", "duration"]
                )
            ),
            types.FunctionDeclaration(
                name="look",
                description="Changes player orientation.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "pitch": types.Schema(type="NUMBER", description="degrees rotation from the x-z plane (up/down)"),
                        "yaw": types.Schema(type="NUMBER", description="degrees rotation around the y axis (left/right)")
                    },
                    required=["pitch", "yaw"]
                )
            ),
            types.FunctionDeclaration(
                name="jump",
                description="Makes the player jump for a specified duration.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "duration": types.Schema(type="NUMBER", description="Duration to hold jump in seconds")
                    },
                    required=["duration"]
                )
            ),
            types.FunctionDeclaration(
                name="inventory_action",
                description="Selects a hotbar slot (0-8) to equip an item, e.g., blocks to place.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "action_type": types.Schema(type="STRING", description="Always 'select_slot'"),
                        "slot": types.Schema(type="INTEGER", description="Hotbar slot number (0-8)")
                    },
                    required=["action_type", "slot"]
                )
            ),
            types.FunctionDeclaration(
                name="execute_minescript_command",
                description="Executes a Minescript or Minecraft command (e.g. /setblock, /give, \\fill). Useful for building or complex tasks.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "command": types.Schema(type="STRING", description="The command to execute")
                    },
                    required=["command"]
                )
            )
        ])
    ]
    
    config = types.LiveConnectConfig(
        tools=tools, 
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text="You are a Minecraft voice controller. You will receive periodic images of the player's view. You can and should execute MULTIPLE tool calls in sequence to complete complex tasks like gathering wood and building a house. For example, to chop a tree: look at it, walk to it, then use hold_action(attack, 3.0). To build: select block slot, look down, hold_action(use, 0.5), jump, etc. DO NOT narrate extensively, just act.")]
        )
    )
    
    try:
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
            m.echo_json({"text": "Connected to Gemini 3.1 Live API with Vision.", "color": "green"})
            send_task = asyncio.create_task(audio_stream_task(session))
            receive_task = asyncio.create_task(receive_from_gemini(session))
            vision_task = asyncio.create_task(vision_stream_task(session))
            executor_task = asyncio.create_task(action_executor())
            
            await asyncio.gather(send_task, receive_task, vision_task, executor_task)
    except Exception as e:
        m.echo_json({"text": f"Error connecting to Gemini: {e}", "color": "red"})
        emergency_stop.set()

def main():
    m.echo("Starting Voice Control with Vision... (Press Shift to Stop)")
    
    stop_thread = threading.Thread(target=monitor_emergency_stop, daemon=True)
    stop_thread.start()
    
    def run_loop():
        asyncio.run(run_websocket())
        
    ws_thread = threading.Thread(target=run_loop, daemon=True)
    ws_thread.start()
    
    while not emergency_stop.is_set():
        time.sleep(0.5)
        
    m.echo("Voice Control terminated.")

if __name__ == "__main__":
    main()
