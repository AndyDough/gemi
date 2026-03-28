import sys, os, time, threading, asyncio, pyaudio, math
import minescript as m
from google import genai
from google.genai import types

# Audio Config
FORMAT, CHANNELS, RATE, CHUNK = pyaudio.paInt16, 1, 16000, 512
emergency_stop, interrupt_signal = threading.Event(), threading.Event()

# Track active tool tasks
active_tool_tasks = set()

async def audio_reader(p, aq):
    stream = None
    try:
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        m.log("Audio: Reader stream opened.")
        while not emergency_stop.is_set():
            data = await asyncio.to_thread(stream.read, CHUNK, exception_on_overflow=False)
            if not data: continue
            
            # Maintain real-time: if queue is full, drop the oldest packet
            if aq.full():
                try: aq.get_nowait()
                except: pass
            await aq.put(data)
    except Exception as e:
        m.log(f"Audio Reader Error: {e}")
    finally:
        if stream:
            m.log("Audio: Closing reader stream...")
            try:
                stream.stop_stream()
                stream.close()
            except: pass
            m.log("Audio: Reader stream closed.")

def get_nearby_interesting_blocks():
    try:
        px, py, pz = [int(v) for v in m.player_position()]
        radius = 10
        positions = []
        for x in range(px-radius, px+radius):
            for z in range(pz-radius, pz+radius):
                for y in range(py-1, py+6):
                    positions.append([x, y, z])
        
        block_types = m.getblocklist(positions)
        unique_blocks = set()
        boring = {"minecraft:air", "minecraft:cave_air", "minecraft:grass_block", "minecraft:dirt", "minecraft:stone", "minecraft:water", "minecraft:lava", "minecraft:tall_grass", "minecraft:grass", "minecraft:poppy", "minecraft:dandelion", "minecraft:oak_leaves", "minecraft:birch_leaves", "minecraft:spruce_leaves", "minecraft:jungle_leaves", "minecraft:acacia_leaves", "minecraft:dark_oak_leaves", "minecraft:mangrove_leaves", "minecraft:cherry_leaves", "minecraft:azalea_leaves", "minecraft:flowering_azalea_leaves"}
        
        for b in block_types:
            if b.lower() not in boring:
                name = b.lower().replace("minecraft:", "")
                unique_blocks.add(name)
        
        return sorted(list(unique_blocks))
    except Exception as e:
        m.log(f"Initial Scan Error: {e}")
        return []

def do_equip(item_name):
    m.echo(f"§7Equipping {item_name}...")
    inventory = m.player_inventory()
    for item in inventory:
        if item.slot is not None and 0 <= item.slot <= 8:
            if item_name.lower() in item.item.lower():
                m.player_inventory_select_slot(item.slot)
                m.echo(f"§aEquipped {item.item}")
                return True
    m.echo(f"§cCould not find {item_name} in hotbar")
    return False

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

def do_chop(tx, ty, tz, duration=10.0):
    ix, iy, iz = int(tx), int(ty), int(tz)
    # Check if block still exists
    block = m.getblock(ix, iy, iz).lower()
    if "air" in block:
        m.echo(f"§7Block at {ix},{iy},{iz} is already gone. Skipping.")
        return

    m.echo(f"§6Chopping block at {ix}, {iy}, {iz}...")
    target_x, target_y, target_z = float(tx) + 0.5, float(ty) + 0.5, float(tz) + 0.5
    m.player_look_at(target_x, target_y, target_z)
    m.player_press_attack(True)
    
    start = time.time()
    while time.time() - start < duration:
        if interrupt_signal.is_set() or emergency_stop.is_set(): break
        # Early break if block is destroyed mid-action
        # Use a more explicit check for air to avoid finishing too early
        current_block = m.getblock(ix, iy, iz).lower()
        if "air" in current_block:
            break
        m.player_look_at(target_x, target_y, target_z)
        time.sleep(0.05)
    
    # Tiny buffer to ensure the final break packet is processed
    time.sleep(0.2)
    m.player_press_attack(False)
    m.echo("§aChop complete.")

def find_blocks(query):
    try:
        query = query.lower().replace(" ", "_")
        px, py, pz = [int(v) for v in m.player_position()]
        radius = 10
        found_blocks = []
        positions = []
        for x in range(px-radius, px+radius):
            for z in range(pz-radius, pz+radius):
                for y in range(py-1, py+6):
                    positions.append([x, y, z])
        
        block_types = m.getblocklist(positions)
        for i, b_type in enumerate(block_types):
            b_lower = b_type.lower()
            if query in b_lower:
                found_blocks.append({"x": positions[i][0], "y": positions[i][1], "z": positions[i][2]})
        
        sorted_blocks = sorted(found_blocks, key=lambda t: (t['x']-px)**2 + (t['y']-py)**2 + (t['z']-pz)**2)
        m.echo(f"§bDetected {len(sorted_blocks)} blocks matching '{query}'.")
        return sorted_blocks[:15]
    except Exception as e:
        m.log(f"Scan Error: {e}")
        return []

