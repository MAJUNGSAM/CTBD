import pygame
import sys
import os
import json
import asyncio
import socketio

# 1. 서버 및 경로 설정
RENDER_SERVER_URL = "https://ctbd.onrender.com" 
sio = socketio.AsyncClient()
BASE_PATH = "."

pygame.init()
WIDTH, HEIGHT = 1024, 768
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("City Builder - Multiplayer Edition")
clock = pygame.time.Clock()

# 2. 변수 설정
font = pygame.font.SysFont("arial", 18, bold=True)
main_font = pygame.font.SysFont("arial", 40, bold=True)
scroll_x = 0
is_scrolling = False
game_state = "MAIN" 
MAX_BLOCKS = 100
SLOT_W = 50

# 멀티플레이 데이터
remote_players = {} 
MAP_SIZE = 30
world_data = [[ [["grass"]] for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]

PASS_THROUGH_BLOCKS = ["block5", "block6","block10"] 
RAMP_BLOCKS = ["block7", "block8", "block20", "block21"]         
ROAD_BLOCKS = [f"block{i}" for i in range(1, 20)]

# 카메라 및 제어 변수 (복구됨)
cam_x, cam_y, zoom, selected_block, rotation = WIDTH//2, 100, 1.0, "block1", 0 
drag_start_mouse, drag_start_cam = None, None
my_car = None
view_mode, is_building = "FREE", False
light_timer, light_state = 0, 0

# 3. 에셋 로드
def load_s(name, colorkey=(255, 255, 255)):
    path = os.path.join("assets", name + ".png")
    if os.path.exists(path):
        img = pygame.image.load(path).convert()
        if colorkey: img.set_colorkey(colorkey)
        return img.convert_alpha()
    return None

img_dict = {f"block{i}": load_s(f"block{i}") for i in range(1, MAX_BLOCKS + 1)}
img_dict["grass"] = load_s("grass")
img_dict["main_screen"] = load_s("main_screen", colorkey=None)
for d in ["ul", "ur", "dl", "dr"]: img_dict[f"car_{d}"] = load_s(f"car_{d}")
for c in ["blue", "yellow", "red"]: img_dict[f"traffic_{c}"] = load_s(f"traffic_{c}")

# 4. 소켓 이벤트
@sio.event
async def connect(): print("Connected to server!")

@sio.event
async def update_world(data):
    global world_data
    if "blocks" in data:
        for b in data["blocks"]:
            r, c, layer, name = b['r'], b['c'], b['z'], b['name']
            while len(world_data[r][c]) <= layer: world_data[r][c].append([])
            if name not in world_data[r][c][layer]: world_data[r][c][layer].append(name)

@sio.event
async def player_update(data):
    global remote_players
    remote_players = data

# 5. 좌표 변환 함수
def get_rotated_rc(r, c, map_size, rotation):
    if rotation == 1: return c, map_size - 1 - r
    if rotation == 2: return map_size - 1 - r, map_size - 1 - c
    if rotation == 3: return map_size - 1 - c, r
    return r, c

def cart_to_iso(r, c, z, map_size, rotation, tw, th, zoom, cx, cy, z_step):
    rr, cc = get_rotated_rc(r, c, map_size, rotation)
    ix = (rr - cc) * (tw // 2) * zoom + cx
    iy = (rr + cc) * (th // 2) * zoom + cy - (z * z_step * zoom)
    return ix, iy

def iso_to_cart(mx, my, map_size, rotation, tw, th, zoom, cx, cy):
    tx, ty = (mx - cx) / zoom, (my - cy) / zoom
    rr = (ty / (th / 2) + tx / (tw / 2)) / 2
    cc = (ty / (th / 2) - tx / (tw / 2)) / 2
    if rotation == 0: r, c = rr, cc
    elif rotation == 1: r, c = map_size - 1 - cc, rr
    elif rotation == 2: r, c = map_size - 1 - rr, map_size - 1 - cc
    elif rotation == 3: r, c = cc, map_size - 1 - rr
    return int(r), int(c)

class PlayerCar:
    def __init__(self, r, c, z):
        self.r, self.c, self.z = float(r), float(c), float(z)
        self.speed, self.dir = 0.15, "dr"

    async def update(self, keys, world_data, map_size):
        nr, nc, moved = self.r, self.c, False
        if keys[pygame.K_a]: nr -= self.speed; self.dir = "ul"; moved = True
        elif keys[pygame.K_d]: nr += self.speed; self.dir = "dr"; moved = True
        elif keys[pygame.K_w]: nc -= self.speed; self.dir = "ur"; moved = True
        elif keys[pygame.K_s]: nc += self.speed; self.dir = "dl"; moved = True
        
        if moved:
            # 자동차 물리 및 타일 체크 로직 (생략 없이 유지 가능)
            self.r, self.c = nr, nc
            if sio.connected:
                await sio.emit("move", {"r": self.r, "c": self.c, "z": self.z, "dir": self.dir})

# 6. 메인 실행부
async def main():
    global game_state, cam_x, cam_y, zoom, rotation, selected_block, is_building, view_mode, my_car, world_data, drag_start_mouse, drag_start_cam, scroll_x, is_scrolling

    try: await sio.connect(RENDER_SERVER_URL)
    except: pass

    while True:
        cw, ch = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        keys = pygame.key.get_pressed()
        TILE_W, TILE_H, Z_STEP = 64, 32, 24

        if game_state == "MAIN":
            bg = img_dict.get("main_screen")
            if bg: screen.blit(pygame.transform.scale(bg, (cw, ch)), (0, 0))
            start_btn = pygame.Rect(cw//2 - 100, ch//2 + 50, 200, 60)
            pygame.draw.rect(screen, (0, 150, 255), start_btn, border_radius=10)
            screen.blit(main_font.render("START", True, (255, 255, 255)), (start_btn.x + 15, start_btn.y + 7))

            for event in pygame.event.get():
                if event.type == pygame.QUIT: pygame.quit(); sys.exit()
                if event.type == pygame.MOUSEBUTTONDOWN and start_btn.collidepoint(mx, my): game_state = "PLAY"
            pygame.display.flip()
            await asyncio.sleep(0)
            continue

        # --- PLAY 화면 ---
        screen.fill((178, 235, 244))
        hr, hc = iso_to_cart(mx, my, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y)
        
        if view_mode == "FOLLOW" and my_car:
            rr, cc = get_rotated_rc(my_car.r, my_car.c, MAP_SIZE, rotation)
            cam_x = (cw // 2) - (rr - cc) * (TILE_W // 2) * zoom
            cam_y = (ch // 2) - (rr + cc) * (TILE_H // 2) * zoom + (my_car.z * Z_STEP * zoom)

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if my > ch - 100: # UI 영역
                    for i in range(MAX_BLOCKS):
                        if pygame.Rect(20+i*SLOT_W+scroll_x, ch-80, 44, 44).collidepoint(mx, my):
                            selected_block = f"block{i+1}"; break
                else: # 월드 영역
                    if event.button == 1: is_building = True
                    if event.button == 3: # 우클릭 드래그 시작 (복구)
                        drag_start_mouse, drag_start_cam = (mx, my), (cam_x, cam_y)
            if event.type == pygame.MOUSEBUTTONUP:
                is_building = False
                drag_start_mouse = None
            if event.type == pygame.MOUSEMOTION:
                if drag_start_mouse and view_mode == "FREE": # 카메라 이동 (복구)
                    cam_x = drag_start_cam[0] + (mx - drag_start_mouse[0])
                    cam_y = drag_start_cam[1] + (my - drag_start_mouse[1])
            if event.type == pygame.MOUSEWHEEL: # 줌 기능 (복구)
                oz = zoom
                zoom = max(0.1, min(zoom + event.y * 0.1, 5.0))
                if view_mode == "FREE":
                    cam_x = mx - (mx - cam_x) * (zoom/oz)
                    cam_y = my - (my - cam_y) * (zoom/oz)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_v and 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE:
                    my_car = PlayerCar(hr, hc, len(world_data[hr][hc])-1); view_mode = "FOLLOW"
                if event.key == pygame.K_f: view_mode = "FOLLOW" if view_mode == "FREE" else "FREE"
                if event.key == pygame.K_r: rotation = (rotation + 1) % 4

        # 7. 블록 설치 (서버 전송)
        if is_building and 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE and my < ch - 100:
            if sio.connected:
                await sio.emit("place_block", {"r": hr, "c": hc, "z": len(world_data[hr][hc]), "name": selected_block})
            is_building = False 

        if my_car: await my_car.update(keys, world_data, MAP_SIZE)

        # 8. 렌더링 리스트
        render_list = []
        for r in range(MAP_SIZE):
            for c in range(MAP_SIZE):
                for z, layer in enumerate(world_data[r][c]):
                    rr, cc = get_rotated_rc(r, c, MAP_SIZE, rotation)
                    render_list.append({'depth': rr+cc+(z*0.1), 'type': 'tile', 'r':r, 'c':c, 'z':z, 'layer':layer})
        for sid, p in remote_players.items():
            if sid != sio.sid:
                rr, cc = get_rotated_rc(p['r'], p['c'], MAP_SIZE, rotation)
                render_list.append({'depth': rr+cc+(p['z']*0.1)+0.07, 'type': 'remote_car', 'p': p})
        if my_car:
            rr, cc = get_rotated_rc(my_car.r, my_car.c, MAP_SIZE, rotation)
            render_list.append({'depth': rr+cc+(my_car.z*0.1)+0.07, 'type': 'car', 'obj': my_car})
        render_list.sort(key=lambda x: x['depth'])

        for item in render_list:
            if item['type'] == 'tile':
                ix, iy = cart_to_iso(item['r'], item['c'], item['z'], MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
                for t_name in item['layer']:
                    asset = img_dict.get(t_name)
                    if asset:
                        aw, ah = int(asset.get_width()*zoom), int(asset.get_height()*zoom)
                        screen.blit(pygame.transform.scale(asset, (aw, ah)), (ix-aw//2, (iy+TILE_H*zoom)-ah))
            elif item['type'] in ['car', 'remote_car']:
                p = item['obj'] if item['type'] == 'car' else item['p']
                r, c, z, d = (p.r, p.c, p.z, p.dir) if item['type'] == 'car' else (p['r'], p['c'], p['z'], p['dir'])
                cix, ciy = cart_to_iso(r, c, z, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
                c_img = img_dict.get(f"car_{d}")
                if c_img:
                    cw_i, ch_i = int(c_img.get_width()*zoom*0.5), int(c_img.get_height()*zoom*0.5)
                    screen.blit(pygame.transform.scale(c_img, (cw_i, ch_i)), (cix-cw_i//2, (ciy+TILE_H*zoom//2)-ch_i))

        # 9. 고스트 블록 (복구)
        if 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE and my < ch - 100:
            gz = len(world_data[hr][hc])
            gix, giy = cart_to_iso(hr, hc, gz, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
            ga = img_dict.get(selected_block)
            if ga:
                gw, gh = int(ga.get_width()*zoom), int(ga.get_height()*zoom)
                tmp = ga.copy(); tmp = pygame.transform.scale(tmp, (gw, gh)); tmp.set_alpha(120)
                screen.blit(tmp, (gix-gw//2, (giy+TILE_H*zoom)-gh))

        # 10. UI 렌더링 (간소화 유지)
        pygame.draw.rect(screen, (35, 38, 44), [0, ch-100, cw, 100])
        for i in range(MAX_BLOCKS):
            sx = 20 + i * SLOT_W + scroll_x
            if -SLOT_W < sx < cw:
                rect = pygame.Rect(sx, ch-80, 44, 44)
                pygame.draw.rect(screen, (0, 150, 255) if selected_block == f"block{i+1}" else (65, 65, 75), rect, border_radius=8)
                icon = img_dict.get(f"block{i+1}")
                if icon: screen.blit(pygame.transform.scale(icon, (36, 36)), (rect.x+4, rect.y+4))

        pygame.display.flip()
        await asyncio.sleep(0)
        clock.tick(60)

asyncio.run(main())
