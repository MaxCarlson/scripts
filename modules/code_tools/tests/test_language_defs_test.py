from rgcodeblock_lib.language_defs import get_language_type_from_filename

def test_language_detection_known():
    assert get_language_type_from_filename("a.py")[0] == "python"
    assert get_language_type_from_filename("a.cpp")[0] == "brace"
    assert get_language_type_from_filename("a.json")[0] == "json"
    assert get_language_type_from_filename("a.yaml")[0] == "yaml"
    assert get_language_type_from_filename("a.xml")[0] == "xml"
    assert get_language_type_from_filename("a.rb")[0] == "ruby"
    assert get_language_type_from_filename("a.lua")[0] == "lua"

def test_language_detection_unknown():
    lang, ext = get_language_type_from_filename("a.unk")
    assert lang == "other" and ext == ".unk"
