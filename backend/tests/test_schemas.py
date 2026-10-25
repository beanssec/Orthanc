"""Tests for Pydantic v2 schemas and ConfigDict migration."""
from datetime import datetime, timezone
import uuid
import warnings
import pytest
from pydantic.warnings import PydanticDeprecatedSince20

from app.schemas.feed import EventResponse, PostResponse
from app.schemas.credentials import CredentialResponse
from app.schemas.alerts import AlertResponse, AlertHitResponse
from app.schemas.alert_rules import AlertRuleResponse, AlertEventResponse
from app.schemas.auth import UserResponse
from app.schemas.sources import SourceReliabilityInfo, SourceReliabilityOverride, SourceResponse
from app.schemas.api_keys import ApiKeyResponse
from app.schemas.entities import EntitySchema, EntityMentionSchema
from app.schemas.events import PostSummary, EventWithPost


class SimpleObject:
    """Mock object to verify model_validate with from_attributes=True."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_no_pydantic_deprecation_warnings():
    """Ensure schema imports and instantiations produce zero Pydantic deprecation warnings."""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always", PydanticDeprecatedSince20)
        
        # Verify model_config is a ConfigDict or dict with from_attributes
        assert EventResponse.model_config.get("from_attributes") is True
        assert PostResponse.model_config.get("from_attributes") is True
        assert CredentialResponse.model_config.get("from_attributes") is True
        assert AlertResponse.model_config.get("from_attributes") is True
        assert AlertHitResponse.model_config.get("from_attributes") is True
        assert AlertRuleResponse.model_config.get("from_attributes") is True
        assert AlertEventResponse.model_config.get("from_attributes") is True
        assert UserResponse.model_config.get("from_attributes") is True
        assert SourceReliabilityInfo.model_config.get("from_attributes") is True
        assert SourceResponse.model_config.get("from_attributes") is True
        assert SourceReliabilityOverride.model_config.get("extra") == "forbid"

    assert len(recorded) == 0, f"Deprecation warnings caught: {[w.message for w in recorded]}"


def test_feed_schemas_from_attributes():
    event_id = uuid.uuid4()
    post_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_event = SimpleObject(
        id=event_id,
        lat=37.7749,
        lng=-122.4194,
        place_name="San Francisco",
        confidence=0.95,
    )
    event_schema = EventResponse.model_validate(mock_event)
    assert event_schema.id == event_id
    assert event_schema.lat == 37.7749
    assert event_schema.place_name == "San Francisco"

    mock_post = SimpleObject(
        id=post_id,
        source_type="rss",
        source_id="item-123",
        author="Reporter",
        content="News flash",
        timestamp=now,
        ingested_at=now,
        event=mock_event,
        media_type=None,
        media_path=None,
        media_size_bytes=None,
        media_mime=None,
        media_thumbnail_path=None,
        media_metadata=None,
        authenticity_score=None,
        authenticity_analysis=None,
        authenticity_checked_at=None,
        detected_language="en",
        translated_content=None,
        translation_model=None,
    )
    post_schema = PostResponse.model_validate(mock_post)
    assert post_schema.id == post_id
    assert post_schema.event is not None
    assert post_schema.event.place_name == "San Francisco"
    dumped = post_schema.model_dump()
    assert dumped["source_id"] == "item-123"


def test_credentials_schema_from_attributes():
    cred_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    mock_cred = SimpleObject(
        id=cred_id,
        provider="telegram",
        created_at=now,
        updated_at=now,
    )
    cred_schema = CredentialResponse.model_validate(mock_cred)
    assert cred_schema.id == cred_id
    assert cred_schema.provider == "telegram"
    assert cred_schema.model_dump()["provider"] == "telegram"


def test_source_schemas_validation():
    source_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    mock_rel = SimpleObject(
        reliability_score=0.85,
        confidence_band="high",
        analyst_override=None,
        analyst_note=None,
        scoring_inputs={"history": 10},
        updated_at=now,
    )
    rel_schema = SourceReliabilityInfo.model_validate(mock_rel)
    assert rel_schema.reliability_score == 0.85

    mock_source = SimpleObject(
        id=source_id,
        type="rss",
        handle="news_feed",
        display_name="Global News",
        enabled=True,
        last_polled=now,
        config_json={"url": "https://example.com/rss"},
        download_images=False,
        download_videos=False,
        max_image_size_mb=10.0,
        max_video_size_mb=100.0,
        reliability=mock_rel,
        source_class="news",
        default_reliability_prior="0.8",
        ecosystem=None,
        risk_note=None,
        poll_interval_seconds=300,
        filter_keywords=["breaking"],
        filter_mode="include",
    )
    source_schema = SourceResponse.model_validate(mock_source)
    assert source_schema.id == source_id
    assert source_schema.reliability.reliability_score == 0.85

    # Test SourceReliabilityOverride extra=forbid
    override = SourceReliabilityOverride(analyst_override=0.9, analyst_note="Verified")
    assert override.analyst_override == 0.9

    with pytest.raises(Exception):
        SourceReliabilityOverride(analyst_override=0.9, extra_field_disallowed="bad")


def test_auth_schema_from_attributes():
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    mock_user = SimpleObject(
        id=user_id,
        username="analyst1",
        created_at=now,
    )
    user_schema = UserResponse.model_validate(mock_user)
    assert user_schema.id == user_id
    assert user_schema.username == "analyst1"
