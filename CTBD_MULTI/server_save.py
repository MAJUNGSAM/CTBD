import eventlet
import socketio
import json
import os

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio)

DATA_FILE = "world_save.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        world_data = json.load(f)
else:
    world_data = {"blocks": []}

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(world_data, f)

players = {}

@sio.event
async def connect(sid, environ):
    await sio.emit("update_world", world_data, to=sid)

@sio.event
async def disconnect(sid):
    if sid in players: del players[sid]
    await sio.emit("player_update", players)

@sio.event
async def move(sid, data):
    players[sid] = data
    await sio.emit("player_update", players)

@sio.event
async def place_block(sid, data):
    # If z is 0, we overwrite ground; if z > 0, we stack
    if data['z'] == 0:
        world_data["blocks"] = [b for b in world_data["blocks"] if not (b['r'] == data['r'] and b['c'] == data['c'] and b['z'] == 0)]
    world_data["blocks"].append(data)
    save_data()
    await sio.emit("update_world", world_data)

@sio.event
async def remove_block(sid, data):
    tr, tc = data['r'], data['c']
    # Remove the top-most block at (r, c)
    target_idx = -1
    max_z = -1
    for i, b in enumerate(world_data["blocks"]):
        if b['r'] == tr and b['c'] == tc:
            if b['z'] > max_z:
                max_z = b['z']
                target_idx = i
    if target_idx != -1:
        world_data["blocks"].pop(target_idx)
    save_data()
    await sio.emit("update_world", world_data)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=10000)
