import os
import pytest
from yacman2 import yacman
# from yacman2 import FILEPATH_KEY, IK, RO_KEY



def make_cfg_file_path(name, data_path):
    return os.path.join(data_path, name)


def cleanup_locks(lcks):
    if lcks:
        [os.remove(l) for l in lcks]


def make_lock_path(name, data_path):
    return os.path.join(data_path, yacman.LOCK_PREFIX + name)


class TestPathExpand:
    """
    YAMLConfigManager objects should expand environment variables and user paths.
    """
    def test_path_expand_user(self):
        cfg = yacman.YAMLConfigManager({"x": 5})
        cfg["pathA"] = "~"
        assert (cfg["pathA"] == os.path.expanduser("~"))

    def test_path_expand(self):
        cfg = yacman.YAMLConfigManager({"x": 5})
        dummy_path = "/dummy/path/example"
        os.environ['BRAHMS'] = dummy_path
        cfg["bpath"] = "$BRAHMS"
        assert (cfg["bpath"] == dummy_path)

    def test_path_expand_off(self):
        cfg = yacman.YAMLConfigManager({"x": 5}, expand=False)
        dummy_path = "/dummy/path/example"
        os.environ['BRAHMS'] = dummy_path
        cfg["bpath"] = "$BRAHMS"
        assert (cfg["bpath"] == "$BRAHMS")

        
    def test_access_item(self):
        cfg = yacman.YAMLConfigManager({"x": 5})
        print(cfg["x"])
        assert (cfg["x"] == 5)


    def test_write_creates_file(self, data_path, list_locks):
        yacmap = yacman.YacAttMap(entries={}, writable=True)
        yacmap.write(filepath=make_cfg_file_path("writeout.yaml", data_path))
        # assert os.path.exists(make_lock_path("writeout.yaml", data_path))
        assert os.path.exists(make_cfg_file_path("writeout.yaml", data_path))
        del yacmap
        os.remove(make_cfg_file_path("writeout.yaml", data_path))

    def test_no_write_outside_context_manager(self, data_path):
        yacmap = yacman.YacAttMap(entries={})
        yacmap.write(filepath=make_cfg_file_path("writeout.yaml", data_path))       
        yacmap2 = yacman.YacAttMap(filepath=make_cfg_file_path("writeout.yaml", data_path))
        # This write should raise an error, because it's not in a context manager.
        with pytest.raises(OSError):
            yacmap2["abc"] = 5
            yacmap2.write()
        # This should not have key abc, because the write above should have failed
        yacmap3 = yacman.YacAttMap(filepath=make_cfg_file_path("writeout.yaml", data_path))
        with pytest.raises(KeyError):
            yacmap3["abc"]
        os.remove(make_cfg_file_path("writeout.yaml", data_path))


    def test_render_item(self):
        cfg = yacman.YAMLConfigManager({"x": 5})
        print(cfg)   


class TestReading:
    def test_locks_before_reading_by_default(self, data_path, cfg_file):
        """
        Here we test that the object constructor waits for a second and
        raises a Runtime error because it tries to lock the file for reading by default
        """
        yacmap = yacman.YacAttMap(filepath=cfg_file, writable=True)
        with pytest.raises(RuntimeError):
            yacman.YacAttMap(filepath=cfg_file, wait_max=0.01)
        yacmap.make_readonly()

    def test_skip_locks_before_reading(self, data_path, cfg_file):
        """
        Here we test that the you can skip the read lock if you want.
        """
        yacmap = yacman.YacAttMap(filepath=cfg_file, writable=True)
        yacman.YacAttMap(filepath=cfg_file, skip_read_lock=True)
        yacmap.make_readonly()

    def test_locking_is_opt_in(self, cfg_file, locked_cfg_file):
        """
        this tests backwards compatibility, in the past the locking system did not exist.
        Consequently, to make yacman backwards compatible, multiple processes should be able to read and write to
        the file when no arguments but the intput are specified
        """
        yacman.YacAttMap(filepath=cfg_file)
        assert not os.path.exists(locked_cfg_file)

    def test_on_init_file_update(self, cfg_file):
        a, v = "testattr", "testval"
        y = yacman.YacAttMap(entries={a: v}, filepath=cfg_file)
        assert y[a] == v

    def test_init_with_empty_file(self, data_path):
        a, v = "testattr", "testval"
        empty_file_path = os.path.join(data_path, "empty_file.yaml")
        open(empty_file_path, "a").close()
        y = yacman.YacAttMap(entries={a: v}, filepath=empty_file_path)
        assert a in y
        os.remove(empty_file_path)

class TestContextManager:
    @pytest.mark.parametrize("state", [True, False])
    def test_context_manager_does_not_change_state(self, cfg_file, state):
        yacmap = yacman.YacAttMap(filepath=cfg_file, writable=state)
        with yacmap as _:
            print(_)
        assert yacmap.writable == state

    @pytest.mark.parametrize("state", [True, False])
    def test_context_manager_saves_updates(self, cfg_file, state):
        yacmap = yacman.YacAttMap(filepath=cfg_file, writable=state)
        with yacmap as y:
            y["testattr"] = "testval"
            yacmap.write()
        if yacmap.writable:
            yacmap.make_readonly()
        yacmap1 = yacman.YacAttMap(filepath=cfg_file, writable=True)
        assert yacmap1["testattr"] == "testval"
        del yacmap1["testattr"]
        yacmap1.make_readonly()

    def test_context_manager_allows_writing(self, data_path):
        with yacman.YAMLConfigManager(filepath=make_cfg_file_path("conf.yaml", data_path)) as ycm:
            assert (ycm["x"] == 15)
            # The context manager should create the lock for us
            assert os.path.exists(make_lock_path("conf.yaml", data_path))
            print(ycm["x"])
            ycm["abc"] = 3
            print(ycm)
            ycm.write()

    def test_context_works_with_objects_created_from_entries_with_filepath(
        self, cfg_file
    ):
        yacmap = yacman.YacAttMap(entries={})
        yacmap.filepath = cfg_file
        with yacmap as _:
            pass


    def test_context_should_error_if_no_filepath(self, cfg_file):
        """Test for TypeError raised in case no valid filepath is set but write requested"""
        yacmap = yacman.YacAttMap(entries={})
        with pytest.raises(TypeError):
            with yacmap as _:
                pass


yaml_str = """\
---
one: 1
2: two
"""

def test_float_idx():
    data = yacman.YacAttMap(yamldata=yaml_str)
    # We should be able to access this by string, not by int index.
    assert data["2"] == "two"
    with pytest.raises(KeyError):
        data[2]
