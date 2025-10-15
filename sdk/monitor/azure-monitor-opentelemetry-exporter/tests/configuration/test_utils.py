# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import unittest
from unittest.mock import Mock, patch
import requests

from azure.monitor.opentelemetry.exporter._configuration._utils import (
    _ConfigurationProfile,
    OneSettingsResponse,
    make_onesettings_request,
    _parse_onesettings_response,
    evaluate_feature,
    _matches_override_rule,
    _matches_condition,
    _compare_versions,
    _parse_version_with_beta,
)
from azure.monitor.opentelemetry.exporter._constants import (
    _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS,
    _ONE_SETTINGS_CHANGE_VERSION_KEY,
)


class TestConfigurationProfile(unittest.TestCase):
    """Test cases for _ConfigurationProfile class."""

    def setUp(self):
        """Reset profile before each test."""
        _ConfigurationProfile.os = ""
        _ConfigurationProfile.rp = ""
        _ConfigurationProfile.attach = ""
        _ConfigurationProfile.version = ""
        _ConfigurationProfile.component = ""
        _ConfigurationProfile.region = ""

    def test_fill_empty_profile(self):
        """Test filling an empty profile with all parameters."""
        _ConfigurationProfile.fill(
            os="w",
            rp="f",
            attach="m",
            version="1.0.0",
            component="ext",
            region="westus"
        )
        
        self.assertEqual(_ConfigurationProfile.os, "w")
        self.assertEqual(_ConfigurationProfile.rp, "f")
        self.assertEqual(_ConfigurationProfile.attach, "m")
        self.assertEqual(_ConfigurationProfile.version, "1.0.0")
        self.assertEqual(_ConfigurationProfile.component, "ext")
        self.assertEqual(_ConfigurationProfile.region, "westus")

    def test_fill_partial_profile(self):
        """Test filling profile with only some parameters."""
        _ConfigurationProfile.fill(os="l", version="2.0.0")
        
        self.assertEqual(_ConfigurationProfile.os, "l")
        self.assertEqual(_ConfigurationProfile.version, "2.0.0")
        self.assertEqual(_ConfigurationProfile.rp, "")
        self.assertEqual(_ConfigurationProfile.attach, "")
        self.assertEqual(_ConfigurationProfile.component, "")
        self.assertEqual(_ConfigurationProfile.region, "")

    def test_fill_no_overwrite(self):
        """Test that fill doesn't overwrite existing values."""
        # Set initial values
        _ConfigurationProfile.os = "w"
        _ConfigurationProfile.version = "1.0.0"
        
        # Try to overwrite - should be ignored
        _ConfigurationProfile.fill(os="l", version="2.0.0", rp="f")
        
        # Original values should be preserved
        self.assertEqual(_ConfigurationProfile.os, "w")
        self.assertEqual(_ConfigurationProfile.version, "1.0.0")
        # New value should be set
        self.assertEqual(_ConfigurationProfile.rp, "f")


class TestOneSettingsResponse(unittest.TestCase):
    """Test cases for OneSettingsResponse class."""

    def test_default_initialization(self):
        """Test OneSettingsResponse with default values."""
        response = OneSettingsResponse()
        
        self.assertIsNone(response.etag)
        self.assertEqual(response.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(response.settings, {})
        self.assertIsNone(response.version)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.has_exception)

    def test_custom_initialization(self):
        """Test OneSettingsResponse with custom values."""
        settings = {"key": "value"}
        response = OneSettingsResponse(
            etag="test-etag",
            refresh_interval=3600,
            settings=settings,
            version=5,
            status_code=304
        )
        
        self.assertEqual(response.etag, "test-etag")
        self.assertEqual(response.refresh_interval, 3600)
        self.assertEqual(response.settings, settings)
        self.assertEqual(response.version, 5)
        self.assertEqual(response.status_code, 304)
        self.assertFalse(response.has_exception)

    def test_exception_initialization(self):
        """Test OneSettingsResponse with exception indicator."""
        response = OneSettingsResponse(
            has_exception=True,
            status_code=500
        )
        
        self.assertIsNone(response.etag)
        self.assertEqual(response.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(response.settings, {})
        self.assertIsNone(response.version)
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.has_exception)

    def test_timeout_initialization(self):
        """Test OneSettingsResponse with timeout indicator."""
        response = OneSettingsResponse(
            has_exception=True
        )
        
        self.assertIsNone(response.etag)
        self.assertEqual(response.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(response.settings, {})
        self.assertIsNone(response.version)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.has_exception)

    def test_all_error_indicators(self):
        """Test OneSettingsResponse with all error indicators set."""
        response = OneSettingsResponse(
            status_code=408,
            has_exception=True,
        )
        
        self.assertEqual(response.status_code, 408)
        self.assertTrue(response.has_exception)


