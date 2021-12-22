import logging
import os
from collections.abc import Iterable, Mapping
from sys import _getframe

import yaml as yaml
from jsonschema import validate as _validate
from jsonschema.exceptions import ValidationError
from ubiquerg import create_lock, expandpath, is_url, make_lock_path, mkabs, remove_lock

_LOGGER = logging.getLogger(__name__)

# Hack for string indexes of both ordered and unordered yaml representations
# Credit: Anthon
# https://stackoverflow.com/questions/50045617
# https://stackoverflow.com/questions/5121931
# The idea is: if you have yaml keys that can be interpreted as an int or a float,
# then the yaml loader will convert them into an int or a float, and you would
# need to access them with dict[2] instead of dict['2']. But since we always
# expect the keys to be strings, this doesn't work. So, here we are adjusting
# the loader to keep everything as a string.

# Only do once.
if not hasattr(yaml.SafeLoader, "patched_yaml_loader"):

    _LOGGER.debug("Patching yaml loader")

    def my_construct_mapping(self, node, deep=False):
        data = self.construct_mapping_org(node, deep)
        return {
            (str(key) if isinstance(key, float) or isinstance(key, int) else key): data[
                key
            ]
            for key in data
        }

    yaml.SafeLoader.construct_mapping_org = yaml.SafeLoader.construct_mapping
    yaml.SafeLoader.construct_mapping = my_construct_mapping
    yaml.SafeLoader.patched_yaml_loader = True


# Constants: to do, remove these

IK = "__internal"

USE_LOCKS_KEY = "locks"
WAIT_MAX_KEY = "wait_time"
ALIASES_KEY = "aliases"
ALIASES_KEY_RAW = "aliases_raw"
WRITE_VALIDATE_KEY = "validate_on_write"
SCHEMA_KEY = "schema"

ATTR_KEYS = (
    IK,
    USE_LOCKS_KEY,
    WAIT_MAX_KEY,
    ALIASES_KEY,
    ALIASES_KEY_RAW,
    WRITE_VALIDATE_KEY,
    SCHEMA_KEY,
)

LOCK_PREFIX = "lock."
DEFAULT_RO = False
DEFAULT_WAIT_TIME = 60


