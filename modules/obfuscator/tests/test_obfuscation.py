import unittest
from obfuscator import obfuscate_text  # Use direct import
from obfuscator import DEFAULT_TEXT_DEFAULT  # import defaults


class TestObfuscation(unittest.TestCase):
    def setUp(self):
        self.default_obfuscate_args = {
            "obfuscate_ip": False,
            "obfuscate_user": False,
            "obfuscate_machine": False,
            "obfuscate_paths": False,
            "partial_path": None,
            "glob_patterns": None,
            "regex_patterns": None,
            "partial_path_case_sensitive": False,
            "DEFAULT_TEXT": DEFAULT_TEXT_DEFAULT
        }

    def call_obfuscate_text(self, input_text, **kwargs):
        args = self.default_obfuscate_args.copy()
        args.update(kwargs)
        return obfuscate_text(input_text, **args)

    def test_path_obfuscation_linux_long_path(self):
        input_text = "/data/application/logs/server.log"
        expected_output = "/this/is/a/path/f1"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_linux_short_path(self):
        input_text = "/opt/software"
        expected_output = "/this/is"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_linux_exact_match(self):
        input_text = "/var/log/apache2/access.log"
        expected_output = "/this/is/a/path"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_windows_long_path(self):
        input_text = "D:\\Program Files\\Company\\App\\data.config"
        expected_output = "D:\\this\\is\\a\\path"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_windows_short_path(self):
        input_text = "C:\\Users"
        expected_output = "C:\\this"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_windows_exact_match(self):
        input_text = "E:\\Temp\\Downloads\\archive"
        expected_output = "E:\\this\\is\\a\\path"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_empty_path(self):
        input_text = ""
        expected_output = ""
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_path_obfuscation_path_with_spaces(self):
         input_text = "/path with spaces/file.txt"
         expected_output = "/this/is/a/path/f1"
         self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_paths=True), expected_output)

    def test_partial_path_obfuscation_case_sensitive_match(self):
        input_text = "/users/Mcarls/documents/project/file.txt"
        expected_output = "/users/this/is/project/file.txt"
        self.assertEqual(self.call_obfuscate_text(input_text, partial_path="Mcarls/documents"), expected_output)

    def test_partial_path_obfuscation_case_sensitive_no_match(self):
        input_text = "/users/mcarls/documents/project/file.txt"
        expected_output = "/users/mcarls/documents/project/file.txt"
        self.assertEqual(self.call_obfuscate_text(input_text, partial_path="Mcarls/documents"), input_text)

    def test_partial_path_obfuscation_case_insensitive_match(self):
         input_text = "/users/Mcarls/documents/project/file.txt"
         expected_output = "/users/this/is/project/file.txt"
         self.assertEqual(self.call_obfuscate_text(input_text, partial_path="mcarls/documents", partial_path_case_sensitive=True), expected_output)

    def test_username_obfuscation_linux(self):
        input_text = "/home/eve/logs/errors.log"
        expected_output = "/home/username/logs/errors.log"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_user=True), expected_output)

    def test_username_obfuscation_windows(self):
        input_text = "C:\\Users\\john.doe\\desktop\\report.docx"
        expected_output = "C:\\Users\\username\\desktop\\report.docx"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_user=True), expected_output)

    def test_machine_name_obfuscation_present(self):
        input_text = "admin@workstation42"
        expected_output = "admin@machine"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_machine=True), "admin@machine")

    def test_machine_name_obfuscation_not_present(self):
        input_text = "user_gary on another_server"
        expected_output = "user_gary on another_server"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_machine=True), expected_output)

    def test_ip_obfuscation_ipv4(self):
        input_text = "10.0.0.5"
        expected_output = "192.168.0.1"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_ip=True), expected_output)

    def test_ip_obfuscation_ipv6(self):
        input_text = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        expected_output = "fe80::abcd:abcd:abcd:abcd"
        self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_ip=True), expected_output)

    def test_ip_obfuscation_in_url(self):
         input_text = "http://172.16.0.1:8080/index.html"
         expected_output = "http://192.168.0.1:8080/index.html"
         self.assertEqual(self.call_obfuscate_text(input_text, obfuscate_ip=True), expected_output)

    def test_glob_replacement_basic(self):
        input_text = "/home/tester/top_secret/data.csv"
        expected_output = "/home/tester/hidden_data/data.csv"
        self.assertEqual(self.call_obfuscate_text(input_text, glob_patterns=["top_secret:hidden_data"]), expected_output)

    def test_glob_replacement_multiple(self):
        input_text = "replace_this and replace_that"
        expected_output = "replaced_this and replaced_that_too"
        self.assertEqual(self.call_obfuscate_text(input_text, glob_patterns=["replace_this:replaced_this", "replace_that:replaced_that_too"]), expected_output)

    def test_regex_replacement_basic(self):
        input_text = "/logs/errors-20231231.log"
        expected_output = "/logs/errors-REDACTED.log"
        self.assertEqual(self.call_obfuscate_text(input_text, regex_patterns=["errors-\\d{8}:errors-REDACTED"]), expected_output)

    def test_regex_replacement_multiple(self):
        input_text = "version=1.2.3 build=456"
        expected_output = "version=X.X.X build=Y"
        self.assertEqual(self.call_obfuscate_text(input_text, regex_patterns=["\\d+\\.\\d+\\.\\d+:X.X.X", "build=\\d+:build=Y"]), expected_output)

    def test_glob_replacement_invalid_pattern(self):
        input_text = "some text"
        expected_output = "some text"
        self.assertEqual(self.call_obfuscate_text(input_text, glob_patterns=["invalid_pattern"]), expected_output)

    def test_regex_replacement_invalid_pattern(self):
        input_text = "some text"
        expected_output = "some text"
        self.assertEqual(self.call_obfuscate_text(input_text, regex_patterns=["invalid(pattern"]), expected_output)

if __name__ == "__main__":
    unittest.main()
