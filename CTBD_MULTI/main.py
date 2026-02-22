import pygame
import sys
import os
import asyncio
import socketio

# 1. Configuration
RENDER_SERVER_URL = "https://ctbd.onrender.com" 
sio = socketio.AsyncClient()

pygame.init()
WIDTH, HEIGHT = 1024, 768
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
clock = pygame.time.Clock()

# 2. Variables
font = pygame.font.SysFont("arial", 18, bold=True)
scroll_x = 0
game_state = "PLAY"
MAX_BLOCKS = 100
SLOT_W = 50
MAP_SIZE = 30

# Multiplayer Data
world_data = [[ [["grass"]] for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]
remote_players = {}

# Camera & Control
cam_x, cam_y, zoom, selected_block, rotation = WIDTH//2, 100, 1.0, "block1", 0 
drag_start_mouse, drag_start_cam = None, None

# 3. Assets Load
def load_s(name):
    path = os.path.join("assets", name + ".png")
    if os.path.exists(path):
        return pygame.image.load(path).convert_alpha()
    return None

img_dict = {f"block{i}": load_s(f"block{i}") for i in range(1, MAX_BLOCKS + 1)}
img_dict["grass"] = load_s("grass")
for d in ["ul", "ur", "dl", "dr"]: img_dict[f"car_{d}"] = load_s(f"car_{d}")

# 4. Socket Events
@sio.event
async def connect(): print("Server Connected")

@sio.event
async def update_world(data):
    global world_data
    temp_world = [[ [["grass"]] for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]
    if "blocks" in data:
        for b in data["blocks"]:
            r, c, z, name = b['r'], b['c'], b['z'], b['name']
            if 0 <= r < MAP_SIZE and 0 <= c < MAP_SIZE:
                while len(temp_world[r][c]) <= z: temp_world[r][c].append([])
                temp_world[r][c][z] = [name]
    world_data = temp_world

@sio.event
async def player_update(data):
    global remote_players
    remote_players = data

# 5. Math Functions
def get_rotated_rc(r, c, rot):
    if rot == 1: return c, MAP_SIZE - 1 - r
    if rot == 2: return MAP_SIZE - 1 - r, MAP_SIZE - 1 - c
    if rot == 3: return MAP_SIZE - 1 - c, r
    return r, c

def cart_to_iso(r, c, z, rot, tw, th, zm, cx, cy):
    rr, cc = get_rotated_rc(r, c, rot)
    ix = (rr - cc) * (tw // 2) * zm + cx
    iy = (rr + cc) * (th // 2) * zm + cy - (z * 24 * zm)
    return ix, iy

def iso_to_cart(mx, my, rot, tw, th, zm, cx, cy):
    tx, ty = (mx - cx) / zm, (my - cy) / zm
    rr = (ty / (th / 2) + tx / (tw / 2)) / 2
    cc = (ty / (th / 2) - tx / (tw / 2)) / 2
    if rot == 0: r, c = rr, cc
    elif rot == 1: r, c = MAP_SIZE - 1 - cc, rr
    elif rot == 2: r, c = MAP_SIZE - 1 - rr, MAP_SIZE - 1 - cc
    elif rot == 3: r, c = cc, MAP_SIZE - 1 - rr
    return int(r), int(c)

async def main():
    global cam_x, cam_y, zoom, rotation, selected_block, drag_start_mouse, drag_start_cam, scroll_x
    try: await sio.connect(RENDER_SERVER_URL)
    except: pass

    while True:
        cw, ch = screen.get_size()
        mx, my = pygame.mouse.get_pos()
        keys = pygame.key.get_pressed()
        TILE_W, TILE_H = 64, 32

        screen.fill((178, 235, 244))
        hr, hc = iso_to_cart(mx, my, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y)

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if my > ch - 100: # UI Scroll & Select
                    for i in range(MAX_BLOCKS):
                        if pygame.Rect(20+i*SLOT_W+scroll_x, ch-80, 44, 44).collidepoint(mx, my):
                            selected_block = f"block{i+1}"; break
                else:
                    if event.button == 1: # Left Click: Place or Remove
                        if 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE:
                            if keys[pygame.K_x]: # X key for Delete
                                await sio.emit("remove_block", {"r": hr, "c": hc})
                            else: # Place Block
                                # SHIFT = Stack, No SHIFT = Ground(0)
                                target_z = len(world_data[hr][hc]) if keys[pygame.K_LSHIFT] else 0
                                await sio.emit("place_block", {"r": hr, "c": hc, "z": target_z, "name": selected_block})
                    if event.button == 3: # Right Click: Camera Drag
                        drag_start_mouse, drag_start_cam = (mx, my), (cam_x, cam_y)
            
            if event.type == pygame.MOUSEBUTTONUP: drag_start_mouse = None
            if event.type == pygame.MOUSEMOTION and drag_start_mouse:
                cam_x = drag_start_cam[0] + (mx - drag_start_mouse[0])
                cam_y = drag_start_cam[1] + (my - drag_start_mouse[1])
            if event.type == pygame.MOUSEWHEEL:
                zoom = max(0.2, min(zoom + event.y * 0.1, 3.0))

        # Render World
        render_list = []
        for r in range(MAP_SIZE):
            for c in range(MAP_SIZE):
                for z, layer in enumerate(world_data[r][c]):
                    rr, cc = get_rotated_rc(r, c, rotation)
                    render_list.append({'depth': rr+cc+(z*0.1), 'r':r, 'c':c, 'z':z, 'layer':layer})
        render_list.sort(key=lambda x: x['depth'])

        for item in render_list:
            ix, iy = cart_to_iso(item['r'], item['c'], item['z'], rotation, TILE_W, TILE_H, zoom, cam_x, cam_y)
            for t_name in item['layer']:
                img = img_dict.get(t_name)
                if img:
                    tw, th = int(img.get_width()*zoom), int(img.get_height()*zoom)
                    screen.blit(pygame.transform.scale(img, (tw, th)), (ix-tw//2, iy+TILE_H*zoom-th))

        # Ghost Preview (with SHIFT stacking logic)
        if 0 <= hr < MAP_SIZE and 0 <= hc < MAP_SIZE and my < ch - 100:
            gz = len(world_data[hr][hc]) if keys[pygame.K_LSHIFT] else 0
            gix, giy = cart_to_iso(hr, hc, gz, rotation, TILE_W, TILE_H, zoom, cam_x, cam_y)
            img = img_dict.get(selected_block)
            if img:
                tw, th = int(img.get_width()*zoom), int(img.get_height()*zoom)
                ghost = pygame.transform.scale(img.copy(), (tw, th))
                ghost.set_alpha(128)
                screen.blit(ghost, (gix-tw//2, giy+TILE_H*zoom-th))

        # UI Bar
        pygame.draw.rect(screen, (35, 38, 44), [0, ch-100, cw, 100])
        for i in range(MAX_BLOCKS):
            sx = 20 + i * SLOT_W + scroll_x
            rect = pygame.Rect(sx, ch-80, 44, 44)
            pygame.draw.rect(screen, (0, 150, 255) if selected_block == f"block{i+1}" else (65, 65, 75), rect, border_radius=8)
            icon = img_dict.get(f"block{i+1}")
            if icon: screen.blit(pygame.transform.scale(icon, (36, 36)), (rect.x+4, rect.y+4))

        pygame.display.flip()
        await asyncio.sleep(0)
        clock.tick(60)

asyncio.run(main())

