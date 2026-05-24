"""
Media Tool
==========
Convert files between formats using external tools:
- ffmpeg for audio/video conversion
- ImageMagick for image operations
- markitdown for document conversion (PDF→Markdown, etc.)
Self-contained — no BaseTool dependency.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _check_command(cmd: str) -> str | None:
    """Return the path to a command if available, else None."""
    return shutil.which(cmd)


def _run_command(args: list[str], timeout: int = 120) -> dict[str, Any]:
    """Run a subprocess command and return structured result."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command not found: {args[0]}",
            "exit_code": -1,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
        }
    except Exception as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
        }


def _make_output_path(input_path: str, output_format: str | None, suffix: str = "") -> str:
    """Generate an output path from the input path and desired format."""
    p = Path(input_path)
    ext = f".{output_format}" if output_format else p.suffix
    out_name = f"{p.stem}{suffix}{ext}"
    return str(p.parent / out_name)


def execute(
    operation: str,
    input_path: str,
    output_path: str | None = None,
    output_format: str | None = None,
    width: int | None = None,
    height: int | None = None,
    quality: int = 80,
    extra_args: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a media operation.

    Returns:
        Dict with success, output (human-readable), and result-specific data.
    """
    operations = {
        "convert": _convert,
        "extract_audio": _extract_audio,
        "resize_image": _resize_image,
        "convert_document": _convert_document,
        "get_info": _get_info,
        "thumbnail": _thumbnail,
        "compress": _compress,
    }

    handler = operations.get(operation)
    if handler is None:
        return {
            "success": False,
            "output": f"Unknown operation: {operation}. Supported: {', '.join(operations.keys())}",
            "error": "invalid_operation",
        }

    # Validate input file
    if not os.path.isfile(input_path):
        return {
            "success": False,
            "output": f"Input file not found: {input_path}",
            "error": "file_not_found",
        }

    return handler(
        input_path=input_path,
        output_path=output_path,
        output_format=output_format,
        width=width,
        height=height,
        quality=quality,
        extra_args=extra_args or [],
    )


# ── Operations ─────────────────────────────────────────────────────


def _convert(
    input_path: str,
    output_path: str | None = None,
    output_format: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Convert a media file using ffmpeg."""
    if not _check_command("ffmpeg"):
        return {"success": False, "output": "ffmpeg not found. Install ffmpeg.", "error": "missing_tool"}
    if not output_format and not output_path:
        return {"success": False, "output": "output_format or output_path required", "error": "missing_param"}

    out = output_path or _make_output_path(input_path, output_format)
    args = ["ffmpeg", "-y", "-i", input_path, out]
    result = _run_command(args)

    if result["success"]:
        out_size = os.path.getsize(out) if os.path.exists(out) else 0
        return {
            "success": True,
            "output": f"Converted {input_path} → {out} ({out_size} bytes)",
            "input": input_path,
            "output_file": out,
            "output_size": out_size,
        }
    return {
        "success": False,
        "output": f"Conversion failed: {result['stderr'][:500]}",
        "error": result["stderr"],
    }


def _extract_audio(
    input_path: str,
    output_path: str | None = None,
    output_format: str = "mp3",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Extract audio track from a video file."""
    if not _check_command("ffmpeg"):
        return {"success": False, "output": "ffmpeg not found. Install ffmpeg.", "error": "missing_tool"}

    out = output_path or _make_output_path(input_path, output_format, "_audio")
    args = ["ffmpeg", "-y", "-i", input_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", out]
    result = _run_command(args, timeout=300)

    if result["success"]:
        out_size = os.path.getsize(out) if os.path.exists(out) else 0
        return {
            "success": True,
            "output": f"Extracted audio: {out} ({out_size} bytes)",
            "input": input_path,
            "output_file": out,
            "output_size": out_size,
        }
    return {
        "success": False,
        "output": f"Audio extraction failed: {result['stderr'][:500]}",
        "error": result["stderr"],
    }


def _resize_image(
    input_path: str,
    output_path: str | None = None,
    output_format: str | None = None,
    width: int | None = None,
    height: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Resize an image using ImageMagick (convert/magick)."""
    magick = _check_command("magick") or _check_command("convert")
    if not magick:
        return {"success": False, "output": "ImageMagick not found. Install imagemagick.", "error": "missing_tool"}
    if not width and not height:
        return {"success": False, "output": "At least one of width/height required", "error": "missing_param"}

    out_fmt = output_format or Path(input_path).suffix.lstrip(".")
    out = output_path or _make_output_path(input_path, out_fmt, "_resized")
    size_spec = f"{width or ''}x{height or ''}"

    if magick.endswith("magick"):
        args = [magick, "convert", input_path, "-resize", size_spec, out]
    else:
        args = [magick, input_path, "-resize", size_spec, out]

    result = _run_command(args)

    if result["success"]:
        out_size = os.path.getsize(out) if os.path.exists(out) else 0
        return {
            "success": True,
            "output": f"Resized image: {out} ({out_size} bytes)",
            "input": input_path,
            "output_file": out,
            "output_size": out_size,
        }
    return {
        "success": False,
        "output": f"Image resize failed: {result['stderr'][:500]}",
        "error": result["stderr"],
    }


def _convert_document(
    input_path: str,
    output_path: str | None = None,
    output_format: str = "md",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Convert a document (PDF, DOCX, etc.) to Markdown using markitdown."""
    markitdown_bin = _check_command("markitdown")
    if markitdown_bin:
        out = output_path or _make_output_path(input_path, output_format, "_converted")
        args = [markitdown_bin, input_path, "-o", out]
        result = _run_command(args, timeout=180)

        if result["success"]:
            out_size = os.path.getsize(out) if os.path.exists(out) else 0
            return {
                "success": True,
                "output": f"Converted document: {out} ({out_size} bytes)",
                "input": input_path,
                "output_file": out,
                "output_size": out_size,
            }
        return {
            "success": False,
            "output": f"Document conversion failed: {result['stderr'][:500]}",
            "error": result["stderr"],
        }

    # Fallback: try Python markitdown library
    try:
        from markitdown import MarkItDown

        md_converter = MarkItDown()
        result = md_converter.convert(input_path)
        out = output_path or _make_output_path(input_path, output_format, "_converted")
        Path(out).write_text(result.text_content, encoding="utf-8")
        out_size = os.path.getsize(out)
        return {
            "success": True,
            "output": f"Converted document: {out} ({out_size} bytes)",
            "input": input_path,
            "output_file": out,
            "output_size": out_size,
        }
    except ImportError:
        return {
            "success": False,
            "output": "Neither markitdown CLI nor Python library found. Install: pip install markitdown",
            "error": "missing_tool",
        }
    except Exception as exc:
        return {
            "success": False,
            "output": f"Document conversion failed: {exc}",
            "error": str(exc),
        }


def _get_info(input_path: str, **_kwargs: Any) -> dict[str, Any]:
    """Get media file info using ffprobe."""
    if not _check_command("ffprobe"):
        return {"success": False, "output": "ffprobe not found. Install ffmpeg.", "error": "missing_tool"}

    args = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        input_path,
    ]
    result = _run_command(args)

    if result["success"]:
        return {
            "success": True,
            "output": result["stdout"],
            "info": result["stdout"],
            "input": input_path,
        }
    # Fallback: basic stat info
    stat = os.stat(input_path)
    return {
        "success": True,
        "output": f"File: {input_path}\nSize: {stat.st_size} bytes",
        "info": {"size": stat.st_size},
    }


def _thumbnail(
    input_path: str,
    output_path: str | None = None,
    output_format: str = "jpg",
    **_kwargs: Any,
) -> dict[str, Any]:
    """Generate a thumbnail from a video or image."""
    ffmpeg = _check_command("ffmpeg")
    if ffmpeg:
        out = output_path or _make_output_path(input_path, output_format, "_thumb")
        args = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "scale=320:-1", "-frames:v", "1",
            out,
        ]
        result = _run_command(args)
        if result["success"]:
            out_size = os.path.getsize(out) if os.path.exists(out) else 0
            return {
                "success": True,
                "output": f"Thumbnail: {out} ({out_size} bytes)",
                "output_file": out,
                "output_size": out_size,
            }

    magick = _check_command("magick") or _check_command("convert")
    if magick:
        out = output_path or _make_output_path(input_path, output_format, "_thumb")
        args = [magick, input_path, "-resize", "320x320", out]
        result = _run_command(args)
        if result["success"]:
            out_size = os.path.getsize(out) if os.path.exists(out) else 0
            return {
                "success": True,
                "output": f"Thumbnail: {out} ({out_size} bytes)",
                "output_file": out,
                "output_size": out_size,
            }

    return {
        "success": False,
        "output": "No suitable tool found (need ffmpeg or ImageMagick)",
        "error": "missing_tool",
    }


def _compress(
    input_path: str,
    output_path: str | None = None,
    output_format: str | None = None,
    quality: int = 80,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Compress a media file. Uses ffmpeg for audio/video, ImageMagick for images."""
    ext = Path(input_path).suffix.lower()

    # Audio/Video → ffmpeg
    if ext in (".mp4", ".avi", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".flac", ".ogg", ".aac"):
        if not _check_command("ffmpeg"):
            return {"success": False, "output": "ffmpeg not found.", "error": "missing_tool"}

        out_fmt = output_format or ext.lstrip(".")
        out = output_path or _make_output_path(input_path, out_fmt, "_compressed")

        crf = max(18, min(51, 51 - int(quality * 0.33)))

        if ext in (".mp3", ".wav", ".flac", ".ogg", ".aac"):
            bitrate = f"{max(64, int(quality * 3.2))}k"
            args = ["ffmpeg", "-y", "-i", input_path, "-b:a", bitrate, out]
        else:
            args = ["ffmpeg", "-y", "-i", input_path, "-crf", str(crf), "-preset", "medium", out]

        result = _run_command(args, timeout=300)
        if result["success"]:
            orig_size = os.path.getsize(input_path)
            new_size = os.path.getsize(out) if os.path.exists(out) else 0
            ratio = f"{(1 - new_size / orig_size) * 100:.1f}%" if orig_size > 0 else "N/A"
            return {
                "success": True,
                "output": f"Compressed: {out}\n{orig_size} → {new_size} bytes ({ratio} reduction)",
                "output_file": out,
                "original_size": orig_size,
                "compressed_size": new_size,
                "ratio": ratio,
            }
        return {"success": False, "output": f"Compression failed: {result['stderr'][:500]}", "error": result["stderr"]}

    # Images → ImageMagick
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"):
        magick = _check_command("magick") or _check_command("convert")
        if not magick:
            return {"success": False, "output": "ImageMagick not found.", "error": "missing_tool"}

        out_fmt = output_format or ext.lstrip(".")
        out = output_path or _make_output_path(input_path, out_fmt, "_compressed")
        args = [magick, input_path, "-quality", str(quality), out]
        result = _run_command(args)
        if result["success"]:
            orig_size = os.path.getsize(input_path)
            new_size = os.path.getsize(out) if os.path.exists(out) else 0
            ratio = f"{(1 - new_size / orig_size) * 100:.1f}%" if orig_size > 0 else "N/A"
            return {
                "success": True,
                "output": f"Compressed: {out}\n{orig_size} → {new_size} bytes ({ratio} reduction)",
                "output_file": out,
                "original_size": orig_size,
                "compressed_size": new_size,
                "ratio": ratio,
            }
        return {"success": False, "output": f"Compression failed: {result['stderr'][:500]}", "error": result["stderr"]}

    return {
        "success": False,
        "output": f"Unsupported file type for compression: {ext}",
        "error": "unsupported_format",
    }