from collections import UserDict
class YAMLConfigManager(UserDict):
    """
    A YAML configuration manager benefits, providing file locking, loading,
    writing, etc.  for YAML configuration files. but without the requirement
    of attmap (and without providing the attribute-style access).
    """

    def __init__(
        self,
        entries=None,
        filepath=None,
        yamldata=None,
        writable=False,
        wait_max=DEFAULT_WAIT_TIME,
        skip_read_lock=False,
        schema_source=None,
        validate_on_write=False,
        create_file=False,
    ):
        """
        Object constructor

        :param Iterable[(str, object)] | Mapping[str, object] entries: YAML collection
            of key-value pairs.
        :param str filepath: YAML filepath to the config file.
        :param str yamldata: YAML-formatted string
        :param bool writable: whether to create the object with write capabilities
        :param int wait_max: how long to wait for creating an object when the file
            that data will be read from is locked
        :param bool skip_read_lock: whether the file should not be locked for reading
            when object is created in read only mode
        :param str schema_source: path or a URL to a jsonschema in YAML format to use
            for optional config validation. If this argument is provided the object
            is always validated at least once, at the object creation stage.
        :param bool validate_on_write: a boolean indicating whether the object should be
            validated every time the `write` method is executed, which is
            a way of preventing invalid config writing
        :param bool expand: indicator of whether this object should automatically
            expand paths.
        """

        # Settings for this config object
        if filepath:
            self.filepath = mkabs(filepath)
        else:
            self.filepath = None
        self.wait_max = wait_max
        self.skip_read_lock = skip_read_lock
        self.schema_source = schema_source
        self.validate_on_write = validate_on_write
        self.writable = writable
        self.already_writable = writable

        if self.writable:
            if filepath:
                create_lock(filepath, wait_max)
            else:
                self.writable = False
                writable = False
                _LOGGER.warning(
                    "Argument 'writable' is disregarded when the object is created "
                    "with 'entries' rather than 'filepath'"
                )
        if filepath:
            if not skip_read_lock and not writable and os.path.exists(filepath):
                create_lock(filepath, wait_max)
                file_contents = load_yaml(filepath)
                remove_lock(filepath)
            elif os.path.exists(filepath):
                file_contents = load_yaml(filepath)
            elif create_file:
                _LOGGER.debug("File does not exist, create_file is true")
                file_contents = {}
                with open(filepath, 'w') as file:
                    pass
            else:
                raise FileNotFoundError(f"No such file: {filepath}")

            if entries:
                if file_contents is None:
                    # if file is empty, initialize its contents to an empty dict
                    file_contents = {}
                file_contents.update(entries)
            entries = file_contents
        elif yamldata:
            entries = yaml.load(yamldata, yaml.SafeLoader)

        # We store the values in a dict under .data
        self.data = dict(entries or {})
        if schema_source is not None:
            assert isinstance(schema_source, str), TypeError(
                f"Path to the schema to validate the config must be a string"
            )
            sp = expandpath(schema_source)
            assert os.path.exists(sp), FileNotFoundError(
                f"Provided schema file does not exist: {schema_source}."
                f" Also tried: {sp}"
            )
            # validate config
            setattr(getattr(self, IK), SCHEMA_KEY, load_yaml(sp))
            self.validate()

    def __del__(self):
        if self.filepath and self.writable:
            self.make_readonly()

    # def __repr__(self):
    #     # Here we want to render the data in a nice way; and we want to indicate
    #     # the class if it's NOT a YacAttMap. If it is a YacAttMap we just want
    #     # to give you the data without the class name.
    #     return self._render(self.data)

    def __enter__(self):
        if self.writable:
            _LOGGER.debug("Already writable upon entering context manager")
            self.already_writable = True
        self.make_writable()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.already_writable:
            self.writable = True
            self.already_writable = True
            return False
        self.make_readonly()

        # Must return False, otherwise context exceptions are suppressed
        return False

    def _reinit(self, filepath=None):
        """
        Reload the object from file, then update with current information

        :param str filepath: path to the file that should be read
        """
        fp = filepath or self.filepath
        if fp is not None:
            local_data = self.data
            self.__init__(filepath=fp, skip_read_lock=True)
            deep_update(self.data, local_data)
            # self.data.update(local_data)
        else:
            _LOGGER.warning("Reinit has no effect if no filepath")


    def _reset(self, filepath=None):
        """
        Reset dict contents to file contents, or to empty dict if no filepath found.
        """
        fp = filepath or self.filepath
        if fp is not None:
            self.__init__(filepath=fp, skip_read_lock=True)
        else:
            self.__init__(entries={}, skip_read_lock=True)


    def validate(self, schema=None, exclude_case=False):
        """
        Validate the object against a schema

        :param dict schema: a schema object to use to validate, it overrides the one
            that has been provided at object construction stage
        :param bool exclude_case: whether to exclude validated objects
            from the error. Useful when used with large configs
        """
        try:
            _validate(
                self.to_dict(expand=True),
                schema or getattr(getattr(self, IK), SCHEMA_KEY),
            )
        except ValidationError as e:
            _LOGGER.error(
                f"{self.__class__.__name__} object did not pass schema validation"
            )
            if self.filepath is not None:
                # need to unlock locked files in case of validation error so that no
                # locks are left in place
                self.make_readonly()
            if not exclude_case:
                raise
            raise ValidationError(
                f"{self.__class__.__name__} object did not pass schema validation: "
                f"{e.message}"
            )
        _LOGGER.debug("Validated successfully")

    def write(self, filepath=None, schema=None, exclude_case=False):
        """
        Write the contents to a file.

        Make sure that the object has been created with write capabilities

        :param str filepath: a file path to write to
        :param dict schema: a schema object to use to validate, it overrides the one
            that has been provided at object construction stage
        :raise OSError: when the object has been created in a read only mode or other
            process has locked the file
        :raise TypeError: when the filepath cannot be determined. This takes place only
            if YacAttMap initialized with a Mapping as an input, not read from file.
        :raise OSError: when the write is called on an object with no write capabilities
            or when writing to a file that is locked by a different object
        :return str: the path to the created files
        """
        if filepath:
            _check_filepath(filepath)
            lock = make_lock_path(filepath)
            if os.path.exists(filepath):
                if os.path.exists(lock):
                    raise OSError(
                        f"The file '{filepath}' is locked by a different process"
                    )
                else:
                    _LOGGER.warning(
                        "Writing to an unlocked, existing file. Beware of collisions."
                    )
            create_lock(filepath, self.wait_max)
            _LOGGER.debug(f"writing to file path: {filepath}")
            with open(filepath, "w") as f:
                f.write(self.to_yaml())
            self._remove_lock(filepath)
        else:
            # Previously we didn't allow you to just 'write'.
            #  But now the idea is that w
            if not self.writable:
                raise OSError(
                    "You should write from within a context manager, which sets the object to writable"
                )

            if schema is not None or self.validate_on_write:
                self.validate(schema=schema, exclude_case=exclude_case)
            filepath = _check_filepath(self.filepath)
            lock = make_lock_path(filepath)
            if filepath != self.filepath:
                if os.path.exists(filepath):
                    if not os.path.exists(lock):
                        _LOGGER.warning(
                            "Writing to a non-locked, existing file. Beware of collisions."
                        )
                    else:
                        raise OSError(
                            f"The file '{filepath}' is locked by a different process"
                        )
            with open(filepath, "w") as f:
                f.write(self.to_yaml())

        abs_path = os.path.abspath(filepath)
        _LOGGER.debug(f"Wrote to a file: {abs_path}")
        return os.path.abspath(abs_path)

    def to_yaml(self, trailing_newline=True):
        """
        Get text for YAML representation.

        :param bool trailing_newline: whether to add trailing newline
        :return str: YAML text representation of this instance.
        """
        return "\n".join(self.get_yaml_lines()) + ("\n" if trailing_newline else "")

    def to_dict(self, expand=True):
        # Seems like it's probably not necessary; can just use the object now.
        # but for backwards compatibility.
        return self.data

    def get_yaml_lines(
        self,
        conversions=((lambda obj: isinstance(obj, Mapping) and 0 == len(obj), None),),
    ):
        """
        Get collection of lines that define YAML text rep. of this instance.

        :param Iterable[(function(object) -> bool, object)] conversions:
            collection of pairs in which first component is predicate function
            and second is what to replace a value with if it satisfies the predicate
        :return list[str]: YAML representation lines
        """
        if 0 == len(self.data):
            return ["{}"]
        # data = self._simplify_keyvalue(
        #     self._data_for_repr(), self._new_empty_basic_map, conversions=conversions
        # )
        # data = dict(self.items())
        return self._render(self.data).split("\n")[1:]

    def _render(self, data, exclude_class_list=[]):
        def _custom_repr(obj, prefix=""):
            """
            Calls the ordinary repr on every object but list, which is
            converted to a block style string instead.

            :param object obj: object to convert to string representation
            :param str prefix: string to prepend to each list line in block
            :return str: custom object representation
            """
            if isinstance(obj, list) and len(obj) > 0:
                return f"\n{prefix} - " + f"\n{prefix} - ".join([str(i) for i in obj])
            return obj.strip("'") if hasattr(obj, "strip") else str(obj)

        class_name = self.__class__.__name__
        if class_name in exclude_class_list:
            base = ""
        else:
            base = class_name + "\n"

        if data:
            return base + "\n".join(get_data_lines(data, _custom_repr))
        else:
            return class_name + ": {}"

    @staticmethod
    def _remove_lock(filepath):
        """
        Remove lock

        :param str filepath: path to the file to remove the lock for. Not the
            path to the lock!
        :return bool: whether the lock was found and removed
        """
        lock = make_lock_path(_check_filepath(filepath))
        if os.path.exists(lock):
            os.remove(lock)
            return True
        return False

    def make_readonly(self):
        """
        Remove lock and make the object read only.

        :return bool: a logical indicating whether any locks were removed
        """
        self.writable = False
        if self._remove_lock(self.filepath):
            _LOGGER.debug("Made object read-only")
            return True
        return False

    def make_writable(self, filepath=None):
        """
        Grant write capabilities to the object and re-read the file.

        Any changes made to the attributes are overwritten so that the object
        reflects the contents of the specified config file

        :param str filepath: path to the file that the contents will be written to
        :return YacAttMap: updated object
        """
        if filepath and filepath != self.filepath:
            _LOGGER.info(f"Resetting filepath to: {filepath}")
            self.filepath = filepath

        if self.writable:
            _LOGGER.info(f"Object is already writable, path: {self.filepath}")
            return True

        _check_filepath(self.filepath)
        create_lock(self.filepath, self.wait_max)
        try:
            self._reinit(self.filepath)
        except OSError:
            _LOGGER.debug(f"File '{self.filepath}' not found")
            pass
        except Exception as e:
            self._reinit()
            _LOGGER.info(f"File '{self.filepath}' was not read, got an exception: {e}")
        self.writable = True
        _LOGGER.debug("Made object writable")
        return True

    def __setitem__(self, item, value):
        self.data[item] = value

    def __getitem__(self, item):
        """
        Fetch the value of given key.

        :param hashable item: key for which to fetch value
        :return object: value mapped to given key, if available
        :raise KeyError: if the requested key is unmapped.
        """
        return self.data[item]
        # return _safely_expand_path(self.data[item]) if self.expand else self.data[item]

    @property
    def exp(self):
        """
        Returns a copy of the object's data elements with env vars and user vars
        expanded. Use it like: object.exp["item"]
        """
        return _safely_expand_path(self.data)

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __delitem__(self, key):
        value = self[key]
        del self.data[key]
        self.pop(value, None)

    def __repr__(self):
        return f"{type(self).__name__}({self.data})"


