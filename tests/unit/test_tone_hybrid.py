from unittest.mock import AsyncMock, patch

import pytest

from core.tone_hybrid import ToneHybridClassifier


@pytest.mark.asyncio
async def test_tone_hybrid_ack_is_short_and_mirrored():
    classifier = ToneHybridClassifier()
    with patch.object(classifier, "_embedding_classify", new=AsyncMock(return_value=None)):
        result = await classifier.classify("passt, danke dir :)")
    assert result["dialogue_act"] == "ack"
    assert result["response_tone"] == "mirror_user"
    assert result["response_length_hint"] == "short"
    assert 0.0 <= float(result["tone_confidence"]) <= 1.0


@pytest.mark.asyncio
async def test_tone_hybrid_request_detects_action_turn():
    classifier = ToneHybridClassifier()
    with patch.object(classifier, "_embedding_classify", new=AsyncMock(return_value=None)):
        result = await classifier.classify("okey, leg los und prüf das bitte")
    assert result["dialogue_act"] == "request"
    assert result["response_length_hint"] in {"medium", "long"}


@pytest.mark.asyncio
async def test_tone_hybrid_formal_tone_detection():
    classifier = ToneHybridClassifier()
    with patch.object(classifier, "_embedding_classify", new=AsyncMock(return_value=None)):
        result = await classifier.classify(
            "Sehr geehrte Damen und Herren, könnten Sie das strukturiert prüfen?"
        )
    assert result["response_tone"] == "formal"
