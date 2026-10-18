"""Spec daily-digest: digest size, summary and audio."""

from __future__ import annotations

import json

from daily_reading import dr_digest
from daily_reading.dr_summary import make_audio, make_summary, trim_to_words
from daily_reading.dr_rank import Ranked
from helpers import NOW, FakeFeeds, RecordingModel, RecordingTTS, days_ago, make_settings, rss, write_feeds
from test_rank import cand


def ranked(n):
    return [Ranked(cand(i, title=f"title {i}"), {}, 0.0, []) for i in range(1, n + 1)]


def _setup(tmp_path, count, **settings_values):
    settings = make_settings(tmp_path, **settings_values)
    write_feeds(settings.feeds_file, [{"url": "https://a.com/feed"}])
    body = rss([{"title": f"Story number {i}", "link": f"https://a.com/{i}", "date": days_ago(1 + i / 100)}
                for i in range(count)])
    return settings, FakeFeeds({"https://a.com/feed": body})


def test_fewer_candidates_than_max_items(tmp_path):
    settings, feeds = _setup(tmp_path, 3, max_items=8)
    result = dr_digest.run(settings, call_model=RecordingModel(), dispatch=None, fetcher=feeds, now=NOW)
    assert [i["number"] for i in result.digest["items"]] == [1, 2, 3]


def test_summary_in_the_configured_language():
    model = RecordingModel()
    summary = make_summary(ranked(8), language="pt-BR", target_words=750, max_excerpt=1200, call_model=model)
    call = model.calls[0]
    assert "pt-BR" in call["instructions"] and "750 words" in call["instructions"]
    assert call["input"].startswith("<<<UNTRUSTED_FEED_DATA") and call["input"].count('"number"') == 8
    assert summary.intro == "Today's reading." and summary.paragraphs == [f"Paragraph {n}." for n in range(1, 9)]


def test_summary_words_override(tmp_path):
    settings = make_settings(tmp_path, summary_words=300, audio_minutes=5)
    assert settings.summary_target == 300
    assert make_settings(tmp_path, audio_minutes=5).summary_target == 750


def test_summary_too_long():
    sentence = "This sentence has exactly seven words."  # 6 words + punctuation
    long_text = " ".join([sentence] * 230)  # 1380 words
    model = RecordingModel(summary=lambda t: {"intro": long_text, "items": []})
    summary = make_summary(ranked(1), language="en", target_words=750, max_excerpt=1200, call_model=model)
    words = summary.spoken_text.split()
    assert summary.trimmed and len(words) <= 1125 and summary.spoken_text.endswith(".")
    assert len(words) > 1100


def test_trim_keeps_text_under_the_limit():
    intro, paragraphs, trimmed = trim_to_words("One two.", ["Three four."], 10)
    assert (intro, paragraphs, trimmed) == ("One two.", ["Three four."], False)


def test_summary_fails_or_is_malformed():
    for bad in (RuntimeError("down"), None, "text", {"intro": "", "items": []}, {"items": [{"number": "x", "text": 1}]}):
        model = RecordingModel(summary=lambda t, b=bad: b)
        summary = make_summary(ranked(2), language="en", target_words=100, max_excerpt=1200, call_model=model)
        assert summary.failed and summary.spoken_text == ""


def test_summary_failure_keeps_items_and_skips_audio(tmp_path):
    settings, feeds = _setup(tmp_path, 3)
    tts = RecordingTTS(tmp_path / "tts")
    result = dr_digest.run(settings, call_model=RecordingModel(summary=lambda t: RuntimeError("x")), dispatch=tts,
                           fetcher=feeds, now=NOW)
    assert len(result.digest["items"]) == 3 and result.digest["summary_failed"] and tts.calls == []
    assert "Summary: failed." in result.message


def test_missing_paragraph():
    model = RecordingModel(summary=lambda t: {"intro": "Hi.", "items": [{"number": 1, "text": "One."}, {"number": 2, "text": "Two."}]})
    summary = make_summary(ranked(3), language="en", target_words=100, max_excerpt=1200, call_model=model)
    assert summary.paragraphs == ["One.", "Two.", ""] and not summary.failed


