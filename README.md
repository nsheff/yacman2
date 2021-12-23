<img src="https://raw.githubusercontent.com/databio/yacman/master/docs/img/yacman_logo.svg?sanitize=true" alt="yacman" height="70"/><br>
![Run pytests](https://github.com/databio/yacman/workflows/Run%20pytests/badge.svg)
![Test locking parallel](https://github.com/databio/yacman/workflows/Test%20locking%20parallel/badge.svg)
[![codecov](https://codecov.io/gh/databio/yacman/branch/master/graph/badge.svg)](https://codecov.io/gh/databio/yacman)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Anaconda-Server Badge](https://anaconda.org/conda-forge/yacman/badges/version.svg)](https://anaconda.org/conda-forge/yacman)

Yacman is a YAML configuration manager. It provides some convenience tools for dealing with YAML configuration files.

Please see [this](docs/usage.md) Python notebook for features and usage instructions and [this](docs/api_docs.md) document for API documentation.


## New in 2.0

yacman2 changes a lot of things philosophically about how to use yacman. These changes greatly simplify the codebase and dependencies, and in my opinion also make it more straightforward to use.

### 1. All locking should be handled in context managers.

In the earlier version, keeping track of when the thing was locked was a pain. There was 'writable' and 'readonly', and the user had to keep track of creating and removing locks. Yacman2 simplifies things. You should never worry about locks. 

There are 3 things you can do that might necessitate locking the file: 

.load()
.rebase()
.write()

These should all happen in context managers.

So, 

```
cfg = YAMLConfigManager(filepath="...")
cfg["item"] = "value"
with cfg as cfg_locked:
	cfg_locked.write()
```

### 2. Rebasing is now streamlined

I renamed and revised the behavior of 'reinit'. Now, it's called `rebase`, and what it does is re-load the underlying file, and then update it with the current dict contents in memory.
If you need to `rebase`, you should do it within a context manager. 

```
cfg = YAMLConfigManager(filepath="...")
cfg["item"] = "value"
with cfg as cfg_locked:
	cfg_locked.rebase()
	cfg_locked.write()
```

Rebases will never happen automatically. If you want to rebase before writing, you simply call `.rebase()` first.


### 3. No more attribute access

Yacman2 goes back to the Python ideology, where the object settings are stored as attributes, and the data itself is stored in a dict. So, you no longer need `to_dict`, for example, to get the data, out, you can just use the object directly because it basically *is* a dict. Or just use `dict(obj)`.

```
cfg = YAMLConfigManager(filepath="...")
cfg["item"] = "value"
```

You can use `.settings` to get all the settings (which are all stored as attributes and not items).

```
cfg = YAMLConfigManager(filepath="...")
cfg.settings
```