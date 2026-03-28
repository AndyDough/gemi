import sys, os, time, threading, asyncio, pyaudio, math
import minescript as m
from google import genai
from google.genai import types

# Audio Config
FORMAT, CHANNELS, RATE, CHUNK = pyaudio.paInt16, 1, 16000, 512
emergency_stop, interrupt_signal = threading.Event(), threading.Event()

# Track active tool tasks
active_tool_tasks = set()

def monitor_emergency_stop():
    try:
        with m.EventQueue() as eq:
            eq.register_key_listener()
            while not emergency_stop.is_set():
                ev = eq.get(block=True, timeout=0.1)
                if ev.type == "KEY" and ev.key == 340 and ev.action == 1:
                    m.echo("§cEmergency Stop!")
                    emergency_stop.set(); interrupt_signal.set()
    except: pass

async def action_executor(aq):
    while not emergency_stop.is_set():
        try:
            try:
                item = await asyncio.wait_for(aq.get(), timeout=0.5)
                func, args, kwargs, future = item
                
                # IMPORTANT: Clear interrupt signal at the VERY start of a new action
                interrupt_signal.clear()
                
                fname = getattr(func, '__name__', 'Task')
                m.log(f"Executor: Starting {fname}")
                
                await asyncio.to_thread(func, *args, **kwargs)
                
                if not future.done():
                    future.set_result(True)
                
                aq.task_done()
                m.log(f"Executor: Finished {fname}")
            except asyncio.TimeoutError: continue
        except Exception as e:
            m.log(f"Exec Error: {e}")
            if 'future' in locals() and not future.done():
                future.set_exception(e)
            await asyncio.sleep(0.1)

def do_move_to(tx, ty, tz):
    tx, ty, tz = float(tx) + 0.5, float(ty) + 0.5, float(tz) + 0.5
    m.echo("§7Moving...")
    while not emergency_stop.is_set() and not interrupt_signal.is_set():
        try:
            px, py, pz = m.player_position()
            dist = math.sqrt((tx-px)**2 + (tz-pz)**2)
            if dist < 1.2: break
            m.player_look_at(tx, py + 1.5, tz)
            m.player_press_forward(True)
            time.sleep(0.1)
        except: break
    m.player_press_forward(False)

def do_chop(tx, ty, tz, duration=5.0):
    ix, iy, iz = int(tx), int(ty), int(tz)
    # Check if log still exists
    block = m.getblock(ix, iy, iz).lower()
    if "log" not in block and "wood" not in block and "stem" not in block:
        m.echo(f"§7Log at {ix},{iy},{iz} is gone. Skipping.")
        return

    m.echo(f"§6Chopping log at {ix}, {iy}, {iz}...")
    target_x, target_y, target_z = float(tx) + 0.5, float(ty) + 0.5, float(tz) + 0.5
    m.player_look_at(target_x, target_y, target_z)
    m.player_press_attack(True)
    
    start = time.time()
    while time.time() - start < duration:
        if interrupt_signal.is_set() or emergency_stop.is_set(): break
        # Early break if log is destroyed mid-action
        if time.time() - start > 0.5 and "air" in m.getblock(ix, iy, iz).lower():
            break
        m.player_look_at(target_x, target_y, target_z)
        time.sleep(0.05)
    
    m.player_press_attack(False)
    m.echo("§aChop complete.")

def find_trees():
    try:
        px, py, pz = [int(v) for v in m.player_position()]
        radius = 10
        trees = []
        positions = []
        for x in range(px-radius, px+radius):
            for z in range(pz-radius, pz+radius):
                for y in range(py-1, py+6):
                    positions.append([x, y, z])
        
        block_types = m.getblocklist(positions)
        for i, b_type in enumerate(block_types):
            b_lower = b_type.lower()
            if "log" in b_lower or "wood" in b_lower or "stem" in b_lower:
                trees.append({"x": positions[i][0], "y": positions[i][1], "z": positions[i][2]})
        
        sorted_trees = sorted(trees, key=lambda t: (t['x']-px)**2 + (t['y']-py)**2 + (t['z']-pz)**2)
        m.echo(f"§bDetected {len(sorted_trees)} logs.")
        return sorted_trees[:15]
    except Exception as e:
        m.log(f"Scan Error: {e}")
        return []

