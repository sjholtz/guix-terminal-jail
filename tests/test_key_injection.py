"""Offline proxy-header security tests; no mitmdump or network required."""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class KeyInjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="guix-auth-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.credentials = self.root / "credentials.env"
        self.credentials.write_text(
            "OPENAI_API_KEY=example-only-not-real\n"
            "CUSTOM_HEADER=example-custom\n"
            "LITERAL_VALUE=${NOT_EXPANDED}\n"
        )
        self.config = self.root / "key-injector.toml"
        self.config.write_text(
            '[[auth.headers]]\nhost = "api.example.test"\n'
            'environment_variable = "OPENAI_API_KEY"\n'
            '[[x-api.headers]]\nhost = "custom.example.test"\n'
            'environment_variable = "CUSTOM_HEADER"\n'
        )
        mitmproxy = ModuleType("mitmproxy")
        http = ModuleType("mitmproxy.http")
        vars(http)["HTTPFlow"] = type("HTTPFlow", (), {})
        vars(mitmproxy)["http"] = http
        # http.HTTPFlow = type("HTTPFlow", (), {})
        # mitmproxy.http = http
        spec = importlib.util.spec_from_file_location(
            "guix_key_injector_offline_tests", ROOT / "inject_keys.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not import inject_keys.py")
        self.module = cast(Any, importlib.util.module_from_spec(spec))
        with (
            mock.patch.dict(
                os.environ,
                {
                    "GUIX_JAIL_CREDENTIALS": str(self.credentials),
                    "GUIX_JAIL_CONFIG_DIR": str(self.root),
                },
            ),
            mock.patch.dict(
                sys.modules, {"mitmproxy": mitmproxy, "mitmproxy.http": http}
            ),
        ):
            sys.modules[spec.name] = self.module
            self.addCleanup(sys.modules.pop, spec.name, None)
            spec.loader.exec_module(self.module)
        self.injector = self.module.addons[0]

    @staticmethod
    def flow(host, scheme="https", port=443):
        return SimpleNamespace(
            request=SimpleNamespace(host=host, scheme=scheme, port=port, headers={})
        )

    def test_exact_https_host_receives_authorization(self):
        flow = self.flow("api.example.test")
        self.injector.request(flow)
        self.assertEqual(
            flow.request.headers["Authorization"], "Bearer example-only-not-real"
        )
        self.assertNotIn("x-api-key", flow.request.headers)

    def test_custom_host_receives_only_its_configured_header(self):
        flow = self.flow("custom.example.test")
        self.injector.request(flow)
        self.assertEqual(flow.request.headers["x-api-key"], "example-custom")
        self.assertNotIn("Authorization", flow.request.headers)

    def test_near_match_and_untrusted_subdomain_never_receive_secrets(self):
        for host in (
            "sub.api.example.test",
            "api.example.test.attacker.invalid",
            "other.example.test",
        ):
            with self.subTest(host=host):
                flow = self.flow(host)
                self.injector.request(flow)
                self.assertEqual(flow.request.headers, {})

    def test_plain_http_and_wrong_port_never_receive_secrets(self):
        for scheme, port in (("http", 80), ("https", 8443), ("http", 443)):
            with self.subTest(scheme=scheme, port=port):
                flow = self.flow("api.example.test", scheme, port)
                self.injector.request(flow)
                self.assertEqual(flow.request.headers, {})

    def test_host_matching_normalizes_case_and_terminal_dot(self):
        flow = self.flow("API.EXAMPLE.TEST.")
        self.injector.request(flow)
        self.assertIn("Authorization", flow.request.headers)

    def test_unset_credentials_do_not_replace_existing_header(self):
        self.injector.credentials.pop("OPENAI_API_KEY")
        flow = self.flow("api.example.test")
        flow.request.headers["Authorization"] = "original-value"
        self.injector.request(flow)
        self.assertEqual(flow.request.headers["Authorization"], "original-value")

    def test_credentials_are_not_interpolated(self):
        self.assertEqual(self.injector.credentials["LITERAL_VALUE"], "${NOT_EXPANDED}")

    def test_missing_header_mapping_file_fails_explicitly(self):
        with self.assertRaises(FileNotFoundError):
            self.module.load_header_mappings(self.root / "missing.toml")

    def test_invalid_mapping_table_shape_is_rejected(self):
        self.config.write_text('[auth]\nheaders = "not-an-array"\n')
        with self.assertRaisesRegex(TypeError, "array of tables"):
            self.module.load_header_mappings(self.config)

    def test_missing_host_or_environment_variable_is_rejected(self):
        for text in (
            '[[auth.headers]]\nenvironment_variable = "TOKEN"\n',
            '[[auth.headers]]\nhost = "api.example.test"\n',
        ):
            with self.subTest(text=text):
                self.config.write_text(text)
                with self.assertRaises(TypeError):
                    self.module.load_header_mappings(self.config)


if __name__ == "__main__":
    unittest.main()
