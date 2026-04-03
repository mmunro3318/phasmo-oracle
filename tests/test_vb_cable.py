"""Tests for VB-Cable device discovery.

All tests mock sounddevice.query_devices() — no audio hardware needed.
"""

import sys
from unittest.mock import patch, MagicMock

import pytest

from oracle.voice.audio_config import find_vb_cable_device


def _device(name, max_input=0, max_output=2, sr=48000.0):
    """Helper to create a mock device dict."""
    return {
        "name": name,
        "max_input_channels": max_input,
        "max_output_channels": max_output,
        "default_samplerate": sr,
    }


def _call_with_devices(devices):
    """Call find_vb_cable_device with a mocked sounddevice module."""
    mock_sd = MagicMock()
    mock_sd.query_devices.return_value = devices
    with patch.dict(sys.modules, {"sounddevice": mock_sd}):
        return find_vb_cable_device()


class TestFindVBCableDevice:
    def test_finds_cable_input(self):
        devices = [
            _device("Speaker (Realtek HD Audio)"),
            _device("CABLE Input (VB-Audio Virtual Cable)"),
            _device("Microphone Array", max_input=2, max_output=0),
        ]
        result = _call_with_devices(devices)
        assert result == "CABLE Input (VB-Audio Virtual Cable)"

    def test_finds_voicemeeter_input(self):
        devices = [
            _device("Speaker (Realtek HD Audio)"),
            _device("VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)"),
        ]
        result = _call_with_devices(devices)
        assert result == "VoiceMeeter Input (VB-Audio VoiceMeeter VAIO)"

    def test_finds_voicemeeter_aux_input(self):
        devices = [
            _device("VoiceMeeter Aux Input (VB-Audio VoiceMeeter AUX VAIO)"),
        ]
        result = _call_with_devices(devices)
        assert result == "VoiceMeeter Aux Input (VB-Audio VoiceMeeter AUX VAIO)"

    def test_finds_cable_a_variant(self):
        devices = [
            _device("CABLE-A Input (VB-Audio Cable A)"),
        ]
        result = _call_with_devices(devices)
        assert result == "CABLE-A Input (VB-Audio Cable A)"

    def test_returns_none_when_no_vb_cable(self):
        devices = [
            _device("Speaker (Realtek HD Audio)"),
            _device("Monitor (HD Audio Display)"),
            _device("Microphone Array", max_input=2, max_output=0),
        ]
        result = _call_with_devices(devices)
        assert result is None

    def test_ignores_cable_output_input_device(self):
        """CABLE Output is an INPUT device — should not match."""
        devices = [
            _device("CABLE Output (VB-Audio Virtual Cable)", max_input=2, max_output=0),
        ]
        result = _call_with_devices(devices)
        assert result is None

    def test_case_insensitive_match(self):
        devices = [
            _device("cable input (VB-Audio)"),
        ]
        result = _call_with_devices(devices)
        assert result == "cable input (VB-Audio)"

    def test_returns_first_match_when_multiple(self):
        devices = [
            _device("CABLE Input (VB-Audio Virtual Cable)"),
            _device("VoiceMeeter Input (VB-Audio VoiceMeeter)"),
        ]
        result = _call_with_devices(devices)
        assert result == "CABLE Input (VB-Audio Virtual Cable)"

    def test_returns_none_on_sounddevice_import_error(self):
        """When sounddevice is not installed, import raises ImportError."""
        with patch.dict(sys.modules, {"sounddevice": None}):
            result = find_vb_cable_device()
        assert result is None

    def test_empty_device_list(self):
        result = _call_with_devices([])
        assert result is None
