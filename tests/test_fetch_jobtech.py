import ssl
import subprocess
import urllib.error
import unittest
from unittest import mock

from scripts import fetch_jobtech


class CurlFallbackTests(unittest.TestCase):
    @mock.patch.object(fetch_jobtech, "_curl_get_json")
    @mock.patch.object(fetch_jobtech.urllib.request, "urlopen")
    def test_certificate_error_uses_curl_fallback(self, urlopen, curl_get_json):
        certificate_error = ssl.SSLCertVerificationError(
            1, "certificate verify failed"
        )
        urlopen.side_effect = urllib.error.URLError(certificate_error)
        curl_get_json.return_value = {"hits": []}

        result = fetch_jobtech._http_get_json("https://example.com/jobs")

        self.assertEqual(result, {"hits": []})
        curl_get_json.assert_called_once_with("https://example.com/jobs")

    @mock.patch.object(fetch_jobtech.subprocess, "run")
    @mock.patch.object(fetch_jobtech.shutil, "which")
    def test_curl_fallback_keeps_tls_verification_enabled(self, which, run):
        which.return_value = "curl.exe"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b'{"hits": []}', stderr=b""
        )

        result = fetch_jobtech._curl_get_json("https://example.com/jobs")

        self.assertEqual(result, {"hits": []})
        command = run.call_args.args[0]
        self.assertNotIn("--insecure", command)
        self.assertNotIn("-k", command)
        self.assertIn("--fail", command)


if __name__ == "__main__":
    unittest.main()