async def audio_stream_task(session):
    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        while not emergency_stop.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
            await asyncio.sleep(0)
    except: pass
    finally: p.terminate()

async def handle_tool_call(session, fc, aq):
    name, args, call_id = fc.name, fc.args, fc.id
    res_body = {"status": "ok"}
    try:
        if name == "find_nearby_trees":
            res_body["trees"] = find_trees()
        elif name == "move_to":
            fut = asyncio.get_event_loop().create_future()
            await aq.put((do_move_to, (args['x'], args['y'], args['z']), {}, fut))
            await fut
        elif name == "chop_at":
            fut = asyncio.get_event_loop().create_future()
            dur = float(args.get("duration", 5.0))
            await aq.put((do_chop, (args['x'], args['y'], args['z'], dur), {}, fut))
            await fut
        elif name == "stop":
            interrupt_signal.set()
            while not aq.empty():
                try: aq.get_nowait(); aq.task_done()
                except asyncio.QueueEmpty: break
    except asyncio.CancelledError:
        # Don't send a response if cancelled, or send an interrupted status
        return
    except Exception as e:
        res_body = {"status": "error", "message": str(e)}
    
    try:
        await session.send_tool_response(function_responses=[types.FunctionResponse(name=name, id=call_id, response=res_body)])
    except: pass

async def receive_from_gemini(session, aq):
    m.log("Receiver: Loop started.")
    try:
        async for response in session.receive():
            if response.server_content:
                if response.server_content.interrupted:
                    m.log("Receiver: GEMINI INTERRUPTED signal received.")
                    interrupt_signal.set()
                    # Clear internal action queue
                    while not aq.empty():
                        try: aq.get_nowait(); aq.task_done()
                        except asyncio.QueueEmpty: break
                    # Cancel all background tool tasks
                    for task in active_tool_tasks:
                        if not task.done(): task.cancel()
                    active_tool_tasks.clear()
                    # RESET INTERRUPT SIGNAL for next command
                    await asyncio.sleep(0.1)
                    interrupt_signal.clear()
                    m.echo("§eReady for new command.")
            
            if response.tool_call:
                m.log(f"Receiver: Tool calls received: {[fc.name for fc in response.tool_call.function_calls]}")
                for fc in response.tool_call.function_calls:
                    task = asyncio.create_task(handle_tool_call(session, fc, aq))
                    active_tool_tasks.add(task)
                    task.add_done_callback(active_tool_tasks.discard)
    except Exception as e:
        m.log(f"Receiver Error: {e}")

async def run_websocket():
    aq = asyncio.Queue()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for path in [os.path.join(script_dir, "gemini_key.txt"), os.path.join(os.path.dirname(os.path.dirname(script_dir)), "gemini_key.txt"), "gemini_key.txt"]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        api_key = f.read().strip().split("=")[-1].strip("'\"")
                        if api_key: break
                except: pass
    if not api_key: m.echo("§cKey Error."); return

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name="find_nearby_trees", description="Get log coordinates.", parameters=types.Schema(type="OBJECT", properties={})),
        types.FunctionDeclaration(name="move_to", description="Walk to coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="chop_at", description="Break log at coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER"),"duration":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="stop", description="Emergency stop.", parameters=types.Schema(type="OBJECT", properties={}))
    ])]
    
    prompt = "You are a silent Minecraft bot. Clear the tree trunk completely. 1. find_nearby_trees. 2. move_to then chop_at. 3. Re-scan and repeat until NO logs are found. If the user talks, listen carefully and change your plan immediately. Always use tools to complete the goal."
    config = types.LiveConnectConfig(tools=tools, system_instruction=types.Content(parts=[types.Part(text=prompt)]), response_modalities=["AUDIO"])
    
    try:
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
            m.echo("§aRobot Ready.")
            await asyncio.gather(audio_stream_task(session), receive_from_gemini(session, aq), action_executor(aq))
    except Exception as e: m.echo(f"§cError: {e}")

if __name__ == "__main__":
    threading.Thread(target=monitor_emergency_stop, daemon=True).start()
    asyncio.run(run_websocket())
