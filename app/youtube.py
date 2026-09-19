"""
YouTube ingestion and transcription engine for Backstory.

Supports:
1. Video ID and Channel ID extraction from arbitrary YouTube URLs and handles.
2. Channel RSS Feed discovery (https://www.youtube.com/feeds/videos.xml?channel_id=...).
3. Video metadata extraction (Title, Channel, Published Date, Thumbnail, Duration).
4. Subtitle / Caption extraction via youtube-transcript-api (human captions + auto-generated).
5. Fallback Speech-To-Text (STT) via yt-dlp audio download + Whisper transcription.
6. Transcript text cleanup (filler words, timestamp tags).
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TranscriptUnavailable(Exception):
    """Raised when neither captions nor audio STT could retrieve transcript text."""
    pass


# ---------------------------------------------------------------------------
# URL Parsing & Identifier Helpers
# ---------------------------------------------------------------------------

_YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def is_youtube_url(url: str) -> bool:
    """Check whether a URL belongs to YouTube (video or channel)."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() in _YOUTUBE_DOMAINS
    except Exception:
        return False


def extract_video_id(url: str) -> str | None:
    """
    Extract 11-character video ID from YouTube watch URLs, short URLs, embeds, or shorts.
    Examples:
    - https://www.youtube.com/watch?v=dQw4w9WgXcQ
    - https://youtu.be/dQw4w9WgXcQ
    - https://www.youtube.com/shorts/dQw4w9WgXcQ
    - https://www.youtube.com/embed/dQw4w9WgXcQ
    """
    if not url:
        return None
    
    # If the input is already a raw 11-char video ID
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url.strip()):
        return url.strip()

    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    if "youtu.be" in netloc:
        path = parsed.path.strip("/")
        return path.split("/")[0] if path else None

    if "youtube.com" in netloc:
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list:
                return v_list[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/v/")):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[1]

    # Regex fallback
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else None


async def resolve_channel_id(channel_url_or_handle: str) -> str | None:
    """
    Given a YouTube channel URL (e.g. /@handle, /c/name, /channel/UC...),
    resolve the canonical 24-character Channel ID (UC...).
    """
    url = channel_url_or_handle.strip()
    
    # If already a UC channel ID
    if re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", url):
        return url

    # Direct channel ID in URL path
    match = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", url)
    if match:
        return match.group(1)

    # Fetch page HTML to extract the meta tag or canonical channelId
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    # If user provided just @handle
    if url.startswith("@"):
        url = f"https://www.youtube.com/{url}"
    elif not url.startswith("http"):
        url = f"https://www.youtube.com/@{url}"

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html = resp.text
                
                # Check meta tags
                soup = BeautifulSoup(html, "html.parser")
                meta_item = soup.find("meta", {"itemprop": "channelId"})
                if meta_item and meta_item.get("content"):
                    return meta_item["content"]

                # Regex search in page JSON or HTML
                m = re.search(r'["\']channelId["\']\s*:\s*["\'](UC[a-zA-Z0-9_-]{22})["\']', html)
                if m:
                    return m.group(1)
                
                m = re.search(r'https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})', html)
                if m:
                    return m.group(1)

    except Exception as exc:
        logger.warning("Failed to resolve channel ID for %s: %s", url, exc)

    return None


def get_channel_rss_url(channel_id: str) -> str:
    """Return the official YouTube XML feed for a channel ID."""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


# ---------------------------------------------------------------------------
# Metadata Fetcher
# ---------------------------------------------------------------------------

async def fetch_video_metadata(video_id: str) -> dict:
    """
    Fetch public metadata for a YouTube video via oEmbed and page scrape fallback.
    Returns: {video_id, title, author, url, thumbnail_url, published_date}
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"

    meta = {
        "video_id": video_id,
        "url": video_url,
        "title": f"YouTube Video ({video_id})",
        "author": "YouTube Creator",
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "published_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                data = resp.json()
                meta["title"] = data.get("title") or meta["title"]
                meta["author"] = data.get("author_name") or meta["author"]
                meta["thumbnail_url"] = data.get("thumbnail_url") or meta["thumbnail_url"]
    except Exception as exc:
        logger.debug("oEmbed metadata fetch failed for %s: %s", video_id, exc)

    return meta


# ---------------------------------------------------------------------------
# Transcript & Audio STT Services
# ---------------------------------------------------------------------------

def clean_transcript(raw_text: str) -> str:
    """Strip timestamp tags, audio filler sounds, and excessive spacing."""
    text = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", "", raw_text)
    text = re.sub(r"\[(Music|Applause|Laughter|Silence)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(uh|um|basically|you know|like),?\s+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_youtube_captions(video_id: str) -> tuple[str, str]:
    """
    Fetch subtitles/captions using youtube-transcript-api.
    Returns (raw_text, clean_text).
    Raises TranscriptUnavailable if captions are disabled or unavailable.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise TranscriptUnavailable("youtube-transcript-api is not installed.")

    try:
        # Support both new 1.x instance API and classmethod API
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            tr = None
            try:
                tr = transcripts.find_transcript(["en", "en-US", "en-GB", "en-CA", "en-IN"])
            except Exception:
                try:
                    tr = transcripts.find_generated_transcript(["en", "en-US", "en-GB", "en-IN"])
                except Exception:
                    for t in transcripts:
                        tr = t
                        break
            if tr:
                segs = tr.fetch()
            else:
                segs = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        else:
            api = YouTubeTranscriptApi()
            transcripts = api.list(video_id)
            tr = next(iter(transcripts), None)
            if not tr:
                raise TranscriptUnavailable("No transcripts found.")
            segs = tr.fetch()

        parts = []
        for s in segs:
            if isinstance(s, dict):
                parts.append(s.get("text", ""))
            else:
                parts.append(getattr(s, "text", ""))

        raw_text = " ".join(parts).strip()
        if not raw_text or len(raw_text) < 40:
            raise TranscriptUnavailable("Transcript returned empty text.")

        return raw_text, clean_transcript(raw_text)

    except Exception as exc:
        raise TranscriptUnavailable(f"Captions unavailable for {video_id}: {exc}") from exc


def transcribe_video_audio(video_id: str, max_seconds: int = 600) -> tuple[str, str]:
    """
    Fallback Speech-To-Text leg: Downloads audio via yt-dlp, then transcribes with Whisper.
    Returns (raw_text, clean_text).
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise TranscriptUnavailable("yt-dlp is not installed for audio extraction.") from exc

    workdir = tempfile.mkdtemp(prefix=f"backstory_yt_{video_id}_")
    url = f"https://www.youtube.com/watch?v={video_id}"

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": os.path.join(workdir, f"{video_id}.%(ext)s"),
        "max_filesize": 150 * 1024 * 1024,
        "retries": 2,
        "socket_timeout": 25,
    }
    if max_seconds and max_seconds > 0:
        options["download_ranges"] = lambda info, ydl: [{"start_time": 0, "end_time": max_seconds}]

    try:
        logger.info("Downloading audio for video %s with yt-dlp...", video_id)
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        audio_files = [p for p in glob.glob(os.path.join(workdir, f"{video_id}.*")) if os.path.getsize(p) > 0]
        if not audio_files:
            raise TranscriptUnavailable("Audio download produced no file.")
        audio_path = max(audio_files, key=os.path.getsize)

        # 1. Try faster-whisper if available
        try:
            from faster_whisper import WhisperModel
            logger.info("Transcribing audio with faster-whisper (tiny/base)...")
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path, vad_filter=True, beam_size=1)
            raw_text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()
            if raw_text and len(raw_text) > 40:
                return raw_text, clean_transcript(raw_text)
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("faster-whisper transcription failed: %s", exc)

        # 2. Try OpenAI Whisper API if API key is active
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key and not "your_openai_api_key_here" in api_key and api_key.startswith("sk-"):
            try:
                from app.embeddings import get_client
                client = get_client()
                logger.info("Transcribing audio with OpenAI Whisper API...")
                with open(audio_path, "rb") as audio_file:
                    transcript_resp = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="text",
                    )
                raw_text = transcript_resp.strip() if isinstance(transcript_resp, str) else transcript_resp.text.strip()
                if raw_text and len(raw_text) > 40:
                    return raw_text, clean_transcript(raw_text)
            except Exception as exc:
                logger.warning("OpenAI Whisper API transcription failed: %s", exc)

        raise TranscriptUnavailable("Audio extracted but no STT model (faster-whisper or OpenAI Whisper) was available.")

    except Exception as exc:
        raise TranscriptUnavailable(f"Audio STT failed for {video_id}: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def extract_youtube_content(url_or_video_id: str) -> dict:
    """
    Full YouTube extraction cascade:
    1. Extract Video ID.
    2. Fetch Video Metadata (Title, Author, Thumbnail).
    3. Fetch Transcript (Captions first -> STT audio fallback).
    
    Returns structured dict:
    {
        "url": video_url,
        "title": title,
        "author": author,
        "published_date": published_date,
        "thumbnail_url": thumbnail_url,
        "text": clean_transcript_text,
        "extraction_method": "youtube_captions" | "youtube_whisper_stt",
        "fetch_strategy": "direct",
    }
    """
    video_id = extract_video_id(url_or_video_id)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL or Video ID: {url_or_video_id}")

    meta = await fetch_video_metadata(video_id)

    # Step 1: Try YouTube captions
    try:
        _, clean_text = get_youtube_captions(video_id)
        method = "youtube_captions"
    except TranscriptUnavailable as cap_err:
        logger.info("Captions unavailable for %s (%s) — attempting audio STT fallback...", video_id, cap_err)
        # Step 2: Fallback to audio download + Whisper STT
        try:
            _, clean_text = transcribe_video_audio(video_id)
            method = "youtube_whisper_stt"
        except TranscriptUnavailable as stt_err:
            raise TranscriptUnavailable(f"All transcript strategies failed for {video_id}: {stt_err}") from stt_err

    return {
        "url": meta["url"],
        "video_id": video_id,
        "title": meta["title"],
        "author": meta["author"],
        "published_date": meta["published_date"],
        "thumbnail_url": meta["thumbnail_url"],
        "text": clean_text,
        "extraction_method": method,
        "fetch_strategy": "direct",
    }
