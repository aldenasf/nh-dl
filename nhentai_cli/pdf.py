from pathlib import Path
from PIL import Image


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img.copy()
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        return bg
    return img.convert("RGB")


def build_pdf_from_images(image_paths: list[Path], pdf_path: Path) -> None:
    if not image_paths:
        raise ValueError("No images provided for PDF generation.")

    sorted_paths = sorted(image_paths, key=lambda p: p.name)
    temp_path = pdf_path.with_suffix(".pdf.tmp")

    rgb_images: list[Image.Image] = []
    try:
        for path in sorted_paths:
            with Image.open(path) as img:
                rgb_images.append(_to_rgb(img))

        first, rest = rgb_images[0], rgb_images[1:]
        first.save(temp_path, "PDF", resolution=100.0, save_all=True, append_images=rest)
        temp_path.replace(pdf_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        for img in rgb_images:
            img.close()