from ubiquerg import expandpath

# A big issue here is: if you route the __getitem__ through this,
# then it returns a copy of the data, rather than the data itself.
# That's the point, so we don't adjust it. But then you can't use multi-level
# item setting, like ycm["x"]["y"] = value, because ycm['x'] returns a different
# dict, and so you're updating that copy of it.
# The solution is that we have to route expansion through a separate property,
# so the setitem syntax can remain intact while preserving original values.
def _safely_expand_path(x):
    if isinstance(x, str):
        return expandpath(x)
    elif isinstance(x, Mapping):
        return {k: _safely_expand_path(v) for k, v in x.items()}
    return x

def _unsafely_expand_path(x):
    if isinstance(x, str):
        return expandpath(x)
    elif isinstance(x, Mapping):
        for k in x.keys():
            x[k] = _safely_expand_path(x[k])
        return x
        # return {k: _safely_expand_path(v) for k, v in x.items()}
    return x
def get_data_lines(data, fun_key, space_per_level=2, fun_val=None):
    """
    Get text representation lines for a mapping's data.

    :param Mapping data: collection of data for which to get repr lines
    :param function(object, prefix) -> str fun_key: function to render key
        as text
    :param function(object, prefix) -> str fun_val: function to render value
        as text
    :param int space_per_level: number of spaces per level of nesting
    :return Iterable[str]: collection of lines
    """

    # If no specific value-render function, use key-render function
    fun_val = fun_val or fun_key

    def space(lev):
        return " " * lev * space_per_level

    # Render a line; pass val=<obj> for a line with a value (i.e., not header)
    def render(lev, key, **kwargs):
        ktext = fun_key(key) + ":"
        try:
            val = kwargs["val"]
        except KeyError:
            return space(lev) + ktext
        else:
            return space(lev) + "{} {}".format(
                ktext, "null" if val is None else fun_val(val, space(lev))
            )

    def go(kvs, curr_lev, acc):
        try:
            k, v = next(kvs)
        except StopIteration:
            return acc
        if not isinstance(v, Mapping) or len(v) == 0:
            # Add line representing single key-value or empty mapping
            acc.append(render(curr_lev, k, val=v))
        else:
            # Add section header and section data.
            acc.append(render(curr_lev, k))
            acc.append("\n".join(go(iter(v.items()), curr_lev + 1, [])))
        return go(kvs, curr_lev, acc)

    return go(iter(data.items()), 0, [])