class TestMakeOneSettingsRequest(unittest.TestCase):
    """Test cases for make_onesettings_request function."""

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_successful_request(self, mock_get):
        """Test successful OneSettings request."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "ETag": "test-etag",
            "x-ms-onesetinterval": "30"
        }
        mock_response.content = json.dumps({
            "settings": {"key": "value", _ONE_SETTINGS_CHANGE_VERSION_KEY: "5"}
        }).encode('utf-8')
        mock_get.return_value = mock_response
        
        # Make request
        result = make_onesettings_request("http://test.com", {"param": "value"}, {"header": "value"})
        
        # Verify request was made correctly
        mock_get.assert_called_once_with(
            "http://test.com",
            params={"param": "value"},
            headers={"header": "value"},
            timeout=10
        )
        
        # Verify response
        self.assertEqual(result.etag, "test-etag")
        self.assertEqual(result.refresh_interval, 1800)  # 30 minutes * 60
        self.assertEqual(result.settings, {"key": "value", _ONE_SETTINGS_CHANGE_VERSION_KEY: "5"})
        self.assertEqual(result.version, 5)
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.has_exception)

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_request_timeout_exception(self, mock_get):
        """Test OneSettings request with timeout exception."""
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with timeout and exception indicators
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_request_connection_exception(self, mock_get):
        """Test OneSettings request with connection exception."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with exception indicator but no timeout
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_request_http_exception(self, mock_get):
        """Test OneSettings request with HTTP exception."""
        mock_get.side_effect = requests.exceptions.HTTPError("HTTP 500 Error")
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with exception indicator
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_request_generic_exception(self, mock_get):
        """Test OneSettings request with generic exception."""
        mock_get.side_effect = Exception("Unexpected error")
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with exception indicator
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    @patch('azure.monitor.opentelemetry.exporter._configuration._utils._parse_onesettings_response')
    def test_json_decode_exception(self, mock_parse, mock_get):
        """Test OneSettings request with JSON decode exception."""
        # Setup mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"ETag": "test-etag"}
        mock_response.content = b"invalid json content"
        mock_get.return_value = mock_response
        
        # Mock _parse_onesettings_response to raise JSONDecodeError
        from json import JSONDecodeError
        mock_parse.side_effect = JSONDecodeError("Expecting value", "invalid json content", 0)
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with exception indicator
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)


    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_http_error_status_codes(self, mock_get):
        """Test OneSettings request with various HTTP error status codes."""
        # Test different HTTP error codes
        error_codes = [400, 401, 403, 404, 429, 500, 502, 503, 504]
        
        for status_code in error_codes:
            with self.subTest(status_code=status_code):
                mock_response = Mock()
                mock_response.status_code = status_code
                mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(f"HTTP {status_code}")
                mock_get.return_value = mock_response
                
                result = make_onesettings_request("http://test.com")
                
                # Should return response with exception indicator
                self.assertTrue(result.has_exception)
                self.assertEqual(result.status_code, 200)  # Default status when exception occurs

    @patch('azure.monitor.opentelemetry.exporter._configuration._utils.requests.get')
    def test_request_exception_legacy(self, mock_get):
        """Test OneSettings request with network exception (legacy behavior test)."""
        mock_get.side_effect = requests.exceptions.RequestException("Network error")
        
        result = make_onesettings_request("http://test.com")
        
        # Should return response with exception indicator
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.has_exception)


class TestParseOneSettingsResponse(unittest.TestCase):
    """Test cases for _parse_onesettings_response function."""

    def test_parse_200_response(self):
        """Test parsing successful 200 response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "ETag": "test-etag",
            "x-ms-onesetinterval": "45"
        }
        mock_response.content = json.dumps({
            "settings": {"feature": "enabled", _ONE_SETTINGS_CHANGE_VERSION_KEY: "10"}
        }).encode('utf-8')
        
        result = _parse_onesettings_response(mock_response)
        
        self.assertEqual(result.etag, "test-etag")
        self.assertEqual(result.refresh_interval, 2700)  # 45 minutes * 60
        self.assertEqual(result.settings, {"feature": "enabled", _ONE_SETTINGS_CHANGE_VERSION_KEY: "10"})
        self.assertEqual(result.version, 10)
        self.assertEqual(result.status_code, 200)

    def test_parse_304_response(self):
        """Test parsing 304 Not Modified response."""
        mock_response = Mock()
        mock_response.status_code = 304
        mock_response.headers = {
            "ETag": "cached-etag",
            "x-ms-onesetinterval": "60"
        }
        mock_response.content = b""
        
        result = _parse_onesettings_response(mock_response)
        
        self.assertEqual(result.etag, "cached-etag")
        self.assertEqual(result.refresh_interval, 3600)  # 60 minutes * 60
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 304)

    def test_parse_invalid_json(self):
        """Test parsing response with invalid JSON."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.content = b"invalid json"
        
        result = _parse_onesettings_response(mock_response)
        
        self.assertIsNone(result.etag)
        self.assertEqual(result.refresh_interval, _ONE_SETTINGS_DEFAULT_REFRESH_INTERVAL_SECONDS)
        self.assertEqual(result.settings, {})
        self.assertIsNone(result.version)
        self.assertEqual(result.status_code, 200)


class TestEvaluateFeature(unittest.TestCase):
    """Test cases for evaluate_feature function."""

    def setUp(self):
        """Set up test configuration profile."""
        _ConfigurationProfile.os = "w"
        _ConfigurationProfile.rp = "f"
        _ConfigurationProfile.attach = "m"
        _ConfigurationProfile.version = "1.0.0"
        _ConfigurationProfile.component = "ext"
        _ConfigurationProfile.region = "westus"

    def tearDown(self):
        """Reset profile after each test."""
        _ConfigurationProfile.os = ""
        _ConfigurationProfile.rp = ""
        _ConfigurationProfile.attach = ""
        _ConfigurationProfile.version = ""
        _ConfigurationProfile.component = ""
        _ConfigurationProfile.region = ""

    def test_feature_enabled_by_default(self):
        """Test feature that is enabled by default with no overrides."""
        settings = {
            "test_feature": {
                "default": "enabled"
            }
        }
        
        result = evaluate_feature("test_feature", settings)
        self.assert