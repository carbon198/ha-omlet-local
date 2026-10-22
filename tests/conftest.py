"""Shared test configuration."""

from datetime import datetime, timezone
from io import StringIO
import sys
from pathlib import Path
from types import SimpleNamespace

from coverage import Coverage
from homeassistant.components import mqtt
from homeassistant.core import State
from homeassistant.helpers.restore_state import StoredState, async_get
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEVICE_ID = "dcda0c242af4"


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Enforce the quality-scale coverage threshold for every integration module."""
    if exitstatus != pytest.ExitCode.OK or not getattr(
        session.config.option, "cov_source", None
    ):
        return

    coverage = Coverage(data_file=".coverage")
    coverage.load()
    integration_path = (
        Path(__file__).resolve().parents[1] / "custom_components" / "omlet_coop"
    )
    undercovered = []
    for module_path in sorted(integration_path.glob("*.py")):
        module_coverage = coverage.report(
            morfs=[str(module_path)],
            file=StringIO(),
            precision=2,
            output_format="total",
        )
        if module_coverage <= 95:
            undercovered.append(f"{module_path.name}: {module_coverage:.2f}%")

    if undercovered:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        reporter.write_sep("!", "Each integration module must exceed 95% coverage")
        reporter.write("\n".join(undercovered) + "\n")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def restored_states():
    """Return optional prior entity states for RestoreEntity tests."""
    return {}


@pytest.fixture
def mqtt_messages(monkeypatch):
    """Capture entity subscriptions and deliver test MQTT messages."""
    subscriptions = {}

    async def async_subscribe(hass, topic, callback, **kwargs):
        subscriptions.setdefault(topic, []).append(callback)

        def unsubscribe():
            subscriptions[topic].remove(callback)

        return unsubscribe

    monkeypatch.setattr(mqtt, "async_subscribe", async_subscribe)

    def fire(topic, payload, *, retain=False):
        message = SimpleNamespace(topic=topic, payload=payload, retain=retain)
        for subscribed_topic, callbacks in subscriptions.items():
            if topic == subscribed_topic or (
                subscribed_topic.endswith("/#")
                and topic.startswith(subscribed_topic[:-1])
            ):
                for callback in tuple(callbacks):
                    callback(message)

    return fire


@pytest.fixture
async def omlet_entry(
    hass, enable_custom_integrations, mqtt_messages, restored_states
):
    """Set up an Omlet entry with captured MQTT subscriptions."""
    from custom_components.omlet_coop.const import CONF_DEVICE_ID, DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEVICE_ID,
        data={CONF_DEVICE_ID: DEVICE_ID},
        title=f"Omlet Coop {DEVICE_ID}",
    )
    restore_data = async_get(hass)
    restore_data.last_states = {
        entity_id: StoredState(
            State(entity_id, state, {}),
            None,
            datetime.now(timezone.utc),
        )
        for entity_id, state in restored_states.items()
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mqtt_messages(
        f"device/{DEVICE_ID}/status/connected",
        "true",
    )
    await hass.async_block_till_done()

    yield entry

    if entry.state.value == "loaded":
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