def _check_filepath(filepath):
    """
    Validate if the filepath is a str

    :param str filepath: object to validate
    :return str: validated filepath
    :raise TypeError: if the filepath is not a string
    """
    # might be useful if we want to have multiple locked paths in the future
    # def _check_string(obj):
    #     """ check if object is a string or a list of strings """
    #     return bool(obj) and all(isinstance(elem, str) for elem in obj)
    if not isinstance(filepath, str):
        raise TypeError(
            f"No valid filepath provided. It must be a str, got: {filepath.__class__.__name__}"
        )
    return filepath


def load_yaml(filepath):
    """Load a yaml file into a python dict"""

    def read_yaml_file(filepath):
        """
        Read a YAML file

        :param str filepath: path to the file to read
        :return dict: read data
        """
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
        return data

    if is_url(filepath):
        _LOGGER.debug(f"Got URL: {filepath}")
        try:  # python3
            from urllib.error import HTTPError
            from urllib.request import urlopen
        except:  # python2
            from urllib2 import URLError as HTTPError
            from urllib2 import urlopen
        try:
            response = urlopen(filepath)
        except HTTPError as e:
            raise e
        data = response.read()  # a `bytes` object
        text = data.decode("utf-8")
        return yaml.safe_load(text)
    else:
        return read_yaml_file(filepath)


