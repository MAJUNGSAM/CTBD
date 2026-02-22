# pygbag: async
import pygame
import sys
import os
import json
import asyncio
import socketio

# 1. 경로 및 환경 설정
BASE_PATH = "assets"
if not os.path.exists(BASE_PATH):
    os.makedirs(BASE_PATH)

sio = socketio.AsyncClient()
remote_players = {}
world_data = None

# 2. 에셋 로더 (원본 엔진 방식 유지)
def load_s(name, colorkey=(255, 255, 255)):
    for ext in ['.png', '.jpg', '.jpeg', '.bmp']:
        path = os.path.join(BASE_PATH, name + ext)
        if os.path.exists(path):
            try:
                img = pygame.image.load(path).convert()
                if colorkey: img.set_colorkey(colorkey)
                return img.convert_alpha()
            except: pass
    return None

# --- 서버 통신 이벤트 ---
@sio.event
async def init_world(data):
    global world_data
    world_data = data

@sio.event
async def world_updated(data):
    global world_data
    world_data = data

@sio.event
async def remote_update(data):
    remote_players[data['sid']] = data['pos']

@sio.event
async def player_left(sid):
    if sid in remote_players: del remote_players[sid]

# --- 원본 엔진 핵심 함수 (좌표 변환) ---
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

def get_tile_info(r, c, world_data, map_size):
    ir, ic = int(r), int(c)
    if 0 <= ir < map_size and 0 <= ic < map_size:
        stack = world_data[ir][ic]
        z_top = len(stack) - 1
        flattened_tiles = [t for layer in stack for t in layer]
        return float(z_top), flattened_tiles
    return 0.0, []

# --- 자동차 클래스 (원본 물리 로직) ---
class PlayerCar:
    def __init__(self, r, c, z):
        self.r, self.c, self.z = float(r), float(c), float(z)
        self.speed = 0.15
        self.dir = "dr"

    def update(self, keys, world_data, map_size, RAMP_BLOCKS, PASS_THROUGH_BLOCKS, ROAD_BLOCKS):
        nr, nc = self.r, self.c
        if keys[pygame.K_a]: nr -= self.speed; self.dir = "ul"
        elif keys[pygame.K_d]: nr += self.speed; self.dir = "dr"
        elif keys[pygame.K_w]: nc -= self.speed; self.dir = "ur"
        elif keys[pygame.K_s]: nc += self.speed; self.dir = "dl"
        
        tz, tiles = get_tile_info(nr, nc, world_data, map_size)
        has_ramp = any(t in RAMP_BLOCKS for t in tiles)
        has_overpass = any(t in PASS_THROUGH_BLOCKS for t in tiles)
        has_road = any(t in ROAD_BLOCKS for t in tiles)
        
        target_z = tz
        if has_ramp: target_z = tz + 1.0
        elif has_overpass: target_z = tz + 1.0 if self.z >= 0.8 else 0.0
        
        if (has_road or tz == 0) and abs(target_z - self.z) <= 1.5:
            self.r, self.c = nr, nc
            self.z += (target_z - self.z) * 0.2
        self.r, self.c = max(0, min(self.r, map_size-0.1)), max(0, min(self.c, map_size-0.1))

