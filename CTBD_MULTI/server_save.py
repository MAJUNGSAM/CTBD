import socketio
import uvicorn
import json
import os
from fastapi import FastAPI

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
app_combined = socketio.ASGIApp(sio, app)

SAVE_FILE = "world_save.json"

# 서버 시작 시 저장된 월드 로드
if os.path.exists(SAVE_FILE):
    with open(SAVE_FILE, "r") as f: world_data = json.load(f)
    print("저장된 월드를 불러왔습니다.")
else:
    world_data = [[ [["grass"]] for _ in range(30)] for _ in range(30)]

players = {}

@sio.event
async def connect(sid, environ):
    await sio.emit('init_world', world_data, room=sid)

@sio.event
async def update_position(sid, data):
    players[sid] = data
    await sio.emit('remote_update', {"sid": sid, "pos": data}, skip_sid=sid)

@sio.event
async def sync_world(sid, data):
    global world_data
    world_data = data
    with open(SAVE_FILE, "w") as f: json.dump(world_data, f)
    await sio.emit('world_updated', world_data, skip_sid=sid)

@sio.event
async def disconnect(sid):
    if sid in players: del players[sid]
    await sio.emit('player_left', sid)

if __name__ == "__main__":
    uvicorn.run(app_combined, host="0.0.0.0", port=8000)
