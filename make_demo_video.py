from pathlib import Path

import imageio.v2 as imageio
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
FRAME_DIR = ROOT / "video_frames"
OUTPUT_MP4 = ROOT / "demo-video.mp4"

FRAME_DIR.mkdir(exist_ok=True)
for existing in FRAME_DIR.glob("*.png"):
    existing.unlink()

slides = [
    {
        "title": "SPARKS",
        "subtitle": "Public-first hackathon platform",
        "tag": "DISCOVERY · REGISTRATION · JUDGING",
        "bg": "#0b1720",
        "accent": "#63d0a6",
    },
    {
        "title": "Browse events first",
        "subtitle": "Public directory, search, and filters",
        "tag": "DISCOVER",
        "bg": "#112733",
        "accent": "#8ee0ff",
    },
    {
        "title": "Join and form teams",
        "subtitle": "Register, pick a track, and invite teammates",
        "tag": "TEAM FORMATION",
        "bg": "#1c2436",
        "accent": "#f7d774",
    },
    {
        "title": "Submit projects",
        "subtitle": "Save drafts, publish final work, and share links",
        "tag": "SUBMISSIONS",
        "bg": "#1a2c30",
        "accent": "#75e4c2",
    },
    {
        "title": "Organizer control room",
        "subtitle": "Assign judges, set rubric, and publish results",
        "tag": "ORGANIZER",
        "bg": "#2b1f2e",
        "accent": "#e89fd8",
    },
    {
        "title": "Private judging",
        "subtitle": "Judges see only their own assigned scores",
        "tag": "FAIRNESS",
        "bg": "#1f2b2b",
        "accent": "#9fe4ff",
    },
    {
        "title": "Public results + certificates",
        "subtitle": "Share winners, votes, and verify awards",
        "tag": "RESULTS",
        "bg": "#1a2432",
        "accent": "#8ef1c9",
    },
    {
        "title": "Dogfood-ready MVP",
        "subtitle": "Self-hostable platform for hackathons and community events",
        "tag": "T1/T2 PASS",
        "bg": "#101b1c",
        "accent": "#8fe8bc",
    },
]

font_paths = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_font(size: int):
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

large_font = load_font(120)
medium_font = load_font(52)
small_font = load_font(36)

for idx, slide in enumerate(slides):
    image = Image.new("RGB", (1920, 1080), slide["bg"])
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, 1920, 120), fill=slide["accent"])
    draw.rectangle((120, 150, 1800, 180), fill=(255, 255, 255, 25))
    draw.rectangle((130, 220, 170, 910), fill=slide["accent"])

    x = 220
    y = 260
    title_parts = slide["title"].split()
    line = ""
    lines = []
    for word in title_parts:
        candidate = f"{line} {word}".strip()
        if len(candidate) <= 18:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)

    for line_text in lines[:3]:
        draw.text((x, y), line_text, font=large_font, fill="white")
        y += 120

    draw.text((x, y + 35), slide["subtitle"], font=medium_font, fill=(230, 240, 245))

    draw.rounded_rectangle((220, 850, 780, 930), radius=24, fill=slide["accent"])
    draw.text((260, 865), slide["tag"], font=small_font, fill="#0b1720")

    draw.rounded_rectangle((1380, 850, 1760, 930), radius=24, fill=(255, 255, 255, 28))
    draw.text((1425, 865), "SPARKS", font=small_font, fill="white")

    for gx in range(0, 1920, 120):
        draw.line((gx, 0, gx, 1080), fill=(255, 255, 255, 18), width=1)
    for gy in range(0, 1080, 120):
        draw.line((0, gy, 1920, gy), fill=(255, 255, 255, 12), width=1)

    image.save(FRAME_DIR / f"{idx:03d}.png")

writer = imageio.get_writer(
    str(OUTPUT_MP4),
    fps=3,
    codec="libx264",
    macro_block_size=None,
)

for image_path in sorted(FRAME_DIR.glob("*.png")):
    writer.append_data(imageio.imread(str(image_path)))

writer.close()
print(f"created {OUTPUT_MP4}")
