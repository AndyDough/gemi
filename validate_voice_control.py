import sys
import os
import asyncio
from google import genai
from google.genai import types

# Mock Minescript
class MockMinescript:
    def echo(self, msg): pass
    def log(self, msg): pass
    def player_position(self): return [0, 0, 0]
    def getblocklist(self, pos): return ["air"] * len(pos)
    def player_get_targeted_block(self, max_distance=5): return None
    def player_look_at(self, x, y, z): pass
    def player_press_forward(self, state): pass
    def player_press_attack(self, state): pass
    def player_press_use(self, state): pass
    def player_set_orientation(self, yaw, pitch): pass

sys.modules['minescript'] = MockMinescript()

async def test_connection(config_variant):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            with open("gemini_key.txt", "r") as f:
                api_key = f.read().strip().split("=")[-1].strip("'\"")
        except: pass
    
    client = genai.Client(api_key=api_key, http_options={'api_version': 'v1alpha'})
    
    print(f"Testing config: {config_variant['name']}")
    try:
        async with client.aio.live.connect(model="gemini-3.1-flash-live-preview", config=config_variant['config']) as session:
            print(f"  SUCCESS: {config_variant['name']} connected!")
            return True
    except Exception as e:
        print(f"  FAIL: {config_variant['name']} error: {e}")
        return False

async def main():
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name="find_nearby_trees", description="Get log coords.", parameters=types.Schema(type="OBJECT", properties={})),
        types.FunctionDeclaration(name="move_to", description="Walk to coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="look_at", description="Aim at coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER")}, required=["x","y","z"])),
        types.FunctionDeclaration(name="hold_action", description="Attack/Use.", parameters=types.Schema(type="OBJECT", properties={"type": types.Schema(type="STRING"), "duration": types.Schema(type="NUMBER")}, required=["type", "duration"])),
        types.FunctionDeclaration(name="stop", description="Stop all.", parameters=types.Schema(type="OBJECT", properties={}))
    ])]

    variants = [
        {
            "name": "Audio + All Tools",
            "config": types.LiveConnectConfig(
                tools=tools,
                system_instruction=types.Content(parts=[types.Part(text="You are a robot.")]),
                response_modalities=["AUDIO"]
            )
        },
        {
            "name": "Audio + Simplified Tools",
            "config": types.LiveConnectConfig(
                tools=[types.Tool(function_declarations=[
                    types.FunctionDeclaration(name="move_to", description="Walk to coord.", parameters=types.Schema(type="OBJECT", properties={"x":types.Schema(type="NUMBER"),"y":types.Schema(type="NUMBER"),"z":types.Schema(type="NUMBER")}, required=["x","y","z"]))
                ])],
                system_instruction=types.Content(parts=[types.Part(text="You are a robot.")]),
                response_modalities=["AUDIO"]
            )
        }
    ]

    for v in variants:
        await test_connection(v)
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