def get_first_env_var(ev):
    """
    Get the name and value of the first set environment variable

    :param str | Iterable[str] ev: a list of the environment variable names
    :return (str, str): name and the value of the environment variable
    """
    if isinstance(ev, str):
        ev = [ev]
    elif not isinstance(ev, Iterable):
        raise TypeError(
            f"Env var must be single name or collection of names; got {type(ev)}"
        )
    # TODO: we should handle the null (not found) case, as client code is
    #  inclined to unpack, and ValueError guard is vague.
    for v in ev:
        try:
            return v, os.environ[v]
        except KeyError:
            pass


def select_config(
    config_filepath=None,
    config_env_vars=None,
    default_config_filepath=None,
    check_exist=True,
    on_missing=lambda fp: IOError(fp),
    strict_env=False,
):
    """
    Selects the config file to load.

    This uses a priority ordering to first choose a config filepath if it's given,
    but if not, then look in a priority list of environment variables and choose
    the first available filepath to return.

    :param str | NoneType config_filepath: direct filepath specification
    :param Iterable[str] | NoneType config_env_vars: names of environment
        variables to try for config filepaths
    :param str default_config_filepath: default value if no other alternative
        resolution succeeds
    :param bool check_exist: whether to check for path existence as file
    :param function(str) -> object on_missing: what to do with a filepath if it
        doesn't exist
    :param bool strict_env: whether to raise an exception if no file path provided
        and environment variables do not point to any files
    raise: OSError: when strict environment variables validation is not passed
    """

    # First priority: given file
    if config_filepath:
        config_filepath = os.path.expandvars(config_filepath)
        if not check_exist or os.path.isfile(config_filepath):
            return os.path.abspath(config_filepath)
        _LOGGER.error(f"Config file path isn't a file: {config_filepath}")
        result = on_missing(config_filepath)
        if isinstance(result, Exception):
            raise result
        return os.path.abspath(result)

    _LOGGER.debug("No local config file was provided")
    selected_filepath = None

    # Second priority: environment variables (in order)
    if config_env_vars:
        _LOGGER.debug(f"Checking for environment variable: {config_env_vars}")

        cfg_env_var, cfg_file = get_first_env_var(config_env_vars) or ["", ""]

        if not check_exist or os.path.isfile(cfg_file):
            _LOGGER.debug(f"Found config file in {cfg_env_var}: {cfg_file}")
            selected_filepath = cfg_file
        if selected_filepath is None and cfg_file and strict_env:
            raise OSError(
                f"Environment variable ({', '.join(config_env_vars)}) does "
                f"not point to any existing file: {cfg_file}"
            )
    if selected_filepath is None:
        # Third priority: default filepath
        _LOGGER.info(
            f"Using default config. No config found in env var: {str(config_env_vars)}"
        )
        return default_config_filepath
    return (
        os.path.abspath(selected_filepath) if selected_filepath else selected_filepath
    )


def deep_update(old, new):
    """
    Recursively update nested dict, modifying source
    """
    for key, value in new.items():
        if isinstance(value, Mapping) and value:
            old[key] = deep_update(old.get(key, {}), value)
        else:
            old[key] = new[key]
    return old




class YacAttMap(YAMLConfigManager):
    """
    A dummy class that provides drop-in replacement for yacman version 1.
    """

    pass
