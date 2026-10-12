import json

from trueup.neatlogs_detections import GROUP, PACK, Writer, install


class FakeWriter:
    def __init__(self):
        self.writes = []

    def call(self, tool, **kwargs):
        if tool == "list_detection_groups":
            return {"groups": [{"id": "g1", "name": GROUP}]}
        if tool == "list_detections":
            return {"detections": [{"display_name": PACK[0]["display_name"]}]}
        if tool == "preview_detection":
            return {"total_count": 2}
        raise AssertionError(tool)

    def write(self, tool, **kwargs):
        self.writes.append((tool, kwargs))
        return {"id": "new"}


def test_install_is_idempotent_and_previews_before_create():
    writer = FakeWriter()
    result = install(writer)
    assert result["created"] == [PACK[1]["display_name"], PACK[2]["display_name"]]
    assert [name for name, _ in writer.writes] == ["create_detection", "create_detection"]


def test_writer_parses_text_content_from_write_tool():
    writer = object.__new__(Writer)
    writer._post = lambda *args, **kwargs: {"content": [{"type": "text", "text": json.dumps({"id": "g1"})}]}
    assert writer.write("create_detection_group", name="x") == {"id": "g1"}
