import sys, json
from playwright.sync_api import sync_playwright
from shot_brief import brief

key, room = sys.argv[1], sys.argv[2]
b = brief(key, room)
slug = f"{key}-{room.lower().replace(' ','').replace('ó','o').replace('ñ','n')}"
with sync_playwright() as p:
    br = p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader","--no-sandbox"])
    pg = br.new_page(viewport={"width":1024,"height":768}, device_scale_factor=1.5)
    pg.goto("file:///home/claude/plano3d/LM20-3d.html")
    pg.wait_for_function("window.__ready === true", timeout=20000)
    for mode in ("clay", "material"):
        pg.evaluate("""([v,mode,eye,tgt,fov])=>{
            window.__setVariant(v);
            if(mode==='clay') window.__clay(true); else window.__material();
            window.__setEye(eye[0],eye[1],eye[2], tgt[0],tgt[1],tgt[2], fov);
        }""", [key, mode, b["eye"], b["target"], b["fov"]])
        pg.wait_for_timeout(900)
        pg.screenshot(path=f"shots/ctrl-{slug}-{mode}.png")
        print("ok", f"shots/ctrl-{slug}-{mode}.png")
    br.close()
json.dump(b, open(f"shots/brief-{slug}.json","w"), ensure_ascii=False, indent=1)