def test_audio_made(tmp_path):
    settings, feeds = _setup(tmp_path, 2)
    tts = RecordingTTS(tmp_path / "tts")
    result = dr_digest.run(settings, call_model=RecordingModel(), dispatch=tts, fetcher=feeds, now=NOW)
    assert len(tts.calls) == 1 and tts.calls[0]["name"] == "text_to_speech"
    assert tts.calls[0]["args"]["text"] == "Today's reading.\n\nParagraph 1.\n\nParagraph 2."
    audio = result.digest["audio"]
    assert audio["files"] == ["audio-01.wav"] and audio["provider"] == "kokoro-mlx"


def test_long_summary_goes_in_segments(tmp_path):
    from daily_reading.dr_summary import SEGMENT_CHARS, audio_segments

    paragraphs = [f"Paragraph {n}. " + "word " * 120 for n in range(9)]  # about 600 characters each
    text = "\n\n".join(paragraphs)
    segments = audio_segments(text)
    assert len(segments) > 1 and all(len(s) <= SEGMENT_CHARS for s in segments)
    assert "\n\n".join(segments).split() == text.split()  # nothing lost, order kept
    folder = tmp_path / "digest"
    folder.mkdir()
    tts = RecordingTTS(tmp_path / "tts", files=1)
    audio = make_audio(text, folder, tts)
    assert len(tts.calls) == len(segments) and [c["args"]["text"] for c in tts.calls] == segments
    assert audio.files == [f"audio-{i:02d}.wav" for i in range(1, len(segments) + 1)]


def test_tts_error_message_is_kept(tmp_path):
    def failing(name, args):
        return json.dumps({"success": False, "error": "Final-encoded TTS chunk exceeds default delivery limit"})
    audio = make_audio("text", tmp_path, failing)
    assert audio.failed and "delivery limit" in audio.reason


def test_audio_in_several_files(tmp_path):
    folder = tmp_path / "digest"
    folder.mkdir()
    tts = RecordingTTS(tmp_path / "tts", files=3)
    audio = make_audio("text", folder, tts)
    assert audio.files == ["audio-01.wav", "audio-02.wav", "audio-03.wav"]
    assert [(folder / n).read_bytes()[4] for n in audio.files] == [0, 1, 2]  # same order as file_paths


def test_tts_fails(tmp_path):
    settings, feeds = _setup(tmp_path, 2)
    result = dr_digest.run(settings, call_model=RecordingModel(), dispatch=RecordingTTS(tmp_path, fail=True),
                           fetcher=feeds, now=NOW)
    digest = result.digest
    assert digest["intro"] and len(digest["items"]) == 2
    assert digest["audio"]["failed"] and digest["audio"]["files"] == []
    assert "audio failed" in result.message


def test_audio_file_vanishes_before_it_is_stored(tmp_path):
    settings, feeds = _setup(tmp_path, 2)

    def vanishing(name, args):
        return json.dumps({"success": True, "file_paths": [str(tmp_path / "gone.wav")], "provider": "x"})
    result = dr_digest.run(settings, call_model=RecordingModel(), dispatch=vanishing, fetcher=feeds, now=NOW)
    assert result.status == "built" and len(result.digest["items"]) == 2
    assert result.digest["audio"]["failed"] and result.digest["audio"]["files"] == []


def test_one_long_paragraph_is_split():
    from daily_reading.dr_summary import SEGMENT_CHARS, audio_segments

    paragraph = " ".join(f"Sentence number {n} talks about integration and agents." for n in range(60))  # ~3400 chars
    unbroken = "x" * 4000
    for text in (paragraph, f"Intro.\n\n{paragraph}\n\nEnd.", unbroken):
        segments = audio_segments(text)
        assert all(0 < len(s) <= SEGMENT_CHARS for s in segments)
        assert "".join(segments).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")