# --- 메인 실행 루프 ---
async def main():
    global world_data, sio
    pygame.init()
    WIDTH, HEIGHT = 1024, 768
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    clock = pygame.time.Clock()

    # 1. 원본 변수 로드
    font = pygame.font.SysFont("arial", 18, bold=True)
    main_font = pygame.font.SysFont("arial", 40, bold=True)
    scroll_x = 0
    is_scrolling = False
    game_state = "MAIN" 
    MAX_BLOCKS = 1000
    SLOT_W = 50
    TILE_W, TILE_H, MAP_SIZE, Z_STEP = 64, 32, 30, 24
    
    PASS_THROUGH_BLOCKS = ["block5", "block6","block10"] 
    RAMP_BLOCKS = ["block7", "block8", "block20", "block21"]         
    ROAD_BLOCKS = [f"block{i}" for i in range(1, 20)]

    # 2. 에셋 로드
    img_dict = {f"block{i}": load_s(f"block{i}") for i in range(1, 101)}
    img_dict["grass"] = load_s("grass")
    img_dict["main_screen"] = load_s("main_screen", colorkey=None)
    for d in ["ul", "ur", "dl", "dr"]: img_dict[f"car_{d}"] = load_s(f"car_{d}")
    for c in ["blue", "yellow", "red"]: img_dict[f"traffic_{c}"] = load_s(f"traffic_{c}")

    cam_x, cam_y, zoom, selected_block, rotation = WIDTH//2, 100, 1.0, "block1", 0 
    player_cars, view_mode, is_building = [], "FREE", False
    last_built_pos, drag_start_mouse, drag_start_cam = (-1, -1), None, None
    light_timer, light_state = 0, 0

    # 서버 연결 시도
    try: await sio.connect('http://localhost:8000')
    except: world_data = [[ [["grass"]] for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]

    while True:
        cw, ch = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        keys = pygame.key.get_pressed()

        if game_state == "MAIN":
            bg = img_dict.get("main_screen")
            if bg: screen.blit(pygame.transform.scale(bg, (cw, ch)), (0, 0))
            else: screen.fill((30, 30, 30))
            start_btn = pygame.Rect(cw//2 - 100, ch//2 + 50, 200, 60)
            pygame.draw.rect(screen, (0, 150, 255), start_btn, border_radius=10)
            screen.blit(main_font.render("START", True, (255, 255, 255)), (start_btn.x + 15, start_btn.y + 7))
            for event in pygame.event.get():
                if event.type == pygame.QUIT: return
                if event.type == pygame.MOUSEBUTTONDOWN and start_btn.collidepoint(mx, my): game_state = "PLAY"
            pygame.display.flip()
            await asyncio.sleep(0)
            continue

        if world_data is None: await asyncio.sleep(0.1); continue

        # --- 게임 플레이 로직 ---
        hr, hc = iso_to_cart(mx, my, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y)
        SAVE_RECT = pygame.Rect(cw - 180, 20, 70, 40)
        LOAD_RECT = pygame.Rect(cw - 90, 20, 70, 40)
        bar_rect = pygame.Rect(20, ch-96, cw-40, 8)
        max_scroll = max(0, (MAX_BLOCKS * SLOT_W) - cw + 40)
        handle_w = max(40, (cw / (MAX_BLOCKS * SLOT_W)) * bar_rect.width) if max_scroll > 0 else bar_rect.width
        scroll_range = bar_rect.width - handle_w
        handle_x = bar_rect.x + (-scroll_x / max_scroll * scroll_range) if max_scroll > 0 else bar_rect.x
        handle_rect = pygame.Rect(handle_x, bar_rect.y - 2, handle_w, 12)

        light_timer = (light_timer + 1) % 181
        if light_timer == 180: light_state = (light_state + 1) % 3

        for event in pygame.event.get():
            if event.type == pygame.QUIT: return
            if event.type == pygame.MOUSEBUTTONDOWN:
                is_ui = False
                if handle_rect.collidepoint(mx, my): is_scrolling = True; is_ui = True
                elif SAVE_RECT.collidepoint(mx, my):
                    if sio.connected: await sio.emit('sync_world', world_data)
                    is_ui = True
                if not is_ui and my > ch - 100:
                    for i in range(MAX_BLOCKS):
                        if pygame.Rect(20+i*SLOT_W+scroll_x, ch-80, 44, 44).collidepoint(mx, my):
                            selected_block = f"block{i+1}"; is_ui = True; break
                if not is_ui:
                    if event.button == 1: is_building = True
                    if event.button == 3: drag_start_mouse, drag_start_cam = (mx, my), (cam_x, cam_y)
            if event.type == pygame.MOUSEBUTTONUP:
                is_scrolling = False
                if event.button == 1: 
                    is_building = False; last_built_pos = (-1, -1)
                    if sio.connected: await sio.emit('sync_world', world_data)
                if event.button == 3 and drag_start_mouse:
                    if abs(mx - drag_start_mouse[0]) < 5 and 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE:
                        if len(world_data[hr][hc]) > 1: world_data[hr][hc].pop()
                        if sio.connected: await sio.emit('sync_world', world_data)
                    drag_start_mouse = None
            if event.type == pygame.MOUSEMOTION:
                if is_scrolling:
                    rel_x = max(0, min(mx - bar_rect.x - handle_w/2, scroll_range))
                    scroll_x = -(rel_x / scroll_range) * max_scroll if scroll_range > 0 else 0
                elif drag_start_mouse:
                    cam_x = drag_start_cam[0] + (mx - drag_start_mouse[0])
                    cam_y = drag_start_cam[1] + (my - drag_start_mouse[1])
            if event.type == pygame.MOUSEWHEEL:
                if my > ch - 100: scroll_x = min(0, max(scroll_x + event.y * 70, -max_scroll))
                else:
                    oz = zoom; zoom = max(0.1, min(zoom + event.y * 0.1, 5.0))
                    cam_x = mx - (mx - cam_x) * (zoom/oz); cam_y = my - (my - cam_y) * (zoom/oz)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_v and 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE:
                    z, _ = get_tile_info(hr, hc, world_data, MAP_SIZE)
                    player_cars.append(PlayerCar(hr, hc, z))
                if event.key == pygame.K_r: rotation = (rotation + 1) % 4

        if is_building and 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE:
            if (hr, hc) != last_built_pos:
                if keys[pygame.K_LSHIFT]: world_data[hr][hc][-1].append(selected_block)
                else: world_data[hr][hc].append([selected_block])
                last_built_pos = (hr, hc)

        for p in player_cars:
            p.update(keys, world_data, MAP_SIZE, RAMP_BLOCKS, PASS_THROUGH_BLOCKS, ROAD_BLOCKS)
            if sio.connected: await sio.emit('update_position', {'r':p.r, 'c':p.c, 'z':p.z, 'dir':p.dir})

        # --- 렌더링 ---
        screen.fill((178, 235, 244))
        render_list = []
        for r in range(MAP_SIZE):
            for c in range(MAP_SIZE):
                for z, layer in enumerate(world_data[r][c]):
                    rr, cc = get_rotated_rc(r, c, MAP_SIZE, rotation)
                    render_list.append({'depth': rr+cc+(z*0.1), 'type': 'tile', 'r':r, 'c':c, 'z':z, 'layer':layer})
        for p in player_cars:
            rr, cc = get_rotated_rc(p.r, p.c, MAP_SIZE, rotation)
            render_list.append({'depth': rr+cc+(p.z*0.1)+0.07, 'type': 'car', 'obj': p, 'sid': 'me'})
        for sid, pd in list(remote_players.items()):
            rr, cc = get_rotated_rc(pd['r'], pd['c'], MAP_SIZE, rotation)
            render_list.append({'depth': rr+cc+(pd['z']*0.1)+0.07, 'type': 'car', 'obj': pd, 'sid': sid})
        render_list.sort(key=lambda x: x['depth'])

        for item in render_list:
            if item['type'] == 'tile':
                ix, iy = cart_to_iso(item['r'], item['c'], item['z'], MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
                for t_name in item['layer']:
                    asset = img_dict.get(["traffic_blue", "traffic_yellow", "traffic_red"][light_state]) if t_name == "block9" else img_dict.get(t_name)
                    if asset:
                        aw, ah = int(asset.get_width()*zoom), int(asset.get_height()*zoom)
                        screen.blit(pygame.transform.scale(asset, (aw, ah)), (ix-aw//2, (iy+TILE_H*zoom)-ah))
            else:
                p = item['obj']
                pr, pc, pz, pdir = (p.r, p.c, p.z, p.dir) if item['sid'] == 'me' else (p['r'], p['c'], p['z'], p['dir'])
                cix, ciy = cart_to_iso(pr, pc, pz, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
                c_img = img_dict.get(f"car_{pdir}")
                if c_img:
                    cw_i, ch_i = int(c_img.get_width()*zoom*0.5), int(c_img.get_height()*zoom*0.5)
                    screen.blit(pygame.transform.scale(c_img, (cw_i, ch_i)), (cix-cw_i//2, (ciy+TILE_H*zoom//2)-ch_i))

        # --- 고스트 블록 (미리보기) ---
        if 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE and my < ch - 100:
            gz = len(world_data[hr][hc]) - (1 if keys[pygame.K_LSHIFT] else 0)
            gix, giy = cart_to_iso(hr, hc, gz, MAP_SIZE, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y, Z_STEP)
            ga = img_dict.get(selected_block)
            if ga:
                gw, gh = int(ga.get_width()*zoom), int(ga.get_height()*zoom)
                tmp = ga.copy(); tmp = pygame.transform.scale(tmp, (gw, gh)); tmp.set_alpha(120)
                screen.blit(tmp, (gix-gw//2, (giy+TILE_H*zoom)-gh))

        # --- UI 렌더링 ---
        pygame.draw.rect(screen, (0, 120, 200), SAVE_RECT, border_radius=5)
        screen.blit(font.render("SYNC", True, (255, 255, 255)), (SAVE_RECT.x + 12, SAVE_RECT.y + 10))
        pygame.draw.rect(screen, (35, 38, 44), [0, ch-100, cw, 100])
        pygame.draw.rect(screen, (25, 25, 30), bar_rect, border_radius=3)
        pygame.draw.rect(screen, (0, 150, 255), handle_rect, border_radius=4)
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