async def audio_stream_task(aq, session):
    # Clear stale audio data when session starts
    while not aq.empty():
        try: aq.get_nowait()
        except: break
        
    try:
        while not emergency_stop.is_set():
            data = await aq.get()
            await session.send_realtime_input(audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))
    except Exception as e:
        m.log(f"Audio Streamer Error: {e}")

async def handle_tool_call(session, fc, aq):
    name, args, call_id = fc.name, fc.args, fc.id
    res_body = {"status": "ok"}
    try:
        if name == "find_nearby_blocks":
            res_body["blocks"] = find_blocks(args.get('block_type', 'log'))
        elif name == "equip_item":
            fut = asyncio.get_event_loop().create_future()
            await aq.put((do_equip, (args['item_name'],), {}, fut))
            await fut
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
        # Don't send responses for cancelled tasks as the turn is likely already gone.
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
            m.log(f"Receiver: Data received: server_content={bool(response.server_content)}, tool_call={bool(response.tool_call)}")
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
                
                # Check for audio content to ensure it's not a turn-ending message
                if response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data:
                            # Process model audio if we wanted to hear it
                            pass
            
            if response.tool_call:
                m.log(f"Receiver: Tool calls received: {[fc.name for fc in response.tool_call.function_calls]}")
                for fc in response.tool_call.function_calls:
                    task = asyncio.create_task(handle_tool_call(session, fc, aq))
                    active_tool_tasks.add(task)
                    task.add_done_callback(active_tool_tasks.discard)
        m.log("Receiver: Loop ended naturally.")
    except Exception as e:
        m.log(f"Receiver Error: {e}")
    finally:
        m.log("Receiver: Loop task exiting.")

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

    # Initial Scan
    m.echo("§7Scanning nearby blocks...")
    nearby_blocks = get_nearby_interesting_blocks()
    if nearby_blocks:
        m.echo(f"§bDetected: {', '.join(nearby_blocks)}")
    else:
        m.echo("§eNo interesting blocks nearby.")

    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name="equip_item", description="Select tool in hotbar.", parameters=types.Schema(type="OBJECT", properties={"item_name":types.Schema(type="STRING")}, required=["item_name"])),
        types.FunctionDeclaration(name="find_nearby_blocks", description="Get coordinates of specific block types.", parameters=types.Schema(type="OBJECT", properties={"block_type":types.Schema(type="STRING")}, required=["block_type"])),
        types.FunctionDeclaration(name="move_to", description="Walk to coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="chop_at", description="Break block at coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER"),"duration":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="stop", description="Emergency stop.", parameters=types.Schema(type="OBJECT", properties={}))
    ])]
    
    nearby_str = f"Nearby interesting blocks: {', '.join(nearby_blocks)}" if nearby_blocks else "No interesting blocks detected nearby yet."
    prompt = f"You are a silent Minecraft bot. {nearby_str}. Listen for the user's command to break one of these blocks. 1. Use equip_item to select the best tool (e.g. iron_pickaxe for ores/blocks, iron_axe for wood). 2. Use find_nearby_blocks(block_type=...) to locate the requested block. 3. move_to then chop_at. 4. Re-scan and repeat until the requested blocks are gone. If the user talks, listen carefully and change your plan immediately."
    config = types.LiveConnectConfig(tools=tools, system_instruction=types.Content(parts=[types.Part(text=prompt)]), response_modalities=["AUDIO"])
    
    # Start the executor once, globally for this script run
    asyncio.create_task(action_executor(aq))
    
    p = pyaudio.PyAudio()
    audio_queue = asyncio.Queue(maxsize=100)
    # Start the persistent audio reader once
    asyncio.create_task(audio_reader(p, audio_queue))
    
    try:
        while not emergency_stop.is_set():
            try:
                async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config) as session:
                    m.echo("§aRobot Ready.")
                    m.log("Session: Connected.")
                    t1 = asyncio.create_task(audio_stream_task(audio_queue, session))
                    t2 = asyncio.create_task(receive_from_gemini(session, aq))
                    # Wait for either communication task to finish
                    done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
                    # If one task ends, cancel the other immediately
                    for task in pending: task.cancel()
                    # Ensure pending tasks are finished canceling
                    if pending: await asyncio.gather(*pending, return_exceptions=True)
                    
            except asyncio.CancelledError: break
            except Exception as e:
                m.log(f"Session Error: {e}")
                if emergency_stop.is_set(): break
                # Only echo Reconnecting if it wasn't a "clean" end
                if "ping timeout" in str(e) or "internal error" in str(e):
                    m.echo("§eConnection issue. Reconnecting...")
                await asyncio.sleep(0.5)
    finally:
        m.log("Audio: Terminating PyAudio system.")
        p.terminate()

if __name__ == "__main__":
    threading.Thread(target=monitor_emergency_stop, daemon=True).start()
    asyncio.run(run_websocket())
