# KLayout batch script: render the final GDS to a PNG.
#
#   klayout -b -r scripts/render_layout.py \
#       -rd gds=<run>/final/gds/sa_top.gds -rd out=docs/layout.png
#   optional: -rd width=1600 -rd zoom=x0,y0,x1,y1 (microns) -rd cells=1
#
# Routing layers are drawn in solid colours on a dark background. With
# cells=1 the device layers (diffusion, poly) are drawn too, which is
# useful for a zoomed-in view of the standard cells.
import pya

gds_path = globals().get("gds")
out_path = globals().get("out", "docs/layout.png")
width = int(globals().get("width", 1600))
zoom = globals().get("zoom")
cells = str(globals().get("cells", "0")) == "1"

# (layer, datatype): (fill colour, frame colour)
ROUTING = [
    ((68, 20), 0x3987E5),   # met1
    ((69, 20), 0x1BAF7A),   # met2
    ((70, 20), 0xEDA100),   # met3
    ((71, 20), 0xE87BA4),   # met4
    ((72, 20), 0x9085E9),   # met5
]
DEVICE = [
    ((65, 20), 0x2E7D32),   # diffusion
    ((66, 20), 0xD84343),   # poly
]

lv = pya.LayoutView()
lv.set_config("grid-visible", "false")
lv.set_config("text-visible", "false")
lv.set_config("background-color", "#0E1117")
lv.load_layout(gds_path)
lv.max_hier()
lv.clear_layers()
ly = lv.active_cellview().layout()

def add(ld, colour, alpha_dither):
    lp = pya.LayerPropertiesNode()
    lp.source = f"{ld[0]}/{ld[1]}@1"
    lp.fill_color = colour
    lp.frame_color = colour
    lp.dither_pattern = alpha_dither
    lp.width = 0
    lv.insert_layer(lv.end_layers(), lp)

if cells:
    for ld, c in DEVICE:
        add(ld, c, 0)
for ld, c in ROUTING:
    add(ld, c, 0 if cells else 0)

if zoom:
    x0, y0, x1, y1 = [float(v) for v in zoom.split(",")]
    box = pya.DBox(x0, y0, x1, y1)
    lv.zoom_box(box)
else:
    box = ly.top_cell().dbbox()
    lv.zoom_fit()
height = int(width * box.height() / box.width())
lv.save_image_with_options(out_path, width, height, oversampling=2)
print(f"wrote {out_path}")
