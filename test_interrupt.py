import asyncio
from google.genai import types
from unittest.mock import MagicMock
import sys

# Mock Minescript to run without actual Minecraft
class MockMinescript:
    def echo(self, msg): print("ECHO:", msg)
    def log(self, msg): print("LOG:", msg)
    def player_position(self): return [0, 0, 0]
    def getblocklist(self, pos): return ["minecraft:air"] * len(pos)
    def player_inventory(self): return []
    def player_look_at(self, x, y, z): pass
    def player_press_forward(self, state): pass
    def player_press_attack(self, state): pass
    def player_inventory_select_slot(self, slot): pass
    def getblock(self, x, y, z): return "minecraft:log"
    class EventQueue:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass
        def register_key_listener(self): pass
        def get(self, block, timeout): raise Exception("timeout")

sys.modules['minescript'] = MockMinescript()

# Import the voice control script modules
import minecraft.minescript.voice_control as vc
vc.CHUNK = 512

async def test_sequential_commands():
    aq = asyncio.Queue()
    session = MagicMock()
    
    # Track sent responses
    sent_responses = []
    async def mock_send_tool_response(function_responses):
        sent_responses.extend(function_responses)
        print(f"  [Tool response sent for ID: {function_responses[0].id}, Status: {function_responses[0].response.get('status')}]")
        
    session.send_tool_response = mock_send_tool_response
    
    # Create the executor
    exec_task = asyncio.create_task(vc.action_executor(aq))
    
    print("--- STARTING TEST: Command 1 -> Interrupt -> Command 2 ---")
    
    # STEP 1: Send Command 1
    fc1 = MagicMock()
    fc1.name = "chop_at"
    fc1.args = {"x": 1, "y": 2, "z": 3, "duration": 5.0}
    fc1.id = "call_1"
    
    print("\n1. Sending tool call 'chop_at' (ID: call_1)...")
    tool_task1 = asyncio.create_task(vc.handle_tool_call(session, fc1, aq))
    vc.active_tool_tasks.add(tool_task1)
    
    await asyncio.sleep(0.5) # Let it start
    
    # STEP 2: Simulate Interrupt
    print("\n2. Simulating Gemini interruption signal...")
    vc.interrupt_signal.set()
    
    # Simulate what receive_from_gemini does when interrupted
    while not aq.empty():
        try: aq.get_nowait(); aq.task_done()
        except asyncio.QueueEmpty: break
        
    for t in list(vc.active_tool_tasks):
        if not t.done(): t.cancel()
    vc.active_tool_tasks.clear()
    
    await asyncio.sleep(0.2)
    vc.interrupt_signal.clear()
    print("   Interrupt cleared. Script ready for next command.")
    
    # STEP 3: Send Command 2
    print("\n3. Sending second tool call 'equip_item' (ID: call_2)...")
    fc2 = MagicMock()
    fc2.name = "equip_item"
    fc2.args = {"item_name": "iron_pickaxe"}
    fc2.id = "call_2"
    
    tool_task2 = asyncio.create_task(vc.handle_tool_call(session, fc2, aq))
    vc.active_tool_tasks.add(tool_task2)
    
    # Wait for it to be processed
    await asyncio.sleep(0.5)
    
    print("\n--- RESULTS ---")
    call_1_sent = any(r.id == "call_1" for r in sent_responses)
    call_2_sent = any(r.id == "call_2" for r in sent_responses)
    
    if not call_1_sent:
        print("FAIL: Tool call 1 response was NEVER sent (Gemini would hang).")
    elif not call_2_sent:
        print("FAIL: Tool call 2 was NEVER processed (system is unresponsive).")
    else:
        print("PASS: Both calls were handled correctly!")
        
    vc.emergency_stop.set()
    await exec_task

if __name__ == "__main__":
    asyncio.run(test_sequential_commands())
