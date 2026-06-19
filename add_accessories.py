import cv2
import numpy as np
import mediapipe as mp
from PIL import Image, ImageDraw, ImageOps

INPUT_PATH = "/root/.claude/uploads/c113c84b-38f7-5932-9d34-441a64121592/b8ac670d-9251.jpg"
OUTPUT_PATH = "/home/user/auto_prepa/output_with_accessories.jpg"

# Load with EXIF orientation correction
pil_img = ImageOps.exif_transpose(Image.open(INPUT_PATH)).convert("RGBA")
img_cv = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)

h, w = img_cv.shape[:2]
print(f"Image size: {w}x{h}")

# Face mesh detection
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True, max_num_faces=1,
    refine_landmarks=True, min_detection_confidence=0.5
)
results = face_mesh.process(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))

if not results.multi_face_landmarks:
    print("No face detected!")
    exit(1)

lms = results.multi_face_landmarks[0].landmark

def pt(idx):
    return (int(lms[idx].x * w), int(lms[idx].y * h))

# Key landmarks
left_eye_outer  = pt(33)
left_eye_inner  = pt(133)
right_eye_inner = pt(362)
right_eye_outer = pt(263)
left_eye_top    = pt(159)
left_eye_bot    = pt(145)
right_eye_top   = pt(386)
right_eye_bot   = pt(374)

# Eye centers
lec = ((left_eye_outer[0] + left_eye_inner[0]) // 2,
       (left_eye_outer[1] + left_eye_inner[1]) // 2)
rec = ((right_eye_inner[0] + right_eye_outer[0]) // 2,
       (right_eye_inner[1] + right_eye_outer[1]) // 2)

# Nose and face boundary for mask
nose_tip   = pt(1)
nose_bot   = pt(94)
left_cheek = pt(234)
right_cheek= pt(454)
chin       = pt(152)

print(f"Left eye center: {lec}")
print(f"Right eye center: {rec}")
print(f"Nose tip: {nose_tip}, Chin: {chin}")

# ── GLASSES ──────────────────────────────────────────────
draw = ImageDraw.Draw(pil_img)

# Lens radius = ~eye width; round glasses are circular
left_eye_w  = abs(left_eye_outer[0] - left_eye_inner[0])
right_eye_w = abs(right_eye_outer[0] - right_eye_inner[0])
lens_r = int((left_eye_w + right_eye_w) / 2 * 0.9)

# Vertical offset so glasses sit naturally on eyes
oy = int(lens_r * 0.05)
lc = (lec[0], lec[1] + oy)
rc = (rec[0], rec[1] + oy)

frame_col  = (60, 60, 70, 255)    # dark grey wire frame
lens_col   = (15, 15, 15, 130)    # dark tinted lenses (semi-opaque)
fw = max(3, lens_r // 12)         # thin wire frame

# Lens tint fill
for cx, cy in [lc, rc]:
    draw.ellipse([cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r],
                 fill=lens_col)

# Lens frames
for cx, cy in [lc, rc]:
    draw.ellipse([cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r],
                 outline=frame_col, width=fw)

# Nose bridge
bx1 = lc[0] + lens_r
bx2 = rc[0] - lens_r
by  = (lc[1] + rc[1]) // 2
draw.line([(bx1, by), (bx2, by)], fill=frame_col, width=fw)

# Temples
le_ear = pt(234)
re_ear = pt(454)
draw.line([(lc[0] - lens_r, lc[1]), (le_ear[0] - 20, lc[1])],
          fill=frame_col, width=fw)
draw.line([(rc[0] + lens_r, rc[1]), (re_ear[0] + 20, rc[1])],
          fill=frame_col, width=fw)

# ── MASK ─────────────────────────────────────────────────
mask_top    = nose_tip[1] - int(abs(chin[1] - nose_tip[1]) * 0.05)
mask_bottom = chin[1] + int(abs(chin[1] - nose_tip[1]) * 0.20)
face_w = abs(right_cheek[0] - left_cheek[0])
mask_left   = left_cheek[0]  - int(face_w * 0.04)
mask_right  = right_cheek[0] + int(face_w * 0.04)
mask_h      = mask_bottom - mask_top
mask_w      = mask_right - mask_left

mask_layer = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
md = ImageDraw.Draw(mask_layer)

# Main mask body
r_corner = max(20, mask_w // 6)
md.rounded_rectangle(
    [mask_left, mask_top, mask_right, mask_bottom],
    radius=r_corner,
    fill=(20, 20, 20, 245)
)

# Subtle crease/seam in the middle (horizontal line)
seam_y = mask_top + mask_h // 2
md.line([(mask_left + 10, seam_y), (mask_right - 10, seam_y)],
        fill=(10, 10, 10, 180), width=2)

# Ear loops
loop_y = mask_top + mask_h // 3
md.line([(mask_left, loop_y), (left_cheek[0] - 30, loop_y)],
        fill=(50, 50, 50, 200), width=3)
md.line([(mask_right, loop_y), (right_cheek[0] + 30, loop_y)],
        fill=(50, 50, 50, 200), width=3)

pil_img = Image.alpha_composite(pil_img, mask_layer)

# Redraw glasses on top of mask
draw2 = ImageDraw.Draw(pil_img)
for cx, cy in [lc, rc]:
    draw2.ellipse([cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r],
                  fill=lens_col)
for cx, cy in [lc, rc]:
    draw2.ellipse([cx - lens_r, cy - lens_r, cx + lens_r, cy + lens_r],
                  outline=frame_col, width=fw)
draw2.line([(bx1, by), (bx2, by)], fill=frame_col, width=fw)
draw2.line([(lc[0] - lens_r, lc[1]), (le_ear[0] - 20, lc[1])],
           fill=frame_col, width=fw)
draw2.line([(rc[0] + lens_r, rc[1]), (re_ear[0] + 20, rc[1])],
           fill=frame_col, width=fw)

# Save
pil_img.convert("RGB").save(OUTPUT_PATH, quality=95)
print(f"Saved to {OUTPUT_PATH}")
