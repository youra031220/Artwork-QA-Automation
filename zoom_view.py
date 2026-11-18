"""Click-to-zoom viewer for the full PDF page (runs entirely in the browser).

The page is rendered once at high resolution (long side ZOOM_SIDE px) and sent
as a JPEG. Every click zooms in around the clicked point; the wheel zooms,
the wheel zooms smoothly, dragging pans, double-click (or '원래 크기') resets. No Streamlit rerun happens
while zooming, so it is instant.
"""
import base64
import html
import io

VERSION = 4               # bump when the viewer changes (Cloud reloads it)
ZOOM_SIDE = 4400          # long side of the zoomable render (px)
VIEW_WIDTH_GUESS = 680    # approximate width of the right-hand column (px)
MAX_VIEW_HEIGHT = 780


def viewer_height(width, height):
    """iframe height: the fitted page plus the toolbar."""
    fitted = VIEW_WIDTH_GUESS * height / max(1, width)
    return int(min(MAX_VIEW_HEIGHT, max(320, fitted))) + 44


def zoom_html(image, caption=""):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=82)
    data = base64.b64encode(buffer.getvalue()).decode()
    height = viewer_height(image.width, image.height) - 44
    return f"""
<div id="zv" style="font-family:sans-serif;">
  <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;font-size:13px;">
    <button id="zin" title="확대">＋</button>
    <button id="zout" title="축소">－</button>
    <button id="zleft" title="왼쪽으로 90° 돌리기">⟲ 90°</button>
    <button id="zright" title="오른쪽으로 90° 돌리기 (두 번 = 거꾸로 보기)">⟳ 90°</button>
    <button id="zreset" title="회전·확대를 처음 상태로">원래 크기</button>
    <span id="zlabel" style="color:#666;margin-left:4px;">100%</span>
    <span style="color:#888;margin-left:auto;">클릭·휠: 확대/축소 · 드래그: 이동 · 더블클릭: 화면 맞춤</span>
  </div>
  <div id="zbox" style="position:relative;overflow:hidden;height:{height}px;border:1px solid #ddd;
       border-radius:4px;background:#f6f6f6;cursor:zoom-in;touch-action:none;user-select:none;">
    <div id="zcont" style="position:absolute;left:0;top:0;transform-origin:0 0;">
      <img id="zimg" src="data:image/jpeg;base64,{data}" draggable="false"
           style="position:absolute;transform-origin:50% 50%;max-width:none;" alt="PDF 전체 페이지">
    </div>
  </div>
  <div style="color:#888;font-size:12px;margin-top:4px;">{html.escape(caption)}</div>
</div>
<style>#zv button{{border:1px solid #ccc;background:#fff;border-radius:4px;padding:2px 9px;cursor:pointer;}}
#zv button:hover{{background:#f0f0f0;}}</style>
<script>
(function(){{
  const box=document.getElementById('zbox'), img=document.getElementById('zimg'),
        cont=document.getElementById('zcont'), label=document.getElementById('zlabel');
  let fit=1, s=1, tx=0, ty=0, rot=0, drag=null, moved=false;
  const MAX=1.6;   // up to 1.6 image pixels per screen pixel (beyond that it only blurs)
  // The rotated page is laid out in a box of the rotated size (cw x ch);
  // zoom and pan work on that box, so they behave the same at any angle.
  const side=()=>rot%180!==0;
  const cw=()=>side()?img.naturalHeight:img.naturalWidth, ch=()=>side()?img.naturalWidth:img.naturalHeight;
  function layout(){{
    cont.style.width=cw()+'px'; cont.style.height=ch()+'px';
    img.style.left=(cw()-img.naturalWidth)/2+'px'; img.style.top=(ch()-img.naturalHeight)/2+'px';
    img.style.transform=`rotate(${{rot}}deg)`;
  }}
  function clamp(){{
    const w=cw()*s, h=ch()*s, W=box.clientWidth, H=box.clientHeight;
    tx = w<=W ? (W-w)/2 : Math.min(0, Math.max(W-w, tx));
    ty = h<=H ? (H-h)/2 : Math.min(0, Math.max(H-h, ty));
  }}
  function draw(){{ clamp(); cont.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;
    label.textContent=Math.round(s/fit*100)+'%'+(rot?` · ${{rot}}°`:''); box.style.cursor = s>=MAX-1e-6 ? 'grab' : 'zoom-in'; }}
  function reset(){{ layout(); fit=Math.min(box.clientWidth/cw(), box.clientHeight/ch());
    s=fit; tx=0; ty=0; draw(); }}
  function turn(deg){{ rot=(rot+deg+360)%360; animate(false); reset(); }}
  function animate(on){{ cont.style.transition = on ? 'transform 0.18s ease-out' : 'none'; }}
  function zoomAt(factor, cx, cy){{
    const ns=Math.max(fit, Math.min(MAX, s*factor));
    tx = cx-(cx-tx)*ns/s; ty = cy-(cy-ty)*ns/s; s=ns; draw();
  }}
  function point(e){{ const r=box.getBoundingClientRect(); return [e.clientX-r.left, e.clientY-r.top]; }}
  box.addEventListener('pointerdown', e=>{{ drag=[e.clientX,e.clientY,tx,ty]; moved=false; box.setPointerCapture(e.pointerId); }});
  box.addEventListener('pointermove', e=>{{ if(!drag) return;
    const dx=e.clientX-drag[0], dy=e.clientY-drag[1];
    if(Math.abs(dx)+Math.abs(dy)>4) moved=true;
    if(moved){{ animate(false); tx=drag[2]+dx; ty=drag[3]+dy; box.style.cursor='grabbing'; draw(); }} }});
  box.addEventListener('pointerup', e=>{{ const wasDrag=moved; drag=null;
    if(!wasDrag && e.detail<2){{ const [x,y]=point(e); animate(true); zoomAt(1.8,x,y); }} else draw(); }});
  box.addEventListener('dblclick', e=>{{ e.preventDefault(); animate(true); reset(); }});
  // Wheel / trackpad zoom, proportional to the scroll amount so it is smooth.
  box.addEventListener('wheel', e=>{{ e.preventDefault(); const [x,y]=point(e);
    const unit = e.deltaMode===1 ? 33 : (e.deltaMode===2 ? 400 : 1);
    const dy = Math.max(-120, Math.min(120, e.deltaY*unit));
    animate(false); zoomAt(Math.exp(-dy*0.0025), x, y); }}, {{passive:false}});
  document.getElementById('zin').onclick=()=>{{ animate(true); zoomAt(1.8, box.clientWidth/2, box.clientHeight/2); }};
  document.getElementById('zout').onclick=()=>{{ animate(true); zoomAt(1/1.8, box.clientWidth/2, box.clientHeight/2); }};
  document.getElementById('zreset').onclick=()=>{{ rot=0; animate(true); reset(); }};
  document.getElementById('zleft').onclick=()=>turn(-90);
  document.getElementById('zright').onclick=()=>turn(90);
  if(img.complete) reset(); else img.onload=reset;
  window.addEventListener('resize', reset);
}})();
</script>
"""
