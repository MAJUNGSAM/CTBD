import eventlet
import socketio
import json
import os

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio)

# 데이터 저장 파일 경로
DATA_FILE = "world_save.json"

# 월드 데이터 초기화
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
    print(f"접속: {sid}")
    # 접속 시 현재 월드 전체 데이터를 보내줌
    await sio.emit("update_world", world_data, to=sid)

@sio.event
async def disconnect(sid):
    if sid in players:
        del players[sid]
    await sio.emit("player_update", players)
    print(f"퇴장: {sid}")

@sio.event
async def move(sid, data):
    players[sid] = data
    await sio.emit("player_update", players)

# --- 블록 설치 처리 ---
@sio.event
async def place_block(sid, data):
    # data: {'r': r, 'c': c, 'z': z, 'name': name}
    world_data["blocks"].append(data)
    save_data()
    # 모든 사람에게 업데이트된 월드 전송
    await sio.emit("update_world", world_data)

# --- 블록 파괴 처리 ---
@sio.event
async def remove_block(sid, data):
    # data: {'r': r, 'c': c}
    target_r, target_c = data['r'], data['c']
    # 해당 위치의 가장 위에 있는 블록 찾아서 삭제
    for i in range(len(world_data["blocks"]) - 1, -1, -1):
        b = world_data["blocks"][i]
        if b['r'] == target_r and b['c'] == target_c:
            world_data["blocks"].pop(i)
            break
    save_data()
    await sio.emit("update_world", world_data)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=10000)
