from vdedup.pipeline import parse_pipeline

def test_parse_pipeline_ranges():
    assert parse_pipeline("1-3") == [1,2,3]
    assert parse_pipeline("3-1") == [1,2,3]
    assert parse_pipeline("1,3-4") == [1,3,4]
    assert parse_pipeline("") == [1,2,3,4]
