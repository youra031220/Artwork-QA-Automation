"""Click-to-zoom viewer for the full PDF page (runs entirely in the browser).

The page is rendered once at high resolution (long side ZOOM_SIDE px) and sent
as a JPEG. Every click zooms in around the clicked point; the wheel zooms,
dragging pans, double-click (or '원래 크기') resets. No Streamlit rerun happens
while zooming, so it is instant.
"""
import base64
import html
import io

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
    <button id="zreset">원래 크기</button>
    <span id="zlabel" style="color:#666;margin-left:4px;">100%</span>
    <span style="color:#888;margin-left:auto;">클릭: 확대 · 드래그: 이동 · 휠: 확대/축소 · 더블클릭: 원래 크기</span>
  </div>
  <div id="zbox" style="position:relative;overflow:hidden;height:{height}px;border:1px solid #ddd;
       border-radius:4px;background:#f6f6f6;cursor:zoom-in;touch-action:none;user-select:none;">
    <img id="zimg" src="data:image/jpeg;base64,{data}" draggable="false"
         style="position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;" alt="PDF 전체 페이지">
  </div>
  <div style="color:#888;font-size:12px;margin-top:4px;">{html.escape(caption)}</div>
</div>
<style>#zv button{{border:1px solid #ccc;background:#fff;border-radius:4px;padding:2px 9px;cursor:pointer;}}
#zv button:hover{{background:#f0f0f0;}}</style>
<script>
(function(){{
  const box=document.getElementById('zbox'), img=document.getElementById('zimg'), label=document.getElementById('zlabel');
  let fit=1, s=1, tx=0, ty=0, drag=null, moved=false;
  const MAX=1.6;   // up to 1.6 image pixels per screen pixel (beyond that it only blurs)
  function clamp(){{
    const w=img.naturalWidth*s, h=img.naturalHeight*s, W=box.clientWidth, H=box.clientHeight;
    tx = w<=W ? (W-w)/2 : Math.min(0, Math.max(W-w, tx));
    ty = h<=H ? (H-h)/2 : Math.min(0, Math.max(H-h, ty));
  }}
  function draw(){{ clamp(); img.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{s}})`;
    label.textContent=Math.round(s/fit*100)+'%'; box.style.cursor = s>=MAX-1e-6 ? 'grab' : 'zoom-in'; }}
  function reset(){{ fit=Math.min(box.clientWidth/img.naturalWidth, box.clientHeight/img.naturalHeight);
    s=fit; tx=0; ty=0; draw(); }}
  function zoomAt(factor, cx, cy){{
    const ns=Math.max(fit, Math.min(MAX, s*factor));
    tx = cx-(cx-tx)*ns/s; ty = cy-(cy-ty)*ns/s; s=ns; draw();
  }}
  function point(e){{ const r=box.getBoundingClientRect(); return [e.clientX-r.left, e.clientY-r.top]; }}
  box.addEventListener('pointerdown', e=>{{ drag=[e.clientX,e.clientY,tx,ty]; moved=false; box.setPointerCapture(e.pointerId); }});
  box.addEventListener('pointermove', e=>{{ if(!drag) return;
    const dx=e.clientX-drag[0], dy=e.clientY-drag[1];
    if(Math.abs(dx)+Math.abs(dy)>4) moved=true;
    if(moved){{ tx=drag[2]+dx; ty=drag[3]+dy; box.style.cursor='grabbing'; draw(); }} }});
  box.addEventListener('pointerup', e=>{{ const wasDrag=moved; drag=null;
    if(!wasDrag && e.detail<2){{ const [x,y]=point(e); zoomAt(1.8,x,y); }} else draw(); }});
  box.addEventListener('dblclick', e=>{{ e.preventDefault(); reset(); }});
  box.addEventListener('wheel', e=>{{ e.preventDefault(); const [x,y]=point(e);
    zoomAt(e.deltaY<0 ? 1.25 : 0.8, x, y); }}, {{passive:false}});
  document.getElementById('zin').onclick=()=>zoomAt(1.8, box.clientWidth/2, box.clientHeight/2);
  document.getElementById('zout').onclick=()=>zoomAt(1/1.8, box.clientWidth/2, box.clientHeight/2);
  document.getElementById('zreset').onclick=reset;
  if(img.complete) reset(); else img.onload=reset;
  window.addEventListener('resize', reset);
}})();
</script>
"""
